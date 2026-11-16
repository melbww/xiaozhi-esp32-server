#!/usr/bin/env bash
# =============================================================================
# 独立日志查看器 (log-viewer) 管理脚本
#
# 用法 (在仓库任意位置执行均可):
#   my_explorations/log-viewer/log-viewer.sh start
#   my_explorations/log-viewer/log-viewer.sh stop
#   my_explorations/log-viewer/log-viewer.sh restart
#   my_explorations/log-viewer/log-viewer.sh status
#   my_explorations/log-viewer/log-viewer.sh logs
#
# 环境变量:
#   LOG_VIEWER_PORT    端口, 默认 8007
#   LOG_VIEWER_HOST    监听地址, 默认 127.0.0.1 (改 0.0.0.0 会暴露到局域网)
#   LOG_VIEWER_CONFIG  源配置, 默认 my_explorations/log-viewer/sources.json
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP="$ROOT/my_explorations/log-viewer"
SCRIPT="$APP/log_viewer.py"
PID_FILE="$APP/.log-viewer.pid"
LOG_FILE="$APP/log-viewer.log"
PORT="${LOG_VIEWER_PORT:-8007}"
HOST="${LOG_VIEWER_HOST:-127.0.0.1}"
CONFIG="${LOG_VIEWER_CONFIG:-$APP/sources.json}"

is_running() {
  [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

case "${1:-start}" in
  start)
    if is_running; then
      echo "already running (pid $(cat "$PID_FILE"), http://127.0.0.1:$PORT/logs.html)"
      exit 0
    fi
    command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }
    if command -v lsof >/dev/null && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "port $PORT already in use (set LOG_VIEWER_PORT=8008)" >&2
      exit 1
    fi
    nohup python3 "$SCRIPT" --host "$HOST" --port "$PORT" --config "$CONFIG" \
      > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if ! is_running; then
      rm -f "$PID_FILE"
      echo "failed to start; see $LOG_FILE" >&2
      tail -20 "$LOG_FILE" >&2 || true
      exit 1
    fi
    echo "started log viewer (pid $(cat "$PID_FILE"))"
    echo "  page:    http://127.0.0.1:$PORT/logs.html"
    echo "  stream:  ws://127.0.0.1:$PORT/logs-ws"
    echo "  health:  http://127.0.0.1:$PORT/health"
    echo "  sources: $CONFIG"
    echo "  log:     $LOG_FILE"
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
  restart)
    "$0" stop
    "$0" start
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
    echo "usage: $0 {start|stop|restart|status|logs}" >&2
    exit 2
    ;;
esac
