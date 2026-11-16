# Duplicate Checker: Project Facts and Test Reference

This report records the project facts gathered for the duplicate-checker test
document request. It is based on the current code and read-only inspection of
`data/finance.db`. Personal names, card digits, and locations in raw OCR have
been anonymized. No code was changed to prepare this report.

## 1. Pipeline overview

1. The import page, `app/templates/upload.html`, lets the user select one or more
   screenshots, choose an OCR engine, and set the screenshot's “taken on” date.
   That date defaults to the local system date.
2. The upload route in `app/main.py` saves each image under `data/uploads/` and
   calls `ocr.run_ocr(...)`.
3. `app/ocr/__init__.py` chooses the configured engine. In the inspected
   environment, configuration is `auto`, and **Apple Vision** is the only
   available engine. Tesseract is implemented as a fallback, but was not
   available here. OCR is local; this pipeline does not send the image to a
   remote OCR service.
4. The OCR engine returns text boxes with coordinates and confidence. For each
   saved import, the app stores the box data in `imports.boxes_json` and a
   line-grouped rendering in `imports.raw_text`.
5. `app/parsing.py` dispatches the boxes to the Wallet, notification,
   bank-statement, or generic parser. It canonicalizes merchant names and assigns
   categories. `reconcile_screenshot_dates()` then attempts to resolve dates
   across adjacent screenshots.
6. Before the review page is shown, `main.upload` loads the saved transactions
   into a duplicate index and calls `dedupe.annotate(...)`.
7. The `/confirm/{batch_id}` route renders `app/templates/confirm.html`, where
   exact matches are locked and possible matches are warnings. Nothing is saved
   merely by uploading.
8. On confirmation, `main.save_batch` validates selected rows and checks
   duplicates again against the database before inserting them. Accepted rows
   are written using `db.insert_transactions(...)` in `app/db.py`.

Relevant files:

- `app/main.py` — upload, confirmation, and save routes.
- `app/ocr/__init__.py`, `app/ocr/apple_vision.py`,
  `app/ocr/tesseract_engine.py` — engine selection and OCR adapters.
- `app/parsing.py`, `app/wallet_parser.py`,
  `app/notification_parser.py`, `app/statement_parser.py` — extraction.
- `app/dedupe.py` — duplicate rules.
- `app/db.py` — persistence and duplicate index loading.
- `app/templates/confirm.html` — review controls.

The raw examples below use OCR observations already stored in
`imports.boxes_json`; OCR was not rerun. Each line in the code block is one
stored OCR box string. Redactions are the only changes to those strings.

## 2. Raw OCR samples

The local database contains real screenshots from a bank card statement and
Apple Wallet. It contains no real notification screenshot, email, or receipt OCR
example. The notification example in `tools/check_parsers.py` is a hand-written
parser fixture, not real OCR output, so it is not presented as real OCR here.

### Sample 1 — Bank card statement, iFood purchase

Stored import 67, Apple Vision. This purchase is also present in Sample 2 from
Wallet. Person and location text is redacted.

```text
09:42 1
594,
Faturas
Despesas da fatura
Domingo, 20 de set
YP
Restaurantes
-R$ 24,98
IFD *[NAME]
Sábado, 19 de set
!!
Supermercado
-R$ 17,97
ARMAZZEM BE LIFE II C [LOCATION]
[LOCATION]
Restaurantes
-R$ 24,80
SMARVIC COMERCIO E SE [LOCATION]
[LOCATION]
[LOCATION]
Transporte
-R$ 20,00
POSTO NATUREZA PARQUE [LOCATION]
[LOCATION]
[LOCATION]
YP
Restaurantes
-R$ 24,90
KFC SH MA RIO ANIL [LOCATION]
[LOCATION]
[LOCATION]
Antecipar fatura
```

| Merchant | Amount | Date | Category | Date source | OCR confidence |
|---|---:|---|---|---|---:|
| iFood | R$ 24.98 | 2026-09-20 | Food & Dining | header | 1.00 |
| ARMAZZEM BE LIFE II C | R$ 17.97 | 2026-09-19 | Groceries | header | 0.65 |
| SMARVIC COMERCIO E | R$ 24.80 | 2026-09-19 | Food & Dining | header | 1.00 |
| POSTO NATUREZA PARQUE | R$ 20.00 | 2026-09-19 | Transport | header | 1.00 |
| KFC SH MA RIO ANIL | R$ 24.90 | 2026-09-19 | Food & Dining | header | 0.75 |

