# Personal Finance Manager

A local-first tracker for what your cards cost you each month. Three parts:

- **Spending** — screenshot your purchases on your phone, drop the images into the web
  page, and the app reads the merchants, amounts and dates out of them, categorises
  them, and lists them.
- **Installments** — the "parcelamentos" you are paying off, with a bar for each
  showing how much of the plan is behind you.
- **Subscriptions** — the fixed monthly charges, grouped by bank.

The **Summary** screen adds the three together, so you can see the whole month at once.

Deliberately styled like software from 2001.

## Running it

```bash
bin/finance
```

That starts the server in the background and opens the app. First run also creates
the virtualenv and installs dependencies.

To type just `finance` from anywhere, add this to `~/.zshrc`:

```bash
alias finance="$HOME/finance/bin/finance"
```

| Command | What it does |
| --- | --- |
| `finance` | Start the server if needed, then open the app |
| `finance start` / `stop` / `restart` | Control the server |
| `finance status` | Running or not, plus which OCR engines are available |
| `finance logs` | Follow the server log |
| `finance read IMG` | Read a screenshot in the terminal, saving nothing |
| `finance export FILE.csv` | Write every transaction to a CSV |
| `finance check` | Test the parsers and merchant-name rules |
| `finance reparse` | Re-read stored imports after changing a parser |
| `finance shell` | Python shell with the app importable |

The server is started in its own session, so it keeps running after you close the
terminal. Use `finance stop` to actually stop it.

`./run.sh` still exists if you want a foreground server with auto-reload for
development. Set `FINANCE_PORT` (or `PORT` for `run.sh`) to use a different port.

## How to import screenshots

You do **not** put image files in a folder. Everything goes through the browser:

1. Screenshot your purchases on your phone.
2. Get the images onto this Mac (AirDrop, iCloud Photos, Messages to yourself).
3. Open <http://127.0.0.1:8000/upload> and **drag them all in at once**, or click to
   choose several files.
4. Every image is read into one batch and shown on a **confirm** screen: each purchase
   with its date, time, merchant, amount and category, all editable.
5. Tick what you want and press **Confirm and save**. Nothing reaches the database
   until you do.

Uploaded images are copied into `data/uploads/` so you can re-open a batch later from
the Import History page.

### Why the "taken on" date matters

Push notifications do not carry a full date. A card just says `Sun, 19:26`, so the
weekday has to be resolved backwards from the day the screenshot was taken. Import a
week-old screenshot with today's date and every transaction lands on the wrong day.

The app uses, in order: the date you type in the form, the image's EXIF capture date,
then today. Screenshots that arrive via chat apps are normally EXIF-stripped, so the
form field is what you should rely on.

## The spending list

- **Sorting**: click any column heading. The first click sorts ascending, clicking the
  same heading again reverses it. The current column shows ▲ or ▼, and your filters
  survive the sort.
- **Day of the week** is shown instead of a clock time, because that is what you
  actually recognise a purchase by. Hover it for the full name.
- **Bulk recategorising**: press *Edit multiple categories*, tick rows, pick a category
  and press *Apply to selected*. It also teaches the categoriser, so the next import of
  those merchants lands in the right place by itself.
- The **category filter** only lists categories that appear in your transactions. The
  add and edit pickers still offer the full set.

### Merchant names are collapsed onto brands

Card descriptors are acquirer strings, not brand names, so one iFood habit shows up as
`IFD*53.700.820 ELIZABE`, `IFD Sal Parrilla` and `IFD ESPETIN DE RUA PRI`. Totals and
grouping are useless if those count as three merchants, so `app/merchants.py` rewrites
them:

| Anything matching | Stored as |
| --- | --- |
| `IFD`, `IFOOD`, `i food` | **iFood** |
| `uber` as a word | **Uber** |
| starts with `99`, `99*`, `99pop`… | **99** |

The rules match on a word basis, so `Cyber Cafe` is not Uber and `Loja 99 Centro` is not
99. The original text stays on the transaction and is shown on its edit page.

## Installments and subscriptions

Both are typed in by hand — there is no image reading here, because a plan changes once
a month at most.

**Installments** (`/installments`) hold what you pay each month, how many installments
are already billed, how many are left, and the bank. The plan length is the two counts
added up, so a 12x plan on its third month is `3 paid, 9 left`. Each row draws a bar of
little squares, filled for paid and hollow for remaining, and the same bar is drawn per
bank. *Mark one more installment as paid* on the edit page moves a plan along.

A plan with **0 paid** has not been billed yet, so it is left out of this month's total
and flagged `not started`. One on its **last** installment is flagged `last one`.

**Subscriptions** (`/subscriptions`) are simply a name, a monthly amount and a bank,
with yearly figures and a per-bank breakdown.

### A note on the spreadsheet this came from

