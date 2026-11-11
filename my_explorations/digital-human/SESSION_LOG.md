# SESSION LOG — digital-human 上手指南

> 记录实际执行的每一个动作、结果与结论,便于复盘与复现。
> 日期:2026-11-01。环境:macOS (Apple Silicon), Python 3.13.9。
>
> **历史说明:** 2026-11-09 起后端（docker-stack、deploy、bootstrap）已拆分到
> `my_explorations/server/`。本文保留当时的原始路径记录。

## 动作记录

| # | 时间 | 动作 | 结果 / 备注 |
|---|------|------|-------------|
| 1 | 17:17 | 阅读 `main/README.md` + 检查 `digital-human/` 代码 | 确认页面 = 模拟 ESP32;运行时 = 本地自包含 |
| 2 | 17:17 | 绘制并落盘组件关系图 / 迁移图到 `docs/my_exploration/` | 已同步到 `my_explorations/docs/` |
| 3 | 17:21 | 检查 Python 环境 | 有 3.13.9 / 3.11.15;3.14 无适配 wheel 风险,选用 3.13 |
| 4 | 17:21 | `python3.13 -m venv .venv` + `pip install -r requirements.txt` | ✅ 成功(sherpa-onnx 1.12.29 arm64 wheel) |
| 5 | 17:22 | 后台下载唤醒词模型(GitHub Releases, 31.1MB) | ✅ 12s 完成 |
| 6 | 17:22 | 编写 IaC:`setup.sh` / `start.sh` / `stop.sh` / `docker-compose.yml` | 见 `iac/` |
| 7 | 17:23 | 运行 `setup.sh` 端到端验证(venv+依赖+模型下载+重命名) | ✅ 全部 [ok],生成 `models/{encoder,decoder,joiner}.onnx + tokens.txt` |
| 8 | 17:23 | `start.sh --background` 首次启动 | ❌ 崩溃:`ModuleNotFoundError: No module named 'numpy'` |
| 9 | 17:23 | **修复 bug**:`requirements.txt` 补 `numpy>=1.26.0`(detector.py 模块级 import) | ✅ 重新安装后 imports 全部 OK |
| 10 | 17:23 | 再次启动 | ✅ 健康检查 `{"status":"ok"}`,index.html HTTP 200,麦克风+唤醒词检测启动 |
| 11 | 17:24 | 验证唤醒词 WebSocket 事件桥 | ✅ HTTP/1.1 101 Switching Protocols |
| 12 | 17:24 | 发现 start.sh PID 捕获错误(子shell 导致),重写 start/stop 脚本 | 见下方「脚本修正」 |
| 13 | 17:24 | stop.sh → start.sh 干净重启 | ✅ PID 文件指向真实 python 进程(57066),健康检查通过 |
| 14 | 17:30 | 启动 Docker Desktop(daemon 未运行) | ✅ 就绪(aarch64 / Docker 29.2.1) |
| 15 | 17:31 | 检查全栈 compose 与镜像 | ✅ `server_latest`/`web_latest` **含 arm64 变体**(文档仍写 x86-only,已过时);registry 可达 |
| 16 | 17:32 | 检查本地模型 | ✅ silero-vad 齐全;❌ `SenseVoiceSmall/model.pt` 缺失(约 1GB) |
| 17 | 17:33 | 后台下载 SenseVoiceSmall model.pt(ModelScope) | ⏳ 约 1GB,下载中 |
| 18 | 17:34 | 创建部署目录 `deploy/`(data/.config.yaml + models 软链 + uploadfile) | ✅ 复用仓库 compose 不改动仓库文件 |
| 19 | 17:35 | 确认 OTA 归属:全栈模式下 `/xiaozhi/ota/` 由 **manager-api(:8002)** 提供 | ✅ 与 digital-human 页面默认 OTA 地址一致 |
| 20 | 17:35 | 梳理 manager-api 引导流程 | 注册需 SM2 加密密码 + 图形验证码(验证码明文存 Redis `sys:captcha:<uuid>`) |
| 21 | 17:36 | 编写 `bootstrap-admin.py`(SM2+captcha+register+login+取 server.secret) | ✅ gmssl 已装入 digital-human venv |
| 22 | 17:36 | 编写 `docker-stack.sh`(up/down/status/logs/restart/bootstrap) | ✅ chmod +x |
| 23 | 17:36 | `docker compose pull` 全量镜像 | ⏳ redis 完成;server/web/mysql 拉取中 |
| 24 | 18:00 | 修复 deploy/models 符号链接:绝对路径 → 相对路径 `../../../main/xiaozhi-server/models` | ✅ 可移植;git 中显示为文件(120000 符号链接模式)属正常 |
| 25 | 18:05 | 诊断 web_latest 拉取卡死 | ❌ 日志显示 `short read ... unexpected EOF`——镜像源断流,非网络封锁 |
| 26 | 18:05 | **网络诊断结论(中国网络)** | `ghcr.nju.edu.cn` 国内镜像直连可达(60ms);本地已有代理 7897(Clash);`NO_PROXY` 含 `.cn`,TUN 模式对国内镜像无意义 → **无需 VPN/TUN** |
| 27 | 18:06 | 编写镜像回退 override `deploy/docker-compose.mirror.yml`(DaoCloud/1ms) | ✅ 备选 |
| 28 | 18:06 | 后台重试 web_latest 拉取(带 3 次重试) | ⏳ 进行中 |

