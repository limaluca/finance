# Personal Finance Manager

A local-first tracker for what your cards cost you each month. Four parts:

- **Spending** — screenshot your purchases on your phone, drop the images into the web
  page, and the app reads the merchants, amounts and dates out of them, categorises
  them, and lists them. Wallet screenshots are the main source; lock-screen
  notifications and the bank's statement list still work when you drop those in.
- **Installments** — the "parcelamentos" you are paying off. Each plan is stored as
  "N installments starting in month M", so a 9/10 this month becomes 10/10 next month
  and then leaves the bill on its own.
- **Subscriptions** — the fixed monthly charges, grouped by bank.
- **Fixed expenses** — rent, electricity and anything else you tick off as paid each
  month. Ticks reset every month.

The **Summary** screen adds the four together, so you can see the whole month at once.

Deliberately styled like software from 2001.

## Set up on a new machine

Works on **macOS** and **Linux**. On Windows, use WSL. The app stores everything in
a local SQLite file; nothing is sent anywhere.

### 1. Install the system tools

| What | macOS | Debian / Ubuntu |
| --- | --- | --- |
| Git | `xcode-select --install` (or [git-scm](https://git-scm.com)) | `sudo apt install git` |
| Python 3.11+ | already there on recent macOS, or `brew install python` | `sudo apt install python3 python3-venv python3-pip` |
| OCR | nothing extra — Apple Vision is built in | `sudo apt install tesseract-ocr tesseract-ocr-por` |

On macOS you can also use Tesseract instead of Vision (`brew install tesseract tesseract-lang`).
On Linux, Tesseract is required; there is no Apple Vision.

### 2. Clone and start

```bash
git clone https://github.com/YOUR_GITHUB_USER/finance.git
cd finance
bin/finance
```

The first run creates `.venv`, installs the Python packages from `requirements.txt`,
starts the server on [http://127.0.0.1:8000](http://127.0.0.1:8000), and opens it.
`pyobjc` (Apple Vision) is only installed on macOS; Linux gets `pytesseract` instead.

### 3. Optional: type `finance` from anywhere

```bash
bin/finance install
```

That links the script into `~/.local/bin` and puts that directory on your `PATH` in
`~/.zshrc` and `~/.zprofile` (zsh) plus `~/.bashrc` and `~/.profile` (bash). It is a
symlink rather than a shell alias, so it also works in scripts. Moving this folder
only means running `install` again. Open a new terminal afterwards, or
`export PATH="$HOME/.local/bin:$PATH"` in the one you have.

If `finance` ever stops being found, `bin/finance doctor` says which part is missing.

### 4. Optional: load the sample installments, subscriptions and bills

The database starts empty. To put the transcribed spreadsheet back:

```bash
.venv/bin/python tools/seed_commitments.py --replace
```

Spending still comes from screenshots you drop on the Import page; the seed script
does not invent card purchases.

### What gets installed where

| Path | Role |
| --- | --- |
| `.venv/` | Python virtualenv (gitignored; created on first `bin/finance`) |
| `data/finance.db` | SQLite database |
| `data/uploads/` | copies of imported screenshots |
| `data/server.log`, `data/server.pid` | running server |
| `~/.local/bin/finance` | optional symlink from `finance install` |

None of `data/` is committed. Copy that folder if you want the same numbers on
another machine; otherwise start from a fresh clone and re-import.

### 5. Check it is working

```bash
finance status          # or bin/finance status
finance check           # parsers, merchant names, duplicate matching
open http://127.0.0.1:8000/health
```

`/health` lists the OCR engines the process can actually use. If Vision is missing
on a Mac, the usual cause is running inside a sandbox; start it from a normal
terminal with `bin/finance`.

| Command | What it does |
| --- | --- |
| `finance` | Start the server if needed, then open the app |
| `finance start` / `stop` / `restart` | Control the server |
| `finance status` | Running or not, plus which OCR engines are available |
| `finance install` | Put `finance` on your `PATH` |
| `finance doctor` | Check the install and report anything broken |
| `finance logs` | Follow the server log |
| `finance read IMG` | Read a screenshot in the terminal, saving nothing |
| `finance export FILE.csv` | Write every transaction to a CSV |
| `finance check` | Test the parsers, merchant-name rules and duplicate matching |
| `finance reparse` | Re-read stored imports after changing a parser |
| `finance shell` | Python shell with the app importable |

`stop` and `status` do not depend on the pidfile: if it goes missing they find the
server by the port it is listening on, so a lost pidfile cannot leave a server you
cannot stop.

The server is started in its own session, so it keeps running after you close the
terminal. Use `finance stop` to actually stop it.

`./run.sh` still exists if you want a foreground server with auto-reload for
development. Set `FINANCE_PORT` (or `PORT` for `run.sh`) to use a different port.

## How to import screenshots

You do **not** put image files in a folder. Everything goes through the browser:

1. Screenshot your purchases on your phone.
2. Get the images onto this computer (AirDrop, iCloud Photos, Messages, USB, …).
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

## Installments, subscriptions and fixed expenses

All three are typed in by hand — there is no image reading here, because they change
once a month at most.

### Installments roll over on their own

**Installments** (`/installments`) are stored as *"N installments starting in month M"*,
not as a "paid so far" counter. Which installment is due is then worked out from the
month you are looking at, which is what makes the screen keep itself up to date: a plan
showing `9/10` in September shows `10/10` in October and is gone from November's bill,
with nothing to tick over by hand.

You still type the numbers the way the spreadsheet had them — *total installments* and
*which one is billed this month* — and the first month is worked back from that.

The month stepper at the top walks through past and future months, so you can see next
month's bill before it arrives. A plan is flagged:

| Flag | Meaning |
| --- | --- |
| `starts YYYY-MM` | First installment not billed yet, so left out of this month's total |
| `last one` | This month's installment is the final one |
| `done` | Finished before this month; hidden unless you tick *show finished plans* |

The headline figures are all for the month on screen: what is billed now, how many
individual installments are still to come and what they are worth, next month's bill
with the difference, and how many plans have finished.

### Fixed expenses

**Fixed expenses** (`/fixed`) are the bills that repeat unchanged — rent, electricity.
Each one has a box you click to flip it between **pending** and **paid**.

The tick belongs to a *month*, not to the expense, so ticking September off leaves
October pending and September's record intact. Changing an amount changes it for every
month; the ticks are kept separately and are not touched.

### Subscriptions

**Subscriptions** (`/subscriptions`) are simply a name, a monthly amount and a bank,
with yearly figures and a per-bank breakdown.

### A note on the spreadsheet this came from

The starting data was transcribed from spreadsheet screenshots by
`tools/seed_commitments.py`, which checks itself against the totals printed in those
images. Worth recording: the column headed **"Parcelas Restantes" actually holds the
plan length**, not the number of installments still to pay. Reading it as the plan
length reproduces every per-bank figure exactly — including BB and C6 showing R$ 0,00
still owed, and R$ 2.925,24 in total — while reading it as a pending count matches none
of them.

Because those figures were only true for September 2026, the seed script treats that as
the anchor month and converts each *parcela atual* into the month installment 1 fell in.
`finance check`-style verification still runs against September, so the transcription
stays provable even though the app has since moved on.

The only figure that does not tie out is the monthly subtotal: the app says
R$ 2.215,65 where the spreadsheet shows R$ 2.215,64, because Excel sums unrounded
values behind rounded displays. Every per-bank number agrees to the cent.

## Duplicate handling

A fingerprint is **date + vendor + amount**. Same vendor and amount on a different
day is a new purchase — that is how several 99 rides at R$ 8,10 stay in the list.

Several copies of that fingerprint on the *same* day can also be real (two 8,10
trips before lunch). Those are kept when they appear together in one screenshot.
What we block is the overlap case: you screenshot the Wallet list, scroll, screenshot
again, and the same purchase is in both pictures. We keep however many times a
fingerprint appears in any single image, and extra copies on a later shot are
dropped.

The same purchase can also arrive under two different names — a notification says
`Uber UBER * PENDING` while the settled statement row says `Uber UBER TRIP HELP U`.
Merchant names are canonicalised first (`IFD*` → iFood, `uber` → Uber, leading `99`
→ 99), then compared loosely:

| Verdict | Meaning | What happens |
| --- | --- | --- |
| **exact** | Same date, same amount, same vendor, and this occurrence is already covered by another screenshot | Locked. Never saved. |
| **likely** | Same date and amount, related merchant name | Unticked and flagged. You can override it. |

Exact duplicates are re-checked against the database **at save time**, not just when
the page is drawn, so a stale tab cannot sneak one in. Typing a trip in by hand is
always allowed, even if another 8,10 99 ride is already on that day.

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
3. **Extraction** tries the Wallet parser first, then notifications, then the bank's
   statement list, then a generic fallback. The first one that produces rows wins.
4. **Categorisation** matches the merchant against a few hundred built-in keywords
   (`app/categorize.py`). When you correct a category in the review screen, the app
   remembers that merchant and applies it automatically next time — see the
   Category Rules page.

Amounts are stored as integer cents, never floats. Both `1.234,56` and `1,234.56`
are understood.

### Parser 1: the iPhone Wallet list (`app/wallet_parser.py`)

The main one. Each purchase is up to three lines — merchant with amount, then where
it happened or the payment rail, then when:

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

### Parser 2: push notifications (`app/notification_parser.py`)

Reads cards like this off a lock screen or notification centre:

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

### Parser 3: the bank's statement list (`app/statement_parser.py`)

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
| `FINANCE_HOST` | `127.0.0.1` | Address the server binds to |
| `FINANCE_PORT` | `8000` | Port for `bin/finance` |
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

Not built yet, in rough order of usefulness: monthly budgets and alerts, charts,
recurring-charge detection from the spending list, multi-card support, and deploying
this to a small server with Postgres and a login.
