"""Generates a fake credit-card statement screenshot for testing the reader.

    python tools/make_sample_screenshot.py data/sample.png

Handy for exercising the OCR + parsing pipeline without uploading a real
statement.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 420, 900
MARGIN = 22

FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

CONTENT = [
    ("status", "09:41", "5G  100%"),
    ("title", "Fatura atual", ""),
    ("big", "R$ 1.234,56", ""),
    ("header", "15 SET", ""),
    ("row", "Uber Trip", "R$ 24,90"),
    ("row", "Padaria Pao Doce", "R$ 12,50"),
    ("row", "iFood", "R$ 63,80"),
    ("header", "14 SET", ""),
    ("row", "Netflix.com  2/12", "R$ 55,90"),
    ("row", "Drogasil", "R$ 38,45"),
    ("row", "Posto Ipiranga", "R$ 210,00"),
    ("header", "13 SET", ""),
    ("row", "Pagamento recebido", "-R$ 500,00"),
    ("row", "Amazon.com.br", "R$ 149,99"),
    ("row", "Uber 99 Viagem", "R$ 18,30"),
    ("header", "12 SET", ""),
    ("row", "Supermercado Zona Sul", "R$ 287,64"),
    ("row", "Cinemark Shopping", "R$ 96,00"),
    ("row", "Farmacia Pacheco", "R$ 21,90"),
    ("total", "Total da fatura", "R$ 1.234,56"),
]


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def main(out_path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)

    small = load_font(13)
    normal = load_font(16)
    header_font = load_font(13)
    big = load_font(30)

    y = 14
    for kind, left, right in CONTENT:
        if kind == "status":
            draw.text((MARGIN, y), left, font=small, fill="#111111")
            draw.text((WIDTH - MARGIN - draw.textlength(right, font=small), y),
                      right, font=small, fill="#111111")
            y += 34
        elif kind == "title":
            draw.text((MARGIN, y), left, font=normal, fill="#666666")
            y += 28
        elif kind == "big":
            draw.text((MARGIN, y), left, font=big, fill="#111111")
            y += 52
        elif kind == "header":
            draw.line([(MARGIN, y), (WIDTH - MARGIN, y)], fill="#dddddd")
            y += 10
            draw.text((MARGIN, y), left, font=header_font, fill="#888888")
            y += 26
        elif kind == "total":
            y += 12
            draw.line([(MARGIN, y), (WIDTH - MARGIN, y)], fill="#dddddd")
            y += 12
            draw.text((MARGIN, y), left, font=normal, fill="#666666")
            draw.text((WIDTH - MARGIN - draw.textlength(right, font=normal), y),
                      right, font=normal, fill="#111111")
            y += 34
        else:
            draw.text((MARGIN, y), left, font=normal, fill="#111111")
            draw.text((WIDTH - MARGIN - draw.textlength(right, font=normal), y),
                      right, font=normal, fill="#111111")
            y += 32

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    print(f"wrote {out_path} ({WIDTH}x{HEIGHT})")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/sample.png")
    main(target)