### Sample 2 — Apple Wallet, same iFood purchase

Stored import 68, Apple Vision. Card digits, person name, and locations are
redacted. The parser canonicalized the descriptor to `iFood`; this candidate was
marked exact against the saved statement transaction.

```text
•••• [CARD-1]
Latest Transactions
Sesc Turismo
[LOCATION]
2 hours ago
Uber
Apple Pay
4 hours ago
IFD* [NAME]
Yesterday
Armazzem Be Life li C
[LOCATION]
Saturday
Smarvic
[LOCATION]
Saturday
R$ 18,88
R$ 2,86
R$ 24,98
R$ 17,97
R$ 24,80
```

| Merchant | Amount | Date | Category | Date source | Duplicate result |
|---|---:|---|---|---|---|
| Sesc Turismo | R$ 18.88 | 2026-09-21 | Other | wallet | — |
| Uber | R$ 2.86 | 2026-09-21 | Transport | wallet | — |
| iFood | R$ 24.98 | 2026-09-20 | Food & Dining | wallet | exact: already in system |
| Armazzem Be Life li C | R$ 17.97 | 2026-09-19 | Groceries | wallet | likely: `ARMAZZEM BE LIFE II C` |
| Smarvic | R$ 24.80 | 2026-09-19 | Other | wallet | likely: `SMARVIC COMERCIO E` |

### Sample 3 — Bank statement with no visible purchase date

Stored import 52, Apple Vision. No transaction date header appears in the OCR
output. The parser stored screenshot-reference date `2026-09-21` with
`date_source=fallback`; that is a placeholder, not a date recognized in this
text. Locations are redacted.

```text
09:44 1
594,
Faturas
Transporte
-R$ 90,00
MIRANDA NETO E CIA LTD
[LOCATION]
[LOCATION]
Supermercado
-R$ 4,00
LANCHE CENTRAL
[LOCATION]
[LOCATION]
Supermercado
-R$ 26,00
LANCHE CENTRAL
[LOCATION]
[LOCATION]
Drogaria
-R$ 11,50
HIPER POPULAR
[LOCATION]
[LOCATION]
Transporte
-R$ 7,00
MIRANDA NETO E CIA LTD
[LOCATION]
[LOCATION]
Transporte
-R$ 90,00
MIRANDA NETO E CIA LTD
[LOCATION]
[LOCATION]
Antecipar fatura
```

| Merchant | Amount | Stored date | Category | Date source | Historical stored duplicate flag |
|---|---:|---|---|---|---|
| MIRANDA NETO E CIA LTD | R$ 90.00 | 2026-09-21 | Transport | fallback | exact: already in another screenshot |
| LANCHE CENTRAL | R$ 4.00 | 2026-09-21 | Groceries | fallback | — |
| LANCHE CENTRAL | R$ 26.00 | 2026-09-21 | Groceries | fallback | — |
| HIPER POPULAR | R$ 11.50 | 2026-09-21 | Health | fallback | — |
| MIRANDA NETO E CIA LTD | R$ 7.00 | 2026-09-21 | Transport | fallback | — |
| MIRANDA NETO E CIA LTD | R$ 90.00 | 2026-09-21 | Transport | fallback | — |

These are cached values in that import's `parsed_json`, not a new run of the
current parser. The historical exact flag conflicts with the current fallback
bypass in `dedupe.Index.cover`; old imports are not automatically reprocessed
when code changes.

### Sample 4 — Bank statement with a suspicious merchant extraction

Stored import 94, Apple Vision. The OCR observations contain `00` before the
category and `MP QUIOSQUEATLAN` after the amount. The parser extracted merchant
`00`. The true merchant cannot be confirmed from OCR text alone, so this is a
suspect extraction, not a verified correction.

