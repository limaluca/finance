# Expense rules and categorization regression plan

Run this check after every change to screenshot parsing, date inference,
duplicate handling, merchant canonicalization, categorization, or the save path:

```sh
.venv/bin/python tools/check_parsers.py
```

The command is read-only: it uses fixed examples and does not open or modify
`data/finance.db`. It exits nonzero and prints the failed case if a rule changes
unexpectedly. Keep each case below in `tools/check_parsers.py`; add a regression
case there whenever a real screenshot exposes a new failure.

## Required acceptance cases

### Screenshot parsing and dates

- Wallet, notification, and bank statement layouts dispatch to the right parser.
- A statement row above the first visible date header gets the next calendar day.
- A row under a visible date header gets that exact date.
- Six purchases under one visible header all keep that header's date.
- A row with no date can inherit a date only when the same canonical merchant
  and amount appears with one unambiguous visible date in an adjacent screenshot.
- Up to six otherwise-unmatched undated statement rows use one day after the first
  visible date in an adjacent screenshot; more than six stay unresolved.
- If that matching purchase is absent or appears with conflicting dates, leave
  the date unresolved and require review.
- A month or year boundary is handled by ordinary calendar arithmetic.
- A provisional screenshot-taken date is never treated as proof that an
  unresolved purchase is a duplicate.

### Duplicate handling

- Same canonical merchant, amount, and confirmed date is an exact duplicate,
  including a repeat within one screenshot or across screenshots.
- The same merchant and amount on different dates are separate purchases,
  including dates in the same week.
- An unresolved `fallback` date is not locked as an exact duplicate and is not
  added to the in-memory duplicate index.
- Once a person confirms a date on the review form, the save-time check uses
  that submitted date and blocks an exact match already in the database.
- Related but non-identical merchant names on the same date and amount produce
  a review warning, not an exact block.

### Amounts, merchants, and categories

- Money parsing keeps integer cents and handles Brazilian decimal commas.
- Merchant canonicalization maps common bank descriptors (IFD/iFood, Uber, 99)
  to their stable names without merging unrelated merchants.
- A source bank category outranks automatic merchant keywords.
- A learned merchant correction outranks both the source hint and keyword rule.
- Refunds/credits map to `Payments & Refunds`; unknown spending maps to `Other`.
- Include at least one check for every changed category keyword or precedence
  rule in the categorized examples.

## Manual screenshot review when changing date rules

The fixed check cannot prove OCR behavior on a new screenshot shape. For a date
inference change, also use a copy of the relevant screenshots on the Import page
and confirm all of the following before saving:

1. Upload the screenshots in the user's capture order (bottom to top).
2. Verify an undated purchase repeated with a visible date in the next image
   takes that visible date.
3. Verify undated rows above a visible header use the following calendar day.
4. Verify six rows under one visible header remain on that header's date.
5. Verify unresolved rows remain editable and are not labeled as duplicates.
6. Verify a same-merchant, same-amount purchase on another date stays available.
7. Confirm one exact same-day duplicate is blocked when the batch is saved.

Do not use the live finance database for manual regression imports. Use a
disposable database copy or cancel the review page after checking it.
