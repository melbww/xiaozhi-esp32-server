#!/usr/bin/env bash
# =============================================================================
# macOS 本地 say TTS 服务管理 (供 xiaozhi-server CustomTTS 调用)
#
# 用法 (在仓库根目录):
#   my_explorations/local-say-tts/local-say-tts.sh start   # 后台启动, 端口 8880
#   my_explorations/local-say-tts/local-say-tts.sh stop    # 停止
#   my_explorations/local-say-tts/local-say-tts.sh status  # 查看状态
#   my_explorations/local-say-tts/local-say-tts.sh logs    # tail 日志
#
# 说明:
#   - 仅 macOS 可用, 使用系统 say + afconvert, 无需联网/API Key
#   - 服务监听 0.0.0.0:8880, Docker 内通过 host.docker.internal:8880 访问
#   - 音色可用 SAY_TTS_VOICE 覆盖, 例如 Tingting(大陆)、Meijia(台湾)、Sinji(粤语)
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/my_explorations/local-say-tts/local-say-tts.py"
PID_FILE="$ROOT/my_explorations/local-say-tts/.local-say-tts.pid"
LOG_FILE="$ROOT/my_explorations/local-say-tts/local-say-tts.log"
PORT="${SAY_TTS_PORT:-8880}"

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "${1:-start}" in
  start)
    if is_running; then
      echo "already running (pid $(cat "$PID_FILE"), port $PORT)"
      exit 0
    fi
    command -v say >/dev/null || { echo "macOS say not found" >&2; exit 1; }
    command -v afconvert >/dev/null || { echo "macOS afconvert not found" >&2; exit 1; }
    nohup python3 "$SCRIPT" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if ! is_running; then
      echo "failed to start; see $LOG_FILE" >&2
      tail -20 "$LOG_FILE" >&2 || true
      exit 1
    fi
    echo "started local say TTS (pid $(cat "$PID_FILE"))"
    echo "  endpoint: http://127.0.0.1:$PORT/tts"
    echo "  docker:   http://host.docker.internal:$PORT/tts"
    echo "  health:   http://127.0.0.1:$PORT/health"
    echo "  voice:    ${SAY_TTS_VOICE:-Meijia} (override with SAY_TTS_VOICE)"
    echo "  log:      $LOG_FILE"
    ;;
  stop)
    if is_running; then
      kill "$(cat "$PID_FILE")"
      rm -f "$PID_FILE"
      echo "stopped"
    else
      rm -f "$PID_FILE"
      echo "not running"
    fi
    ;;
  status)
    if is_running; then
      echo "running (pid $(cat "$PID_FILE"), port $PORT)"
      curl -s -m 3 "http://127.0.0.1:$PORT/health" || true
      echo
    else
      echo "not running"
      exit 1
    fi
    ;;
  logs)
    tail -f "$LOG_FILE"
    ;;
  *)
    echo "usage: $0 {start|stop|status|logs}" >&2
    exit 2
    ;;
esac