## 全栈联调阶段 (2026-11-01 晚)

| # | 时间 | 动作 | 结果 |
|---|------|------|------|
| 29 | 20:3x | 诊断 web_latest 拉取卡死:镜像源断流 + **本地层缓存损坏**(digest mismatch) | 与网络封锁无关;**无需 VPN/TUN** |
| 30 | 20:3x | `docker system prune` 清理 12.6GB 损坏/悬空数据 | ✅ |
| 31 | 20:4x | 换 **ghcr.1ms.run** 镜像拉取 web_latest | ✅ 约 20s 完成(比 NJU 快得多),retag 为 nju 名 |
| 32 | 20:4x | `docker compose up -d` 全栈启动 | ✅ 4 容器全 Up;db/redis healthy;manager-api HTTP 200 |
| 33 | 20:5x | 引擎容器 crash-loop(placeholder secret)→ bootstrap 脚本 | 见下方「bootstrap 排障」 |
| 34 | 20:5x | `server.secret` 回填 `.config.yaml` + restart 引擎 | ✅ 引擎成功连上 manager-api,VAD/ASR(FunASR+SenseVoice)初始化成功,WS 监听 :8000 |
| 35 | 20:5x | OTA 冒烟测试 | ⚠️ 返回占位地址 `ws://xiaozhi.server.com:8000` |
| 36 | 20:5x | 用 API 把 `server.websocket` 参数改为 `ws://192.168.1.6:8000/xiaozhi/v1/` | ✅ 通过服务端 WS 连通校验 |
| 37 | 20:5x | 复测 OTA + WS hello | ✅ OTA 返回正确 LAN 地址;WS 端口连通;引擎回复"端口正常…请启动digital-human测试"(设备未绑定的提示) |

## bootstrap 排障记录 (重要踩坑)

1. **验证码带字面引号**:Redis 中验证码存为 `'"7tHd8"'`(redisUtils JSON 序列化加了引号),
   直接读出来当验证码会失败 → 脚本需 `strip('"')` 并校验长度=5。
2. **HTTP 200 ≠ 成功**:接口业务失败时 HTTP 状态仍是 200,body 里 `code:10067`。
   脚本必须检查 `resp["code"] == 0`,否则会误报"注册成功"。
3. **验证码接口返回 GIF 图片**:`http()` 需容忍非 JSON 响应(图片)。
4. **更新参数需完整 DTO**:`server.websocket` 更新报 `Value type cannot be empty`,
   PUT 时必须带上 `valueType` 字段。

## 当前运行状态 (2026-11-01 21:00)

