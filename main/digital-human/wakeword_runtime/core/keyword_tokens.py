"""生成 sherpa-onnx 关键词 token 序列。

- 中文唤醒词 → pypinyin 拼音 token
- 英文唤醒词 → en.phone (CMU 发音词典) ARPABET 音素 token

适配模型:
- sherpa-onnx-kws-zipformer-wenetspeech (纯中文): 只有拼音 token, 英文不可用
- sherpa-onnx-kws-zipformer-zh-en (中英混合): 中文拼音 + 英文音素, 均可用
- sherpa-onnx-kws-zipformer-gigaspeech (纯英文): 使用 BPE, 本模块不适用
"""
import re
from functools import lru_cache
from pathlib import Path

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


@lru_cache(maxsize=4)
def _load_en_phone(model_dir: str) -> dict:
    """加载 en.phone (CMU 风格发音词典): WORD -> [PHONE, ...]"""
    phone_file = Path(model_dir) / "en.phone"
    if not phone_file.exists():
        return {}
    phones: dict = {}
    for line in phone_file.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            phones[parts[0]] = parts[1:]
    return phones


def build_keyword_tokens(text: str, model_dir) -> str:
    """根据唤醒词文本生成模型可用的 token 序列 (空格分隔)。"""
    model_dir = str(model_dir)
    if _CJK_RE.search(text):
        return _pinyin_tokens(text)
    return _english_tokens(text, model_dir)


def _pinyin_tokens(text: str) -> str:
    try:
        from pypinyin import Style, pinyin
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: pypinyin. Install runtime dependencies before generating keywords."
        ) from exc

    initials = pinyin(text, style=Style.INITIALS, strict=False)
    finals = pinyin(
        text,
        style=Style.FINALS_TONE,
        strict=False,
        neutral_tone_with_five=True,
    )
    tokens: list[str] = []
    for initial_parts, final_parts in zip(initials, finals):
        initial = initial_parts[0].strip()
        final = final_parts[0].strip()
        if initial:
            tokens.append(initial)
        if final:
            tokens.append(final)
    if not tokens:
        raise ValueError(f"failed to generate pinyin tokens for wake word: {text}")
    return " ".join(tokens)


def _english_tokens(text: str, model_dir: str) -> str:
    phones = _load_en_phone(model_dir)
    if not phones:
        raise ValueError(
            f"en.phone not found in {model_dir}: "
            "English wake words require the bilingual (zh-en) or English KWS model"
        )
    tokens: list[str] = []
    for word in text.split():
        key = word.upper()
        if key not in phones and key.startswith("'"):
            key = key[1:]
        if key not in phones:
            raise ValueError(
                f"'{word}' not found in en.phone pronunciation dictionary "
                f"(checked {key}); keep wake words to common English words"
            )
        tokens.extend(phones[key])
    if not tokens:
        raise ValueError(f"failed to generate phoneme tokens for wake word: {text}")
    return " ".join(tokens)
