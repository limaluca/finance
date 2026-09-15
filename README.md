# Personal Finance Manager

A local-first credit card spending tracker. You screenshot your statement on your
phone, drop the image into the web page, and the app reads the merchants, amounts
and dates out of it, categorises them, and lists them.

Deliberately styled like software from 2001.

## Running it

```bash
./run.sh
```

Then open <http://127.0.0.1:8000>. That's it — `run.sh` creates the virtualenv and
installs dependencies on first run.

To use a different port: `PORT=9000 ./run.sh`

## How to import a screenshot

You do **not** put image files in a folder. Everything goes through the browser:

1. Screenshot the bank's purchase notifications on your phone.
2. Get the image onto this Mac (AirDrop, iCloud Photos, Messages to yourself — any way).
3. Open <http://127.0.0.1:8000/upload>, pick the file, and check the
   **"Screenshot taken on"** date (see the warning below).
4. The app OCRs the image and shows you a **review** table: every purchase it found,
   with the date, time, merchant, amount and guessed category, all editable.
5. Fix anything wrong, uncheck rows you don't want, and save. Only then does anything
   reach the database.

The uploaded image is copied into `data/uploads/` so you can re-review it later from
the Import History page.

### Why the "taken on" date matters

Phone notifications do not carry a full date. A card just says `Sun, 19:26`, so the
weekday has to be resolved backwards from the day the screenshot was taken. Import a
week-old screenshot with today's date and every transaction lands on the wrong day.

The app uses, in order: the date you type in the form, the image's EXIF capture date,
then today. Screenshots that arrive via chat apps are normally EXIF-stripped, so the
form field is what you should rely on.

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

### Parser 2: statement lists (`app/parsing.py`)

Fallback for in-app statement screenshots, where rows look like
`Uber Trip     R$ 24,90` under a `15 SET` date header. It handles Portuguese and
English month names, `Hoje`/`Ontem`, installment markers (`Netflix 2/12` keeps the
marker instead of reading it as a date), refunds, and filters out phone status bars,
balance headers and "Total da fatura" summary rows.

### Both parsers

Re-importing an overlapping screenshot flags the repeats as duplicates and leaves them
unchecked on the review screen, so you can screenshot freely without worrying about
double-counting.

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
app/
  main.py          FastAPI routes
  config.py        settings from environment variables
  db.py            SQLite schema and queries
  parsing.py       OCR text -> transactions
  categorize.py    merchant -> category, with learned rules
  ocr/             pluggable OCR engines
  templates/       Jinja2 pages
  static/style.css the 2001 look
tools/             sample screenshot generator, CLI reader
data/              SQLite database + uploaded images (gitignored)
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
