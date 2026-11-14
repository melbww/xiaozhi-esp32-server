# 组件关系图 (Component Relationships)

> 基于 `main/README.md` 与 `main/digital-human/` 实际代码梳理。
> 关键点:`digital-human` 的浏览器页面其实是**模拟的 ESP32 设备**,与真实硬件走同一套 WebSocket 协议。

## 全景关系图

```mermaid
flowchart TB
    subgraph ADMIN["管理侧 (管理员)"]
        WEB["manager-web<br/>Web管理界面 · Vue.js<br/>端口 8001"]
        MOBILE["manager-mobile<br/>手机/小程序管理端 · uni-app"]
    end

    subgraph BACKEND["后端服务"]
        API["manager-api<br/>管理后端 · Java Spring Boot<br/>端口 8002 · MySQL + Redis"]
        SERVER["xiaozhi-server<br/>核心AI引擎 · Python<br/>WS:8000 · OTA:8003"]
    end

    subgraph DEVICE["设备/客户端 (语音入口)"]
        ESP32["ESP32 实体硬件<br/>(真实设备)"]
    end

    subgraph DH["digital-human 数字人测试模块"]
        DHPAGE["浏览器测试页面<br/>= 模拟ESP32设备<br/>(Live2D数字人 + 麦克风 + 播放器)"]
        DHRT["本地Python运行时 · 端口8006<br/>页面服务 / 唤醒词Sherpa-ONNX / 事件桥"]
    end

    subgraph OBS["开发工具 (本机)"]
        LOGV["log-viewer · 端口8007<br/>实时日志面板"]
    end

    subgraph AI["外部AI服务"]
        AISVC["ASR / LLM / TTS / VAD<br/>(云端或本地)"]
    end

    %% 管理主线
    WEB -- "RESTful API (JSON)" --> API
    MOBILE -- "RESTful API (JSON)" --> API
    API -- "① 存配置/用户/设备" --> DB[("MySQL")]
    API -- "② 缓存热点数据" --> REDIS[("Redis")]
    SERVER -- "③ 启动/运行时拉取配置" --> API

    %% 语音主线 - 真实设备
    ESP32 -- "WebSocket 音频流 (8000)" <--> SERVER
    ESP32 -- "OTA 固件下载 (8003)" --> SERVER

    %% 语音主线 - 数字人(模拟设备)
    DHPAGE -- "WebSocket 音频流 (8000)<br/>同一套设备协议" <--> SERVER
    DHPAGE -- "OTA 握手获取WS地址+Token" --> SERVER
    DHPAGE -- "本地事件桥 ws://127.0.0.1:8006/wakeword-ws<br/>(本地·自包含)" <--> DHRT

    %% 日志观测(只读)
    LOGV -. "docker logs" .-> SERVER
    LOGV -. "docker logs" .-> API
    LOGV -. "tail 日志文件" .-> DHRT

    %% AI 服务
    SERVER -- "调用" --> AISVC

    %% 样式
    classDef dev fill:#fff3cd,stroke:#e6a700
    classDef backend fill:#d1ecf1,stroke:#0c5460
    classDef admin fill:#d4edda,stroke:#155724
    classDef ai fill:#f8d7da,stroke:#721c24
    class DH,ESP32 dev
    class OBS dev
    class API,SERVER backend
    class WEB,MOBILE admin
    class AISVC ai
```

## 一句话总结

| 组件 | 角色 | 语言/技术 | 端口 | 服务对象 |
|------|------|-----------|------|----------|
| `xiaozhi-server` | 核心AI引擎(大脑) | Python + asyncio | 8000 (WS), 8003 (OTA) | ESP32 设备 / 数字人模拟设备 |
| `manager-api` | 管理后端(行政部) | Java + Spring Boot | 8002 | 管理界面 + 给大脑提供配置 |
| `manager-web` | Web 管理界面 | Vue.js | 8001 | 管理员(浏览器) |
| `manager-mobile` | 移动管理端 | uni-app + Vue3 | 无固定 | 管理员(手机/小程序) |
| `digital-human` | 数字人测试模块 | Python + HTML/JS | 8006 (本地) | 开发者(无硬件测试) |
| `log-viewer` | 实时日志面板(排障) | Python (stdlib) + HTML/JS | 8007 (本地) | 开发者(看整栈日志) |

## 两条主线

1. **语音主线 (实时)**:ESP32 设备 或 digital-human 模拟设备 ⇄ `xiaozhi-server` (WebSocket)
2. **管理主线 (非实时)**:管理员通过 `manager-web` / `manager-mobile` → `manager-api` → 保存到 MySQL → `xiaozhi-server` 拉取配置生效

## digital-human 的双重身份

| 部分 | 自包含? | 与后端交互? |
|------|---------|-------------|
| Python 运行时 (`start.py` + `wakeword_runtime/`,端口 8006) | ✅ 完全本地 | ❌ 不交互 |
| 浏览器测试页面 (`index.html` + `js/`) | ❌ 需要后端 | ✅ 直接连 `xiaozhi-server` |

- **与后端的连接**:页面扮演"假 ESP32",走 OTA 握手 → WebSocket 连 `xiaozhi-server`,实现完整语音链路。
- **对 manager-api**:仅间接 (通过 xiaozhi-server 的配置/OTA 流程)。
- **本地自包含部分**:唤醒词检测 (Sherpa-ONNX) 与页面托管,完全不需要服务器。
