# digital-human 探索记录 (Exploration)

> 目标:把 `main/digital-human` 跑起来,验证"浏览器模拟 ESP32 + 本地唤醒词"链路,
> 并沉淀可复用的 IaC(脚本 + 容器化)。
> 行动追踪见 [SESSION_LOG.md](./SESSION_LOG.md)。

## 状态: ✅ 运行中

| 项 | 值 |
|----|----|
| 页面 | http://127.0.0.1:8006/index.html |
| 唤醒词事件桥 | ws://127.0.0.1:8006/wakeword-ws |
| 健康检查 | http://127.0.0.1:8006/health → `{"status":"ok"}` |
| 进程 | PID 见 `.digital-human.pid`(由 start.sh 维护) |
| 日志 | `main/digital-human/digital-human.log` |
| 唤醒词 | 已启用,模型已就位,默认词表(你好小智 等) |

## 全栈联调状态(2026-11-01)

| 项 | 状态 |
|----|------|
| xiaozhi-server | ✅ :8000(WS)/:8003,已连 manager-api,本地 ASR(FunASR+SenseVoice)就绪 |
| manager-api + 智控台 | ✅ :8002(admin / Admin@123456) |
| MySQL / Redis | ✅ healthy |
| OTA 握手 → WS 连通 | ✅ 链路通(server.websocket 已设为 LAN 地址) |
| 语音对话 | ⏳ 需在智控台①绑定设备到 Agent ②配 LLM Key |
| 运维 | `iac/docker-stack.sh up / down / status / logs / restart / bootstrap` |

**快速开始语音对话**:浏览器开 http://127.0.0.1:8002 登录 → 设备绑定 Agent →
模型配置加 LLM(如智谱免费 glm-4-flash)→ 数字人页面点连接。

## 一键使用

```bash
# 1. 环境准备(venv + 依赖 + 下载唤醒词模型, 幂等)
my_explorations/digital-human/iac/setup.sh

# 2. 启动(前台) 或 后台
my_explorations/digital-human/iac/start.sh
my_explorations/digital-human/iac/start.sh --background

# 3. 停止
my_explorations/digital-human/iac/stop.sh
```

## 这个模块是什么(一句话)

它有两部分:

1. **浏览器测试页面**(`index.html` + `js/`)= **模拟的 ESP32 设备**。
   走与真实硬件完全相同的协议:OTA 握手 → WebSocket 连 `xiaozhi-server`(8000),
   实现语音识别/LLM/TTS 全链路,并在浏览器里用 Live2D 数字人呈现。
2. **本地 Python 运行时**(`start.py` + `wakeword_runtime/`,端口 8006)= **自包含**。
   承载页面服务、Sherpa-ONNX 本地唤醒词检测、以及页面↔运行时的 WebSocket 事件桥。

## 本地环境实测结论

- Python 3.13.9 (venv) 可运行;sherpa-onnx 1.12.29 有 macOS arm64 wheel。
- **发现并修复一个 bug**:`requirements.txt` 缺少 `numpy`(被 `core/detector.py`
  模块级 import),导致全新 venv 启动即崩溃。已在仓库内补上 `numpy>=1.26.0`。
- 唤醒词模型(~31MB)需从 GitHub Releases 下载(GitHub 可能较慢/被墙,
  备选 ModelScope 方案见 `docs/digital-human-wakeword.md`)。
- 页面与 `xiaozhi-server` 交互需要后者也在运行;纯本地测试(页面+唤醒词)则无需。

## 关键文件索引

| 路径 | 说明 |
|------|------|
| `main/digital-human/start.py` | 运行时入口 |
| `main/digital-human/wakeword_runtime/config.json` | 唤醒词开关/模型目录/音频/检测参数 |
| `main/digital-human/wakeword_runtime/requirements.txt` | 依赖(已补 numpy) |
| `main/digital-human/js/core/network/ota-connector.js` | OTA 握手(模拟设备注册) |
| `main/digital-human/js/core/network/websocket.js` | 与 xiaozhi-server 的 WS 协议实现 |
| `docs/digital-human-wakeword.md` | 官方模型下载/配置说明 |

## 相关探索文档

- [组件关系图](../docs/component-relationships.md)
- [数字人 → ESP32 硬件迁移](../docs/digital-human-to-esp32-migration.md)

---

## 全栈联调 (digital-human ↔ xiaozhi-server ↔ manager-api)

数字人页面要跑通完整语音链路,还需要 `xiaozhi-server`(WS:8000 / OTA:8003)
和 `manager-api`(8002,含 manager-web 智控台 + MySQL + Redis)。

### IaC: `iac/docker-stack.sh`

