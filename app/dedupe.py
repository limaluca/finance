"""Duplicate detection.

Screenshots overlap constantly — you scroll, screenshot again, and the same
purchase appears twice. Worse, the same purchase can arrive under two different
names: a push notification says `Uber UBER * PENDING` while the settled
statement row says `Uber UBER TRIP HELP U`.

So matching is done on date + amount first, which is the reliable part, and the
merchant name is then compared loosely:

- **exact**   same date, same amount, same normalised merchant. Treated as a
              hard block: it is never written, even if the form says otherwise.
- **likely**  same date, same amount, merchant names that look related. Flagged
              and unchecked, but you can override it, because two genuinely
              separate purchases can coincide.
"""

import re
import unicodedata
from dataclasses import dataclass

EXACT = "exact"
LIKELY = "likely"


def merchant_key(merchant: str) -> str:
    """Comparable form of a merchant name: no accents, no punctuation, lowercase."""
    decomposed = unicodedata.normalize("NFKD", merchant or "")
    ascii_text = decomposed.encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text)).strip()


def _relatedness(left: str, right: str) -> str | None:
    """How alike two merchant keys are, given they share a date and amount."""
    if not left or not right:
        return None
    if left == right:
        return EXACT

    # One name being a truncation of the other: OCR cuts long names off.
    if left.startswith(right) or right.startswith(left):
        return LIKELY

    left_tokens, right_tokens = left.split(), right.split()
    # Same brand, different descriptor: "uber uber pending" vs "uber uber trip".
    if (left_tokens and right_tokens and left_tokens[0] == right_tokens[0]
            and len(left_tokens[0]) >= 3):
        return LIKELY

    shared = set(left_tokens) & set(right_tokens)
    union = set(left_tokens) | set(right_tokens)
    if union and len(shared) / len(union) >= 0.5:
        return LIKELY

    return None


@dataclass
class Match:
    kind: str            # EXACT or LIKELY
    where: str           # "system" or "batch"
    merchant: str        # the merchant already recorded

    @property
    def is_blocking(self) -> bool:
        return self.kind == EXACT

    def describe(self) -> str:
        already = ("already in the system" if self.where == "system"
                   else "repeated in this upload")
        if self.kind == EXACT:
            return f"Same purchase {already}"
        return f"Looks like \u201c{self.merchant}\u201d {already}"


class Index:
    """Lookup of what we already have, bucketed by (date, amount)."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, int], list[tuple[str, str, str]]] = {}

    def add(self, occurred_on: str, merchant: str, amount_cents: int,
            where: str = "system") -> None:
        key = (occurred_on, int(amount_cents))
        self._buckets.setdefault(key, []).append(
            (merchant_key(merchant), merchant, where))

    def find(self, occurred_on: str, merchant: str, amount_cents: int) -> Match | None:
        bucket = self._buckets.get((occurred_on, int(amount_cents)))
        if not bucket:
            return None
        candidate = merchant_key(merchant)
        best: Match | None = None
        for existing_key, existing_name, where in bucket:
            kind = _relatedness(candidate, existing_key)
            if kind == EXACT:
                return Match(EXACT, where, existing_name)
            if kind == LIKELY and best is None:
                best = Match(LIKELY, where, existing_name)
        return best

    @classmethod
    def from_rows(cls, rows) -> "Index":
        index = cls()
        for row in rows:
            index.add(row["occurred_on"], row["merchant"], row["amount_cents"])
        return index


def annotate(transactions, index: Index) -> None:
    """Flags each parsed transaction, also catching repeats within the batch itself."""
    for tx in transactions:
        match = index.find(tx.occurred_on, tx.merchant, tx.amount_cents)
        tx.duplicate = match is not None
        tx.duplicate_kind = match.kind if match else ""
        tx.duplicate_note = match.describe() if match else ""
        # Register it either way, so a third copy in the same batch is caught.
        index.add(tx.occurred_on, tx.merchant, tx.amount_cents, where="batch")