```text
20:23
67
Faturas
00
Supermercado
-R$ 10,00
MP QUIOSQUEATLAN
[LOCATION]
[LOCATION]
YP
Restaurantes
-R$ 50,00
BUMERANGUE
[LOCATION]
[LOCATION]
Sexta, 30 de out
Supermercado
-R$ 3,75
PANIFICADORA ESTRELA [LOCATION]
[LOCATION]
[LOCATION]
YP
Restaurantes
-R$ 29,70
PONTO LAGOA
[LOCATION]
[LOCATION]
Bares
-R$ 52,47
LUDORAMA LTDA
[LOCATION]
[LOCATION]
[LOCATION]
Transporte
-R$ 12,24
Uber UBER TRIP HELP U [LOCATION]
[LOCATION]
Antecipar fatura
```

| Merchant extracted | Amount | Stored date | Category | Date source | Duplicate result |
|---|---:|---|---|---|---|
| `00` | R$ 10.00 | 2026-10-31 | Groceries | guess | — |
| BUMERANGUE | R$ 50.00 | 2026-10-31 | Food & Dining | adjacent | exact: already in upload batch |
| PANIFICADORA ESTRELA | R$ 3.75 | 2026-10-30 | Groceries | header | — |
| PONTO LAGOA | R$ 29.70 | 2026-10-30 | Food & Dining | header | — |
| LUDORAMA LTDA | R$ 52.47 | 2026-10-30 | Food & Dining | header | — |
| Uber | R$ 12.24 | 2026-10-30 | Transport | header | — |

### Sample 5 — Bank statement with a thousands separator and credit

Stored import 75, Apple Vision. The person and location text is redacted. The
OCR includes `+R$ 3.755,83`; the parser stored it as negative 375583 cents.

```text
16:14 1
704
Faturas
[NAME]
[NAME]
Outros
-R$ 20,43
SESC TURISMO
[LOCATION]
[LOCATION]
[LOCATION]
YP
Restaurantes
-R$ 32,90
BOB S GOLDEN SHOPPING [LOCATION]
[LOCATION]
Quarta, 30 de set
Saúde
-R$ 175,00
[NAME]
[LOCATION]
Parcela 1 de 2
Outros
+R$ 3.755,83
PAGAMENTO ON LINE
Segunda, 28 de set
Transporte
-R$ 3,90
99
[LOCATION]
[LOCATION]
Antecipar fatura
```

| Merchant | Amount extracted | Date | Category | Date source |
|---|---:|---|---|---|
| SESC TURISMO | R$ 20.43 | 2026-10-01 | Other | guess |
| BOB S GOLDEN SHOPPING | R$ 32.90 | 2026-10-01 | Food & Dining | guess |
| [NAME] | R$ 175.00 | 2026-09-30 | Health | header |
| PAGAMENTO ON LINE | **−R$ 3,755.83** (`−375583` cents) | 2026-09-30 | Payments & Refunds | header |
| 99 | R$ 3.90 | 2026-09-28 | Transport | header |

### Sample 6 — Bank statement showing a likely laundry match

Stored import 100, Apple Vision. The app-header name and locations are
redacted. The laundry row was marked likely against a saved same-date,
same-amount row with the shorter merchant name `LAVANDERIA 60 MINUTOS`.

```text
20:22
67
Faturas
[NAME]
[NAME]
Quarta, 28 de out
Outros
-R$ 6,00
SESC TURISMO
[LOCATION]
[LOCATION]
Terça, 27 de out
Drogaria
-R$ 116,88
DROGASIL 3392
[LOCATION]
[LOCATION]
Serviços
-R$ 15,00
LAVANDERIA 60 MINUTOS SAO JOSE
[LOCATION]
Supermercado
-R$ 30,00
CHURRASCO RAIZ
[LOCATION]
[LOCATION]
Supermercado
-R$ 81,07
MATEUS SUPERMERCADOS [LOCATION]
[LOCATION]
Antecipar fatura
```

