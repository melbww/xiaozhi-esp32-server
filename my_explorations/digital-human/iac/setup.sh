#!/usr/bin/env bash
# =============================================================================
# digital-human 一键环境准备 (macOS/Linux)
# 追踪文档: my_explorations/digital-human/SESSION_LOG.md
#
# 功能:
#   1. 创建 Python venv (优先 python3.13, 回退 python3)
#   2. 安装依赖 (sherpa-onnx, sounddevice, pypinyin)
#   3. 若 models/ 缺少必需模型文件, 自动下载并重命名
#   4. 校验最终目录结构
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"      # 仓库根
DH_DIR="$ROOT/main/digital-human"
RT_DIR="$DH_DIR/wakeword_runtime"
VENV_DIR="$DH_DIR/.venv"
MODEL_DIR="$RT_DIR/models"
MODEL_VER="sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
MODEL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/${MODEL_VER}.tar.bz2"

REQUIRED=(encoder.onnx decoder.onnx joiner.onnx tokens.txt)

log()  { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn ]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

# ---------- 1. 创建 venv ----------
if [ ! -x "$VENV_DIR/bin/python" ]; then
  PY_BIN=""
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY_BIN=$(command -v "$c"); break; fi
  done
  [ -n "$PY_BIN" ] || { err "no python3 found"; exit 1; }
  log "create venv: $PY_BIN -> $VENV_DIR"
  "$PY_BIN" -m venv "$VENV_DIR"
else
  log "venv already exists: $VENV_DIR"
fi

# ---------- 2. 安装依赖 ----------
log "install dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$RT_DIR/requirements.txt" -q
log "dependencies installed"

# ---------- 3. 检查/下载模型 ----------
model_ok() {
  [ -d "$MODEL_DIR" ] || return 1
  local f
  for f in "${REQUIRED[@]}"; do [ -f "$MODEL_DIR/$f" ] || return 1; done
  return 0
}

if model_ok; then
  log "model files already present in $MODEL_DIR"
else
  mkdir -p "$MODEL_DIR"
  log "downloading wakeword model: $MODEL_VER"
  log "  url: $MODEL_URL"
  curl -fL --retry 3 -o "$RT_DIR/model.tar.bz2" "$MODEL_URL"
  tar xjf "$RT_DIR/model.tar.bz2" -C "$RT_DIR"
  rm -f "$RT_DIR/model.tar.bz2"

  SRC="$RT_DIR/$MODEL_VER"
  [ -d "$SRC" ] || { err "model dir not found after extract: $SRC"; exit 1; }

  # 精度优先 (方案一): epoch-99 fp32
  for f in encoder decoder joiner; do
    src_file="$SRC/${f}-epoch-99-avg-1-chunk-16-left-64.onnx"
    if [ ! -f "$src_file" ]; then
      # 速度优先 (方案二): epoch-99 int8
      src_file="$SRC/${f}-epoch-99-avg-1-chunk-16-left-64.int8.onnx"
    fi
    if [ ! -f "$src_file" ]; then
      err "cannot find ${f} model file in $SRC"; exit 1
    fi
    cp "$src_file" "$MODEL_DIR/$f.onnx"
    log "  $f.onnx <- $(basename "$src_file")"
  done
  [ -f "$SRC/tokens.txt" ] || { err "tokens.txt not found"; exit 1; }
  cp "$SRC/tokens.txt" "$MODEL_DIR/tokens.txt"
  log "  tokens.txt copied"
  rm -rf "$SRC"
fi

# ---------- 4. 校验 ----------
log "verify final layout:"
for f in "${REQUIRED[@]}"; do
  [ -f "$MODEL_DIR/$f" ] && echo "  [ok] $MODEL_DIR/$f" || { err "missing $MODEL_DIR/$f"; exit 1; }
done

# keywords.txt 由运行时按需自动生成, 无需手动创建
log "done. start with:  my_explorations/digital-human/iac/start.sh"
