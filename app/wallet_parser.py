"""Reads the iPhone Wallet card transaction list.

Each purchase is one to three lines: the merchant with its amount, then
optionally where it happened, then when — and "when" is always relative:

    Latest Transactions
    Sesc Turismo                                        R$ 13,51  >
    São Luís, MA
    4 hours ago
    Armazzem Be Life li C                               R$ 17,97  >
    São José de Ribamar, MA
    Yesterday
    Uber                                                 R$ 5,94  >
    Apple Pay
    Sunday

Wallet never prints a calendar date for recent purchases, so the day label is
resolved backwards from the day the screenshot was taken. A bare weekday means
the most recent one *before* today, since today's purchases say "N hours ago".
"""

import re
from datetime import date, timedelta

from .notification_parser import (RELATIVE_LABELS, WEEKDAY_INDEX, strip_accents)
from .parsing import (CURRENCY_PATTERN, Line, ParsedTransaction, find_date,
                      group_boxes_into_lines, parse_amount_to_cents)

# Wallet draws a "›" chevron at the end of every row.
CHEVRONS = "><\u203a\u276f\u2771\u3009\u232a"

AMOUNT = re.compile(rf"(?P<amount>{CURRENCY_PATTERN}\s*[\d.,]+)", re.IGNORECASE)

# "4 hours ago", "34 min ago", "2 minutes ago", "just now"
ELAPSED = re.compile(
    r"^\s*(?:(?P<count>\d{1,2})\s*(?P<unit>h|hr|hrs|hour|hours|m|min|mins|minute|minutes)"
    r"\s*ago|just now|agora|now)\s*$", re.IGNORECASE)

# A location line: "São Luís, MA", "São José de Ribamar, MA", or the payment rail.
LOCATION = re.compile(
    r"^(?:apple\s*pay|google\s*pay|carteira|wallet|.+,\s*[A-Z]{2})$", re.IGNORECASE)

TITLES = re.compile(
    r"^(?:latest transactions|transactions|transa[cç][õo]es|"
    r"[uú]ltimas transa[cç][õo]es|latest|hist[oó]rico)$", re.IGNORECASE)


def _day_label(text: str, reference: date) -> tuple[date, str] | None:
    """Interprets a Wallet day label. Returns (date, how_confident) or None."""
    cleaned = text.strip().strip("".join(CHEVRONS)).strip()
    if not cleaned:
        return None

    if ELAPSED.match(cleaned):
        return reference, "wallet"

    key = strip_accents(cleaned).lower().strip(".,")
    if key in RELATIVE_LABELS:
        return reference + timedelta(days=RELATIVE_LABELS[key]), "wallet"

    if key in WEEKDAY_INDEX:
        delta = (reference.weekday() - WEEKDAY_INDEX[key]) % 7
        # Today would have been written "N hours ago", so a matching weekday
        # name means a week back.
        return reference - timedelta(days=delta or 7), "wallet"

    # Older purchases get a real date, which the shared date reader handles.
    match = find_date(cleaned, today=reference)
    if match and not match.ambiguous:
        return match.value, "wallet"

    return None


def _strip_chevrons(text: str) -> str:
    return text.strip().strip("".join(CHEVRONS)).strip(" .·|")


def looks_like_wallet(lines: list[Line], reference: date | None = None) -> bool:
    """True when amount rows are followed by Wallet's relative day labels."""
    reference = reference or date.today()
    if any(TITLES.match(line.text.strip()) for line in lines):
        # The title alone is not enough; still require at least one dated row.
        pass
    hits = 0
    for index, line in enumerate(lines):
        if not AMOUNT.search(line.text):
            continue
        for follower in lines[index + 1:index + 3]:
            if _day_label(follower.text, reference):
                hits += 1
                break
    return hits >= 2


def parse(lines: list[Line], reference_date: date | None = None,
          default_currency: str | None = None) -> list[ParsedTransaction]:
    from . import config
    from .merchants import canonical

    reference = reference_date or date.today()
    default_currency = default_currency or config.CURRENCY

    results: list[ParsedTransaction] = []
    # The list runs newest first, so a row whose day label was cut off by the
    # bottom of the screen happened on or before the row above it.
    carried: date | None = None

    for index, line in enumerate(lines):
        text = line.text.strip()
        if TITLES.match(text):
            continue

        match = AMOUNT.search(text)
        if not match:
            continue

        cents = parse_amount_to_cents(match.group("amount"))
        if not cents:
            continue

        merchant_text = _strip_chevrons(text[:match.start()])
        if not merchant_text or not re.search(r"[A-Za-zÀ-ÿ0-9]", merchant_text):
            continue

        # Walk the next couple of lines: an optional location, then the day.
        occurred: date | None = None
        source = "fallback"
        location = ""
        for follower in lines[index + 1:index + 4]:
            follower_text = _strip_chevrons(follower.text)
            resolved = _day_label(follower_text, reference)
            if resolved:
                occurred, source = resolved
                break
            if LOCATION.match(follower_text):
                location = follower_text
                continue
            if AMOUNT.search(follower.text):
                break       # Already into the next purchase.

        if occurred is None:
            occurred, source = (carried or reference), "fallback"
        else:
            carried = occurred

        results.append(ParsedTransaction(
            merchant=canonical(merchant_text),
            amount_cents=cents,
            occurred_on=occurred.isoformat(),
            occurred_time=None,
            currency=default_currency,
            raw_line=" | ".join(p for p in (merchant_text, location) if p),
            confidence=round(line.confidence, 3),
            date_source=source,
        ))

    return results


def parse_boxes(boxes, **kwargs) -> list[ParsedTransaction]:
    return parse(group_boxes_into_lines(boxes), **kwargs)