| Merchant | Amount | Date | Category | Date source | Duplicate result |
|---|---:|---|---|---|---|
| SESC TURISMO | R$ 6.00 | 2026-10-28 | Other | header | — |
| DROGASIL 3392 | R$ 116.88 | 2026-10-27 | Health | header | — |
| LAVANDERIA 60 MINUTOS SAO JOSE | R$ 15.00 | 2026-10-27 | Other | header | likely: `LAVANDERIA 60 MINUTOS` |
| CHURRASCO RAIZ | R$ 30.00 | 2026-10-27 | Groceries | header | — |
| MATEUS SUPERMERCADOS | R$ 81.07 | 2026-10-27 | Groceries | header | exact: already in system |

## 3. Database

The inspected database was `data/finance.db`, opened read-only. It contains 237
transaction rows and 63 import records. Transactions span `2026-08-22` through
`2026-11-02`; all saved transaction currencies are BRL. A scan using the current
duplicate fingerprint found zero groups with a repeated persisted fingerprint.

### `transactions` schema

Defined in `app/db.py`:

| Column | SQLite type | Nullability / constraint |
|---|---|---|
| `id` | INTEGER | Primary key, autoincrement |
| `occurred_on` | TEXT | NOT NULL; no SQL date-format CHECK |
| `occurred_time` | TEXT | Nullable |
| `merchant` | TEXT | NOT NULL |
| `amount_cents` | INTEGER | NOT NULL |
| `currency` | TEXT | NOT NULL |
| `category` | TEXT | NOT NULL |
| `notes` | TEXT | Nullable |
| `import_id` | INTEGER | Nullable FK to `imports.id`; delete sets it NULL |
| `raw_line` | TEXT | Nullable |
| `created_at` | TEXT | NOT NULL |

Indexes: `idx_tx_occurred_on` on `occurred_on`, `idx_tx_category` on
`category`, and the primary-key index. There is no unique index or database
constraint on date, merchant, and amount.

The current database has no NULL `occurred_on`, `merchant`, `amount_cents`,
`category`, `import_id`, or `raw_line` values. A missing date therefore does
not appear as NULL in this table; parsers may instead use a provisional date
such as the screenshot date.

### Example saved rows

`amount_cents` is shown alongside formatted value. These are actual rows from
the database.

| ID | Date | Merchant | Amount (`amount_cents`) | Category |
|---:|---|---|---:|---|
| 465 | 2026-08-24 | SUPERMERCADO MATEUS | R$ 125.33 (`12533`) | Groceries |
| 470 | 2026-08-25 | 99 | R$ 8.10 (`810`) | Transport |
| 478 | 2026-08-26 | 99 | R$ 8.10 (`810`) | Transport |
| 678 | 2026-08-27 | 99 | R$ 8.10 (`810`) | Transport |
| 484 | 2026-08-28 | 99 | R$ 8.10 (`810`) | Transport |
| 473 | 2026-08-24 | iFood | R$ 26.99 (`2699`) | Food & Dining |
| 528 | 2026-09-09 | LAVANDERIA 60 MINUTOS SAO JOSE | R$ 15.00 (`1500`) | Other |
| 529 | 2026-09-09 | iFood | R$ 7.95 (`795`) | Food & Dining |
| 573 | 2026-09-20 | iFood | R$ 24.98 (`2498`) | Food & Dining |
| 583 | 2026-09-23 | LAVANDERIA 60 MINUTOS | R$ 15.00 (`1500`) | Other |
| 640 | 2026-10-13 | LAVANDERIA 60 MINUTOS SAO JOSE | R$ 15.00 (`1500`) | Other |
| 644 | 2026-10-14 | GOLDBEER BOTECO | R$ 20.00 (`2000`) | Food & Dining |
| 655 | 2026-10-20 | LAVANDERIA 60 MINUTOS SAO JOSE | R$ 15.00 (`1500`) | Other |
| 658 | 2026-10-22 | LAVANDERIA 60 MINUTOS SAO JOSE | R$ 15.00 (`1500`) | Other |
| 669 | 2026-10-27 | LAVANDERIA 60 MINUTOS | R$ 15.00 (`1500`) | Other |
| 681 | 2026-11-02 | TIO HUGO PET SHOP | R$ 23.00 (`2300`) | Pets |
| 700 | 2026-10-29 | iFood | R$ 24.98 (`2498`) | Food & Dining |
| 701 | 2026-10-28 | SESC TURISMO | R$ 6.00 (`600`) | Other |

