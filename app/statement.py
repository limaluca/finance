"""Credit card statement cycles.

Purchases are grouped by when they land on the bill, not by calendar month.
The cutoff day (default 21) is the last purchase date that still belongs to
the *next* month's statement:

    purchase on or before 21 Oct  → November statement
    purchase from 22 Oct onward   → December statement

The statement is labelled by the month the bill is due (YYYY-MM).
"""

from datetime import date, timedelta
import calendar

from . import db

SETTING_CUTOFF = "statement_cutoff_day"
DEFAULT_CUTOFF = 21


def cutoff_day() -> int:
    raw = db.get_setting(SETTING_CUTOFF)
    if not raw:
        return DEFAULT_CUTOFF
    try:
        day = int(raw)
    except ValueError:
        return DEFAULT_CUTOFF
    return max(1, min(day, 31))


def save_cutoff(day: int) -> None:
    db.set_setting(SETTING_CUTOFF, str(max(1, min(int(day), 31))))


def statement_for_date(occurred_on: str, cutoff: int | None = None) -> str:
    """Which statement (bill due month) a purchase belongs to."""
    cutoff = cutoff if cutoff is not None else cutoff_day()
    d = date.fromisoformat(occurred_on)
    effective_cutoff = min(cutoff, calendar.monthrange(d.year, d.month)[1])
    offset = 1 if d.day <= effective_cutoff else 2
    return db.shift_month(d.strftime("%Y-%m"), offset)


def statement_period(statement: str, cutoff: int | None = None) -> tuple[str, str]:
    """Inclusive purchase dates that belong on this statement."""
    cutoff = cutoff if cutoff is not None else cutoff_day()
    # Bill due in `statement` closes on cutoff day of the month before,
    # and opens the day after cutoff two months before.
    end_month = db.shift_month(statement, -1)
    start_month = db.shift_month(statement, -2)
    sy, sm = int(start_month[:4]), int(start_month[5:7])
    ey, em = int(end_month[:4]), int(end_month[5:7])
    # Adding the cutoff to the first of the month naturally rolls into the
    # following month when (for example) February has no cutoff + 1 day.
    start_cutoff = min(cutoff, calendar.monthrange(sy, sm)[1])
    end_cutoff = min(cutoff, calendar.monthrange(ey, em)[1])
    start = date(sy, sm, 1) + timedelta(days=start_cutoff)
    return (start.isoformat(),
            date(ey, em, end_cutoff).isoformat())


def period_label(statement: str, cutoff: int | None = None) -> str:
    start, end = statement_period(statement, cutoff)
    return f"{start} – {end}"


def current_statement(today: date | None = None, cutoff: int | None = None) -> str:
    """Statement purchases are accumulating toward right now."""
    return statement_for_date((today or date.today()).isoformat(), cutoff)


def next_statement(today: date | None = None, cutoff: int | None = None) -> str:
    return db.shift_month(current_statement(today, cutoff), 1)


def available_statements(cutoff: int | None = None) -> list[str]:
    cutoff = cutoff if cutoff is not None else cutoff_day()
    seen: set[str] = set()
    with db.connect() as conn:
        rows = conn.execute("SELECT occurred_on FROM transactions").fetchall()
    for row in rows:
        seen.add(statement_for_date(row["occurred_on"], cutoff))
    return sorted(seen, reverse=True)
