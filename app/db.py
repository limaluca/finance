"""SQLite data layer.

Amounts are stored as integer cents so we never do money math in floats.
Dates are split into `occurred_on` (YYYY-MM-DD) and an optional
`occurred_time` (HH:MM), because receipts often give one without the other.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT NOT NULL,
    original_name TEXT,
    engine        TEXT,
    raw_text      TEXT,
    parsed_json   TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    batch_id      TEXT
);

CREATE INDEX IF NOT EXISTS idx_imports_batch ON imports(batch_id);

CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_on   TEXT NOT NULL,
    occurred_time TEXT,
    merchant      TEXT NOT NULL,
    amount_cents  INTEGER NOT NULL,
    currency      TEXT NOT NULL,
    category      TEXT NOT NULL,
    notes         TEXT,
    import_id     INTEGER REFERENCES imports(id) ON DELETE SET NULL,
    raw_line      TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_occurred_on ON transactions(occurred_on);
CREATE INDEX IF NOT EXISTS idx_tx_category ON transactions(category);

CREATE TABLE IF NOT EXISTS merchant_rules (
    pattern    TEXT PRIMARY KEY,
    category   TEXT NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.ensure_dirs()
    # Create the schema whenever the file is absent, so deleting data/ to start
    # over works without restarting the server.
    fresh = not config.DB_PATH.exists()
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if fresh:
        conn.executescript(SCHEMA)
    else:
        _migrate(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after the first release. Kept tiny on purpose: SQLite can add
# nullable columns in place, which is all we have needed so far.
_ADDED_COLUMNS = [
    ("imports", "batch_id", "TEXT"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, column_type in _ADDED_COLUMNS:
        existing = {row["name"] for row in
                    conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if not existing:
            continue    # Table itself is missing; the schema script will make it.
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    # Imports predating batches get one of their own, so every import stays
    # reachable through the batch-based confirm page.
    conn.execute("UPDATE imports SET batch_id = 'single-' || id WHERE batch_id IS NULL")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


# --- imports ---------------------------------------------------------------

def create_import(filename: str, original_name: str, engine: str, raw_text: str,
                  parsed_json: str, batch_id: str | None = None) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO imports (filename, original_name, engine, raw_text,"
            " parsed_json, status, created_at, batch_id)"
            " VALUES (?,?,?,?,?,'pending',?,?)",
            (filename, original_name, engine, raw_text, parsed_json,
             now_iso(), batch_id),
        )
        return int(cur.lastrowid)


def get_batch(batch_id: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM imports WHERE batch_id = ? ORDER BY id", (batch_id,)
        ).fetchall()


def set_batch_status(batch_id: str, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE imports SET status = ? WHERE batch_id = ?",
                     (status, batch_id))


def get_import(import_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM imports WHERE id = ?", (import_id,)).fetchone()


def list_imports() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT i.*, (SELECT COUNT(*) FROM transactions t WHERE t.import_id = i.id)"
            " AS tx_count FROM imports i ORDER BY i.id DESC"
        ).fetchall()


def set_import_status(import_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE imports SET status = ? WHERE id = ?", (status, import_id))


def delete_import(import_id: int) -> str | None:
    """Deletes the import and any transactions saved from it.

    Returns the stored filename so the caller can remove the image file.
    """
    with connect() as conn:
        row = conn.execute("SELECT filename FROM imports WHERE id = ?", (import_id,)).fetchone()
        conn.execute("DELETE FROM transactions WHERE import_id = ?", (import_id,))
        conn.execute("DELETE FROM imports WHERE id = ?", (import_id,))
        return row["filename"] if row else None


# --- transactions ----------------------------------------------------------

def insert_transactions(rows: list[dict]) -> int:
    if not rows:
        return 0
    created = now_iso()
    with connect() as conn:
        conn.executemany(
            "INSERT INTO transactions (occurred_on, occurred_time, merchant,"
            " amount_cents, currency, category, notes, import_id, raw_line,"
            " created_at) VALUES (:occurred_on, :occurred_time, :merchant,"
            " :amount_cents, :currency, :category, :notes, :import_id,"
            " :raw_line, :created_at)",
            [{**r, "created_at": created} for r in rows],
        )
    return len(rows)


def list_transactions(month: str | None = None, category: str | None = None,
                      search: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM transactions WHERE 1=1"
    params: list = []
    if month:
        sql += " AND substr(occurred_on, 1, 7) = ?"
        params.append(month)
    if category:
        sql += " AND category = ?"
        params.append(category)
    if search:
        sql += " AND merchant LIKE ?"
        params.append(f"%{search}%")
    sql += " ORDER BY occurred_on DESC, COALESCE(occurred_time,'') DESC, id DESC"
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def get_transaction(tx_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()


def update_transaction(tx_id: int, **fields) -> None:
    allowed = {"occurred_on", "occurred_time", "merchant", "amount_cents",
               "category", "notes", "currency"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    assignments = ", ".join(f"{k} = :{k}" for k in sets)
    with connect() as conn:
        conn.execute(f"UPDATE transactions SET {assignments} WHERE id = :id",
                     {**sets, "id": tx_id})


def delete_transaction(tx_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))


def duplicate_index():
    """Everything already recorded, in a form `dedupe.Index` can search."""
    from .dedupe import Index

    with connect() as conn:
        rows = conn.execute(
            "SELECT occurred_on, merchant, amount_cents FROM transactions"
        ).fetchall()
    return Index.from_rows(rows)


# --- aggregates ------------------------------------------------------------

def available_months() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT substr(occurred_on, 1, 7) AS m FROM transactions"
            " ORDER BY m DESC"
        ).fetchall()
    return [r["m"] for r in rows]


def known_categories() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM transactions ORDER BY category"
        ).fetchall()
    return [r["category"] for r in rows]


def totals_by_category(month: str | None = None) -> list[sqlite3.Row]:
    sql = ("SELECT category, COUNT(*) AS n, SUM(amount_cents) AS total"
           " FROM transactions WHERE 1=1")
    params: list = []
    if month:
        sql += " AND substr(occurred_on, 1, 7) = ?"
        params.append(month)
    sql += " GROUP BY category ORDER BY total DESC"
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


# --- learned merchant -> category rules -----------------------------------

def all_merchant_rules() -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute("SELECT pattern, category FROM merchant_rules").fetchall()
    return {r["pattern"]: r["category"] for r in rows}


def remember_merchant(pattern: str, category: str) -> None:
    pattern = pattern.strip().lower()
    if not pattern:
        return
    with connect() as conn:
        conn.execute(
            "INSERT INTO merchant_rules (pattern, category, hits, updated_at)"
            " VALUES (?,?,1,?) ON CONFLICT(pattern) DO UPDATE SET"
            " category = excluded.category, hits = hits + 1,"
            " updated_at = excluded.updated_at",
            (pattern, category, now_iso()),
        )


def list_merchant_rules() -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM merchant_rules ORDER BY hits DESC, pattern"
        ).fetchall()


def delete_merchant_rule(pattern: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM merchant_rules WHERE pattern = ?", (pattern,))
