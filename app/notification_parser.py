"""Reads bank push notifications off a phone lock-screen / notification-centre
screenshot.

Each card looks like this, with the timestamp on the same visual row as the title:

    Compra no crédito                                        Sun, 19:26
    Olá, Lucas. Você acaba de comprar R$ 43,89 em PONTO LAGOA. A compra
    foi no crédito nacional, com o cartão final 9523.

Only purchase cards are wanted. The same screenshot usually also contains
marketing pushes ("Quer tirar R$5,94 da fatura...") and notifications from
other apps entirely, and those must be dropped.

The hard part is the date: the card only says "Sun", so a weekday has to be
resolved backwards from the day the screenshot was taken.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

from .parsing import (CURRENCY_PATTERN, CURRENCY_CODE_BY_SYMBOL, Line,
                      ParsedTransaction, parse_amount_to_cents)

# The notification title that marks a credit-card purchase. Matched against
# accent-stripped text because OCR is not always careful with "crédito".
TITLE_PATTERN = re.compile(r"compra\s+no\s+credito", re.IGNORECASE)

# "Você acaba de comprar R$ 43,89 em PONTO LAGOA. A compra foi no crédito..."
# The merchant runs to the end of the sentence, and may itself contain dots
# ("IFD*53.700.820 ELIZABE"), so the terminator is looked for explicitly
# instead of just splitting on the first period.
BODY_PATTERN = re.compile(
    rf"comprar\s+(?P<amount>{CURRENCY_PATTERN}\s*[\d.,]+)\s+em\s+(?P<merchant>.+?)"
    rf"(?=\s*\.\s*a\s+compra\b|\s*\.\s*$|\s*$)",
    re.IGNORECASE | re.DOTALL)

# Trailing timestamp on a card's title row: "Sun, 19:26", "Yesterday, 08:04",
# "13/09, 19:26" or a bare "19:26" for today.
TIMESTAMP_PATTERN = re.compile(
    r"(?:(?P<label>[A-Za-zÀ-ÿ]{3,9})\.?\s*,?\s*)?"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<meridiem>am|pm)?\s*$",
    re.IGNORECASE)

WEEKDAY_INDEX = {
    "mon": 0, "monday": 0, "seg": 0, "segunda": 0,
    "tue": 1, "tues": 1, "tuesday": 1, "ter": 1, "terca": 1,
    "wed": 2, "wednesday": 2, "qua": 2, "quarta": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "qui": 3, "quinta": 3,
    "fri": 4, "friday": 4, "sex": 4, "sexta": 4,
    "sat": 5, "saturday": 5, "sab": 5, "sabado": 5,
    "sun": 6, "sunday": 6, "dom": 6, "domingo": 6,
}

RELATIVE_LABELS = {
    "today": 0, "hoje": 0, "now": 0, "agora": 0,
    "yesterday": -1, "ontem": -1,
}


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return decomposed.encode("ascii", "ignore").decode()


def is_purchase_title(text: str) -> bool:
    return TITLE_PATTERN.search(strip_accents(text)) is not None


@dataclass
class Timestamp:
    time: str | None = None            # "HH:MM"
    label: str | None = None           # "Sun", "Yesterday", ...


def parse_timestamp(text: str) -> Timestamp | None:
    """Reads the timestamp from the right-hand end of a card's title row."""
    match = TIMESTAMP_PATTERN.search(text.strip())
    if not match:
        return None
    hour, minute = int(match.group("hour")), int(match.group("minute"))
    meridiem = (match.group("meridiem") or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    label = match.group("label")
    return Timestamp(time=f"{hour:02d}:{minute:02d}",
                     label=label.lower() if label else None)


def resolve_date(label: str | None, reference: date) -> tuple[date, str]:
    """Turns a notification's day label into a real date.

    Notification lists only label things relative to now, so everything is
    resolved backwards from the day the screenshot was taken. A weekday equal to
    the reference day means a week ago, because the phone would have written
    "Today" for today.
    """
    if not label:
        return reference, "notification"

    key = strip_accents(label).lower().strip(".,")

    if key in RELATIVE_LABELS:
        return reference + timedelta(days=RELATIVE_LABELS[key]), "notification"

    if key in WEEKDAY_INDEX:
        delta = (reference.weekday() - WEEKDAY_INDEX[key]) % 7
        return reference - timedelta(days=delta or 7), "notification"

    return reference, "fallback"


def _looks_like_card_header(text: str) -> bool:
    """A new notification card starts on any row that ends with a timestamp."""
    return parse_timestamp(text) is not None


def parse(lines: list[Line], reference_date: date | None = None,
          default_currency: str | None = None) -> list[ParsedTransaction]:
    """Extracts credit-card purchases from notification-screenshot lines."""
    from . import config

    reference_date = reference_date or date.today()
    default_currency = default_currency or config.CURRENCY

    results: list[ParsedTransaction] = []

    for index, line in enumerate(lines):
        if not is_purchase_title(line.text):
            continue

        timestamp = parse_timestamp(line.text) or Timestamp()

        # Collect the card's body: everything up to the next card's header.
        body_parts: list[str] = []
        for follower in lines[index + 1:index + 7]:
            if _looks_like_card_header(follower.text) or is_purchase_title(follower.text):
                break
            body_parts.append(follower.text)
        body = " ".join(body_parts)

        match = BODY_PATTERN.search(body)
        if not match:
            continue

        cents = parse_amount_to_cents(match.group("amount"))
        if not cents:
            continue

        # Merchants are kept exactly as the bank wrote them, uppercase included.
        merchant = re.sub(r"\s+", " ", match.group("merchant")).strip(" .,;:")
        if not merchant:
            continue

        symbol = re.search(CURRENCY_PATTERN, match.group("amount"), re.IGNORECASE)
        currency = (CURRENCY_CODE_BY_SYMBOL.get(symbol.group(0).upper())
                    if symbol else None) or default_currency

        occurred_on, date_source = resolve_date(timestamp.label, reference_date)

        results.append(ParsedTransaction(
            merchant=merchant,
            amount_cents=cents,
            occurred_on=occurred_on.isoformat(),
            occurred_time=timestamp.time,
            currency=currency,
            raw_line=f"{line.text} | {body}".strip(),
            confidence=round(line.confidence, 3),
            date_source=date_source,
        ))

    return results