```bash
my_explorations/digital-human/iac/docker-stack.sh up         # 拉镜像 + 启动全栈
my_explorations/digital-human/iac/docker-stack.sh bootstrap  # 自动注册管理员 + 回填 server.secret
my_explorations/digital-human/iac/docker-stack.sh restart    # 重启 xiaozhi-server 使配置生效
my_explorations/digital-human/iac/docker-stack.sh status     # 查看容器状态
my_explorations/digital-human/iac/docker-stack.sh logs web   # 查看 manager-api 日志
my_explorations/digital-human/iac/docker-stack.sh down       # 停止
```

> **开发调试覆盖**: `iac/compose.server-source.yml` 会被 docker-stack.sh 自动加载, 把
> 本地 `main/xiaozhi-server/core` bind-mount 进容器, 使 core 下的源码改动
> (含下方 LLM 请求/响应全文日志)即时生效, 无需重新构建镜像;
> 同时把容器内 `tmp/`(server.log)落盘到 `deploy/logs/`, 容器重建不丢日志。
> 不需要时删除该文件(或去掉 COMPOSE_ARGS 中的 `-f` 即可)。

### 查看 LLM 完整请求/响应日志(远端 LLM 往返)

默认日志(INFO)只显示 `大模型收到用户消息` / `HTTP Request: ... 200 OK` / TTS 分段。
已在本仓库 `core/providers/llm/openai/openai.py` 打了补丁(随上述覆盖自动生效),
现在每轮对话会额外打印**发给远端 LLM 的完整 JSON**(messages/tools)和**流式响应的全文**:

```bash
docker-stack.sh logs server            # 或 docker logs -f xiaozhi-esp32-server
# 只看 LLM 往返:
docker logs -f xiaozhi-esp32-server 2>&1 | grep -E "LLM 请求|LLM 响应全文|LLM 工具调用|HTTP Request: POST|大模型收到用户消息"
# 持久化日志(容器内 tmp/ 已落盘到主机):
tail -f my_explorations/digital-human/deploy/logs/server.log
```

日志形状: `LLM 请求 -> https://api.deepseek.com model=deepseek-flash messages=[{...全文...}]`,
回复时 `LLM 响应全文: ...`(带工具调用时另有 `LLM 工具调用: [...]`)。

### 查看语音转文字(ASR)实时过程日志

VAD/SenseVoice 已加实时埋点(INFO 级), 说话时 `tail -f` 即可看到全过程:

```bash
tail -f my_explorations/digital-human/deploy/logs/server.log
# 只看语音相关:
grep -E "\[VAD\]|\[ASR\]" my_explorations/digital-human/deploy/logs/server.log
```

说话 → 识别的完整日志流(实时):

```text
[VAD] 语音开始
[VAD] 说话中... 已 1320ms, 当前电平 18432/32768     ← 约每秒一条, 说话时实时刷新
[VAD] 语音结束, 说话时长 1980ms, 峰值电平 30120/32768
[ASR] 开始识别, 音频 63360 字节 (1.98s @16kHz单声道)
[ASR] 引擎识别耗时: 3.312s | 结果: 你可以查询下新闻吗？
[ASR] 识别完成, 耗时 3.351s
识别语言: zh
识别情绪: 😶
识别文本: 你可以查询下新闻吗？
```

> 提示: 当前是离线 SenseVoice, 识别在说完话后才开始(耗时约 1.2~1.5× 音频时长)。
> 想边说话边出字(流式), 需换 streaming ASR 引擎(见对话记录), 暂未启用。



### 要点

- 复用仓库 `main/xiaozhi-server/docker-compose_all.yml`,通过 `--project-directory`
  把 `data/`、`models/`、`mysql/`、`uploadfile/` 解析到 `deploy/` 目录,不改动仓库文件。
- 官方镜像 **server_latest / web_latest 已含 arm64 变体**(`Deployment_all.md` 说 x86-only 已过时)。
- 首次启动引导(被 SM2 加密 + 图形验证码挡住的手动步骤)由 `bootstrap-admin.py` 自动化:
  从 Redis 直接读验证码明文,用 gmssl(SM2 C1C3C2)加密,注册首个超级管理员,再读取
  `server.secret` 回填 `deploy/data/.config.yaml`。
- OTA 归属:全栈模式下 `/xiaozhi/ota/` 由 **manager-api(:8002)** 提供,与数字人页面
  默认 OTA 地址一致;单服务模式下才是 xiaozhi-server 的 8003。
- 本地 ASR 依赖 `SenseVoiceSmall/model.pt`(约 1GB,ModelScope 下载),VAD 模型已就位。
- **语音 AI 仍需用户提供 LLM API Key**(如智谱免费 `glm-4-flash`),在智控台模型配置中填写。
