"""OCR through Tesseract. Works anywhere, including the Linux box we will
eventually deploy to. Requires the `tesseract` binary on PATH."""

from pathlib import Path

from .base import OcrResult, OcrUnavailable, TextBox

NAME = "tesseract"

# Tesseract wants ISO 639-2 codes, not BCP 47 tags.
_LANG_MAP = {
    "pt": "por", "pt-br": "por", "en": "eng", "en-us": "eng",
    "es": "spa", "fr": "fra", "de": "deu", "it": "ita",
}


def _tesseract_langs(languages: list[str] | None) -> str:
    if not languages:
        return "eng"
    codes = []
    for lang in languages:
        code = _LANG_MAP.get(lang.strip().lower())
        if code and code not in codes:
            codes.append(code)
    return "+".join(codes) or "eng"


def is_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True


def recognize(path: Path, languages: list[str] | None = None) -> OcrResult:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise OcrUnavailable("Tesseract engine needs: pip install pytesseract pillow") from exc

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise OcrUnavailable(
            "The `tesseract` binary was not found. Install it with"
            " `brew install tesseract tesseract-lang` (macOS) or"
            " `apt-get install tesseract-ocr tesseract-ocr-por` (Debian/Ubuntu)."
        ) from exc

    with Image.open(path) as img:
        img = img.convert("RGB")
        img_w, img_h = img.size
        data = pytesseract.image_to_data(
            img, lang=_tesseract_langs(languages),
            output_type=pytesseract.Output.DICT,
        )

    # Tesseract reports word-level boxes; stitch words back into their lines so
    # the output shape matches Apple Vision's phrase-level observations.
    lines: dict[tuple, list[int]] = {}
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        try:
            if float(data["conf"][i]) < 0:
                continue
        except (TypeError, ValueError):
            continue
        key = (data["page_num"][i], data["block_num"][i],
               data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(i)

    boxes: list[TextBox] = []
    for indexes in lines.values():
        words = [data["text"][i].strip() for i in indexes]
        left = min(data["left"][i] for i in indexes)
        top = min(data["top"][i] for i in indexes)
        right = max(data["left"][i] + data["width"][i] for i in indexes)
        bottom = max(data["top"][i] + data["height"][i] for i in indexes)
        confs = [float(data["conf"][i]) for i in indexes]
        boxes.append(TextBox(
            text=" ".join(words),
            x=left / img_w,
            y=top / img_h,
            width=(right - left) / img_w,
            height=(bottom - top) / img_h,
            confidence=sum(confs) / len(confs) / 100.0,
        ))
    return OcrResult(engine=NAME, boxes=boxes)
