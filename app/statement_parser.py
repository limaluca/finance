"""Reads the bank's in-app statement list ("Faturas" / "Despesas da fatura").

Each purchase occupies three stacked lines, indented away from the left margin,
with date headers sitting at the margin between groups:

    Domingo, 13 de set                      <- date header, at the left margin
        Restaurantes                        <- the bank's own category
        -R$ 43,89                           <- amount, shown as money leaving
        IFD*53.700.820 ELIZABE              <- merchant, then city and state

The merchant line is the awkward one. The bank appends the city and state
("PONTO LAGOA    SAO LUIS    MA") and the text wraps unpredictably, so the
merchant is taken from the first OCR box on that line and any location remnant
fused into it is stripped afterwards.

Two things this format gives us that push notifications do not: the bank's own
category, which beats guessing from the merchant name, and a real calendar date
from the group headers.
"""

import re
from datetime import date

from .ocr.base import TextBox
from .parsing import (CURRENCY_PATTERN, Line, ParsedTransaction, find_date,
                      group_boxes_into_lines, looks_like_date_header,
                      parse_amount_to_cents)

# Row content is indented; date headers and section titles sit at the margin.
CONTENT_LEFT_EDGE = 0.18

# The bank's categories, mapped onto ours. Anything mapping to None is too
# generic to trust and falls through to merchant keyword matching instead.
BANK_CATEGORIES: dict[str, str | None] = {
    "supermercado": "Groceries",
    "supermercados": "Groceries",
    "mercado": "Groceries",
    "restaurantes": "Food & Dining",
    "restaurante": "Food & Dining",
    "alimentacao": "Food & Dining",
    "bares e restaurantes": "Food & Dining",
    "transporte": "Transport",
    "transportes": "Transport",
    "combustivel": "Transport",
    "entretenimento": "Entertainment",
    "lazer": "Entertainment",
    "saude": "Health",
    "saude e bem-estar": "Health",
    "farmacia": "Health",
    "vestuario": "Shopping",
    "compras": "Shopping",
    "eletronicos": "Shopping",
    "casa": "Home",
    "moradia": "Home",
    "educacao": "Education",
    "viagem": "Travel",
    "viagens": "Travel",
    "assinaturas": "Subscriptions",
    "telefonia": "Bills & Utilities",
    "pets": "Pets",
    # Deliberately unmapped: these tell us nothing useful.
    "servicos": None,
    "outros": None,
    "diversos": None,
    "nao categorizado": None,
}

# Buttons and headings that are not transaction data.
UI_CHROME = re.compile(
    r"^(faturas?|despesas da fatura|antecipar fatura|fatura atual|pagar fatura|"
    r"parcelar( fatura)?|ver mais|mostrar mais|extrato|total|resumo|"
    r"lan[çc]amentos|limite\b.*|saldo\b.*)$", re.IGNORECASE)

# "-R$ 43,89" — the minus is how the app draws money going out.
AMOUNT_LINE = re.compile(
    rf"(?P<sign>[-+\u2212\u2013])?\s*{CURRENCY_PATTERN}\s*(?P<num>[\d.,]+)",
    re.IGNORECASE)

# Brazilian state codes and the country codes the bank prints.
STATE_CODES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}
COUNTRY_CODES = {
    "BRA", "USA", "ARG", "URY", "PRY", "CHL", "COL", "PER", "MEX", "PRT",
    "ESP", "FRA", "ITA", "DEU", "GBR", "NLD", "CAN", "JPN", "CHN", "AUS",
}
# First words of Brazilian city names, which is what gets fused onto the end of
# a merchant when the line wraps ("... TRIP HELP U SAO" + "PAULO BRA").
CITY_PREFIXES = {
    "SAO", "SÃO", "RIO", "BELO", "PORTO", "SANTO", "SANTA", "NOVA", "NOVO",
    "CAMPO", "CAMPOS", "RIBEIRAO", "RIBEIRÃO", "PRESIDENTE", "GOVERNADOR",
    "MONTES", "JUIZ", "VOLTA", "FOZ", "SETE", "TRES", "TRÊS", "SERRA",
}


def _normalize_key(text: str) -> str:
    import unicodedata
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", stripped).strip().lower()


def map_bank_category(text: str) -> str | None:
    """Translates the bank's category label into one of ours."""
    return BANK_CATEGORIES.get(_normalize_key(text).rstrip(":"))


def is_bank_category(text: str) -> bool:
    return _normalize_key(text).rstrip(":") in BANK_CATEGORIES


