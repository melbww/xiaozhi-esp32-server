#!/usr/bin/env bash
# =============================================================================
# digital-human 启动脚本 (macOS/Linux)
# 用法: ./start.sh            # 前台运行 (Ctrl+C 停止)
#       ./start.sh --background   # 后台运行, PID 写入 .digital-human.pid
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DH_DIR="$ROOT/main/digital-human"
VENV_BIN="$DH_DIR/.venv/bin/python"
PID_FILE="$ROOT/my_explorations/digital-human/.digital-human.pid"
LOG_FILE="$DH_DIR/digital-human.log"

[ -x "$VENV_BIN" ] || { echo "venv missing, run setup.sh first" >&2; exit 1; }
[ -f "$DH_DIR/wakeword_runtime/models/encoder.onnx" ] || \
  { echo "model missing, run setup.sh first" >&2; exit 1; }

case "${1:-}" in
  "" )
    echo "starting digital-human (port 8006). Press Ctrl+C to stop."
    cd "$DH_DIR" && exec "$VENV_BIN" start.py
    ;;
  --background )
    # 已在运行则直接退出
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "already running (pid $(cat "$PID_FILE"))"
      exit 0
    fi
    cd "$DH_DIR"
    nohup "$VENV_BIN" start.py > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "started digital-human in background (pid $(cat "$PID_FILE"))"
    echo "  page:     http://127.0.0.1:8006/index.html"
    echo "  bridge:   ws://127.0.0.1:8006/wakeword-ws"
    echo "  live logs: http://127.0.0.1:8006/logs.html  (ws://127.0.0.1:8006/logs-ws)"
    echo "  health:   http://127.0.0.1:8006/health"
    echo "  log:      $LOG_FILE"
    echo "  stop:     my_explorations/digital-human/iac/stop.sh"
    ;;
  * )
    echo "unknown arg: $1" >&2
    echo "usage: $0 [--background]" >&2
    exit 2
    ;;
esac
