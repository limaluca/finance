"""Shared vocabulary for OCR engines.

Every engine returns the same thing: a flat list of TextBox, with coordinates
normalised to 0..1 and the origin at the TOP-left. Downstream code then never
needs to know which engine produced the text.
"""

from dataclasses import dataclass, field


@dataclass
class TextBox:
    text: str
    x: float          # left edge, 0..1
    y: float          # top edge, 0..1
    width: float      # 0..1
    height: float     # 0..1
    confidence: float = 0.0

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    @property
    def right(self) -> float:
        return self.x + self.width


@dataclass
class OcrResult:
    engine: str
    boxes: list[TextBox] = field(default_factory=list)

    def as_text(self) -> str:
        """Reading-order plain text, mainly for debugging a bad import."""
        from ..parsing import group_boxes_into_lines
        return "\n".join(line.text for line in group_boxes_into_lines(self.boxes))


class OcrUnavailable(RuntimeError):
    """Raised when an engine's dependencies are not installed on this machine."""
