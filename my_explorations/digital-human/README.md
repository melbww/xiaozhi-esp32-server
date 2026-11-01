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
