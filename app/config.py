"""Central settings. Everything is overridable by environment variable so the
same code can run on a laptop and on a server without edits."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("FINANCE_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = Path(os.environ.get("FINANCE_DB_PATH", DATA_DIR / "finance.db"))
# Written by `finance start`, so the server can tidy it up when it stops itself.
PID_PATH = Path(os.environ.get("FINANCE_PID_PATH", DATA_DIR / "server.pid"))

# The server stops itself after this many minutes without a page view, so it is
# not left running all day for nothing. 0 keeps it up until you stop it.
IDLE_TIMEOUT_MINUTES = int(os.environ.get("FINANCE_IDLE_TIMEOUT_MINUTES", "60"))

# "auto" picks Apple Vision on macOS and falls back to Tesseract elsewhere.
OCR_ENGINE = os.environ.get("FINANCE_OCR_ENGINE", "auto")
OCR_LANGUAGES = os.environ.get("FINANCE_OCR_LANGUAGES", "pt-BR,en-US").split(",")

# Numeric dates are ambiguous: 03/04 is March 4th in the US and April 3rd
# nearly everywhere else. "DMY" or "MDY".
DATE_ORDER = os.environ.get("FINANCE_DATE_ORDER", "DMY").upper()

CURRENCY = os.environ.get("FINANCE_CURRENCY", "BRL")
CURRENCY_SYMBOLS = {"BRL": "R$", "USD": "$", "EUR": "€", "GBP": "£"}

MAX_UPLOAD_BYTES = int(os.environ.get("FINANCE_MAX_UPLOAD_BYTES", 20 * 1024 * 1024))
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}


def currency_symbol(code: str | None = None) -> str:
    return CURRENCY_SYMBOLS.get(code or CURRENCY, code or CURRENCY)


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
