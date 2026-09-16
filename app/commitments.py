"""Rollups for the two manually-kept sections: installments and subscriptions.

Both answer the same two questions — what leaves my account this month, and how
much is still owed after that — so the maths lives here instead of in the
templates.

One rule is worth spelling out: a plan whose first installment has not been
billed yet (`paid_installments` is 0) is *not* part of this month's bill. That
matches how the spreadsheet totals were built.
"""

from dataclasses import dataclass, field


@dataclass
class Plan:
    """One installment plan with everything the screens need precomputed."""
    id: int
    description: str
    bank: str
    monthly_cents: int
    paid: int
    remaining: int
    currency: str = "BRL"

    @property
    def total(self) -> int:
        return self.paid + self.remaining

    @property
    def remaining_cents(self) -> int:
        return self.monthly_cents * self.remaining

    @property
    def total_cents(self) -> int:
        return self.monthly_cents * self.total

    @property
    def started(self) -> bool:
        """Whether this plan is on the current bill."""
        return self.paid > 0

    @property
    def percent_paid(self) -> int:
        if self.total <= 0:
            return 0
        return round(self.paid * 100 / self.total)

    @property
    def finishes_after(self) -> int:
        """Months until the last installment, counting the current one."""
        return self.remaining

    @classmethod
    def from_row(cls, row) -> "Plan":
        return cls(
            id=row["id"],
            description=row["description"],
            bank=row["bank"],
            monthly_cents=row["monthly_cents"],
            paid=row["paid_installments"],
            remaining=row["remaining_installments"],
            currency=row["currency"] if "currency" in row.keys() else "BRL",
        )


@dataclass
class BankRollup:
    bank: str
    plans: list[Plan] = field(default_factory=list)
    subscription_cents: int = 0
    subscription_count: int = 0

    @property
    def monthly_cents(self) -> int:
        """Installments on this month's bill. Plans not yet started are excluded."""
        return sum(p.monthly_cents for p in self.plans if p.started)

    @property
    def pending_cents(self) -> int:
        return sum(p.remaining_cents for p in self.plans)

    @property
    def upcoming_cents(self) -> int:
        """Plans that will start appearing on a later bill."""
        return sum(p.monthly_cents for p in self.plans if not p.started)

    @property
    def plan_count(self) -> int:
        return len(self.plans)

    @property
    def paid_installments(self) -> int:
        return sum(p.paid for p in self.plans)

    @property
    def remaining_installments(self) -> int:
        return sum(p.remaining for p in self.plans)

    @property
    def percent_paid(self) -> int:
        total = self.paid_installments + self.remaining_installments
        if total <= 0:
            return 0
        return round(self.paid_installments * 100 / total)

    @property
    def total_monthly_cents(self) -> int:
        """Installments plus subscriptions — the whole recurring load on this bank."""
        return self.monthly_cents + self.subscription_cents


def plans(rows) -> list[Plan]:
    return [Plan.from_row(r) for r in rows]


def by_bank(installment_rows, subscription_rows=()) -> list[BankRollup]:
    """Groups both sections by bank, biggest monthly commitment first."""
    rollups: dict[str, BankRollup] = {}
    for plan in plans(installment_rows):
        rollups.setdefault(plan.bank, BankRollup(bank=plan.bank)).plans.append(plan)
    for row in subscription_rows:
        rollup = rollups.setdefault(row["bank"], BankRollup(bank=row["bank"]))
        rollup.subscription_cents += row["monthly_cents"]
        rollup.subscription_count += 1
    return sorted(rollups.values(),
                  key=lambda r: (-r.total_monthly_cents, r.bank.lower()))


def installment_totals(rows) -> dict:
    items = plans(rows)
    return {
        "count": len(items),
        "monthly_cents": sum(p.monthly_cents for p in items if p.started),
        "pending_cents": sum(p.remaining_cents for p in items),
        "upcoming_cents": sum(p.monthly_cents for p in items if not p.started),
        "not_started": [p for p in items if not p.started],
        "finishing_now": [p for p in items if p.started and p.remaining == 0],
    }


def subscription_totals(rows) -> dict:
    return {
        "count": len(rows),
        "monthly_cents": sum(r["monthly_cents"] for r in rows),
    }