The 99 rides and laundry purchases demonstrate same merchant/amount on
different dates. The app treats them as separate purchases because date is part
of the fingerprint.

### Actual duplicate match examples

There are no two persisted transaction rows with the same current canonical
fingerprint. Thus there are no duplicate pairs made of two saved rows. Actual
saved-versus-imported matches exist:

| Saved transaction | Imported OCR candidate | Current matcher result |
|---|---|---|
| ID 573: iFood, 2026-09-20, 2498 cents | Import 68 Wallet candidate: iFood, 2026-09-20, 2498 cents | `exact`, system, transaction ID 573 |
| ID 658: LAVANDERIA 60 MINUTOS SAO JOSE, 2026-10-22, 1500 cents | Import 87 parsed candidate with same merchant/date/amount | `exact`, system, transaction ID 658 |

These import candidates are represented in `imports.parsed_json`; they are not
second saved transaction rows.

### Storage formats

- Dates are TEXT in ISO `YYYY-MM-DD` form. The schema does not enforce the
  format.
- Times are nullable TEXT in `HH:MM` form when extracted.
- Amounts are integer cents; no floating-point currency value is stored.
  Negative cents represent credits/refunds.
- Merchant text is stored as text. Screenshot parsing canonicalizes recognized
  merchants such as iFood/Uber/99; duplicate comparison canonicalizes and
  normalizes again.
- `created_at` is an ISO timestamp in UTC with an explicit `+00:00` offset.

## 4. Duplicate checker logic

The complete duplicate-checking module is reproduced below as it exists in
`app/dedupe.py`. `db.duplicate_index()` in `app/db.py` loads saved transaction
IDs, dates, merchant names, and cents into this index. Upload uses `annotate()`;
save checks again with `cover()` using the reviewed form values.

```python
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
```

### Plain-language rules

- Exact key: `(occurred_on, canonicalized-and-normalized merchant,
  amount_cents)`.
- Dates compare as supplied strings. There is no “same week” rule and no fuzzy
  date comparison.
- Amounts compare as exact integer cents.
- Merchant comparison first canonicalizes known brands (`IFD`/`iFood`, `Uber`,
  and leading `99` variants), then removes accents and punctuation, lowercases,
  collapses whitespace, and trims.
- Exact match: all three key components are equal. It returns
  `Match(kind="exact", where=..., merchant=..., transaction_id=...)`; exact is
  blocking.
- Possible match: date and cents are equal, but canonical merchant keys differ
  and satisfy at least one rule: one key is a prefix of the other; their first
  token is identical and at least three characters; or the token-set
  intersection is at least half of the union. It returns `kind="likely"`; that
  is a warning, not a block.
- `where` distinguishes a saved system match from a match in the current batch.
  `describe()` produces the UI text.
- `cover()` counts matches within incoming rows: after the first occurrence,
  another identical fingerprint is exact. A `fallback` date is skipped and is
  not added to the index. Other date sources, including `guess` and `adjacent`,
  are checked.

### Missing-field behavior, actually probed

I called the current in-memory `Index` methods directly; these probes did not
access or write the database.

| Input | Actual output |
|---|---|
| `Index.find("", "Cafe Example", 1250)` | `None` |
| `Index.find(None, "Cafe Example", 1250)` | `None` |
| `Index.find("2026-01-01", "", 1250)` | `None` when no matching blank-merchant key exists |
| `Index.find("2026-01-01", None, 1250)` | `None` when no matching blank-merchant key exists |
| `Index.find("2026-01-01", "Cafe Example", None)` | `TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'` |
| Two identical rows with blank date passed to `cover()` | `[None, ("exact", "batch", "Cafe Example")]` |
| Two identical rows with blank merchant passed to `cover()` | `[None, ("exact", "batch", "")]` |
| One `fallback` row passed to `cover()` | `[None]`; index remains empty |

The low-level checker does not validate missing dates or merchants: repeated
blank values can form an exact fingerprint. Missing amount `None` raises
`TypeError`. The regular app flow guards these cases: screenshot parsers reject
rows without merchant text or amount, and the save route skips a row if merchant,
parsed amount, or parsed date is missing. The database marks required fields
NOT NULL.

## 5. Parsing and normalization