| 项 | 状态 |
|----|------|
| digital-human 页面 | ✅ :8006 |
| xiaozhi-server 引擎 | ✅ :8000(WS) / :8003(OTA/视觉),已连 manager-api,本地 ASR 就绪 |
| manager-api + 智控台 | ✅ :8002(HTTP 200,doc.html 可用) |
| MySQL / Redis | ✅ healthy |
| 管理员账号 | ✅ admin / Admin@123456(首次注册=超管) |
| OTA 握手 → WS 连通 | ✅ 链路通 |
| **语音对话** | ⏳ 待办:①智控台把设备绑定到 Agent ②配置 LLM API Key |
| 遗留 | 唤醒词仍在 PC(数字人)或固件内;manager-web 的 nginx 端口 8001 未单独暴露(web 与 api 同镜像) |

## 待办清单 (用户操作)

1. 浏览器打开 **http://127.0.0.1:8002** 登录 admin / Admin@123456。
2. 在「设备管理」把冒烟测试/digital-human 的 MAC 注册并绑定到某个智能体(Agent)。
3. 在「模型配置」添加一个 **LLM**(如智谱免费 glm-4-flash)并绑到该 Agent。
4. 打开数字人页面 http://127.0.0.1:8006/index.html,OTA 地址保持
   `http://127.0.0.1:8002/xiaozhi/ota/`,点连接即可全链路语音对话。

## 网络/镜像结论 (2026-11-01, 中国网络)

- 镜像源 `ghcr.nju.edu.cn`(南京大学 GHCR 镜像)国内直连, 响应 60ms。
- web_latest 体积大(数 GB), 镜像源大文件传输偶发 `unexpected EOF` 断流。
- **不需要 TUN 模式**: 国内镜像源直连即可; 本地已有代理(127.0.0.1:7897),
  且 `NO_PROXY` 含 `.cn` 会使国内镜像绕过代理。
- 若 NJU 镜像反复断流, 用 `deploy/docker-compose.mirror.yml` 切换到 DaoCloud / 1ms 镜像。
- 只有需要直连 `ghcr.io` 原始源(例如拉其他 GitHub 容器镜像)时才需要代理/TUN,
  届时可给 Docker Desktop 配置代理(设置 → Resources → Proxies → 127.0.0.1:7897)。

## 脚本修正记录

### start.sh (重写)
- 问题:后台分支用子 shell `( ... & echo $! > pid )`,`$!` 捕获到外层 bash 而非 python;
  且引用了未实现的 `--check` 模式。
- 修正:去掉子 shell,直接 `nohup ... &` 捕获真实 PID;补 `--background` 幂等(已在运行则退出);
  前台模式用 `exec`。

### stop.sh (增强)
- 杀掉 PID 文件进程时同时 `pkill -P` 清理子进程,避免遗留孤儿;
- 增加 `pgrep -f "python.*start.py"` 回退,防止 PID 文件失效时停不掉。

## 环境信息(复现用)

```
OS:            macOS (Apple Silicon)
Python:        3.13.9 (venv: main/digital-human/.venv)
依赖:          sherpa-onnx==1.12.29, sounddevice==0.5.6, pypinyin==0.55.0, numpy
模型:          sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01 (epoch-99 fp32)
端口:          8006 (页面/事件桥/健康检查)
忽略规则:      仓库 .gitignore 已忽略 .venv 与 wakeword_runtime/models
```

## 遗留事项 / 观察

- [ ] `xiaozhi-server` 未在本机运行,数字人页面暂不能联调语音 AI 链路(需另起 server)。
- [ ] Docker IaC 仅在 Linux 宿主机可用(麦克风 `/dev/snd` 透传);macOS 请用脚本。
- [ ] 唤醒词模型下载源为 GitHub,国内网络可能需要代理或改用 ModelScope。

## 2026-11-12 · 日志面板拆分为独立应用

- 原 `main/digital-human/logs.html` + `wakeword_runtime/log_streamer.py` 虽然挂在
  digital-human(:8006)上,实际同时 tail `docker logs xiaozhi-esp32-server` 和本模块日志,
  并不属于数字人本身。
- 已拆到 [`../log-viewer/`](../log-viewer/README.md)(:8007):独立的 stdlib HTTP+WebSocket
  服务,日志源在 `sources.json` 配置(`docker` / `file`),不依赖 digital-human 是否运行。
- digital-human 运行时现在只负责页面托管 + 唤醒词 + 事件桥(:8006);`logs.html`、
  `log_streamer.py` 及 `http_server.py` 里的 `/logs-ws` 路由已移除。
