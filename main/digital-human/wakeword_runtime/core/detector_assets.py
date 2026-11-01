from dataclasses import dataclass
from pathlib import Path

from ..config import RuntimeConfig

REQUIRED_MODEL_FILES = (
    "encoder.onnx",
    "decoder.onnx",
    "joiner.onnx",
    "tokens.txt",
)


@dataclass
class DetectorAssets:
    model_root: Path
    tokens_file: Path
    encoder_file: Path
    decoder_file: Path
    joiner_file: Path
    keywords_file: Path


class DetectorAssetsBuilder:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def prepare(self) -> DetectorAssets:
        model_root = self._resolve_model_root()
        keywords_file = self._write_keywords_file(model_root)
        return DetectorAssets(
            model_root=model_root,
            tokens_file=model_root / "tokens.txt",
            encoder_file=model_root / "encoder.onnx",
            decoder_file=model_root / "decoder.onnx",
            joiner_file=model_root / "joiner.onnx",
            keywords_file=keywords_file,
        )

    def _resolve_model_root(self) -> Path:
        preferred = self.config.model_dir
        if self._has_required_files(preferred):
            return preferred

        raise FileNotFoundError(
            "No valid model directory found. Expected configured model files to exist."
        )

    def _write_keywords_file(self, model_root: Path) -> Path:
        from .keyword_tokens import build_keyword_tokens

        wake_words = self.config.wake_words
        if not wake_words:
            raise ValueError("keywords.txt cannot be empty")

        keywords_path = model_root / "keywords.txt"
        lines: list[str] = []
        for keyword_text in wake_words:
            tokens = build_keyword_tokens(keyword_text, model_root)
            # sherpa-onnx 要求 @ 后的关键字为单 token (多词用下划线连接)
            lines.append(f"{tokens} @{keyword_text.replace(' ', '_')}")

        keywords_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return keywords_path

    def _has_required_files(self, directory: Path) -> bool:
        if not directory.exists():
            return False
        return all((directory / file_name).exists() for file_name in REQUIRED_MODEL_FILES)
