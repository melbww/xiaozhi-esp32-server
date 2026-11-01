#!/usr/bin/env python3
"""
bootstrap-admin.py — 自动完成 manager-api 首次启动引导:
  1. 读取 SM2 公钥 (/user/pub-config)
  2. 获取图形验证码 (存于 Redis: sys:captcha:<uuid>)
  3. SM2 加密 (验证码5位 + 密码) 并注册第一个超级管理员
  4. 登录获取 token
  5. 读取 server.secret (admin/params) 并回填 data/.config.yaml

用法:
  python3 bootstrap-admin.py --api http://127.0.0.1:8002/xiaozhi \
      --redis-container xiaozhi-esp32-server-redis \
      --username admin --password 'Admin@123456'

依赖: gmssl (SM2 加密)。pip install gmssl
"""
import argparse
import json
import re
import subprocess
import sys
import urllib.request
import uuid

try:
    from gmssl import sm2, func
except ImportError:
    sys.exit("缺少 gmssl 依赖,请先执行: pip install gmssl")


def http(method, url, data=None, token=None, timeout=30):
    body = None if data is None else json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def get_captcha_from_redis(container, captcha_id):
    """验证码文本明文存在 Redis 中, 直接从容器读取"""
    key = f"sys:captcha:{captcha_id}"
    out = subprocess.run(
        ["docker", "exec", container, "redis-cli", "GET", key],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not out:
        raise RuntimeError(f"Redis 中未找到验证码 {key}")
    return out


def sm2_encrypt(public_key_hex, plaintext):
    """SM2 C1C3C2 模式加密, 输出十六进制 (与 Java SM2Utils 一致)"""
    pri_key = "0000000000000000000000000000000000000000000000000000000000000000"
    # gmssl 3.x: mode=0 -> C1C2C3, mode=1 -> C1C3C2 (Java 侧用的是 C1C3C2)
    crypt = sm2.CryptSM2(public_key=public_key_hex, private_key=pri_key, mode=1)
    return crypt.encrypt(plaintext.encode("utf-8")).hex()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://127.0.0.1:8002/xiaozhi")
    ap.add_argument("--redis-container", default="xiaozhi-esp32-server-redis")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="Admin@123456")
    ap.add_argument("--config-file",
                    default="/Users/wenwu/work/xiaozhi-esp32-server/my_explorations/digital-human/deploy/data/.config.yaml")
    args = ap.parse_args()

    # 1. SM2 公钥
    code, pub = http("GET", f"{args.api}/user/pub-config")
    if code != 200:
        sys.exit(f"pub-config 失败: {code} {pub}")
    pub_key = pub["data"]["sm2PublicKey"]
    print(f"[1/5] SM2 公钥: {pub_key[:24]}...")

    def sm2_password_with_captcha(plain_pwd):
        captcha_id = str(uuid.uuid4())
        # 2. 生成验证码 (GET 触发生成并存 Redis)
        http("GET", f"{args.api}/user/captcha?uuid={captcha_id}")
        captcha = get_captcha_from_redis(args.redis_container, captcha_id)
        print(f"     captcha={captcha} id={captcha_id[:8]}...")
        cipher = sm2_encrypt(pub_key, captcha + plain_pwd)
        return captcha_id, cipher

    # 3. 注册
    print("[2/5] 注册超级管理员 ...")
    captcha_id, cipher = sm2_password_with_captcha(args.password)
    code, resp = http("POST", f"{args.api}/user/register",
                      {"username": args.username, "password": cipher, "captchaId": captcha_id})
    if code != 200:
        sys.exit(f"注册失败: {code} {resp}")
    print("     注册成功")

    # 4. 登录
    print("[3/5] 登录获取 token ...")
    captcha_id, cipher = sm2_password_with_captcha(args.password)
    code, resp = http("POST", f"{args.api}/user/login",
                      {"username": args.username, "password": cipher, "captchaId": captcha_id})
    if code != 200:
        sys.exit(f"登录失败: {code} {resp}")
    token = resp["data"]["token"]
    print(f"     token: {token[:16]}...")

    # 5. 读取 server.secret
    print("[4/5] 读取 server.secret ...")
    code, resp = http("GET", f"{args.api}/admin/params/page?page=1&limit=20&paramCode=server.secret",
                      token=token)
    if code != 200:
        sys.exit(f"查询参数失败: {code} {resp}")
    secret = None
    for row in resp.get("data", {}).get("list", []):
        if row.get("paramCode") == "server.secret":
            secret = row.get("paramValue")
            break
    if not secret:
        sys.exit("未找到 server.secret")
    print(f"     server.secret = {secret}")

    # 6. 回填 .config.yaml
    print("[5/5] 回填 data/.config.yaml ...")
    with open(args.config_file, encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r"(?<=secret:\s).*", f" {secret}", content)
    with open(args.config_file, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"     已写入 {args.config_file}")
    print("\n完成! 重启 xiaozhi-server 容器使配置生效: docker restart xiaozhi-esp32-server")


if __name__ == "__main__":
    main()
