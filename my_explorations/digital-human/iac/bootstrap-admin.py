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
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return resp.status, None  # 非 JSON 响应(如验证码图片)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return e.code, None


def get_captcha_from_redis(container, captcha_id):
    """验证码文本明文存在 Redis 中, 直接从容器读取。
    注意: redisUtils 序列化会把字符串加上字面引号 (如 '"7tHd8"'), 需去掉。"""
    key = f"sys:captcha:{captcha_id}"
    out = subprocess.run(
        ["docker", "exec", container, "redis-cli", "GET", key],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if not out:
        raise RuntimeError(f"Redis 中未找到验证码 {key}")
    if len(out) >= 2 and out[0] == '"' and out[-1] == '"':
        out = out[1:-1]  # 去掉字面引号
    if len(out) != 5:
        raise RuntimeError(f"验证码长度异常: {out!r} (len={len(out)})")
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
    ap.add_argument("--set-websocket", default=None,
                    help="把 server.websocket 参数改为该地址 (如 ws://192.168.1.6:8000/xiaozhi/v1/), 然后退出")
    args = ap.parse_args()

    if args.set_websocket:
        set_websocket(args)
        return

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
    if code != 200 or (isinstance(resp, dict) and resp.get("code") != 0):
        sys.exit(f"注册失败: HTTP={code} resp={resp}")
    print("     注册成功")

    # 4. 登录
    print("[3/5] 登录获取 token ...")
    token = login_get_token(args, pub_key)

    # 5. 读取 server.secret
    print("[4/5] 读取 server.secret ...")
    code, resp = http("GET", f"{args.api}/admin/params/page?page=1&limit=20&paramCode=server.secret",
                      token=token)
    if code != 200 or (isinstance(resp, dict) and resp.get("code") != 0):
        sys.exit(f"查询参数失败: HTTP={code} resp={resp}")
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


def login_get_token(args, pub_key=None):
    """登录并返回 token (供其它模式复用)"""
    if pub_key is None:
        _, pub = http("GET", f"{args.api}/user/pub-config")
        pub_key = pub["data"]["sm2PublicKey"]
    captcha_id = str(uuid.uuid4())
    http("GET", f"{args.api}/user/captcha?uuid={captcha_id}")
    captcha = get_captcha_from_redis(args.redis_container, captcha_id)
    cipher = sm2_encrypt(pub_key, captcha + args.password)
    code, resp = http("POST", f"{args.api}/user/login",
                      {"username": args.username, "password": cipher, "captchaId": captcha_id})
    if code != 200 or (isinstance(resp, dict) and resp.get("code") != 0):
        sys.exit(f"登录失败: HTTP={code} resp={resp}")
    return resp["data"]["token"]


def set_websocket(args):
    """将 server.websocket 参数改为可达地址 (供全栈部署时指向宿主机/局域网)"""
    _, pub = http("GET", f"{args.api}/user/pub-config")
    pub_key = pub["data"]["sm2PublicKey"]
    token = login_get_token(args, pub_key)

    code, resp = http("GET", f"{args.api}/admin/params/page?page=1&limit=20&paramCode=server.websocket",
                      token=token)
    if code != 200 or (isinstance(resp, dict) and resp.get("code") != 0):
        sys.exit(f"查询 server.websocket 失败: HTTP={code} resp={resp}")
    row = next((r for r in resp.get("data", {}).get("list", [])
                if r.get("paramCode") == "server.websocket"), None)
    if not row:
        sys.exit("未找到 server.websocket 参数")
    dto = {k: row.get(k) for k in ("id", "paramCode", "paramValue", "valueType", "remark")}
    dto["paramValue"] = args.set_websocket
    code, resp = http("PUT", f"{args.api}/admin/params", dto, token=token)
    if code != 200 or (isinstance(resp, dict) and resp.get("code") != 0):
        sys.exit(f"更新 server.websocket 失败: HTTP={code} resp={resp}")
    print(f"server.websocket 已更新为: {args.set_websocket}")


if __name__ == "__main__":
    main()
