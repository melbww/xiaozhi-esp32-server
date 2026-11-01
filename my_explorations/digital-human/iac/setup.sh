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
# 唤醒词模型选择: MODEL=zhen(默认, 中英混合) | zh(纯中文) | en(纯英文, 需 BPE, 暂不支持)
MODEL="${MODEL:-zhen}"
case "$MODEL" in
  zhen)
    MODEL_VER="sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"
    ENC_GLOB="encoder-*-chunk-16-left-64.onnx"          # 优先 fp32, 见下方逻辑
    ;;
  zh)
    MODEL_VER="sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
    ENC_GLOB="encoder-epoch-99-avg-1-chunk-16-left-64.onnx"
    ;;
  en)
    err "纯英文模型 (gigaspeech) 使用 BPE 分词, 当前运行时未支持; 请用 MODEL=zhen"
    exit 1
    ;;
  *) err "未知模型: $MODEL (可选 zhen/zh/en)"; exit 1 ;;
esac
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

  # 复制模型文件 (fp32 优先, 回退 int8)
  for f in encoder decoder joiner; do
    src_file="$(ls "$SRC"/${f}-*-chunk-16-left-64.onnx 2>/dev/null | grep -v int8 | head -1)"
    if [ -z "$src_file" ]; then
      src_file="$(ls "$SRC"/${f}-*-chunk-16-left-64.int8.onnx 2>/dev/null | head -1)"
    fi
    if [ -z "$src_file" ]; then
      err "cannot find ${f} model file in $SRC"; exit 1
    fi
    cp "$src_file" "$MODEL_DIR/$f.onnx"
    log "  $f.onnx <- $(basename "$src_file")"
  done
  [ -f "$SRC/tokens.txt" ] || { err "tokens.txt not found"; exit 1; }
  cp "$SRC/tokens.txt" "$MODEL_DIR/tokens.txt"
  log "  tokens.txt copied"
  # 中英混合模型附带英文发音词典, 供英文唤醒词转音素
  if [ -f "$SRC/en.phone" ]; then
    cp "$SRC/en.phone" "$MODEL_DIR/en.phone"
    log "  en.phone copied"
  fi
  # 模型包自带的 keywords.txt 是演示词, 一律丢弃,
  # 由运行时根据默认唤醒词(中文拼音 / 英文音素)自动重新生成。
  rm -f "$MODEL_DIR/keywords.txt"
  rm -rf "$SRC"
fi

# ---------- 4. 校验 ----------
log "verify final layout:"
for f in "${REQUIRED[@]}"; do
  [ -f "$MODEL_DIR/$f" ] && echo "  [ok] $MODEL_DIR/$f" || { err "missing $MODEL_DIR/$f"; exit 1; }
done
[ "$MODEL" = "zhen" ] && [ -f "$MODEL_DIR/en.phone" ] && echo "  [ok] $MODEL_DIR/en.phone"

# keywords.txt 由运行时按需自动生成, 无需手动创建
log "done. start with:  my_explorations/digital-human/iac/start.sh"