The starting data was transcribed from spreadsheet screenshots by
`tools/seed_commitments.py`, which checks itself against the totals printed in those
images. Worth recording: the column headed **"Parcelas Restantes" actually holds the
plan length**, not the number of installments still to pay. Reading it as the plan
length reproduces every per-bank figure exactly — including BB and C6 showing R$ 0,00
still owed, and R$ 2.925,24 in total — while reading it as a pending count matches none
of them. The app therefore stores *paid* and *left* separately and derives the rest.

The only figure that does not tie out is the monthly subtotal: the app says
R$ 2.215,65 where the spreadsheet shows R$ 2.215,64, because Excel sums unrounded
values behind rounded displays. Every per-bank number agrees to the cent.

## Duplicate handling

Screenshots overlap all the time, and the same purchase can even arrive under two
different names — a notification says `Uber UBER * PENDING` while the settled
statement row says `Uber UBER TRIP HELP U`. So matching is done on **date + amount**
first, which is the reliable part, and the merchant name is compared loosely after:

| Verdict | Meaning | What happens |
| --- | --- | --- |
| **exact** | Same date, same amount, same merchant | Locked. Never saved, even if the form is tampered with. |
| **likely** | Same date and amount, related merchant name | Unticked and flagged. You can override it. |

Exact duplicates are re-checked against the database **at save time**, not just when
the page is drawn, so a stale tab cannot sneak one in. Repeats within a single upload
are caught too, not just repeats of what is already stored.

`likely` is a warning rather than a block because two separate purchases really can
land on the same day for the same amount at the same shop.

## CSV export and import

One format, both directions, so you can export, edit in a spreadsheet, and import back.

- **Export**: the *Export CSV* link on the spending page exports exactly what the
  current filter shows. Or `finance export file.csv` for everything.
- **Import**: *Import CSV* in the menu. Rows go through the same confirm screen with
  the same duplicate blocking.

```csv
date,time,merchant,category,amount,currency
2026-09-13,19:26,PONTO LAGOA,Food & Dining,34.55,BRL
2026-09-12,,ArmazemDoCampo,Groceries,17.00,BRL
```

`date`, `merchant` and `amount` are required; the rest may be blank. Amounts are
positive for spending, negative for refunds. Comma, semicolon and tab separated files
all work, column order does not matter, and Portuguese headers (`data`, `valor`,
`estabelecimento`, `categoria`, `hora`) are understood.

### Testing without a real statement

```bash
.venv/bin/python tools/make_sample_screenshot.py data/sample.png
```

That writes a fake statement screenshot you can upload. To check parsing straight
from the terminal, without saving anything:

```bash
.venv/bin/python tools/read_image.py data/sample.png --raw
```

## How the reading works

1. **OCR** turns the image into text boxes with positions (`app/ocr/`).
2. **Line grouping** rejoins boxes that sit on the same visual row, so a notification
   title and its right-aligned timestamp become one line (`app/parsing.py`).
3. **Extraction** runs one of four parsers, tried in order until one produces rows.
4. **Categorisation** matches the merchant against a few hundred built-in keywords
   (`app/categorize.py`). When you correct a category in the review screen, the app
   remembers that merchant and applies it automatically next time — see the
   Category Rules page.

Amounts are stored as integer cents, never floats. Both `1.234,56` and `1,234.56`
are understood.

### Parser 1: push notifications (`app/notification_parser.py`)

The main one. Reads cards like this off a lock screen or notification centre:

```
Compra no crédito                                        Sun, 19:26
Olá, Lucas. Você acaba de comprar R$ 43,89 em PONTO LAGOA. A compra
foi no crédito nacional, com o cartão final 9523.
```

- Only cards titled **"Compra no crédito"** are imported. Marketing pushes
  ("Quer tirar R$5,94 da fatura...") and other apps' notifications are ignored.
- The merchant is whatever follows `em `, kept verbatim including capitalisation:
  `PONTO LAGOA`, `IFD*53.700.820 ELIZABE`, `99*`.
- Merchants containing dots are handled — the sentence ends at `. A compra`, not at
  the first period.
- The time comes from the card's title row, and the weekday is resolved into a date.
- A card whose title is hidden behind the card above it is **skipped**, because
  without the title row there is no timestamp to read.

### Parser 2: the bank's statement list (`app/statement_parser.py`)

The "Faturas" / "Despesas da fatura" screen, where each purchase is three stacked
lines under a day header:

```
Domingo, 13 de set
    Restaurantes                       <- the bank's own category
    -R$ 43,89                          <- amount, drawn as money leaving
    PONTO LAGOA      SAO LUIS    MA    <- merchant, then city and state
```

- The **bank's own category** is used, mapped onto ours, which beats guessing from the
  merchant name. Vague labels like "Serviços" fall through to keyword matching instead.
