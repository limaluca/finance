# Personal Finance Manager

A local-first credit card spending tracker. You screenshot your statement on your
phone, drop the image into the web page, and the app reads the merchants, amounts
and dates out of it, categorises them, and lists them.

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
3. **Extraction** runs one of two parsers, picked automatically.
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

### Parser 3: generic statement lists (`app/parsing.py`)

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
  dedupe.py             duplicate detection
  categorize.py         merchant -> category, with learned rules
  csv_io.py             CSV export and import
  ocr/                  pluggable OCR engines
  templates/            Jinja2 pages
  static/style.css      the 2001 look
tools/                  sample screenshot generator, CLI reader
data/                   SQLite database, uploads, server log (gitignored)
```

## Starting over

The whole app state is one directory:

```bash
rm -rf data/    # deletes all transactions and uploaded images
```

## Later

Not built yet, in rough order of usefulness: monthly budgets and alerts, charts,
CSV/OFX import, recurring-charge detection, multi-card support, and deploying this
to a small server with Postgres and a login.
