# digital-human 探索记录 (Exploration)

> 目标:把 `main/digital-human` 跑起来,验证"浏览器模拟 ESP32 + 本地唤醒词"链路,
> 并沉淀可复用的 IaC(脚本 + 容器化)。
> 行动追踪见 [SESSION_LOG.md](./SESSION_LOG.md)。

## 状态(2026-11-02)

| 组件 | 状态 |
|------|------|
| 后端全栈(对话引擎 :8000 / 智控台 :8002) | 已独立到 [`../server/`](../server/README.md) |
| 数字人运行时 :8006(唤醒词 + 页面 + 日志页) | ⏸ 已停(2026-11-08 与机器人解耦);仅浏览器测试时用 `iac/start.sh [--background]` 启动 |
| 页面 / Live Logs WebUI | http://127.0.0.1:8006/index.html · http://127.0.0.1:8006/logs.html(运行时启动后可用) |
| 日志 | 运行时:`main/digital-human/digital-human.log` |

> **边界（2026-11-09 拆分）:** 机器人后端（xiaozhi-server、manager-api、
> MySQL、Redis、部署 IaC 与运行数据）已移到
> [`my_explorations/server/`](../server/README.md)。本目录只保留浏览器模拟器
> 和本地唤醒词运行时；机器人链路不需要它。

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

### 启动/停止范围:谁控制什么(重要)

这套系统由**三个独立组件**组成,`start.sh/stop.sh` 只控制其中**一个**:

| 组件 | 由谁控制 | 作用 | 停了会怎样 |
|------|---------|------|-----------|
| **数字人运行时**(:8006) | `iac/start.sh` / `iac/stop.sh` | 页面托管 + 本地唤醒词检测 + 事件桥 | 页面打不开、唤醒词失效;**但已打开的浏览器页面仍能继续对话** |
| **对话引擎** xiaozhi-server(:8000) + 全栈(MySQL/Redis/manager :8002) | [`../server/iac/docker-stack.sh`](../server/iac/docker-stack.sh) `up / down` | ASR(SenseVoice)/LLM/TTS 全部重活 | 语音识别、LLM、TTS、对话全部停止 |
| **浏览器页面**(模拟 ESP32) | 浏览器标签页 | OTA 握手 → WS 直连 :8000 对话 | 关掉标签页 = 断开对话 |

> **关键认知**: 对话发生在 **浏览器页面 ↔ xiaozhi-server(:8000)** 之间,与运行时(:8006)**无关**。
> `stop.sh` 只停"唤醒词 + 页面托管";若浏览器标签页还开着且已连上 :8000,
> 服务器会继续用**页面麦克风**收音并回复(这就是"停了还在回答"的原因)。
> 想彻底停止对话:关闭浏览器标签页,或 `server/iac/docker-stack.sh down` /
> `docker stop xiaozhi-esp32-server`。

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

## 后端 (Desk Bot 01)

机器人后端不在本目录，已拆分到 [`../server/`](../server/README.md)：

- 启动/停止后端：`my_explorations/server/iac/docker-stack.sh up|down|status`
- 首次引导、智控台、OTA/WS 参数、日志、冒烟测试：见 [server/README.md](../server/README.md)
- 本地低延迟 TTS：见 [../local-say-tts/README.md](../local-say-tts/README.md)

本目录只负责浏览器模拟器（模拟 ESP32）和本地唤醒词运行时。
