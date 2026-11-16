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

### 工具调用 few-shot

每次 WebSocket 连接初始化时，`core/connection.py` 会注入两条临时 few-shot
（用户消息带 `[示例]` 前缀）：

- `[示例] 谢谢` → `direct_answer`：教模型把直接回复写进 `response` 参数；
- `[示例] 拜拜` → `handle_exit_intent`：教模型完整的“调用→结果→回复”闭环。

它们只是格式示范，`is_temporary=True`，不会进入长期记忆，也不代表用户真的说过
这些话；system prompt 会通过 `<tool_example_rules>` 明确告诉模型：示例不是
真实对话、不是记忆，不要提及、延续或引用。日志里看到它们属于正常现象，不是
上下文串线。

> 旧版本用“给我讲个故事吧 → 选一个我给你开讲”作为 direct_answer 示例，
> 弱模型会把它当成真实历史，在新会话里回答“刚才说要给你讲故事”。现已替换为
> 无待办承诺的“谢谢”，并把 direct_answer 放在示例末尾。

### 首条消息与初始化

连接建立后，`_initialize_components()` 在线程池里构建增强 prompt 和 few-shot；
`startToChat()` 会等待 `components_ready_event`（最多 10 秒）再进入 LLM。
因此首条消息不会只带 `You are ESP, a desktop bot` 的 quick prompt 回复。
如果日志出现“组件初始化超时”，说明初始化异常并已降级放行。

### 图形化实时日志（推荐）

独立面板 [`../log-viewer/`](../log-viewer/README.md)(:8007) 同时聚合两个容器 +
digital-human 运行时，带阶段过滤(VAD/ASR/LLM/TTS/...)、关键字搜索、断线重连：

```sh
my_explorations/log-viewer/log-viewer.sh start
open http://127.0.0.1:8007/logs.html
```

它只读 `docker logs` 和日志文件，不依赖本目录的容器或 digital-human 是否在跑。

### 按会话拆分（`deploy/logs/sessions/`）

`deploy/logs/server.log` 是 append-only 的**原始真源**。直接翻 6 MB 很痛苦，
所以有一个纯标准库脚本把它拆成「一会话一目录 + 索引」的派生视图：

```sh
my_explorations/server/iac/split-sessions.py
open my_explorations/server/deploy/logs/sessions/index.html
```

（等价入口：`my_explorations/server/iac/docker-stack.sh sessions`。）

生成物（每次运行**原子重建**，原始 `server.log` 不会被动）：

```text
deploy/logs/sessions/
  index.html                       # 人看的索引（浏览器打开，带照片缩略图）
  index.md                         # 同一份索引的 Markdown 版本
  index.jsonl                      # 机器读的索引，一行一个会话
  .generated.json                  # 生成信息 + 行数/大小校验
  2026-11-14/
    16-56-00_9bbb6aad/
      session.log                  # 原始日志行（顶部 # 头，正文逐行保留）
      meta.json                    # 与会话相关的元数据
      photos/2026-11-14/*.jpg      # 该会话拍的照片（原图硬链接）
  _global/2026-11-14.log           # 启动/停止/握手等不属于会话的行
  _unassigned/photos/...           # 没有落在任何会话时间段里的照片
```

规则（与 log-viewer 的会话归属一致）：

- `"session_id":"<uuid>"` 开启/继续会话；`"session_id":""`（MCP）忽略。
- VAD/ASR/LLM/TTS 等不带 id 的行按**粘滞**规则归到当前会话。
- `客户端断开连接` 表示开始收尾，`连接资源已释放` 才真正结束一段连接。
- 新握手（`conn - Headers:` / `收到hello消息`）、新 session id、或
  `启动全局GC管理器`（服务重启）都会结束上一段连接。
- 同一个 `session_id` 重连时**合并成一个会话**（index 里 `Seg` 列显示段数），
  重连位置在 `session.log` 里用 `# --- reconnect ... ---` 标出。
- 带时间戳的行才有归属；无时间戳的续行（多行 prompt 等）跟着上一条记录走。
- 每一行**只会**出现在一个地方：某个会话或 `_global/`。

索引字段（`index.jsonl`）：`id` / `short` / `start` / `end` / `duration_s` /
`device` / `turns` / `lines` / `end_reason` / `first_text` / `segments` /
`source.line_start..line_end` / `artifacts` / `dir`。

```sh
# 最近 10 个会话
jq -r '[.start,.short,.device,.turns,.lines,.first_text]|@tsv' \
  my_explorations/server/deploy/logs/sessions/index.jsonl | sort -r | head

# 某个会话里所有 TTS/ASR 行
grep -E '\[ASR\]|语音生成成功' \
  my_explorations/server/deploy/logs/sessions/2026-11-14/16-56-00_9bbb6aad/session.log

# 只读某个设备、某个日期
jq -r 'select(.device=="1c:29:04:3e:ce:50" and (.start|startswith("2026-11-14"))) | .dir' \
  my_explorations/server/deploy/logs/sessions/index.jsonl
```

选项：

| 参数 | 作用 |
|---|---|
| `--photos DIR` | 照片目录（默认 `<log 目录>/photos`） |
| `--artifact-root DIR` | 额外 artifact 目录（可重复；按目录名分组） |
| `--copy-artifacts` | 复制照片而不是硬链接（跨文件系统时脚本会自动回退到复制） |
| `--no-artifacts` | 只拆日志，不处理照片 |
| `--out DIR` | 输出目录（默认 `<log 目录>/sessions`） |
| `--force` | 覆盖没有 `.generated.json` 标记的非空输出目录 |
| `--quiet` | 只打印输出路径（适合脚本/定时任务） |

`deploy/logs/` 已被 gitignore；`sessions/` 是纯派生数据，删掉重跑即可。
照片默认用**硬链接**，不额外占磁盘；删掉会话目录也不会删原图。

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
