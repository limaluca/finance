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

    def as_json(self) -> str:
        """The boxes with their coordinates, so an import can be re-read later."""
        import json
        return json.dumps([{"t": b.text, "x": round(b.x, 5), "y": round(b.y, 5),
                            "w": round(b.width, 5), "h": round(b.height, 5),
                            "c": round(b.confidence, 3)} for b in self.boxes],
                          ensure_ascii=False)


def boxes_from_json(payload: str) -> list[TextBox]:
    import json
    return [TextBox(text=item["t"], x=item["x"], y=item["y"], width=item["w"],
                    height=item["h"], confidence=item.get("c", 0.0))
            for item in json.loads(payload or "[]")]


class OcrUnavailable(RuntimeError):
    """Raised when an engine's dependencies are not installed on this machine."""
