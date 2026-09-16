"""CSV export and import.

One format, both directions, so a file exported from the app can be edited in a
spreadsheet and imported straight back:

    date,time,merchant,category,amount,currency
    2026-09-13,19:26,PONTO LAGOA,Food & Dining,34.55,BRL

`amount` is a plain decimal with a dot, positive for spending and negative for a
refund. `time` may be blank — statement rows do not carry one.
"""

import csv
import io
import re

from . import config
from .parsing import ParsedTransaction, parse_date_input, parse_money_input

COLUMNS = ["date", "time", "merchant", "category", "amount", "currency"]

# Accepted spellings for each column, so a hand-edited or translated file still
# imports. Keys are what we call them internally.
ALIASES = {
    "date": {"date", "data", "occurred_on", "day", "dia"},
    "time": {"time", "hora", "occurred_time", "hour"},
    "merchant": {"merchant", "vendor", "estabelecimento", "description",
                 "descricao", "descrição", "loja", "name"},
    "category": {"category", "categoria"},
    "amount": {"amount", "valor", "value", "total", "price", "preco", "preço"},
    "currency": {"currency", "moeda"},
}


def export_rows(transactions) -> str:
    """Renders transactions as CSV text."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for tx in transactions:
        writer.writerow([
            tx["occurred_on"],
            tx["occurred_time"] or "",
            tx["merchant"],
            tx["category"],
            f"{tx['amount_cents'] / 100:.2f}",
            tx["currency"] or config.CURRENCY,
        ])
    return buffer.getvalue()


def _header_map(fieldnames: list[str]) -> dict[str, str]:
    """Maps the file's actual headers onto our column names."""
    mapping: dict[str, str] = {}
    for raw in fieldnames or []:
        key = (raw or "").strip().lower().lstrip("\ufeff")
        for canonical, spellings in ALIASES.items():
            if key in spellings:
                mapping[canonical] = raw
                break
    return mapping


class CsvFormatError(ValueError):
    pass


def parse_csv(text: str) -> tuple[list[ParsedTransaction], list[str]]:
    """Reads CSV text into transactions, plus a list of per-row complaints."""
    # Sniff the delimiter so semicolon-separated exports (common on pt-BR
    # spreadsheet locales) also work.
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    mapping = _header_map(reader.fieldnames or [])

    missing = [name for name in ("date", "merchant", "amount") if name not in mapping]
    if missing:
        found = ", ".join(reader.fieldnames or []) or "nothing"
        raise CsvFormatError(
            f"The CSV needs {', '.join(missing)} column(s). Found: {found}. "
            f"Expected header: {','.join(COLUMNS)}")

    transactions: list[ParsedTransaction] = []
    problems: list[str] = []

    for number, row in enumerate(reader, start=2):   # row 1 is the header
        def field(name: str) -> str:
            source = mapping.get(name)
            return (row.get(source) or "").strip() if source else ""

        if not any(field(name) for name in COLUMNS):
            continue        # blank line

        merchant = field("merchant")
        occurred_on = parse_date_input(field("date"))
        amount_cents = parse_money_input(field("amount"))

        if not merchant or occurred_on is None or amount_cents is None:
            problems.append(
                f"Row {number}: skipped, needs a date, a merchant and an amount "
                f"(got date={field('date')!r}, merchant={merchant!r}, "
                f"amount={field('amount')!r})")
            continue

        raw_time = field("time")
        occurred_time = None
        if raw_time:
            match = re.match(r"^(\d{1,2})[:h](\d{2})", raw_time)
            if match:
                hour, minute = int(match.group(1)), int(match.group(2))
                if hour <= 23 and minute <= 59:
                    occurred_time = f"{hour:02d}:{minute:02d}"

        transactions.append(ParsedTransaction(
            merchant=merchant,
            amount_cents=amount_cents,
            occurred_on=occurred_on,
            occurred_time=occurred_time,
            currency=field("currency") or config.CURRENCY,
            category=field("category"),
            raw_line=f"CSV row {number}",
            confidence=1.0,
            date_source="line",
        ))

    return transactions, problems
