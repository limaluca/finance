"""Duplicate detection.

A fingerprint is **date + canonical vendor + amount**. Different dates are
never duplicates, even when vendor and amount match. A fingerprint may occur
only once: a repeated same-day entry is blocked, whether it is in the same
screenshot, another screenshot, or already in the database.

- **exact**   this occurrence is already covered by another screenshot or by
              what is already saved. Locked; never written.
- **likely**  same date and amount, merchant names that look related but are
              not the same vendor. Flagged and unchecked; you can override it.
"""

import re
import unicodedata
from collections import Counter, defaultdict
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
    transaction_id: int | None = None

    @property
    def is_blocking(self) -> bool:
        return self.kind == EXACT

    def describe(self) -> str:
        already = ("already in the system" if self.where == "system"
                   else "already in this upload batch")
        if self.kind == EXACT:
            return f"Same purchase {already}"
        return f"Looks like \u201c{self.merchant}\u201d {already}"


def _fingerprint(occurred_on: str, merchant: str, amount_cents: int):
    from .merchants import canonical
    stored = canonical(merchant)
    return (occurred_on, merchant_key(stored), int(amount_cents)), stored


class Index:
    """Which (date, vendor, amount) fingerprints are already accounted for."""

    def __init__(self) -> None:
        # fingerprint -> (count, display name, where, saved transaction id)
        self._exact: dict[tuple[str, str, int], tuple[int, str, str, int | None]] = {}
        # (date, amount) -> merchant keys already seen, for the likely check
        self._related: dict[tuple[str, int], list[tuple[str, str, str, int | None]]] = {}

    def occupancy(self, occurred_on: str, merchant: str, amount_cents: int) -> int:
        fp, _ = _fingerprint(occurred_on, merchant, amount_cents)
        return self._exact.get(fp, (0, "", "system", None))[0]

    def add(self, occurred_on: str, merchant: str, amount_cents: int,
            where: str = "system", n: int = 1,
            transaction_id: int | None = None) -> None:
        fp, stored = _fingerprint(occurred_on, merchant, amount_cents)
        count, name, existing_where, existing_id = self._exact.get(
            fp, (0, stored, where, transaction_id))
        self._exact[fp] = (count + n, name or stored, existing_where or where,
                           existing_id or transaction_id)
        self._remember_related(occurred_on, int(amount_cents), fp[1],
                               name or stored, existing_where or where,
                               existing_id or transaction_id)

    def _remember_related(self, occurred_on: str, amount_cents: int,
                          key: str, name: str, where: str,
                          transaction_id: int | None) -> None:
        bucket = self._related.setdefault((occurred_on, amount_cents), [])
        if any(existing == key for existing, _, _, _ in bucket):
            return
        bucket.append((key, name, where, transaction_id))

    def find(self, occurred_on: str, merchant: str, amount_cents: int) -> Match | None:
        """Presence lookup: any occupancy of this fingerprint, else a related name.

        Screenshot import uses `cover()` so repeats in one batch are checked too.
        `find` is the simple "is this already on the list at least once?" check.
        """
        fp, stored = _fingerprint(occurred_on, merchant, amount_cents)
        count, name, where, transaction_id = self._exact.get(
            fp, (0, stored, "system", None))
        if count:
            return Match(EXACT, where, name, transaction_id)
        return self._related_match(occurred_on, merchant, amount_cents)

    def _related_match(self, occurred_on: str, merchant: str,
                       amount_cents: int) -> Match | None:
        fp, _ = _fingerprint(occurred_on, merchant, amount_cents)
        candidate = fp[1]
        for existing_key, existing_name, where, transaction_id in self._related.get(
                (occurred_on, int(amount_cents)), []):
            if existing_key == candidate:
                continue
            kind = _relatedness(candidate, existing_key)
            if kind is not None:
                return Match(LIKELY if kind == EXACT else kind, where,
                             existing_name, transaction_id)
        return None

    def cover(self, rows: list[tuple],
              where: str = "batch") -> list[Match | None]:
        """Compare one source image against occupancy already recorded.

        Each row is `(occurred_on, merchant, amount_cents)` or the same plus a
        `date_source`. Only one row with a fingerprint is allowed. Date source
        is retained for call compatibility but never weakens the date match.
        """
        normalized: list[tuple[str, str, int, str]] = []
        for row in rows:
            if len(row) == 4:
                occurred_on, merchant, amount_cents, date_source = row
            else:
                occurred_on, merchant, amount_cents = row
                date_source = ""
            normalized.append((occurred_on, merchant, amount_cents, date_source or ""))

        already_fp = {
            _fingerprint(occurred_on, merchant, amount_cents)[0]:
                self.occupancy(occurred_on, merchant, amount_cents)
            for occurred_on, merchant, amount_cents, _ in normalized
        }
        seen_fp: Counter = Counter()
        matches: list[Match | None] = []
        for occurred_on, merchant, amount_cents, _date_source in normalized:
            fp, stored = _fingerprint(occurred_on, merchant, amount_cents)
            if _date_source == "fallback":
                # A screenshot-taken date is only a placeholder. It cannot
                # establish that two purchases happened on the same day.
                matches.append(None)
                continue
            seen_fp[fp] += 1
            blocked = already_fp.get(fp, 0) > 0 or seen_fp[fp] > 1
            if blocked:
                _count, name, existing_where, transaction_id = self._exact.get(
                    fp, (0, stored, where, None))
                matches.append(Match(EXACT, existing_where, name or stored,
                                     transaction_id))
            else:
                matches.append(self._related_match(occurred_on, merchant,
                                                   amount_cents))

        for (occurred_on, merchant, amount_cents, date_source), match in zip(normalized, matches):
            if date_source == "fallback":
                continue
            if match is not None and match.is_blocking:
                continue
            self.add(occurred_on, merchant, amount_cents, where=where)
        return matches

    @classmethod
    def from_rows(cls, rows) -> "Index":
        index = cls()
        for row in rows:
            keys = row.keys() if hasattr(row, "keys") else ()
            transaction_id = row["id"] if "id" in keys else None
            index.add(row["occurred_on"], row["merchant"], row["amount_cents"],
                      transaction_id=transaction_id)
        return index


def annotate(transactions, index: Index) -> None:
    """Flags each parsed transaction, grouping repeats by the screenshot they came from."""
    groups: dict[str, list] = defaultdict(list)
    order: list[str] = []
    for tx in transactions:
        key = tx.source_image or ""
        if key not in groups:
            order.append(key)
        groups[key].append(tx)

    for key in order:
        rows = groups[key]
        matches = index.cover(
            [(tx.occurred_on, tx.merchant, tx.amount_cents, tx.date_source)
             for tx in rows],
            where="batch")
        for tx, match in zip(rows, matches):
            tx.duplicate = match is not None
            tx.duplicate_kind = match.kind if match else ""
            tx.duplicate_note = match.describe() if match else ""
            tx.duplicate_transaction_id = match.transaction_id if match else None