### Dates

`parsing.find_date` accepts:

- ISO `YYYY-MM-DD`.
- Numeric dates with `/`, `.` or `-`, optionally with a two- or four-digit year.
- Day followed by English or Portuguese month names/abbreviations, such as
  `13 de set`.
- Month name followed by day.
- Relative terms `today`/`hoje`, `yesterday`/`ontem`, and `anteontem`.

Numeric order defaults to DMY (`FINANCE_DATE_ORDER` can be `MDY`). If the chosen
month is greater than 12 and the other component is a valid month, the parser
swaps the components. Two-digit years are interpreted as 2000–2099. If the year
is absent, the parser chooses the most recent occurrence no more than 45 days in
the future.

`parse_date_input` accepts ISO HTML date values or a value recognized by
`find_date`; empty or invalid text returns `None`. The generic parser uses
`today` and labels an unidentified date `fallback`. The statement parser assigns
rows above its first visible date header to the following day with
`date_source=guess`; if there is no header, it uses the reference date with
`fallback`.

There is no application-specific timezone setting for purchase dates. They are
calendar dates. Timestamps such as database `created_at` are UTC.

### Amounts

`parse_amount_to_cents` removes non-digit/non-separator characters, then
interprets the last of `.` and `,` as the decimal separator when both are
present. With only one separator, it is decimal only when it occurs once and
has exactly two trailing digits; otherwise separators are treated as grouping
characters. It returns integer cents using `Decimal`.

Examples supported by the code:

- `1.234,56` → 123456 cents.
- `1,234.56` → 123456 cents.
- `12,50` → 1250 cents.
- `1234` → 123400 cents.
- Currency symbols/codes include `R$`, `RS$`, `BRL`, `$`, `US$`, `USD`, `€`,
  `EUR`, `£`, and `GBP`.
- `find_amount` recognizes leading or embedded minus, plus, and trailing minus
  signs. It rejects zero as an extracted transaction amount.
- Bank statement rows invert a leading minus into positive spending; a leading
  plus becomes negative cents, as shown by `+R$ 3.755,83` above.

### Merchant names

`merchants.canonical` maps recognized IFD/iFood descriptors to `iFood`, names
containing `uber` to `Uber`, and names beginning with recognized `99` forms to
`99`. Otherwise, it returns the trimmed original text.

For duplicate comparison, `dedupe.merchant_key` additionally removes accents
and punctuation, converts to lowercase ASCII, collapses whitespace, and trims.
The original `raw_line` is stored separately for screenshot-imported
transactions.

## 6. User flow on duplicates

On the import confirmation page (`app/templates/confirm.html`):

- Exact rows have a disabled checkbox and `duplicate` badge. There is no “add
  anyway” override for an exact duplicate through screenshot confirmation.
- Likely rows show a `maybe dup` warning and are unchecked by default. The user
  can check one to save it or leave it unchecked to discard it.
- The user can edit date, time, merchant, category, and amount before saving.
- The page has “Cancel, save nothing”; if the user submits with no accepted
  rows, the save route marks the batch `discarded`.
- The save route repeats the exact check and skips exact rows, then reports the
  saved, blocked, and incomplete counts.
- Manual “new transaction” and edit routes do not run this duplicate check; see
  Known problems.

## 7. Existing tests

There is no `tests/` directory and no pytest/unittest framework or single-test
selector in the repository. The existing checks are a hand-written script,
`tools/check_parsers.py`. Its screenshot-shaped samples are manually constructed
text turned into synthetic `TextBox` objects; they are not OCR runs against real
screenshots.

Duplicate, parsing, OCR-dispatch, merchant, and category checks in that script
cover:

- Three parser dispatch fixtures: wallet, notification, and statement.
- Six duplicate cases: notification/statement/typed merchant canonicalization
  to the same iFood purchase; a different date; and a different amount.
- Same-day repeated rows within one screenshot and repeats in a later overlapping
  screenshot.
- A fallback date versus a row with a firm date.
- Seven date reconciliation cases: match in adjacent screenshot, preserve a
  visible-header guess, reversed selection order, no matching purchase,
  conflicting visible dates, six undated rows, and seven undated rows.
