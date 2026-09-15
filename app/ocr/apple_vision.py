"""OCR through Apple's Vision framework (macOS only).

Very accurate on phone screenshots and needs no extra binaries, but it will
not exist on a Linux server, which is why the Tesseract engine also exists.
"""

from pathlib import Path

from .base import OcrResult, OcrUnavailable, TextBox

NAME = "apple-vision"


def is_available() -> bool:
    try:
        import Quartz  # noqa: F401
        import Vision  # noqa: F401
    except ImportError:
        return False
    return True


def recognize(path: Path, languages: list[str] | None = None) -> OcrResult:
    try:
        import Quartz
        import Vision
        from Foundation import NSURL
    except ImportError as exc:  # pragma: no cover - platform dependent
        raise OcrUnavailable(
            "Apple Vision needs pyobjc: pip install pyobjc-framework-Vision"
            " pyobjc-framework-Quartz"
        ) from exc

    url = NSURL.fileURLWithPath_(str(path))
    source = Quartz.CGImageSourceCreateWithURL(url, None)
    if source is None:
        raise ValueError(f"Could not read image: {path.name}")
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if image is None:
        raise ValueError(f"Image has no decodable frame: {path.name}")

    request = Vision.VNRecognizeTextRequest.alloc().init()
    # "Accurate" is slower but we are OCRing one screenshot at a time.
    request.setRecognitionLevel_(getattr(Vision, "VNRequestTextRecognitionLevelAccurate", 0))
    # Language correction "fixes" merchant names into real words, which is the
    # opposite of what we want.
    request.setUsesLanguageCorrection_(False)
    if languages:
        try:
            request.setRecognitionLanguages_(languages)
        except Exception:
            pass  # Unsupported language list; Vision falls back to its default.

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, {})
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision OCR failed: {error}")

    boxes: list[TextBox] = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        candidate = candidates[0]
        text = str(candidate.string()).strip()
        if not text:
            continue
        rect = observation.boundingBox()
        # Vision's origin is bottom-left; flip it so y grows downwards.
        boxes.append(TextBox(
            text=text,
            x=float(rect.origin.x),
            y=float(1.0 - (rect.origin.y + rect.size.height)),
            width=float(rect.size.width),
            height=float(rect.size.height),
            confidence=float(candidate.confidence()),
        ))
    return OcrResult(engine=NAME, boxes=boxes)
