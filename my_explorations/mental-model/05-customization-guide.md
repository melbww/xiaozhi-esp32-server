# 05 · 定制指南("我想改 X" → 去哪里改)

> 按"改造成本从低到高"排列。原则:**能改配置就不改代码,能加插件就不动核心。**

## A. 纯配置(不写代码)

| 想做什么 | 怎么做 |
|----------|--------|
| 换 AI 供应商(ASR/LLM/TTS/VAD) | 智控台「模型配置」,或本地 `data/.config.yaml` 的 `selected_module` |
| 改人设/性格 | 智控台 Agent 角色,或 `config.yaml` 的 `prompt:` |
| 改唤醒词 | 智控台 / `config.yaml` 的 `wakeup_words:`;数字人唤醒词在其页面设置 |
| 改端口/时区/日志 | `config.yaml` 的 `server:` / `log:` |
| 开/关某些内置插件 | `config.yaml` 的 `Intent.function_call.functions` 列表 |
| 改设备音色 | 智控台「音色管理」→ 下发到设备 |

## B. 加插件/技能(少量代码,推荐路径)

**目标**:让语音助手能做一件新的事(查快递、开灯、报股票……)。

1. 在 `plugins_func/functions/` 新建 `my_tool.py`(复制 `get_weather.py` 作模板)。
2. 写 JSON Schema 描述(名字/说明/参数),让 LLM 知道何时调用。
3. `@register_function("my_tool", DESC, ToolType.XXX)` 装饰你的 `async def my_tool(conn, ...)`。
4. 在 `config.yaml`(或智控台)的 `Intent.function_call.functions` 加上模块名。
5. 重启/热加载,完事。**核心流水线零改动。**

要点:返回 `ActionResponse(Action.REQLLM, result, None)` = 结果回给 LLM 组织语言;
`Action.RESPONSE` = 直接回复;`ToolType.IOT_CTL` = 需要 `conn` 操作设备/对话流。

## C. 加一个新的 AI 供应商(中等代码)

**目标**:接入一个当前没有的 ASR/LLM/TTS 服务商。

1. 看对应目录的 `base.py` 抽象接口(如 `core/providers/asr/base.py` 的 `speech_to_text`)。
2. 新建 `my_vendor.py`,继承 base,实现接口(通常就是一个异步 HTTP 调用)。
3. 在 `config.yaml` 对应小节(如 `ASR:`)加一段配置块(可参考同类型已有条目)。
4. `selected_module.ASR` 改成你的名字 → `modules_initialize.py` 会自动装配。
5. (可选)在 manager-api 的 `model` 模块注册供应商元数据,让智控台可选。

## D. 改引擎内部行为(较深)

| 目标 | 位置 |
|------|------|
| 改对话主逻辑(上下文、工具循环) | `core/connection.py` 的 `chat()` |
| 改消息路由/加新消息类型 | `core/handle/` + `textMessageType.py` |
| 改配置加载/合并规则 | `config/config_loader.py` |
| 改 OTA/HTTP 辅助接口 | `core/http_server.py`, `core/api/` |
| 改设备状态上报处理 | `core/handle/reportHandle.py` |

## E. 改管理层(Java)

| 目标 | 位置 |
|------|------|
| 新增 REST 接口/业务模块 | `modules/<新模块>/`(controller/service/dao/entity/dto) |
| 改登录/权限 | `modules/security/`, Shiro 配置 |
| 加全局参数项 | `sys_params`(Liquibase 初始数据) |
| 改数据库结构 | Liquibase changelog |
| 改前端管理界面 | `manager-web`(Vue2) / `manager-mobile`(uni-app) |

## F. 改/加设备侧

| 目标 | 位置 |
|------|------|
| 改数字人测试页(模拟设备) | `main/digital-human/`(js/ 与 index.html) |
| 给真实 ESP32 加能力 | 固件仓库 `xiaozhi-esp32`(C++),经 MCP 工具上报 |
| 改设备协议 | 引擎侧 `core/handle/` + 固件侧协议实现,两侧同步 |

## 决策树:定制前先问自己

```
要改的是"行为"还是"管理"?
├─ 行为(语音怎么处理) → xiaozhi-server
│   ├─ 换服务商?        → 改配置 (A)
│   ├─ 加技能?          → 加插件 (B)
│   ├─ 接新 AI?         → 加 Provider (C)
│   └─ 改对话逻辑?      → core/connection.py (D)
└─ 管理(配置/账号/设备档案)
    ├─ 加接口/表?       → manager-api (E)
    └─ 改界面?          → manager-web/mobile (E)
```

## 实践建议

- 先用 **digital-human + 本机 xiaozhi-server** 快速试插件/Provider,别急着碰硬件。
- 改配置永远优先 `data/.config.yaml`(不污染默认模板、不泄露密钥)。
- 加插件时先用 `ToolType.NONE` + `Action.RECORD` 小步验证,再上 `SYSTEM_CTL`。
- 每次改动看 `xiaozhi-server` 日志(`log_dir: tmp/server.log`),热加载信息会打在里面。
