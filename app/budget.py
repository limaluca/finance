"""The spending limit: "I have R$ 300 left, and it has to last until the 30th".

You type those two numbers and everything else is worked out from them, so the
daily allowance keeps itself honest as purchases are imported: it is always
what is left divided by the days still to cover, today included.

Spending is counted from the day the limit was set, because that is the moment
you looked at the money and decided it was R$ 300. Purchases from before then
belong to the part of the month you had already accounted for.
"""

from dataclasses import dataclass
from datetime import date

from . import db

LIMIT_CENTS = "spend_limit_cents"
LIMIT_UNTIL = "spend_limit_until"
LIMIT_FROM = "spend_limit_from"
LIMIT_SET_AT = "spend_limit_set_at"


@dataclass
class Limit:
    limit_cents: int
    until: str                  # YYYY-MM-DD, the last day it has to cover
    start: str                  # the day it was set, first day counted
    spent_cents: int            # net spending from start to until
    spent_today_cents: int
    today: str

    @property
    def remaining_cents(self) -> int:
        return self.limit_cents - self.spent_cents

    @property
    def days_left(self) -> int:
        """Days the limit still has to stretch over, counting today."""
        gap = (date.fromisoformat(self.until) - date.fromisoformat(self.today)).days
        return max(gap + 1, 0)

    @property
    def expired(self) -> bool:
        return self.days_left == 0

    @property
    def over(self) -> bool:
        return self.remaining_cents < 0

    @property
    def per_day_cents(self) -> int:
        """What is spendable each remaining day.

        Rounded down, so following it to the cent every day cannot push you
        past the limit on the last one.
        """
        if self.expired or self.remaining_cents <= 0:
            return 0
        return self.remaining_cents // self.days_left

    @property
    def left_today_cents(self) -> int:
        """Today's slice, less whatever today has already cost."""
        return self.per_day_cents - self.spent_today_cents

    @property
    def percent_used(self) -> int:
        if self.limit_cents <= 0:
            return 0
        return min(max(round(self.spent_cents * 100 / self.limit_cents), 0), 100)


def current(today: date | None = None) -> Limit | None:
    """The limit in force, or None when none has been set."""
    raw_amount = db.get_setting(LIMIT_CENTS)
    until = db.get_setting(LIMIT_UNTIL)
    if not raw_amount or not until:
        return None

    day = (today or date.today()).isoformat()
    start = db.get_setting(LIMIT_FROM) or day
    set_at = db.get_setting(LIMIT_SET_AT)
    return Limit(
        limit_cents=int(raw_amount),
        until=until,
        start=start,
        spent_cents=db.spending_between(start, until, created_after=set_at),
        spent_today_cents=db.spending_between(day, day, created_after=set_at),
        today=day,
    )


def save(limit_cents: int, until: str, start: str | None = None,
         today: date | None = None) -> None:
    db.set_setting(LIMIT_CENTS, str(int(limit_cents)))
    db.set_setting(LIMIT_UNTIL, until)
    db.set_setting(LIMIT_FROM, start or (today or date.today()).isoformat())
    db.set_setting(LIMIT_SET_AT, db.now_iso())


def clear() -> None:
    db.delete_settings(LIMIT_CENTS, LIMIT_UNTIL, LIMIT_FROM, LIMIT_SET_AT)
