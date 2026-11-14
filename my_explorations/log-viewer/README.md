# log-viewer — 独立实时日志面板

**职责：** 在浏览器里实时看整个 desk-bot 栈的日志，一个页面里同时聚合：

| 源 (name) | 类型 | 指向 | 内容 |
|---|---|---|---|
| `server` | docker | 容器 `xiaozhi-esp32-server` | 机器人后端（VAD/ASR/LLM/TTS/HTTP/MCP） |
| `web` | docker | 容器 `xiaozhi-esp32-server-web` | 智控台 / manager-api |
| `runtime` | file | `main/digital-human/wakeword_runtime/logs/wakeword-runtime.log` | digital-human 唤醒词运行时 |

面板会把收到的每一行**自动落盘**（按天 + 按源分文件，带保留期），并按
`session_id` **自动归属到会话**；页面可以只看某个会话，也可以把所有会话折叠成分组视图。

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
`LOG_VIEWER_HOST=0.0.0.0`（那会把日志面板暴露到整个局域网；录制文件同样敏感）。

## 配置日志源

`sources.json`：

```json
{
  "history": 500,
  "record": {
    "enabled": true,
    "dir": "logs",
    "retention_days": 14,
    "max_file_mb": 64,
    "replay_recent": 500
  },
  "sources": [
    {
      "name": "server", "kind": "docker", "target": "xiaozhi-esp32-server", "tail": 20,
      "session": {
        "id": "\"session_id\"\\s*:\\s*\"([^\"]+)\"",
        "device": "'device-id':\\s*'([^']+)'",
        "end": "客户端断开连接",
        "sticky": true
      }
    },
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
| `session` | 可选：如何从这个源的日志里识别会话，见下 |
| `history` | 顶层字段：内存环形缓冲大小（帧数），重启后由录制文件回填 |

### 自动落盘（`record`）

| 字段 | 默认 | 说明 |
|---|---|---|
| `enabled` | `false` | 是否把每一帧写到磁盘 |
| `dir` | `logs` | 相对路径以**本目录**为基准，也可写绝对路径 |
| `retention_days` | `14` | 保留天数，启动时和每小时清理更老的日期目录 |
| `max_file_mb` | `64` | 单文件上限，超过后把 `server.jsonl` 改名为 `server.<HHMMSS>.jsonl` 继续写 |
| `replay_recent` | `200` | 启动时从录制文件回填多少帧到页面（方便重启后仍能看到刚才的日志） |

文件布局是 `<dir>/<YYYY-MM-DD>/<source>.jsonl`，一行一个 JSON，字段与推给浏览器的帧
完全一致（`source` / `level` / `line` / `ts` / `session` / `device`），所以既能回放也能直接查：

```sh
# 某个会话的完整日志
jq -c 'select(.session=="004fcf94-e1d8-451d-8f1b-926f78b98e8c")' \
  my_explorations/log-viewer/logs/2026-11-13/server.jsonl

# 所有错误
jq -r 'select(.level=="error") | "\(.source)\t\(.line)"' my_explorations/log-viewer/logs/*/*.jsonl

# 或者直接 grep
grep -h '识别文本' my_explorations/log-viewer/logs/*/server.jsonl
```

临时关掉录制：`python3 .../log_viewer.py --no-record`（或改 `sources.json`）。
`logs/` 已在 `.gitignore` 里，不会误提交。

### 会话分组（`session`）

每个源可选一段 `session` 规则，正则都用 `search` 匹配，取**第 1 个捕获组**：

| 字段 | 说明 |
|---|---|
| `id` | 匹配到就（重新）设定当前会话，例如 `"session_id":"<uuid>"` |
| `device` | 匹配到就记下设备标签（示例是 `device-id` 头里的 MAC） |
| `end` | 匹配到就把当前会话收尾（示例是 `客户端断开连接`），下一行起重新归属 |
| `sticky` | 默认 `true`：会话开始后，后面不带 id 的行都算这个会话（VAD/ASR/LLM/TTS 大多不带 id） |

后端会给帧加上 `session` / `device` 字段；页面据此提供「会话」下拉过滤和「👥 分组」视图。
直接打开 `http://127.0.0.1:8007/logs.html#group` 就是分组视图，
`#session=<session_id>` 可以直达某个会话。

