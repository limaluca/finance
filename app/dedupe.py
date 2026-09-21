"""Duplicate detection.

A fingerprint is **date + canonical vendor + amount**. Different dates are
never duplicates, even when the vendor and amount match — a 99 ride that
always costs R$ 8,10 is a new purchase every time it happens.

The same fingerprint can also appear several times on one day for real
(several 8,10 motorcycle trips). Those stay. What we block is the other
common case: you screenshot the Wallet list, scroll, screenshot again, and
the same purchase is in both pictures.

So occupancy is counted per source image. We keep the highest number of
times a fingerprint appears in any single screenshot (and in the database).
Extra copies on a later overlapping shot are **exact** duplicates.

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
# Dates the parser invented because the day header scrolled off the screenshot.
# Those rows are matched on vendor + amount only, so they still collapse onto
# the same purchase when it appears with a real date on another shot.
WEAK_DATES = frozenset({"guess", "fallback"})


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
                   else "already in another screenshot")
        if self.kind == EXACT:
            return f"Same purchase {already}"
        return f"Looks like \u201c{self.merchant}\u201d {already}"


def _fingerprint(occurred_on: str, merchant: str, amount_cents: int):
    from .merchants import canonical
    stored = canonical(merchant)
    return (occurred_on, merchant_key(stored), int(amount_cents)), stored


class Index:
    """How many times each (date, vendor, amount) is already accounted for."""

    def __init__(self) -> None:
        # fingerprint -> (count, display name, where)
        self._exact: dict[tuple[str, str, int], tuple[int, str, str]] = {}
        # (merchant_key, amount) -> count, used when a row's date was guessed
        self._by_purchase: dict[tuple[str, int], tuple[int, str, str]] = {}
        # (date, amount) -> merchant keys already seen, for the likely check
        self._related: dict[tuple[str, int], list[tuple[str, str, str]]] = {}

    def occupancy(self, occurred_on: str, merchant: str, amount_cents: int) -> int:
        fp, _ = _fingerprint(occurred_on, merchant, amount_cents)
        return self._exact.get(fp, (0, "", "system"))[0]

    def add(self, occurred_on: str, merchant: str, amount_cents: int,
            where: str = "system", n: int = 1) -> None:
        fp, stored = _fingerprint(occurred_on, merchant, amount_cents)
        count, name, existing_where = self._exact.get(fp, (0, stored, where))
        self._exact[fp] = (count + n, name or stored, existing_where or where)
        purchase = (fp[1], int(amount_cents))
        pcount, pname, pwhere = self._by_purchase.get(purchase, (0, stored, where))
        self._by_purchase[purchase] = (pcount + n, pname or stored, pwhere or where)
        self._remember_related(occurred_on, int(amount_cents), fp[1],
                               name or stored, existing_where or where)

    def purchase_occupancy(self, merchant: str, amount_cents: int) -> int:
        fp, _ = _fingerprint("", merchant, amount_cents)
        return self._by_purchase.get((fp[1], int(amount_cents)), (0, "", "system"))[0]

    def set_at_least(self, occurred_on: str, merchant: str, amount_cents: int,
                     n: int, where: str = "batch") -> None:
        """Raise occupancy to `n` if this image saw the fingerprint more times."""
        current = self.occupancy(occurred_on, merchant, amount_cents)
        if n > current:
            self.add(occurred_on, merchant, amount_cents, where=where, n=n - current)

    def _remember_related(self, occurred_on: str, amount_cents: int,
                          key: str, name: str, where: str) -> None:
        bucket = self._related.setdefault((occurred_on, amount_cents), [])
        if any(existing == key for existing, _, _ in bucket):
            return
        bucket.append((key, name, where))

    def find(self, occurred_on: str, merchant: str, amount_cents: int) -> Match | None:
        """Presence lookup: any occupancy of this fingerprint, else a related name.

        Screenshot import uses `cover()` instead, which compares *counts*.
        `find` is the simple "is this already on the list at least once?" check.
        """
        fp, stored = _fingerprint(occurred_on, merchant, amount_cents)
        count, name, where = self._exact.get(fp, (0, stored, "system"))
        if count:
            return Match(EXACT, where, name)
        return self._related_match(occurred_on, merchant, amount_cents)

    def _related_match(self, occurred_on: str, merchant: str,
                       amount_cents: int) -> Match | None:
        fp, _ = _fingerprint(occurred_on, merchant, amount_cents)
        candidate = fp[1]
        for existing_key, existing_name, where in self._related.get(
                (occurred_on, int(amount_cents)), []):
            if existing_key == candidate:
                continue
            kind = _relatedness(candidate, existing_key)
            if kind is not None:
                return Match(LIKELY if kind == EXACT else kind, where, existing_name)
        return None

    def cover(self, rows: list[tuple],
              where: str = "batch") -> list[Match | None]:
        """Compare one source image against occupancy already recorded.

        Each row is `(occurred_on, merchant, amount_cents)` or the same plus a
        `date_source`. Occurrences up to the number already stored are exact
        duplicates; anything beyond that is a new purchase from this screenshot.

        Rows whose date was guessed (header scrolled off) also match against
        vendor + amount ignoring the date, so they still collide with the same
        purchase on a later shot that has a real day header.
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
        already_va = {
            (_fingerprint(occurred_on, merchant, amount_cents)[0][1], int(amount_cents)):
                self.purchase_occupancy(merchant, amount_cents)
            for occurred_on, merchant, amount_cents, _ in normalized
        }
        seen_fp: Counter = Counter()
        seen_va: Counter = Counter()
        matches: list[Match | None] = []
        for occurred_on, merchant, amount_cents, date_source in normalized:
            fp, stored = _fingerprint(occurred_on, merchant, amount_cents)
            va = (fp[1], int(amount_cents))
            seen_fp[fp] += 1
            seen_va[va] += 1
            weak = date_source in WEAK_DATES
            blocked = (seen_va[va] <= already_va.get(va, 0) if weak
                       else seen_fp[fp] <= already_fp.get(fp, 0))
            if blocked:
                if weak:
                    _count, name, existing_where = self._by_purchase.get(
                        va, (0, stored, "system"))
                else:
                    _count, name, existing_where = self._exact[fp]
                matches.append(Match(EXACT, existing_where, name or stored))
            else:
                matches.append(self._related_match(occurred_on, merchant,
                                                   amount_cents))

        for (occurred_on, merchant, amount_cents, _src), match in zip(normalized, matches):
            if match is not None and match.is_blocking:
                continue
            self.add(occurred_on, merchant, amount_cents, where=where)
        return matches

    @classmethod
    def from_rows(cls, rows) -> "Index":
        index = cls()
        for row in rows:
            index.add(row["occurred_on"], row["merchant"], row["amount_cents"])
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
