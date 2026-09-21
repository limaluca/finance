"""Rollups for the hand-kept sections: installments, subscriptions, fixed bills.

Everything here answers two questions about a particular month — what leaves my
account, and what is still owed after that — so the maths lives here instead of
in the templates.

Installments are stored as "N installments starting in month M" rather than as a
"paid so far" counter, so which installment is due is a function of the month you
are looking at. That is what makes the screens roll over on their own: in
September a 12x plan from April shows 6/12, in October it shows 7/12, and once
the twelfth passes the plan stops counting towards the monthly total.
"""

from dataclasses import dataclass, field
from datetime import date

from .db import months_between, shift_month


def this_month(today: date | None = None) -> str:
    return (today or date.today()).strftime("%Y-%m")


@dataclass
class Plan:
    """One installment plan, seen from a particular month."""
    id: int
    description: str
    bank: str
    monthly_cents: int
    total: int
    first_month: str
    month: str                  # the month being looked at
    currency: str = "BRL"

    @property
    def number(self) -> int:
        """Which installment falls due in `month`. 1-based; may be out of range."""
        return months_between(self.first_month, self.month) + 1

    @property
    def last_month(self) -> str:
        return shift_month(self.first_month, self.total - 1)

    @property
    def due_now(self) -> bool:
        """On this month's bill."""
        return 1 <= self.number <= self.total

    @property
    def finished(self) -> bool:
        """Last installment already went through before this month."""
        return self.number > self.total

    @property
    def upcoming(self) -> bool:
        """First installment has not been billed yet."""
        return self.number < 1

    @property
    def paid(self) -> int:
        """Installments billed up to and including this month."""
        return min(max(self.number, 0), self.total)

    @property
    def remaining(self) -> int:
        """Installments still to be billed after this month."""
        return self.total - self.paid

    @property
    def is_last(self) -> bool:
        return self.due_now and self.remaining == 0

    @property
    def billed_in_month(self) -> int:
        """The number to put on the edit form for this month: 0 if not started yet."""
        if self.upcoming:
            return 0
        return min(max(self.number, 0), self.total)

    @property
    def starts_in(self) -> int:
        """Months until the first installment. 0 once it has started."""
        return max(1 - self.number, 0)

    @property
    def remaining_cents(self) -> int:
        return self.monthly_cents * self.remaining

    @property
    def total_cents(self) -> int:
        return self.monthly_cents * self.total

    @property
    def percent_paid(self) -> int:
        if self.total <= 0:
            return 0
        return round(self.paid * 100 / self.total)

    @property
    def status(self) -> str:
        if self.finished:
            return "finished"
        if self.upcoming:
            return "upcoming"
        if self.is_last:
            return "last"
        return "active"

    @classmethod
    def from_row(cls, row, month: str) -> "Plan":
        return cls(
            id=row["id"],
            description=row["description"],
            bank=row["bank"],
            monthly_cents=row["monthly_cents"],
            total=row["total_installments"] or 1,
            first_month=row["first_month"],
            month=month,
            currency=row["currency"] if "currency" in row.keys() else "BRL",
        )


def plans(rows, month: str) -> list[Plan]:
    return [Plan.from_row(r, month) for r in rows]


@dataclass
class BankRollup:
    bank: str
    plans: list[Plan] = field(default_factory=list)
    subscription_cents: int = 0
    subscription_count: int = 0

    @property
    def due_plans(self) -> list[Plan]:
        return [p for p in self.plans if p.due_now]

    @property
    def monthly_cents(self) -> int:
        """Installments on this month's bill. Finished and future plans excluded."""
        return sum(p.monthly_cents for p in self.due_plans)

    @property
    def pending_cents(self) -> int:
        """Money still owed after this month, including plans yet to start."""
        return sum(p.remaining_cents for p in self.plans if not p.finished)

    @property
    def upcoming_cents(self) -> int:
        return sum(p.monthly_cents for p in self.plans if p.upcoming)

    @property
    def plan_count(self) -> int:
        """Plans that still matter: due now or coming."""
        return sum(1 for p in self.plans if not p.finished)

    @property
    def due_count(self) -> int:
        return len(self.due_plans)

    @property
    def paid_installments(self) -> int:
        return sum(p.paid for p in self.plans if not p.finished)

    @property
    def remaining_installments(self) -> int:
        return sum(p.remaining for p in self.plans if not p.finished)

    @property
    def percent_paid(self) -> int:
        total = self.paid_installments + self.remaining_installments
        if total <= 0:
            return 100
        return round(self.paid_installments * 100 / total)

    @property
    def total_monthly_cents(self) -> int:
        """Installments plus subscriptions — the whole recurring load on this bank."""
        return self.monthly_cents + self.subscription_cents


def by_bank(installment_rows, subscription_rows=(), month: str | None = None
            ) -> list[BankRollup]:
    """Groups both sections by bank, biggest monthly commitment first."""
    month = month or this_month()
    rollups: dict[str, BankRollup] = {}
    for plan in plans(installment_rows, month):
        rollups.setdefault(plan.bank, BankRollup(bank=plan.bank)).plans.append(plan)
    for row in subscription_rows:
        rollup = rollups.setdefault(row["bank"], BankRollup(bank=row["bank"]))
        rollup.subscription_cents += row["monthly_cents"]
        rollup.subscription_count += 1
    return sorted(rollups.values(),
                  key=lambda r: (-r.total_monthly_cents, r.bank.lower()))


def installment_totals(rows, month: str | None = None) -> dict:
    """Headline figures for the installments screen, for one month."""
    month = month or this_month()
    items = plans(rows, month)
    due = [p for p in items if p.due_now]
    upcoming = [p for p in items if p.upcoming]
    finished = [p for p in items if p.finished]
    live = due + upcoming

    return {
        # What actually gets billed this month.
        "monthly_cents": sum(p.monthly_cents for p in due),
        "due_count": len(due),
        # Installments still to come after this month, as a count and as money.
        "pending_installments": sum(p.remaining for p in live),
        "pending_cents": sum(p.remaining_cents for p in live),
        # Installments already billed, for the overall progress bar.
        "paid_installments": sum(p.paid for p in live),
        # Plans that still cost something, versus ones already done.
        "count": len(live),
        "finished_count": len(finished),
        "upcoming_cents": sum(p.monthly_cents for p in upcoming),
        "upcoming": upcoming,
        "finishing_now": [p for p in due if p.remaining == 0],
        "finished": finished,
        "next_month_cents": sum(p.monthly_cents for p in
                                plans(rows, shift_month(month, 1)) if p.due_now),
    }


def subscription_totals(rows) -> dict:
    return {
        "count": len(rows),
        "monthly_cents": sum(r["monthly_cents"] for r in rows),
    }


def fixed_totals(rows) -> dict:
    """Fixed bills split into what is settled and what is still outstanding."""
    paid = [r for r in rows if r["paid"]]
    pending = [r for r in rows if not r["paid"]]
    return {
        "count": len(rows),
        "monthly_cents": sum(r["monthly_cents"] for r in rows),
        "paid_count": len(paid),
        "paid_cents": sum(r["monthly_cents"] for r in paid),
        "pending_count": len(pending),
        "pending_cents": sum(r["monthly_cents"] for r in pending),
    }
