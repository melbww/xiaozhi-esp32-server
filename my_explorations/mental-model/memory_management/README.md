# Memory 模式图解

一组 Excalidraw 图，用来建立「小智的记忆到底怎么工作」的心智模型。
每张图都有 `.excalidraw`（可继续编辑）和 `.png`（直接看）两份。

| 文件 | 讲什么 |
|---|---|
| `00-overview.png` | 五个 Memory 模式的对照表：留下什么 / 注入什么 / 怎么取回 / 钱和隐私 |
| `01-lifecycle.png` | 所有模式共用的生命周期：**读**发生在每一轮 LLM 调用前，**写**发生在连接关闭后 |
| `02-nomem.png` | 无记忆：写是空操作，读永远返回空字符串 |
| `03-mem-local-short.png` | 本地摘要：旧摘要 + 新对话 → LLM 重写一份 JSON，下一场整份回放 |
| `04-mem-report-only.png` | 只上报：聊天记录进管理端 DB 给人和后台看，但读路径被切断 |
| `05-mem0ai.png` | 托管记忆：整段上传 → 云端抽事实建向量 → 每轮语义检索 top-k |
| `06-powermem.png` | 自托管记忆：同一套 add/search，但 LLM、Embedding、向量库都是你自己的 |
| `07-what-is-stored.png` | 同一句话，五种模式各自记成什么形状 |
| `08-choose.png` | 三个问题选出该用哪个模式 |

## 一句话心智模型

**记忆 = 写什么（会话结束）× 存成什么形状 × 怎么读回来（每一轮）。**

五个选项只是在这三件事上给了不同答案：

- `nomem`：不写、不读。
- `mem_report_only`：写的是**日志**，但没有人读回给模型。
- `mem_local_short`：写的是**一份会被重写的摘要**，读回来是**整份回放**。
- `mem0ai` / `powermem`：写的是**一条条事实**，读回来是**按这句话检索出的几条**。

## 容易混的三个点

1. **`mem_report_only` 不是「弱一点的记忆」**，它根本没有读路径。它的价值是留档（后台可回看、可生成总结/标题），而不是让机器人记得你。
2. **`mem_local_short` 不检索**。`query_memory()` 直接把整份摘要原样返回，塞进 system prompt 的 `<memory>` 块，每轮都一样。摘要超过约 900 字时会触发淘汰（低权重、3 轮未提及的先删），所以它记的是**结论**，不是原话。
3. **记忆按设备，不按会话**。`init_memory(role_id=self.device_id)`：同一台设备换一场对话，记忆还在；换设备就是另一份记忆。

## 两个容易忽略的实现细节

- **写是异步的**：连接关闭后开守护线程保存，不等写完就断线；所以关掉服务太急可能丢最后一次保存。
- **`mem_local_short` 有两种落盘方式**：单机 `save_to_file=True` 写 `data/.memory.yaml`；接管理端（`read_config_from_api=True`）时改为调 `POST /agent/chat-summary/{session_id}/save`，下一场通过 `summaryMemory` 回填。

## 对应代码

- 生命周期：`main/xiaozhi-server/core/connection.py`（每轮 `query_memory` 约 1129 行；断线 `save_memory` 约 326 行）
- 注入点：`main/xiaozhi-server/core/utils/dialogue.py` 的 `get_llm_dialogue_with_memory()`，替换 `<memory>…</memory>`
- 实现：`main/xiaozhi-server/core/providers/memory/{nomem,mem_local_short,mem_report_only,mem0ai,powermem}/`
- 配置：`main/xiaozhi-server/config.yaml` 的 `selected_module.Memory` 与 `Memory:` 段

## 打开方式

- 画布（最后一张图）：<http://127.0.0.1:3000>
- 继续编辑某张图：`npx -y mcp-excalidraw-server import <file>.excalidraw --replace`
- 重新导出图片：`npx -y mcp-excalidraw-server screenshot --out x.png --scale 2`