def strip_location(merchant: str) -> str:
    """Removes the city/state/country tail the bank appends to merchant names.

    Works from the end inwards: a country or state code, then any city words
    that got fused into the same OCR box. Never strips everything — if only
    location-looking tokens remain, the original is kept.
    """
    tokens = merchant.split()
    while len(tokens) > 1:
        last = tokens[-1].strip(".,").upper()
        if last in COUNTRY_CODES or last in STATE_CODES or last in CITY_PREFIXES:
            tokens.pop()
            continue
        break
    return " ".join(tokens).strip(" .,-") or merchant


def _first_segment(line: Line) -> str:
    """The merchant is the left-most box; city and state are boxes to its right."""
    if not line.boxes:
        return ""
    return line.boxes[0].text.strip()


def _is_content_line(line: Line) -> bool:
    return bool(line.boxes) and max(b.x for b in line.boxes) >= CONTENT_LEFT_EDGE


def _amount_from_line(line: Line) -> tuple[int, str] | None:
    """Returns (signed cents, matched text) if the line states an amount.

    The bank draws expenses with a leading minus. We store spending as positive,
    so the sign is inverted: "-R$ 43,89" becomes +4389.
    """
    match = AMOUNT_LINE.search(line.text)
    if not match:
        return None
    cents = parse_amount_to_cents(match.group("num"))
    if not cents:
        return None
    is_credit = match.group("sign") == "+"
    return (-cents if is_credit else cents), match.group(0)


def looks_like_statement(lines: list[Line]) -> bool:
    """Detects this layout: indented amount lines with a category above them."""
    hits = 0
    for index, line in enumerate(lines):
        if not _is_content_line(line) or _amount_from_line(line) is None:
            continue
        previous = lines[index - 1].text if index else ""
        if is_bank_category(previous):
            hits += 1
    return hits >= 2


def parse(lines: list[Line], today: date | None = None,
          default_currency: str | None = None) -> list[ParsedTransaction]:
    from . import config

    today = today or date.today()
    default_currency = default_currency or config.CURRENCY

    # Rows above the first visible date header belong to a group whose header
    # scrolled off the top. We anchor them to the first header we do see and
    # flag them, rather than inventing a date.
    first_header: date | None = None
    for line in lines:
        match = find_date(line.text, today=today)
        if match and looks_like_date_header(line.text, match):
            first_header = match.value
            break

    results: list[ParsedTransaction] = []
    header_date: date | None = None

    for index, line in enumerate(lines):
        if UI_CHROME.match(line.text.strip()):
            continue

        date_match = find_date(line.text, today=today)
        if date_match and not date_match.ambiguous and looks_like_date_header(line.text, date_match):
            header_date = date_match.value
            continue

        if not _is_content_line(line):
            continue
        amount = _amount_from_line(line)
        if amount is None:
            continue
        cents, amount_text = amount

        # The category sits on the line above; without it this is not a row.
        category_line = lines[index - 1].text.strip() if index else ""
        bank_category = category_line if is_bank_category(category_line) else None
        if bank_category is None:
            continue

        # The merchant is on the line below, unless the row is clipped at the
        # bottom of the screenshot and got merged into the amount line.
        merchant = ""
        if index + 1 < len(lines):
            candidate = lines[index + 1]
            if (_is_content_line(candidate)
                    and not UI_CHROME.match(candidate.text.strip())
                    and not is_bank_category(candidate.text)
                    and _amount_from_line(candidate) is None):
                merchant = _first_segment(candidate)
        if not merchant:
            leftover = line.text.replace(amount_text, " ").strip(" |")
            merchant = re.sub(r"\s{2,}", " ", leftover).strip()
        merchant = strip_location(merchant)
        if not merchant:
            continue

        occurred = header_date or first_header or today
        if header_date:
            date_source = "header"
        elif first_header:
            date_source = "guess"
        else:
            date_source = "fallback"

        results.append(ParsedTransaction(
            merchant=merchant,
            amount_cents=cents,
            occurred_on=occurred.isoformat(),
            occurred_time=None,
            currency=default_currency,
            category=map_bank_category(bank_category) or "",
            raw_line=f"{bank_category} | {amount_text} | {merchant}",
            confidence=round(line.confidence, 3),
            date_source=date_source,
        ))

    return results


def parse_boxes(boxes: list[TextBox], **kwargs) -> list[ParsedTransaction]:
    return parse(group_boxes_into_lines(boxes), **kwargs)
