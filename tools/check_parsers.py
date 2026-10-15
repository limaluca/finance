"""Checks that each screenshot format still reaches the right parser.

Guards three things that are easy to break when a parser is added or tweaked:
the dispatcher in `parsing.parse_screenshot` picking the wrong reader, the
merchant canonicalisation rules over- or under-matching, and the same purchase
read from two different screenshot formats still colliding as a duplicate.

    tools/check_parsers.py
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import dedupe, statement                          # noqa: E402
from app.merchants import canonical                        # noqa: E402
from app.ocr.base import TextBox                           # noqa: E402
from app.parsing import ParsedTransaction, parse_screenshot  # noqa: E402

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

# The statement list is recognised by its shape, so indentation matters here:
# leading spaces below become a real x offset (see `as_boxes`).
STATEMENT = """\
Faturas
Domingo, 13 de set
    Restaurantes
    -R$ 43,89
    IFD*53.700.820 ELIZABE SAO LUIS MA
Sabado, 12 de set
    Transporte
    -R$ 8,33
    99*99APP SAO PAULO SP
Total: R$ 52,22
"""

# name | sample | which parser must handle it | expected (date, merchant, cents)
CASES = [
    ("wallet", WALLET, "wallet", [
        ("2026-09-16", "Sesc Turismo", 1351),
        ("2026-09-13", "iFood", 4389),
        ("2026-09-12", "Uber", 594),
        ("2026-09-12", "99", 833),
    ]),
    ("notification", NOTIFICATION, "notification", [
        ("2026-09-13", "iFood", 4389),
        ("2026-09-12", "99", 833),
    ]),
    ("statement", STATEMENT, "statement", [
        ("2026-09-13", "iFood", 4389),
        ("2026-09-12", "99", 833),
    ]),
]

# The same purchase as every format reads it. Whichever one arrives second
# (a different screenshot) must be caught as an exact duplicate. Same vendor
# and amount on a *different* day is a new purchase.
DEDUPE_CASES = [
    ("wallet row",       "iFood", 4389, "2026-09-13"),
    ("notification row", "IFD*53.700.820 ELIZABE", 4389, "2026-09-13"),
    ("statement row",    "IFD*53.700.820 ELIZABE SAO LUIS BR", 4389, "2026-09-13"),
    ("typed by hand",    "ifood", 4389, "2026-09-13"),
    ("typed with space", "I Food", 4389, "2026-09-13"),
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
    """Turns a text sample into OCR boxes, one line each.

    Leading spaces become a left offset, because the statement parser tells rows
    from date headers by how far they are indented.
    """
    boxes = []
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        boxes.append(TextBox(text=line.strip(), x=0.25 if indent else 0.0,
                             y=index / 1000, width=0.7, height=0.001,
                             confidence=1.0))
    return boxes


def main() -> None:
    failures = 0

    print("screenshot formats")
    for name, sample, want_parser, expected in CASES:
        parsed = parse_screenshot(as_boxes(sample), reference_date=TODAY,
                                  today=TODAY)
        got = [(t.occurred_on, t.merchant, t.amount_cents) for t in parsed]
        used = parsed[0].source_format if parsed else "none"
        ok = got == expected and used == want_parser
        failures += 0 if ok else 1
        print(f"  {name:<14} read by {used:<13} {'ok' if ok else 'FAILED'}")
        if not ok:
            if used != want_parser:
                print(f"   wanted the {want_parser} parser")
            print("   expected:")
            for row in expected:
                print(f"     {row}")
            print("   got:")
            for row in got:
                print(f"     {row}")

    print("\nduplicates across sources")
    # The first reading is what is already saved; every other way of feeding the
    # same purchase in (a different screenshot) has to be recognised as the same
    # thing. annotate() is called per "image" so occupancy is per screenshot.
    first = DEDUPE_CASES[0]
    index = dedupe.Index()
    index.add(first[3], canonical(first[1]), first[2], where="system")
    for label, merchant, cents, day in DEDUPE_CASES[1:]:
        tx = ParsedTransaction(merchant=canonical(merchant), amount_cents=cents,
                               occurred_on=day, source_image=label)
        dedupe.annotate([tx], index)
        ok = tx.duplicate_kind == "exact"
        failures += 0 if ok else 1
        print(f"  {label:<18} -> {tx.merchant:<8} "
              f"{tx.duplicate_kind or 'not flagged':<12} "
              f"{'ok' if ok else 'FAILED (wanted exact)'}")

    # A different day, or a different amount, must not be swallowed.
    for label, merchant, cents, day in [("other day", "iFood", 4389, "2026-09-14"),
                                        ("other amount", "iFood", 4300, "2026-09-13")]:
        tx = ParsedTransaction(merchant=canonical(merchant), amount_cents=cents,
                               occurred_on=day, source_image=label)
        dedupe.annotate([tx], index)
        ok = tx.duplicate_kind != "exact"
        failures += 0 if ok else 1
        print(f"  {label:<18} -> {tx.duplicate_kind or 'kept':<12} "
              f"{'ok' if ok else 'FAILED (must not block)'}")

    print("\nsame-price trips are not duplicates")
    rides = dedupe.Index()
    shot_a = [
        ParsedTransaction(merchant="99", amount_cents=810, occurred_on="2026-09-13",
                          source_image="wallet-a"),
        ParsedTransaction(merchant="99", amount_cents=810, occurred_on="2026-09-13",
                          source_image="wallet-a"),
        ParsedTransaction(merchant="99", amount_cents=810, occurred_on="2026-09-14",
                          source_image="wallet-a"),
    ]
    dedupe.annotate(shot_a, rides)
    kept = [tx for tx in shot_a if tx.duplicate_kind != "exact"]
    ok = len(kept) == 3
    failures += 0 if ok else 1
    print(f"  two 8,10 on one day plus one the next  "
          f"{'ok' if ok else 'FAILED (wanted all three kept)'}")

    shot_b = [
        ParsedTransaction(merchant="99", amount_cents=810, occurred_on="2026-09-13",
                          source_image="wallet-b"),
        ParsedTransaction(merchant="99", amount_cents=810, occurred_on="2026-09-13",
                          source_image="wallet-b"),
    ]
    dedupe.annotate(shot_b, rides)
    blocked = [tx for tx in shot_b if tx.duplicate_kind == "exact"]
    ok = len(blocked) == 2
    failures += 0 if ok else 1
    print(f"  same two trips on a later overlapping shot  "
          f"{'ok' if ok else 'FAILED (wanted both exact)'}")

    # A guessed date (header scrolled off) still has to collide with the same
    # vendor + amount on a real day.
    rides2 = dedupe.Index()
    firm = ParsedTransaction(merchant="99", amount_cents=810,
                             occurred_on="2026-08-24", date_source="header",
                             source_image="shot-firm")
    weak = ParsedTransaction(merchant="99", amount_cents=810,
                             occurred_on="2026-09-21", date_source="fallback",
                             source_image="shot-weak")
    dedupe.annotate([firm], rides2)
    dedupe.annotate([weak], rides2)
    ok = weak.duplicate_kind == "exact" and firm.duplicate_kind != "exact"
    failures += 0 if ok else 1
    print(f"  fallback date vs earlier real date  "
          f"{'ok' if ok else 'FAILED (wanted weak row exact)'}")

    print("\ninstallment rollover")
    from app.commitments import Plan
    plan = Plan(id=1, description="Phone", bank="X", monthly_cents=10000,
                total=10, first_month="2026-01", month="2026-09")
    # January = 1, so September = 9 of 10, October = 10 of 10, November gone.
    cases = [
        ("2026-08", True, 8, False),
        ("2026-09", True, 9, False),
        ("2026-10", True, 10, True),    # last one, still on the bill
        ("2026-11", False, 11, False),  # finished, drops off
    ]
    for month, due, number, last in cases:
        plan.month = month
        ok = (plan.due_now, plan.number, plan.is_last) == (due, number, last)
        failures += 0 if ok else 1
        print(f"  {month}  {plan.number}/{plan.total}  "
              f"{'on bill' if plan.due_now else 'off bill':<8} "
              f"{'ok' if ok else 'FAILED'}")

    print("\nspending limit")
    from app.budget import Limit
    # R$ 300 from the 21st through the 30th is 10 days, R$ 30 a day.
    lim = Limit(limit_cents=30000, until="2026-09-30", start="2026-09-21",
                spent_cents=0, spent_today_cents=0, today="2026-09-21")
    ok = (lim.days_left, lim.per_day_cents) == (10, 3000)
    failures += 0 if ok else 1
    print(f"  300 over 10 days  {lim.per_day_cents/100:.2f}/day  "
          f"{'ok' if ok else 'FAILED'}")
    lim.spent_cents = 5000
    lim.spent_today_cents = 2000
    ok = lim.per_day_cents == 2500 and lim.left_today_cents == 500
    failures += 0 if ok else 1
    print(f"  after spending 50, 20 of it today  "
          f"{lim.per_day_cents/100:.2f}/day, {lim.left_today_cents/100:.2f} left today  "
          f"{'ok' if ok else 'FAILED'}")

    print("\nstatement cycles (cutoff 21)")
    cutoff = 21
    cases = [
        ("2025-10-21", "2025-11"),
        ("2025-10-22", "2025-12"),
        ("2025-10-06", "2025-11"),
        ("2025-09-21", "2025-10"),
        ("2025-09-22", "2025-11"),
    ]
    for occurred, expected_bill in cases:
        got = statement.statement_for_date(occurred, cutoff)
        ok = got == expected_bill
        failures += 0 if ok else 1
        print(f"  {occurred} -> {got}  {'ok' if ok else f'FAILED (wanted {expected_bill})'}")
    nov_start, nov_end = statement.statement_period("2025-11", cutoff)
    ok = (nov_start, nov_end) == ("2025-09-22", "2025-10-21")
    failures += 0 if ok else 1
    print(f"  2025-11 period {nov_start} .. {nov_end}  {'ok' if ok else 'FAILED'}")

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
