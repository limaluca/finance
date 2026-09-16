"""Turns OCR boxes from a bank/credit-card screenshot into transaction rows.

The screenshots we care about are lists like:

    15 SET
    Uber Trip                     R$ 24,90
    Padaria do Bairro             R$ 12,50
    14 SET
    Netflix.com  2/12             R$ 55,90

so the strategy is:

1. Group OCR boxes into visual lines (merchant on the left, amount far right).
2. Remember "date header" lines and apply them to the rows underneath.
3. On each line, find the money amount, pull out any inline date/time, and
   treat whatever is left as the merchant name.

Anything ambiguous is still surfaced in the review screen, where a human fixes
it before it reaches the database.
"""

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from . import config
from .ocr.base import TextBox

# --------------------------------------------------------------------------
# Line grouping
# --------------------------------------------------------------------------


@dataclass
class Line:
    text: str
    boxes: list[TextBox] = field(default_factory=list)

    @property
    def center_y(self) -> float:
        return sum(b.center_y for b in self.boxes) / len(self.boxes)

    @property
    def confidence(self) -> float:
        if not self.boxes:
            return 0.0
        return sum(b.confidence for b in self.boxes) / len(self.boxes)


def _make_line(boxes: list[TextBox]) -> Line:
    ordered = sorted(boxes, key=lambda b: b.x)
    return Line(text=" ".join(b.text for b in ordered).strip(), boxes=ordered)


def group_boxes_into_lines(boxes: list[TextBox], tolerance: float = 0.6) -> list[Line]:
    """Merges boxes that sit on the same visual row.

    Engines report the left column and the right-aligned amount as separate
    observations, so we rejoin anything whose vertical centre lines up.
    """
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda b: (b.center_y, b.x))
    lines: list[list[TextBox]] = [[ordered[0]]]
    for box in ordered[1:]:
        current = lines[-1]
        avg_center = sum(b.center_y for b in current) / len(current)
        avg_height = sum(b.height for b in current) / len(current)
        if abs(box.center_y - avg_center) <= max(avg_height, box.height) * tolerance:
            current.append(box)
        else:
            lines.append([box])
    return [_make_line(group) for group in lines]


# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------

CURRENCY_PATTERN = r"(?:R\$|RS\$|US\$|USD|BRL|EUR|GBP|\$|€|£)"
_THOUSANDS = r"[.,\u00a0\u202f ]"
_WITH_CENTS = rf"\d{{1,3}}(?:{_THOUSANDS}\d{{3}})*[.,]\d{{2}}(?!\d)|\d+[.,]\d{{2}}(?!\d)"
_NO_CENTS = rf"\d{{1,3}}(?:{_THOUSANDS}\d{{3}})+(?!\d)|\d+(?!\d)"
_MINUS = r"[-\u2010\u2011\u2012\u2013\u2014\u2212]"

# An amount is only trustworthy if it carries a currency symbol or cents;
# otherwise we would happily read card digits and years as money.
_AMOUNT_WITH_SYMBOL = re.compile(
    rf"(?P<pre>{_MINUS}|\+)?\s*{CURRENCY_PATTERN}\s*(?P<mid>{_MINUS}|\+)?\s*"
    rf"(?P<num>{_WITH_CENTS}|{_NO_CENTS})", re.IGNORECASE)
_AMOUNT_WITH_CENTS = re.compile(rf"(?P<pre>{_MINUS}|\+)?\s*(?P<num>{_WITH_CENTS})")

CURRENCY_CODE_BY_SYMBOL = {
    "R$": "BRL", "RS$": "BRL", "BRL": "BRL",
    "$": "USD", "US$": "USD", "USD": "USD",
    "€": "EUR", "EUR": "EUR", "£": "GBP", "GBP": "GBP",
}