- The city and state are stripped off the merchant. This is a heuristic: a trailing
  country code, state code, or city first-word (`SAO`, `RIO`, `BELO`...) is removed.
- The sign is **inverted**: the app draws expenses as `-R$`, but spending is stored
  positive so the dashboard totals read naturally.
- Rows above the first visible day header get the nearest visible date, flagged
  `check date` and left unticked, because their real header scrolled off the top.
  Screenshot with the day header visible and this never comes up.

### Parser 3: the iPhone Wallet list (`app/wallet_parser.py`)

The card's transaction list in Wallet. Each purchase is up to three lines — merchant
with amount, then where it happened or the payment rail, then when:

```
Latest Transactions
Sesc Turismo                                        R$ 13,51  >
São Luís, MA
4 hours ago
Armazzem Be Life li C                               R$ 17,97  >
São José de Ribamar, MA
Yesterday
Uber                                                 R$ 5,94  >
Apple Pay
Sunday
```

- Wallet never prints a calendar date for recent purchases, so `4 hours ago`,
  `Yesterday` and bare weekdays are resolved backwards from the "taken on" date. A bare
  weekday means the most recent one *before* today, since today's purchases say
  "N hours ago".
- Trailing `›` chevrons are stripped, and `Apple Pay` / `São Luís, MA` lines are
  recognised as location rather than mistaken for a merchant.
- The bottom row of a screenshot usually has its day label cut off. Because the list
  runs newest first, that row inherits the date of the row above it rather than
  defaulting to today. Two overlapping screenshots then agree, so the duplicate check
  catches the repeat instead of storing it twice on different days.

### Parser 4: generic statement lists (`app/parsing.py`)

Last-resort fallback for other apps, where rows look like `Uber Trip     R$ 24,90`
under a `15 SET` header. Handles Portuguese and English month names, `Hoje`/`Ontem`,
installment markers (`Netflix 2/12` keeps the marker instead of reading it as a date),
and filters out phone status bars and summary rows.

## OCR engines

| Engine | Platform | Notes |
| --- | --- | --- |
| `apple-vision` | macOS | Default here. Very accurate, nothing extra to install. |
| `tesseract` | anywhere | For the Linux server later. Needs the `tesseract` binary. |

`auto` picks Apple Vision when available, otherwise Tesseract. To install Tesseract:

```bash
brew install tesseract tesseract-lang          # macOS
apt-get install tesseract-ocr tesseract-ocr-por # Debian/Ubuntu
```

Check what's detected: <http://127.0.0.1:8000/health>

## Configuration

All optional, all environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `FINANCE_OCR_ENGINE` | `auto` | `auto`, `apple-vision` or `tesseract` |
| `FINANCE_OCR_LANGUAGES` | `pt-BR,en-US` | Languages to hint to the OCR engine |
| `FINANCE_DATE_ORDER` | `DMY` | How to read `03/04`. `DMY` or `MDY` |
| `FINANCE_CURRENCY` | `BRL` | Default currency when the image shows no symbol |
| `FINANCE_DATA_DIR` | `./data` | Where the database and uploads live |
| `PORT` | `8000` | Port for `run.sh` |

## Layout

```
bin/finance             the CLI: start, stop, open, read, export
app/
  main.py               FastAPI routes
  config.py             settings from environment variables
  db.py                 SQLite schema, queries, migrations
  parsing.py            shared parsing helpers + parser dispatch
  notification_parser.py  push notification cards
  statement_parser.py     the bank's "Faturas" list
  wallet_parser.py        the iPhone Wallet transaction list
  merchants.py          acquirer descriptors -> brand names
  dedupe.py             duplicate detection
  categorize.py         merchant -> category, with learned rules
  commitments.py        installment and subscription rollups
  csv_io.py             CSV export and import
  ocr/                  pluggable OCR engines
  templates/            Jinja2 pages
  static/style.css      the 2001 look
tools/
  check_parsers.py      parser routing + merchant name tests
  reparse_imports.py    re-read stored imports after a parser change
  seed_commitments.py   the starting installments and subscriptions
  make_sample_screenshot.py, read_image.py
data/                   SQLite database, uploads, server log (gitignored)
```

Imports keep the OCR boxes with their coordinates, not just the flattened text, so
`finance reparse` can re-read an old screenshot faithfully after a parser change —
the statement parser reads column positions, which plain text loses.

## Starting over

The whole app state is one directory:

```bash
rm -rf data/    # deletes all transactions and uploaded images
```

To put the installments and subscriptions back afterwards:

```bash
.venv/bin/python tools/seed_commitments.py --replace
```

## Later

Not built yet, in rough order of usefulness: rolling installments forward automatically
when a month turns over, monthly budgets and alerts, charts, recurring-charge detection
from the spending list, multi-card support, and deploying this to a small server with
Postgres and a login.
