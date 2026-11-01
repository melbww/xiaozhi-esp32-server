# SESSION LOG — digital-human 上手指南

> 记录实际执行的每一个动作、结果与结论,便于复盘与复现。
> 日期:2026-11-01。环境:macOS (Apple Silicon), Python 3.13.9。

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
