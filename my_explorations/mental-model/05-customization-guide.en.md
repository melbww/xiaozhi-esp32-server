# 05 · Customization Guide ("I want to change X" → where to go)

> Ordered by increasing effort. Rule of thumb: **prefer config over code, prefer plugins over core.**

## A. Config-only (no code)

| What you want | How |
|---------------|-----|
| Swap AI vendors (ASR/LLM/TTS/VAD) | Console → Model config, or `selected_module` in local `data/.config.yaml` |
| Change persona / personality | Console → Agent, or `prompt:` in `config.yaml` |
| Change wake words | Console / `wakeup_words:` in `config.yaml`; for digital-human use its page settings |
| Change ports / timezone / logging | `server:` / `log:` in `config.yaml` |
| Enable/disable certain built-in plugins | The `Intent.function_call.functions` list in `config.yaml` |
| Change device voice | Console → Voice management → push to device |

## B. Add a plugin / skill (a little code — the recommended path)

**Goal**: let the voice assistant do something new (track a package, turn on a light, quote stock prices...).

1. Create `my_tool.py` under `plugins_func/functions/` (copy `get_weather.py` as a template).
2. Write the JSON Schema description (name / description / params) so the LLM knows when to call it.
3. Decorate your `async def my_tool(conn, ...)` with `@register_function("my_tool", DESC, ToolType.XXX)`.
4. Add the module name to `Intent.function_call.functions` in `config.yaml` (or the console).
5. Restart / hot-reload. Done — **zero changes to the core pipeline.**

Key points: return `ActionResponse(Action.REQLLM, result, None)` = give the result back to the LLM to
phrase the reply; `Action.RESPONSE` = reply directly; `ToolType.IOT_CTL` = needs `conn` to control
devices / dialogue flow.

## C. Add a new AI vendor (moderate code)

**Goal**: integrate an ASR/LLM/TTS provider that isn't supported yet.

1. Read the abstract interface in the relevant `base.py` (e.g. `core/providers/asr/base.py` → `speech_to_text`).
2. Create `my_vendor.py` inheriting base; implement the interface (usually one async HTTP call).
3. Add a config block under the matching section in `config.yaml` (e.g. under `ASR:`) — model it on an existing entry.
4. Point `selected_module.ASR` at your name → `modules_initialize.py` wires it up automatically.
5. (Optional) register the vendor metadata in manager-api's `model` module so it's selectable in the console.

## D. Change engine internals (deeper)

| Goal | Where |
|------|-------|
| Change the dialogue main logic (context, tool loop) | `core/connection.py` → `chat()` |
| Change message routing / add message types | `core/handle/` + `textMessageType.py` |
| Change config loading / merge rules | `config/config_loader.py` |
| Change OTA / auxiliary HTTP endpoints | `core/http_server.py`, `core/api/` |
| Change device status reporting | `core/handle/reportHandle.py` |

## E. Change the management layer (Java)

| Goal | Where |
|------|-------|
| Add a REST API / business module | `modules/<new-module>/` (controller / service / dao / entity / dto) |
| Change login / permissions | `modules/security/`, Shiro config |
| Add a global param | `sys_params` (Liquibase seed data) |
| Change DB schema | Liquibase changelog |
| Change the admin UI | `manager-web` (Vue2) / `manager-mobile` (uni-app) |

## F. Change / add device side

| Goal | Where |
|------|-------|
| Change the digital-human test page (simulated device) | `main/digital-human/` (js/ and index.html) |
| Give a real ESP32 new capabilities | firmware repo `xiaozhi-esp32` (C++), reported via MCP tools |
| Change the device protocol | engine `core/handle/` + firmware protocol implementation, in sync |

## Decision tree: ask yourself before customizing

```
Behavior or management?
├─ Behavior (how voice is processed) → xiaozhi-server
│   ├─ swap vendor?   → config (A)
│   ├─ add a skill?   → add plugin (B)
│   ├─ integrate new AI? → add Provider (C)
│   └─ change dialogue logic? → core/connection.py (D)
└─ Management (config / accounts / device records)
    ├─ add API / table? → manager-api (E)
    └─ change UI?       → manager-web/mobile (E)
```

## Practical tips

- Use **digital-human + local xiaozhi-server** to iterate on plugins/Providers quickly — no hardware needed.
- Always prefer `data/.config.yaml` for config changes (keeps the default template clean, keys safe).
- When adding a plugin, first validate with `ToolType.NONE` + `Action.RECORD`, then graduate to `SYSTEM_CTL`.
- Watch `xiaozhi-server` logs (`log_dir: tmp/server.log`) after each change — hot-reload info is logged there.