def parse_amount_to_cents(raw: str) -> int | None:
    """Reads '1.234,56', '1,234.56', '12,50' and '1234' as cents.

    Separator meaning is decided per string: whichever separator comes last is
    the decimal point, and a lone separator followed by exactly two digits is
    also decimal.
    """
    text = re.sub(r"[^\d.,]", "", raw or "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        for sep in (",", "."):
            if sep in text:
                tail = text.rsplit(sep, 1)[1]
                if text.count(sep) == 1 and len(tail) == 2:
                    text = text.replace(sep, ".")
                else:
                    text = text.replace(sep, "")
                break
    try:
        return int((Decimal(text) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        return None


@dataclass
class AmountMatch:
    cents: int
    start: int
    end: int
    currency: str | None = None


def find_amount(text: str) -> AmountMatch | None:
    """Finds the money value on a line, preferring the right-most one.

    Right-most wins because statement rows put the merchant (which may itself
    contain numbers) on the left and the amount on the right.
    """
    for pattern in (_AMOUNT_WITH_SYMBOL, _AMOUNT_WITH_CENTS):
        candidates = [m for m in pattern.finditer(text) if not _looks_like_date_part(text, m)]
        if not candidates:
            continue
        match = candidates[-1]
        cents = parse_amount_to_cents(match.group("num"))
        if cents is None or cents == 0:
            continue
        negative = bool(match.group("pre") and re.match(_MINUS, match.group("pre")))
        if "mid" in match.groupdict() and match.group("mid"):
            negative = negative or bool(re.match(_MINUS, match.group("mid")))
        # A trailing minus ("120,00-") is a credit in some statements.
        if re.match(rf"\s*{_MINUS}", text[match.end():]):
            negative = True
        symbol = re.search(CURRENCY_PATTERN, match.group(0), re.IGNORECASE)
        currency = CURRENCY_CODE_BY_SYMBOL.get(symbol.group(0).upper()) if symbol else None
        return AmountMatch(
            cents=-cents if negative else cents,
            start=match.start(), end=match.end(), currency=currency,
        )
    return None


def _looks_like_date_part(text: str, match: re.Match) -> bool:
    """Guards against reading '15/09' or '2026-09-15' as an amount."""
    before = text[max(0, match.start() - 1):match.start()]
    after = text[match.end():match.end() + 1]
    return before in {"/", "-"} or after in {"/", "-"}


# --------------------------------------------------------------------------
# Dates and times
# --------------------------------------------------------------------------

MONTHS = {
    "jan": 1, "january": 1, "janeiro": 1,
    "feb": 2, "february": 2, "fev": 2, "fevereiro": 2,
    "mar": 3, "march": 3, "marco": 3, "março": 3,
    "apr": 4, "april": 4, "abr": 4, "abril": 4,
    "may": 5, "mai": 5, "maio": 5,
    "jun": 6, "june": 6, "junho": 6,
    "jul": 7, "july": 7, "julho": 7,
    "aug": 8, "august": 8, "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "september": 9, "set": 9, "setembro": 9,
    "oct": 10, "october": 10, "out": 10, "outubro": 10,
    "nov": 11, "november": 11, "novembro": 11,
    "dec": 12, "december": 12, "dez": 12, "dezembro": 12,
}

WEEKDAYS = {
    "mon", "monday", "tue", "tues", "tuesday", "wed", "wednesday", "thu",
    "thur", "thurs", "thursday", "fri", "friday", "sat", "saturday", "sun",
    "sunday", "seg", "segunda", "ter", "terca", "terça", "qua", "quarta",
    "qui", "quinta", "sex", "sexta", "sab", "sabado", "sábado", "dom",
    "domingo", "feira",
}

_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH_NAME = re.compile(
    rf"\b(\d{{1,2}})\s*(?:de\s+|º\s*|°\s*)?({_MONTH_NAMES})\.?"
    rf"(?:\s*(?:de\s+|,\s*)?(\d{{4}}|\d{{2}})\b)?", re.IGNORECASE)
_MONTH_NAME_DAY = re.compile(
    rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:\s*(?:,\s*)?(\d{{4}})\b)?", re.IGNORECASE)
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{4}|\d{2}))?\b")
_TIME = re.compile(r"\b(\d{1,2})[:hH](\d{2})\b")
_RELATIVE = {
    "hoje": 0, "today": 0,
    "ontem": -1, "yesterday": -1,
    "anteontem": -2,
}


def _normalize_month(name: str) -> int | None:
    key = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    return MONTHS.get(key) or MONTHS.get(name.lower())


def _infer_year(month: int, day: int, today: date | None = None) -> int:
    """Statements omit the year. Assume the most recent occurrence."""
    today = today or date.today()
    for year in (today.year, today.year - 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate <= today + timedelta(days=45):
            return year
    return today.year


def _build_date(year: int | None, month: int, day: int) -> date | None:
    if not (1 <= month <= 12):
        return None
    if year is not None and year < 100:
        year += 2000
    try:
        return date(year if year else _infer_year(month, day), month, day)
    except ValueError:
        return None


@dataclass
class DateMatch:
    value: date
    start: int
    end: int
    # True for things like "2/12" that read as a date but are much more likely
    # to be an installment counter ("charge 2 of 12").
    ambiguous: bool = False


def _looks_like_installment(match: re.Match) -> bool:
    """Distinguishes '2/12' (2nd of 12 installments) from '15/09' (a date).

    Statements zero-pad real dates and print installments unpadded with the
    counter never exceeding the total, so we lean on both signals.
    """
    if match.group(3):          # An explicit year means it is a date.
        return False
    first, second = match.group(1), match.group(2)
    if first.startswith("0") or second.startswith("0"):
        return False
    return int(first) <= int(second) <= 24


def find_date(text: str, today: date | None = None) -> DateMatch | None:
    """Finds the left-most date in a fragment of text, if any."""
    today = today or date.today()

    for word, offset in _RELATIVE.items():
        match = re.search(rf"\b{word}\b", text, re.IGNORECASE)
        if match:
            return DateMatch(today + timedelta(days=offset), match.start(), match.end())

    if match := _ISO_DATE.search(text):
        value = _build_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if value:
            return DateMatch(value, match.start(), match.end())

    if match := _DAY_MONTH_NAME.search(text):
        month = _normalize_month(match.group(2))
        if month:
            year = int(match.group(3)) if match.group(3) else None
            value = _build_date(year, month, int(match.group(1)))
            if value:
                return DateMatch(value, match.start(), match.end())

    if match := _MONTH_NAME_DAY.search(text):
        month = _normalize_month(match.group(1))
        if month:
            year = int(match.group(3)) if match.group(3) else None
            value = _build_date(year, month, int(match.group(2)))
            if value:
                return DateMatch(value, match.start(), match.end())

    if match := _NUMERIC_DATE.search(text):
        first, second = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else None
        if config.DATE_ORDER == "MDY":
            month, day = first, second
        else:
            day, month = first, second
        # Fall back to the other reading when one number cannot be a month.
        if month > 12 and day <= 12:
            day, month = month, day
        value = _build_date(year, month, day)
        if value:
            return DateMatch(value, match.start(), match.end(),
                             ambiguous=_looks_like_installment(match))

    return None


def find_time(text: str) -> tuple[str, int, int] | None:
    for match in _TIME.finditer(text):
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour <= 23 and minute <= 59:
            return f"{hour:02d}:{minute:02d}", match.start(), match.end()
    return None


# --------------------------------------------------------------------------
# Noise
# --------------------------------------------------------------------------

# Checked against what is left of a line AFTER the amount and date are removed,
# so "Total Fitness" survives while a bare "Total" summary row does not.
NOISE_PATTERNS = [
    r"^(total|subtotal|sum|soma)( geral| do m[êe]s| a pagar| gasto)?$",
    r"^(total|subtotal)\s+(da|do|de|of|the)\s+\S+.*$",
    # Phone status bar: a clock, then signal/battery indicators.
    r"^\d{1,2}[:h]\d{2}\s*(am|pm)?$",
    r"^\d{1,2}[:h]\d{2}\b.*\b(5g|4g|3g|lte|wi-?fi)\b.*$",
    r"^(saldo|balance|limite|limit|available|dispon[íi]vel)\b.*$",
    r"^(fatura|invoice|statement|extrato|hist[óo]rico|activity|atividade)\b.*$",
    r"^(vencimento|due date|fecha|closing)\b.*$",
    r"^pagamento (m[íi]nimo|total)\b.*$",
    r"^(minimum payment|current balance|previous balance)\b.*$",
    r"^(cr[ée]dito|credit) (dispon[íi]vel|available|limit)\b.*$",
    r"^(ver|mostrar|show|load) (mais|more|all|tudo)\b.*$",
    r"^(entradas|sa[íi]das|receitas|despesas)$",
    r"^(transa[çc][õo]es|transactions|lan[çc]amentos|purchases|compras)$",
    r"^(parcelar|pagar|pay|installments?)$",
    r"^[•*x\u2022\s]{2,}\d{0,4}$",
]
_NOISE_RE = [re.compile(p, re.IGNORECASE) for p in NOISE_PATTERNS]


def is_noise(text: str) -> bool:
    cleaned = text.strip(" .:,;|-–—\u2022*")
    if not cleaned:
        return True
    return any(rx.match(cleaned) for rx in _NOISE_RE)


def looks_like_date_header(text: str, date_match: DateMatch) -> bool:
    """True when a line carries a date and essentially nothing else."""
    remainder = (text[:date_match.start] + " " + text[date_match.end:])
    tokens = [t for t in re.split(r"[\s,.\u2022|·\-–—]+", remainder.lower()) if t]
    meaningful = [t for t in tokens if t not in WEEKDAYS and t not in {"de", "of", "no", "em"}]
    return not meaningful


def has_merchant_text(text: str) -> bool:
    """A real merchant name has letters. Requiring two of them rejects leftovers
    like "09:41 5G 100%" and "•••• 4321"."""
    return len(re.findall(r"[A-Za-zÀ-ÿ]", text)) >= 2


def clean_merchant(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" \t\u2022*·|,;:-–—.")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    # Screenshots are usually all-caps; make the table easier to read.
    if cleaned.isupper() and len(cleaned) > 4:
        cleaned = cleaned.title()
    return cleaned.strip()


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------


@dataclass
class ParsedTransaction:
    merchant: str
    amount_cents: int
    occurred_on: str
    occurred_time: str | None = None
    currency: str = ""
    category: str = ""
    raw_line: str = ""
    confidence: float = 0.0
    # "line" | "header" | "notification" | "guess" | "fallback"
    date_source: str = "line"
    duplicate: bool = False
    duplicate_kind: str = ""       # "exact" blocks saving, "likely" only warns
    duplicate_note: str = ""
    source_image: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def extract_transactions(boxes: list[TextBox], today: date | None = None,
                         default_currency: str | None = None) -> list[ParsedTransaction]:
    today = today or date.today()
    default_currency = default_currency or config.CURRENCY
    lines = group_boxes_into_lines(boxes)

    results: list[ParsedTransaction] = []
    header_date: date | None = None
    # A merchant whose amount is rendered on the row below, with the line index
    # it came from so we only ever borrow from the row immediately above.
    orphan: tuple[int, str] | None = None

    for index, line in enumerate(lines):
        text = line.text.strip()
        if not text:
            continue

        date_match = find_date(text, today=today)
        if date_match and not date_match.ambiguous and looks_like_date_header(text, date_match):
            header_date = date_match.value
            orphan = None
            continue

        amount = find_amount(text)
        if amount is None:
            if has_merchant_text(text) and not is_noise(text):
                orphan = (index, text)
            continue

        remainder = text[:amount.start] + " " + text[amount.end:]

        occurred: date | None = None
        date_source = "header"
        inline_date = find_date(remainder, today=today)
        # An ambiguous match such as "2/12" is only trusted when we have no
        # header date to fall back on; otherwise it stays in the merchant name.
        if inline_date and not (inline_date.ambiguous and header_date):
            occurred = inline_date.value
            date_source = "line"
            remainder = remainder[:inline_date.start] + " " + remainder[inline_date.end:]
        elif header_date:
            occurred = header_date

        occurred_time = None
        if time_match := find_time(remainder):
            occurred_time, t_start, t_end = time_match
            remainder = remainder[:t_start] + " " + remainder[t_end:]

        merchant = clean_merchant(remainder)
        if not merchant and orphan is not None and orphan[0] == index - 1:
            merchant = clean_merchant(orphan[1])
        orphan = None

        if not has_merchant_text(merchant) or is_noise(merchant):
            continue

        if occurred is None:
            occurred = today
            date_source = "fallback"

        results.append(ParsedTransaction(
            merchant=merchant,
            amount_cents=amount.cents,
            occurred_on=occurred.isoformat(),
            occurred_time=occurred_time,
            currency=amount.currency or default_currency,
            raw_line=text,
            confidence=round(line.confidence, 3),
            date_source=date_source,
        ))

    return results


def parse_screenshot(boxes: list[TextBox], reference_date: date | None = None,
                     today: date | None = None,
                     default_currency: str | None = None) -> list[ParsedTransaction]:
    """Parses a screenshot and categorises the result.

    Three shapes of screenshot are supported, tried in order of how confidently
    they can be identified: bank push notifications, the bank's in-app statement
    list, then a generic right-aligned-amount list as a last resort.

    `reference_date` is the day the screenshot was taken, which notification
    parsing needs to turn "Sun, 19:26" into a real date.
    """
    from . import notification_parser, statement_parser
    from .categorize import categorize

    lines = group_boxes_into_lines(boxes)

    transactions = notification_parser.parse(
        lines, reference_date=reference_date or today,
        default_currency=default_currency)

    if not transactions and statement_parser.looks_like_statement(lines):
        transactions = statement_parser.parse(
            lines, today=today, default_currency=default_currency)

    if not transactions:
        transactions = extract_transactions(
            boxes, today=today, default_currency=default_currency)

    for tx in transactions:
        # A category already set here came from the source itself (the bank's
        # own label), so it is passed along as a hint rather than overwritten.
        tx.category = categorize(tx.merchant, tx.amount_cents,
                                 hint=tx.category or None)
    return transactions


def format_cents(cents: int | None, currency: str | None = None) -> str:
    """Renders cents as money, pt-BR style for BRL and en-US style otherwise."""
    if cents is None:
        return ""
    symbol = config.currency_symbol(currency)
    sign = "-" if cents < 0 else ""
    whole, remainder = divmod(abs(int(cents)), 100)
    if (currency or config.CURRENCY) == "BRL":
        grouped = f"{whole:,}".replace(",", ".")
        return f"{sign}{symbol} {grouped},{remainder:02d}"
    grouped = f"{whole:,}"
    return f"{sign}{symbol}{grouped}.{remainder:02d}"


def parse_money_input(raw: str) -> int | None:
    """Parses whatever the user typed into the review form's amount field."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    negative = raw.startswith("-") or bool(re.match(rf"^{_MINUS}", raw))
    cents = parse_amount_to_cents(raw)
    if cents is None:
        return None
    return -abs(cents) if negative else cents


def image_taken_on(path) -> date | None:
    """Reads the capture date out of an image's EXIF, if it has any.

    Screenshots that travel through chat apps usually arrive stripped, so this
    is a best-effort hint rather than something to rely on.
    """
    try:
        from PIL import Image

        with Image.open(path) as img:
            exif = img.getexif()
        for tag in (36867, 36868, 306):  # DateTimeOriginal, DateTimeDigitized, DateTime
            value = exif.get(tag)
            if not value:
                continue
            try:
                return datetime.strptime(str(value).strip(), "%Y:%m:%d %H:%M:%S").date()
            except ValueError:
                continue
    except Exception:
        return None
    return None


def parse_date_input(raw: str) -> str | None:
    """Accepts YYYY-MM-DD (what the date input sends) or anything find_date knows."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass
    match = find_date(raw)
    return match.value.isoformat() if match else None
