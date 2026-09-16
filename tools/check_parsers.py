"""Checks that each screenshot format still reaches the right parser.

Guards two things that are easy to break when a parser is added or tweaked:
the dispatcher in `parsing.parse_screenshot` picking the wrong reader, and the
merchant canonicalisation rules over- or under-matching.

    tools/check_parsers.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.merchants import canonical                        # noqa: E402
from app.ocr.base import TextBox                           # noqa: E402
from app.parsing import parse_screenshot                   # noqa: E402

TODAY = date(2026, 9, 16)       # a Wednesday

# --- the three screenshot shapes, as OCR lines -----------------------------

WALLET = """\
Latest Transactions
Sesc Turismo R$ 13,51
São Luís, MA
4 hours ago
IFD* 53.700.820 Elizabe R$ 43,89
Sunday
Uber R$ 5,94 ›
Apple Pay
Saturday
99 R$ 8,33
Apple Pay
Saturday
"""

NOTIFICATION = """\
Compra no crédito Sun, 19:26
Olá, Lucas. Você acaba de comprar R$ 43,89 em IFD*53.700.820 ELIZABE. A compra
foi no crédito nacional, com o cartão final 9523.
Compra no crédito Sat, 08:04
Olá, Lucas. Você acaba de comprar R$ 8,33 em 99*99APP. A compra foi no crédito
nacional, com o cartão final 9523.
Quer tirar R$ 5,94 da sua fatura? Aproveite agora.
"""

# despesa | expected rows as (date, merchant, cents)
CASES = [
    ("wallet", WALLET, [
        ("2026-09-16", "Sesc Turismo", 1351),
        ("2026-09-13", "iFood", 4389),
        ("2026-09-12", "Uber", 594),
        ("2026-09-12", "99", 833),
    ]),
    ("notification", NOTIFICATION, [
        ("2026-09-13", "iFood", 4389),
        ("2026-09-12", "99", 833),
    ]),
]

# merchant text -> what it should be stored as
NAME_CASES = [
    ("IFD* 53.700.820 Elizabe", "iFood"),
    ("IFD Sal Parrilla", "iFood"),
    ("iFood", "iFood"),
    ("IFOOD CLUBE", "iFood"),
    ("Uber", "Uber"),
    ("UBER   *TRIP HELP.UBER.CO", "Uber"),
    ("Uber Eats", "Uber"),
    ("99", "99"),
    ("99*99APP", "99"),
    ("99POP", "99"),
    # Names that must be left alone.
    ("Ponto Lagoa", "Ponto Lagoa"),
    ("ArmazemDoCampo", "ArmazemDoCampo"),
    ("Cyber Cafe", "Cyber Cafe"),          # contains "uber" but not as a word
    ("Sesc Turismo", "Sesc Turismo"),
    ("Loja 99 Centro", "Loja 99 Centro"),  # 99 not at the start
]


def as_boxes(text: str) -> list[TextBox]:
    return [TextBox(text=line, x=0.0, y=index / 1000, width=1.0, height=0.001,
                    confidence=1.0)
            for index, line in enumerate(text.splitlines()) if line.strip()]


def main() -> None:
    failures = 0

    for name, sample, expected in CASES:
        parsed = parse_screenshot(as_boxes(sample), reference_date=TODAY,
                                  today=TODAY)
        got = [(t.occurred_on, t.merchant, t.amount_cents) for t in parsed]
        ok = got == expected
        failures += 0 if ok else 1
        print(f"{name:<14} {'ok' if ok else 'FAILED'}")
        if not ok:
            print("   expected:")
            for row in expected:
                print(f"     {row}")
            print("   got:")
            for row in got:
                print(f"     {row}")

    print("\nmerchant names")
    for raw, expected in NAME_CASES:
        got = canonical(raw)
        ok = got == expected
        failures += 0 if ok else 1
        status = "ok" if ok else f"FAILED (wanted {expected!r})"
        print(f"  {raw:<28} -> {got:<16} {status}")

    print()
    if failures:
        print(f"{failures} check(s) failed")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
