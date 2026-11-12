# log-viewer — 独立实时日志面板

**职责：** 在浏览器里实时看整个 desk-bot 栈的日志，一个页面里同时聚合：

| 源 (name) | 类型 | 指向 | 内容 |
|---|---|---|---|
| `server` | docker | 容器 `xiaozhi-esp32-server` | 机器人后端（VAD/ASR/LLM/TTS/HTTP/MCP） |
| `web` | docker | 容器 `xiaozhi-esp32-server-web` | 智控台 / manager-api |
| `runtime` | file | `main/digital-human/wakeword_runtime/logs/wakeword-runtime.log` | digital-human 唤醒词运行时 |

**不依赖** `main/digital-human` 和 `my_explorations/server` 的代码，只读它们的日志：
digital-human 不开、后端不跑，面板本身照样能启动（缺的源会提示）。

## 快速开始

```sh
# 在仓库任意位置执行
my_explorations/log-viewer/log-viewer.sh start

# 打开
open http://127.0.0.1:8007/logs.html

my_explorations/log-viewer/log-viewer.sh status
my_explorations/log-viewer/log-viewer.sh logs      # 面板自己的日志
my_explorations/log-viewer/log-viewer.sh stop
```

纯标准库实现（`http.server` + `subprocess`），**不需要 venv、不用装依赖**。
前台调试可以直接跑：

```sh
python3 my_explorations/log-viewer/log_viewer.py --port 8007
```

## 端口

默认 **8007**（8006 是 digital-human 的页面，两者互不影响）。

```sh
LOG_VIEWER_PORT=8010 my_explorations/log-viewer/log-viewer.sh start
```

默认只监听 `127.0.0.1`。日志里可能含 API Key / 用户对话内容，所以**不要**轻易
`LOG_VIEWER_HOST=0.0.0.0`（那会把日志面板暴露到整个局域网）。

## 配置日志源

`sources.json`：

```json
{
  "history": 200,
  "sources": [
    { "name": "server", "kind": "docker", "target": "xiaozhi-esp32-server", "tail": 20 },
    { "name": "runtime", "kind": "file", "target": "main/digital-human/wakeword_runtime/logs/wakeword-runtime.log" }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `name` | 页面上的源标签（也是 `ws` 帧里的 `source`），必须唯一 |
| `label` | 鼠标悬停提示，写清楚这个源是什么 |
| `kind` | `docker` = `docker logs -f`；`file` = tail 本机文件 |
| `target` | `docker` 填容器名；`file` 填路径（相对路径以**仓库根目录**为基准） |
| `tail` | 首次连接回放多少行（docker 源） |
| `enabled` | 设 `false` 可临时关掉某个源 |
| `history` | 顶层字段：供新页面回放的环形缓冲大小（帧数） |

加一个源只改这个文件，然后 `log-viewer.sh restart`。例如把本地 TTS 也拉进来：

```json
{ "name": "tts", "label": "local-say-tts", "kind": "file",
  "target": "my_explorations/local-say-tts/local-say-tts.log" }
```

检查解析结果：

```sh
python3 my_explorations/log-viewer/log_viewer.py --list-sources
```

## 页面能力

- 源过滤（按 `sources.json` 动态生成）、级别过滤（DEBUG/INFO/WARN/ERROR）
- 阶段过滤：`VAD / ASR / LLM / TTS / HTTP / MCP / WAKE / SYS`（按行内容自动分类）
- 关键字搜索、暂停、清屏、超长行点击展开
- 自动跟随：**只在已经滚到底部时**才跟着新日志滚动；往上翻不会被打断，
  自己滚回底部就恢复跟随
- `空格` 暂停/恢复自动跟随；不在底部时右下角出现 `⬇ 最新` 按钮，
  点击立刻回到最新并恢复跟随
- WebSocket 断线自动重连（2s）

## HTTP 接口

| 路径 | 说明 |
|---|---|
| `/logs.html`（或 `/`） | 日志页面 |
| `/logs-ws` | 日志推送 WebSocket |
| `/api/sources` | 源列表 + 连接状态 / 行数 / 最后一行时间 |
| `/health` | `{"status":"ok","sources":[...]}` |

## 排障

| 现象 | 处理 |
|---|---|
| `[logs] 找不到 docker 命令` | 启动 Docker Desktop / 把 `docker` 放进 PATH |
| `[logs] docker logs 退出 (code 1)` | 容器名不对或容器没起：`docker ps -a` |
| `[logs] 日志文件不存在` | 对应组件还没启动过；启动后自动接上，无需重启面板 |
| 端口被占 | `LOG_VIEWER_PORT=8008 ... start` |
| 面板没反应 | `my_explorations/log-viewer/log-viewer.sh logs` |

## 与其他目录的边界

| 组件 | 属于 | 关系 |
|---|---|---|
| 日志面板（本目录） | 本目录 | 独立进程，只读日志 |
| digital-human 页面 / 唤醒词 (:8006) | `../digital-human/` | 面板消费它的 `wakeword-runtime.log`；digital-human 不再自带日志页 |
| 机器人后端 / 智控台 / MySQL / Redis | `../server/` | 面板消费两个容器的 `docker logs` |
