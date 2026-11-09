#!/usr/bin/env bash
# =============================================================================
# digital-human 停止脚本
# 优先用 PID 文件; 若 PID 文件失效, 回退到按进程名查找
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PID_FILE="$ROOT/my_explorations/digital-human/.digital-human.pid"

stopped=0

if [ -f "$PID_FILE" ]; then
  PID="$(cat "$PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    # 杀掉记录的主进程及其子进程 (避免遗留孤儿进程)
    pkill -TERM -P "$PID" 2>/dev/null || true
    kill "$PID" 2>/dev/null && stopped=1 && echo "stopped digital-human (pid $PID)"
  fi
  rm -f "$PID_FILE"
fi

# 回退: 按进程名查找真实 python start.py 进程
PIDS="$(pgrep -f "python.*start.py" 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
  kill $PIDS 2>/dev/null || true
  echo "stopped by pgrep: $PIDS"
  stopped=1
fi

[ "$stopped" = "1" ] || echo "digital-human not running"
