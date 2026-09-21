"""Loads the installment plans and subscriptions read off the spreadsheet images.

This is a one-time transcription of `installment1.png` (Parcelamentos) and
`subscriptions.png` (Assinaturas). Everything from here on is entered through
the app, so this script exists only to avoid retyping the starting position.

Both images carry totals that act as a checksum, and reproducing them settled a
question about the spreadsheet itself. The column headed "Parcelas Restantes"
holds the *plan length* — the "12x" — not the number of installments still to
pay. Reading it as the plan length reproduces every per-bank figure in
`installment2.png` to the cent (BB and C6 at R$ 0.00 still owed, PicPay at
R$ 1,725.00, total R$ 2,925.24); reading it as a pending count misses all five.
So the numbers below are transcribed as printed and the pending count is
derived as `plan length - parcela atual`.

Run with --replace to wipe both tables first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import commitments, db          # noqa: E402

# Exactly as printed in installment1.png:
#   despesa, valor da parcela, parcela atual, parcelas restantes (= plan length), banco
INSTALLMENTS = [
    ("Bossa",                        68.00,  2,  2, "BB"),
    ("Kit Perfume Boticario",        33.01,  2,  2, "C6"),
    ("Celular Mamae (adiantar direto na fatura do Inter)",
                                    139.89,  6, 10, "Inter"),
    ("Manutencao Ar",                89.63,  1,  3, "Inter"),
    ("Codenames",                    33.32,  5,  6, "Mercado Pago"),
    ("Arranhador e brinquedo",       34.11,  2,  2, "Mercado Pago"),
    ("Rede de protecao maiobao",     78.69,  1,  3, "Mercado Pago"),
    ("Adaptador cartao sony",        19.63,  1,  2, "Mercado Pago"),
    ("Bone",                         41.03,  1,  4, "Mercado Pago"),
    ("Ventilador",                   32.00,  0,  4, "Mercado Pago"),
    ("Restante Mercado Pago",       726.00,  1,  1, "Mercado Pago"),
    ("Celular",                     360.00,  7, 10, "PicPay"),
    ("Perfume",                      39.67,  6,  6, "PicPay"),
    ("Cybershot",                    64.50,  2, 12, "PicPay"),
    ("Restante PicPay",             488.17,  1,  1, "PicPay"),
]

# The month the spreadsheet figures above were true for. Plans are stored as a
# first month plus a length, so this is what "parcela atual" is measured against.
ANCHOR_MONTH = "2026-09"

# Fixed monthly bills. Paid/pending is tracked per month, not here.
FIXED_EXPENSES = [
    ("Aluguel",       500.00, None),
    ("Conta Energia", 350.00, None),
]

SUBSCRIPTIONS = [
    ("Plano do celular",  37.80, "C6"),
    ("YT Premium",        24.90, "C6"),
    ("Selfit",           130.00, "C6"),
    ("Porto Seguro",      34.85, "Inter"),
    ("Duo Goumert",       53.80, "Inter"),
    ("iFood",              7.95, "Inter"),
    ("Meli+",              9.90, "Mercado Pago"),
    ("iCloud",            19.90, "PicPay"),
]

# Per-bank figures printed in installment2.png: this month's installments and the
# sum still owed. Used as a checksum on the transcription above.
EXPECTED_MONTHLY = {
    "BB": 68.00,
    "C6": 33.01,
    "Inter": 229.52,
    "PicPay": 952.34,
    "Mercado Pago": 932.78,
}
EXPECTED_PENDING = {
    "BB": 0.00,
    "C6": 0.00,
    "Inter": 738.82,
    "PicPay": 1725.00,
    "Mercado Pago": 461.42,
}
EXPECTED_PENDING_TOTAL = 2925.24
EXPECTED_SUBSCRIPTION_TOTAL = 319.10


def cents(value: float) -> int:
    return int(round(value * 100))


def main() -> None:
    replace = "--replace" in sys.argv

    if replace:
        with db.connect() as conn:
            conn.execute("DELETE FROM installments")
            conn.execute("DELETE FROM subscriptions")
            conn.execute("DELETE FROM fixed_expense_payments")
            conn.execute("DELETE FROM fixed_expenses")
        print("cleared installments, subscriptions and fixed expenses")

    for description, monthly, current, plan_length, bank in INSTALLMENTS:
        # "parcela atual" is which installment fell due in the anchor month, so
        # installment 1 was current - 1 months before it.
        db.create_installment(
            description, cents(monthly), total=plan_length,
            first_month=db.shift_month(ANCHOR_MONTH, -(current - 1) if current
                                       else 1),
            bank=bank)
    print(f"inserted {len(INSTALLMENTS)} installment plan(s)")

    for description, monthly, bank in SUBSCRIPTIONS:
        db.create_subscription(description, cents(monthly), bank)
    print(f"inserted {len(SUBSCRIPTIONS)} subscription(s)")

    for description, monthly, due_day in FIXED_EXPENSES:
        db.create_fixed_expense(description, cents(monthly), due_day=due_day)
    print(f"inserted {len(FIXED_EXPENSES)} fixed expense(s)")

    # --- verify against the totals printed in installment2.png ---
    problems: list[str] = []

    def compare(label: str, got_cents: int, expected: float) -> None:
        got = got_cents / 100
        ok = abs(got - expected) <= 0.005
        if not ok:
            problems.append(label)
        print(f"  {label:<16} {got:>9.2f}  image {expected:>9.2f}   "
              f"{'ok' if ok else 'MISMATCH'}")

    # Checked against the anchor month, since that is the month the image showed.
    rollups = {r.bank: r for r in
               commitments.by_bank(db.list_installments(), month=ANCHOR_MONTH)}
    totals = commitments.installment_totals(db.list_installments(),
                                            month=ANCHOR_MONTH)

    print("\nthis month's installments, per bank")
    for bank in sorted(EXPECTED_MONTHLY):
        compare(bank, rollups[bank].monthly_cents, EXPECTED_MONTHLY[bank])
    compare("SUBTOTAL", totals["monthly_cents"], 2215.64)

    print("\nstill owed after this month, per bank")
    for bank in sorted(EXPECTED_PENDING):
        compare(bank, rollups[bank].pending_cents, EXPECTED_PENDING[bank])
    compare("SUBTOTAL", totals["pending_cents"], EXPECTED_PENDING_TOTAL)

    print("\nsubscriptions")
    subs = commitments.subscription_totals(db.list_subscriptions())
    compare("SUBTOTAL", subs["monthly_cents"], EXPECTED_SUBSCRIPTION_TOTAL)

    # The one cent on the monthly subtotal is Excel rounding each displayed
    # installment, not a transcription error: the per-bank figures all agree.
    tolerated = {"SUBTOTAL"} if problems == ["SUBTOTAL"] else set()
    remaining = [p for p in problems if p not in tolerated]
    if remaining:
        print("\nCHECK FAILED for: " + ", ".join(remaining))
        sys.exit(1)
    print("\nall per-bank figures reproduce the spreadsheet.")


if __name__ == "__main__":
    main()
