# Desk Bot 01 后端 (Self-Hosted Server)

**职责:** 给 ESP32 机器人（Desk Bot 01）提供 OTA、WebSocket 对话、ASR/LLM/TTS
编排和智控台。**不包含** `digital-human` 浏览器模拟器；后者是可选的调试工具，
见 [../digital-human/README.md](../digital-human/README.md)。

## 架构与端口

```text
Desk Bot 01 (ESP32-S3)
  │  OTA  → http://192.168.1.6:8002/xiaozhi/ota/
  │  WS   → ws://192.168.1.6:8000/xiaozhi/v1/
  ▼
manager-api :8002 (智控台 / 设备 / Agent / OTA)
xiaozhi-server :8000 (WS) / :8003 (vision)
MySQL + Redis
  │
  └─ local TTS on the Mac host :8880 (CustomTTS, 见 ../local-say-tts/)
```

## 目录

| 路径 | 说明 |
|---|---|
| `iac/docker-stack.sh` | 后端全栈的 up/down/status/logs/restart/bootstrap |
| `iac/compose.server-source.yml` | 把本地 `main/xiaozhi-server/core` bind-mount 进容器 |
| `iac/bootstrap-admin.py` | 首次部署时自动注册管理员并回填 `server.secret` |
| `iac/smoke-test.py` | OTA + WS 握手冒烟测试 |
| `deploy/` | 运行时数据：`data/`、`models/`(软链)、`mysql/`、`uploadfile/`、`logs/` |
| `.venv/` | 只给 bootstrap 用的 Python 环境（自动创建，已 gitignore） |

## 启动 / 停止

在仓库根目录执行：

```sh
# 启动 4 个容器：manager-api、xiaozhi-server、MySQL、Redis
my_explorations/server/iac/docker-stack.sh up
my_explorations/server/iac/docker-stack.sh status
my_explorations/server/iac/docker-stack.sh restart   # 改 data/.config.yaml 后
my_explorations/server/iac/docker-stack.sh down
```

`up` 会先尝试 `docker compose pull`；如果 ghcr 镜像源不可达而卡住，直接跳过拉取：

```sh
cd /Users/wenwu/work/xiaozhi-esp32-server
export XIAOZHI_REPO_ROOT="$PWD"
docker compose --project-name xiaozhi \
  --project-directory "$PWD/my_explorations/server/deploy" \
  -f "$PWD/main/xiaozhi-server/docker-compose_all.yml" \
  -f "$PWD/my_explorations/server/iac/compose.server-source.yml" \
  up -d --pull never
```

manager-api 依赖 MySQL/Redis，启动后约 20–30 秒智控台和 OTA 才可用。

## 首次引导

```sh
my_explorations/server/iac/docker-stack.sh bootstrap
```

首次登录智控台：`http://127.0.0.1:8002`（默认 `admin` / `Admin@123456`）。
设备绑定、`server.ota` / `server.websocket` 等参数在智控台配置。
`server.secret` 回填到 `deploy/data/.config.yaml`（gitignored）。

## 日志

```sh
docker logs -f xiaozhi-esp32-server
docker logs -f xiaozhi-esp32-server-web
tail -f my_explorations/server/deploy/logs/server.log
```

`compose.server-source.yml` 会把容器内 `tmp/` 落盘到 `deploy/logs/`，容器重建不丢。

LLM 完整请求/响应、VAD/ASR 实时埋点已随本地源码 bind-mount 生效：

```sh
grep -E "LLM 请求|LLM 响应全文|LLM 工具调用|\[VAD\]|\[ASR\]" \
  my_explorations/server/deploy/logs/server.log
```

### 图形化实时日志（推荐）

独立面板 [`../log-viewer/`](../log-viewer/README.md)(:8007) 同时聚合两个容器 +
digital-human 运行时，带阶段过滤(VAD/ASR/LLM/TTS/...)、关键字搜索、断线重连：

```sh
my_explorations/log-viewer/log-viewer.sh start
open http://127.0.0.1:8007/logs.html
```

它只读 `docker logs` 和日志文件，不依赖本目录的容器或 digital-human 是否在跑。

## 冒烟测试

```sh
python3 -m pip install -q websockets   # 仅首次
python3 my_explorations/server/iac/smoke-test.py
```

## 与 digital-human 的边界

| 组件 | 属于 | 启动方式 |
|---|---|---|
| xiaozhi-server / manager-api / MySQL / Redis | 本目录 | `server/iac/docker-stack.sh` |
| 浏览器模拟器 + 本地唤醒词 (:8006) | `../digital-human/` | `digital-human/iac/start.sh` |

机器人链路只用本目录；`digital-human/` 停着不影响机器人。
