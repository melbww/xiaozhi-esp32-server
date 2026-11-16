i saw there there are memory configs like below for the bot, create a series of excalidraw diagrams to illustrate them to help me build mental models

Memory_nomem
无记忆
nomem


Memory_mem_local_short
本地短期记忆（总结记忆）
mem_local_short


Memory_mem_report_only
仅上报聊天记录（不总结记忆）
mem_report_only


Memory_mem0ai
Mem0AI记忆
mem0ai


Memory_powermem
PowerMem记忆
powermem

---
help me draw a architecture diagram in excalidraw to illustrate the whole system, like the webconsole consle, docker, sql database, and whatever related; also add read along text in the diagram to make it self explanatory
---
| Traffic | Store | Volume character |
|---|---|---|
| Agent/model/timbre config | MySQL | fixed size, rare writes |
| Chat history / audio | MySQL | **grows without bound**, every turn |
| `last_connected_at`, `app_version` | MySQL | one row per device, every session |
| Captcha, SMS counters, activation codes, OTA handles, device-count cache | Redis | fixed/bounded, expires away |
| dict/model-name/timbre caches | Redis | fixed size, invalidated on edit |
