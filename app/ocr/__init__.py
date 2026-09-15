"""Engine selection. Call `run_ocr(path)` and let it pick the best engine."""

from pathlib import Path

from .. import config
from . import apple_vision, tesseract_engine
from .base import OcrResult, OcrUnavailable, TextBox

__all__ = ["run_ocr", "available_engines", "OcrResult", "OcrUnavailable", "TextBox"]

# Ordered by preference for "auto".
ENGINES = {
    apple_vision.NAME: apple_vision,
    tesseract_engine.NAME: tesseract_engine,
}


def available_engines() -> list[str]:
    return [name for name, mod in ENGINES.items() if mod.is_available()]


def run_ocr(path: Path, engine: str | None = None,
            languages: list[str] | None = None) -> OcrResult:
    engine = (engine or config.OCR_ENGINE or "auto").strip().lower()
    languages = languages or config.OCR_LANGUAGES

    if engine != "auto":
        module = ENGINES.get(engine)
        if module is None:
            raise ValueError(f"Unknown OCR engine {engine!r}. "
                             f"Known engines: {', '.join(ENGINES)}")
        return module.recognize(path, languages)

    for module in ENGINES.values():
        if module.is_available():
            return module.recognize(path, languages)

    raise OcrUnavailable(
        "No OCR engine is available. On macOS: pip install pyobjc-framework-Vision"
        " pyobjc-framework-Quartz. Elsewhere: install the tesseract binary."
    )
