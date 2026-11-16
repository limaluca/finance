# Codebase Conventions

Last reviewed: 2026-11-02

## Structure and architecture

- This is a local-first personal finance web app. `app/main.py` is the FastAPI entry
  point and route/controller layer. It wires page handlers to domain modules and
  Jinja templates.
- `app/` contains the application: business rules (`dedupe.py`, `categorize.py`,
  `merchants.py`, `commitments.py`), parsing (`parsing.py`, `statement_parser.py`,
  `wallet_parser.py`, `notification_parser.py`), persistence (`db.py`), OCR adapters
  (`ocr/`), and UI assets (`templates/`, `static/`). This is a small modular
  monolith, with some route and orchestration logic concentrated in `main.py`.
- `tools/` contains command-line utilities and the repeatable parser/rule checks.
  `docs/` contains operational and development documentation. `bin/finance` is
  the local lifecycle CLI; `run.sh` starts a development server.
- The browser flow for screenshot imports is routed through upload and review/save
  handlers in `app/main.py`, rendered by `app/templates/upload.html` and
  `app/templates/confirm.html`.
- Business rules should remain in focused modules (for example, duplicate matching
  in `app/dedupe.py`); SQL and database access belong in `app/db.py`; rendering
  belongs in Jinja templates and `app/static/style.css`.

## Data and boundaries

- Persistence is SQLite. Tables and schema setup are declared in `app/db.py` and
  initialized at application startup; no separate migration framework was found.
- Table and column names use `snake_case`. The main entities include `transactions`
  and `imports`; transaction import provenance is represented by `import_id`.
- Monetary values are stored as integer cents. Dates use ISO calendar-date strings;
  import metadata stores an ISO timestamp.
- Parsing modules turn OCR/text into application values. Route handlers validate
  form input and coordinate persistence. Jinja templates format values through
  helpers registered in `app/main.py`.
- The app copies uploaded screenshots to its local data directory and serves an
  import image through an application route.

## Code style and runtime

- Python 3.11+ is documented as supported. The web framework is FastAPI, with
  Starlette request/upload types, Uvicorn, and Jinja2. Browser behavior is plain
  JavaScript and CSS; no frontend build system is present.
- Python modules and functions use `snake_case`; classes use `PascalCase`; constants
  use uppercase names. Types are added to many public functions and data structures.
- Dependencies are pinned in `requirements.txt`. No formatter, linter, or type-checker
  configuration was found in the repository.
- Route errors generally become redirect query notices or HTTP responses. Database
  access uses SQLite connections from `app/db.py`; there is no general logging
  framework configured in the inspected app code.
- Runtime paths and settings are centralized in `app/config.py`; secrets are not a
  normal part of this local-only application.

## Quality and checks

- No dedicated `tests/` directory or conventional pytest/unittest suite was found.
  `tools/check_parsers.py` is the existing executable regression check for parser,
  merchant, categorization, and duplicate behavior.
- Run the focused/full available rule check with `bin/finance check` (or
  `.venv/bin/python tools/check_parsers.py` when the environment already exists).
- `bin/finance` manages the server and invokes the check script. `./run.sh` starts
  Uvicorn for development. No CI workflow was found in the repository inventory.
- Database-dependent behavior should be checked against a disposable database copy
  or isolated fixture, not by introducing unreviewed records into the personal DB.

## Health signals

- `app/main.py` is a large module containing route orchestration for several finance
  areas; keep new business rules out of it where a focused domain module exists.
- The repository relies on a hand-maintained executable check script rather than a
  standard test framework, so new rule cases must be added to that check and the
  documented regression plan.
- Duplicate matching, date inference, categorization, and merchant canonicalization
  are consequential import rules. Their behavior should have deterministic examples
  and user-facing explanations where the system flags uncertain matches.

## Patterns to follow

- Keep domain decisions in small modules and call them from route orchestration.
- Keep database statements and row-to-domain loading in `app/db.py`.
- Use integer cents and ISO dates at persistence and form boundaries.
- Preserve import provenance when displaying or reviewing imported transactions.
- Add new deterministic rule examples to `tools/check_parsers.py` and
  `docs/EXPENSE_RULE_REGRESSION_PLAN.md` when changing import rules.
- Match the existing server-rendered Jinja and plain CSS/JavaScript UI approach.

## Patterns to avoid or migrate away from

- Do not add business rules directly to templates or route handlers when they belong
  in a domain module.
- Do not use floating-point values for currency.
- Do not treat an inferred or missing date as confirmed duplicate evidence.
- Avoid adding more unrelated responsibilities to `app/main.py`.
- Do not test import behavior by writing experimental rows into the live finance DB.