> 归属是**按源、单条流**粘滞推断的：同一时刻一个源里只跟踪一个"当前会话"。
> 单设备（本项目的常态）完全够用；若真的多设备并发连同一后端，来自其它连接的
> 全局行可能被算到最近那个会话里。这时把 `sticky` 设为 `false`，只标记明确带
> `session_id` 的行。

检查解析结果：

```sh
python3 my_explorations/log-viewer/log_viewer.py --list-sources
```

## 页面能力

- 源过滤（按 `sources.json` 动态生成）、级别过滤（DEBUG/INFO/WARN/ERROR）
- 阶段过滤：`VAD / ASR / LLM / TTS / HTTP / MCP / WAKE / SYS`（按行内容自动分类）
- **会话过滤**：`全部 / 未归属 / #<session_id>`，下拉里带会话**开始时间**（`MM-DD HH:MM:SS`）和设备 MAC
- **会话分组**：同一会话的行折叠成一块，块头显示行数、时间范围、设备；点块头折叠/展开
- 关键字搜索、暂停、清屏、超长行点击展开
- 自动跟随：**只在已经滚到底部时**才跟着新日志滚动；往上翻不会被打断，
  自己滚回底部就恢复跟随
- `空格` 暂停/恢复自动跟随；不在底部时右下角出现 `⬇ 最新` 按钮，
  点击立刻回到最新并恢复跟随
- 暂停期间日志不丢：会先缓存在内存里，点「继续」后一次补齐（缓冲 3000 帧）
- WebSocket 断线自动重连（2s）
- 所有过滤/分组切换都是对已收帧重新渲染，不会出现"过滤前的老行还留在页面上"

## HTTP 接口

| 路径 | 说明 |
|---|---|
| `/logs.html`（或 `/`） | 日志页面 |
| `/logs-ws` | 日志推送 WebSocket（hello 帧带 `sources` / `sessions` / `recording`） |
| `/api/sources` | 源列表 + 连接状态 / 行数 / 最后一行时间 + 已知会话 |
| `/api/recordings` | 录制目录、保留天数、按天列出文件 |
| `/api/recordings/<date>/<source>?limit=2000&session=<id>` | 读取某个源某天的录制（ndjson） |
| `/health` | `{"status":"ok","sources":[...],"recording":{...}}` |

```sh
curl -s 'http://127.0.0.1:8007/api/recordings/2026-11-13/server?session=__none__' | head
```

## 排障

| 现象 | 处理 |
|---|---|
| `[logs] 找不到 docker 命令` | 启动 Docker Desktop / 把 `docker` 放进 PATH |
| `[logs] docker logs 退出 (code 1)` | 容器名不对或容器没起：`docker ps -a` |
| `[logs] 日志文件不存在` | 对应组件还没启动过；启动后自动接上，无需重启面板 |
| 端口被占 | `LOG_VIEWER_PORT=8008 ... start` |
| 面板没反应 | `my_explorations/log-viewer/log-viewer.sh logs` |
| 录制没文件 | 确认 `record.enabled=true`；启动日志里有 `recording : <dir>` 一行 |
| 会话下拉是空的 | 该源没配 `session`，或还没出现过带 `session_id` 的行（设备连一次即可） |
| 磁盘占用大 | 调小 `retention_days` / `max_file_mb`，删掉旧的日期目录即可 |

## 与其他目录的边界

| 组件 | 属于 | 关系 |
|---|---|---|
| 日志面板（本目录） | 本目录 | 独立进程，只读日志；录制写在 `logs/` |
| digital-human 页面 / 唤醒词 (:8006) | `../digital-human/` | 面板消费它的 `wakeword-runtime.log`；digital-human 不再自带日志页 |
| 机器人后端 / 智控台 / MySQL / Redis | `../server/` | 面板消费两个容器的 `docker logs` |