- Two statement-header cases: rows above the first header get the next day and
  six entries below the header share its date.
- Fifteen merchant canonicalization examples.
- Six categorization examples.

The script also contains installment, spending-limit, and statement-cycle
checks. Total checks in the run: **54 passed, 0 failed**.

Command run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tools/check_parsers.py
```

The documented project command is `bin/finance check`. There is no supported
command to run one test in isolation; the script executes the cases together.

## 8. Configuration

Observed current settings in this environment:

| Setting | Value / behavior |
|---|---|
| Default currency | `BRL` (`FINANCE_CURRENCY`) |
| Numeric date order | `DMY` (`FINANCE_DATE_ORDER`) |
| OCR engine preference | `auto`; Apple Vision was the only available engine in this environment |
| OCR languages | `pt-BR,en-US` |
| Locale | No application-wide OS/Python locale setting found. Amount formatting is explicitly pt-BR style for BRL and en-US style for other currencies. |
| Timezone | No app timezone setting found. Import and transaction `created_at` timestamps are UTC; purchase dates are date-only and use Python's local `date.today()` where a reference date is needed. The provided runtime environment timezone is `America/Fortaleza`. |

## 9. Known problems

1. **Guessed dates can still cause exact duplicates.** `statement_parser` assigns
   `date_source="guess"` to rows above a visible header. `Index.cover` skips only
   `"fallback"`; it checks and inserts `"guess"` and `"adjacent"` rows. Stored
   import 87 has an exact same-day laundry match with `date_source=guess`. If
   that guessed date is wrong, the review page may lock the row before the user
   can include it.
2. **Adjacent inferred dates have inconsistent review state.** The route counts
   `adjacent` as undated and excludes it from `ready_count`, but the template's
   `needs_date` check includes only `guess` and `fallback`. Therefore an
   `adjacent` row can be counted as not ready yet initially checked as ready.
3. **Manual creation and editing bypass duplicate detection.**
   `/transactions/new` inserts directly after required-field validation;
   `/transactions/{tx_id}/edit` updates directly. Neither checks the duplicate
   index. Thus the UI's duplicate rule is not a database-wide invariant.
4. **The database does not enforce duplicate uniqueness.** There is no unique
   fingerprint index or constraint. Writes outside the guarded screenshot
   import flow can create duplicate rows; concurrent imports could also race
   between check and insert.
5. **Historical import decisions are cached.** Confirmation loads rows from
   `imports.parsed_json` and does not reparse them. Import 52 still contains an
   exact duplicate annotation on a `fallback` date even though the current
   low-level checker skips fallback dates. Old stored results therefore do not
   necessarily reflect current code.
6. **Bank statement merchant extraction can select a wrong segment.** The parser
   takes the first OCR box on the merchant line. In real import 94, the parser
   extracted `00` while OCR observations also show `MP QUIOSQUEATLAN` after the
   amount. This is an observed suspicious extraction; the actual vendor cannot
   be verified from OCR text alone.
7. **Possible-match rules can be broad.** Any shared first token of at least
   three characters is enough to produce `likely`, and 50% token-set overlap
   also qualifies. Generic shared first words could warn for distinct merchants.
8. **Low-level duplicate functions do not validate missing fields.** Direct
   probes showed repeated blank date or blank merchant values can become an exact
   batch fingerprint; `amount_cents=None` raises `TypeError`. Normal upload
   parsing and save validation guard these cases, but `Index` itself does not.
9. **No TODO/FIXME/XXX comments were found** in the duplicate, date, amount,
   merchant, and parser files searched.

## Things I could not find or verify

- I found no real OCR import from a delivery app, receipt, email, or bank
  push-notification screenshot. Notification examples in the project are
  synthetic fixtures.
- I cannot provide two duplicate pairs both persisted in `transactions`: a
  current-fingerprint scan found none. The duplicate examples above are saved
  transactions paired with actual imported OCR candidates that were flagged.
- I cannot determine whether the suspicious `00` extraction in import 94 was
  truly the wrong merchant from OCR text alone.
- The regression script does not separately test browser interaction, actual
  screenshot OCR accuracy, database concurrency, or duplicate enforcement on
  manual add/edit.
