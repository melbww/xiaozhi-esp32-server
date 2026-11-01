#!/usr/bin/env python3
"""
smoke-test.py — 端到端冒烟测试 (模拟 digital-human 页面行为)

  1. POST /xiaozhi/ota/ (manager-api :8002)  →  拿到 websocket url + token
  2. 用返回的 URL 建立 WebSocket 连接 (xiaozhi-server :8000)
  3. 发送 hello 握手, 等待 hello 响应
  4. 可选: 发送 listen detect 触发一次对话

用法:
  python3 smoke-test.py [--ota http://127.0.0.1:8002/xiaozhi/ota/] [--mac 随机生成]
"""
import argparse
import asyncio
import json
import random
import urllib.request
import uuid

import websockets


def random_mac():
    return ":".join(f"{random.randint(0, 255):02X}" for _ in range(6))


def ota_handshake(ota_url, mac):
    """与 digital-human js/core/network/ota-connector.js 保持一致"""
    payload = {
        "version": 0, "uuid": "",
        "application": {"name": "xiaozhi-web-test", "version": "1.0.0",
                        "compile_time": "2025-04-16 10:00:00", "idf_version": "4.4.3",
                        "elf_sha256": "1234567890abcdef1234567890abcdef1234567890abcdef"},
        "ota": {"label": "xiaozhi-web-test"},
        "board": {"type": "xiaozhi-web-test", "ssid": "xiaozhi-web-test", "rssi": 0,
                  "channel": 0, "ip": "192.168.1.1", "mac": mac},
        "flash_size": 0, "minimum_free_heap_size": 0, "mac_address": mac,
        "chip_model_name": "", "chip_info": {"model": 0, "cores": 0, "revision": 0, "features": 0},
        "partition_table": [{"label": "", "type": 0, "subtype": 0, "address": 0, "size": 0}],
    }
    req = urllib.request.Request(ota_url, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Device-Id", mac)
    req.add_header("Client-Id", "web_test_client")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def ws_hello(ws_url, mac):
    headers = {}
    async with websockets.connect(ws_url, additional_headers=headers, open_timeout=15) as ws:
        hello = {"type": "hello", "device_id": mac, "device_name": "smoke-test",
                 "device_mac": mac, "token": "", "features": {"mcp": True, "emoji": False}}
        await ws.send(json.dumps(hello))
        reply = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(reply)
        if data.get("type") == "hello":
            print(f"  ✅ hello 握手成功, session_id={data.get('session_id')}")
            # 尝试 listen detect (触发一次对话)
            await ws.send(json.dumps({"type": "listen", "state": "detect", "text": "你好小智"}))
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    m = json.loads(msg)
                    if m.get("type") in ("stt", "llm", "tts"):
                        print(f"  💬 {m.get('type')}: {m.get('text', '')[:60]}")
                        if m.get("type") == "tts" and m.get("state") == "stop":
                            break
            except asyncio.TimeoutError:
                print("  (等待对话响应超时 — 语音 AI 可能未配置 LLM Key)")
            return True
        else:
            print(f"  ❌ 未收到 hello 响应: {reply}")
            return False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ota", default="http://127.0.0.1:8002/xiaozhi/ota/")
    ap.add_argument("--mac", default=None)
    args = ap.parse_args()
    mac = args.mac or random_mac()
    print(f"设备 MAC: {mac}")
    print(f"[1/2] OTA 握手 -> {args.ota}")
    result = ota_handshake(args.ota, mac)
    websocket = result.get("websocket") or {}
    ws_url = websocket.get("url")
    if not ws_url:
        print(f"  ❌ OTA 未返回 websocket: {json.dumps(result, ensure_ascii=False)[:300]}")
        return 1
    print(f"  ✅ OTA 返回 websocket: {ws_url}")
    print("[2/2] WebSocket hello 握手")
    ok = await ws_hello(ws_url, mac)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
