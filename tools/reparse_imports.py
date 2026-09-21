"""Re-runs the parsers over OCR output already stored on an import.

Useful after a parser change: the screenshot does not need to be read again.
With --save the results go through the same duplicate check the confirm page
applies and are written as transactions.

    tools/reparse_imports.py --taken-on 2026-09-16            # preview
    tools/reparse_imports.py --taken-on 2026-09-16 --save     # write them

Imports made before `boxes_json` existed only have the line-grouped text, which
loses the x coordinates. The statement parser reads column positions, so those
imports are reported as degraded rather than silently mis-parsed.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import categorize as categorize_mod         # noqa: E402
from app import config, db, dedupe                   # noqa: E402
from app.ocr.base import TextBox, boxes_from_json    # noqa: E402
from app.parsing import parse_screenshot             # noqa: E402


def boxes_from_text(raw_text: str) -> list[TextBox]:
    """Rebuilds one full-width box per stored OCR line.

    Enough for the line-based parsers (notifications, Wallet), but it throws
    away horizontal positions, so anything reading columns will struggle.
    """
    boxes = []
    for index, text in enumerate(raw_text.splitlines()):
        if text.strip():
            boxes.append(TextBox(text=text, confidence=1.0, x=0.0,
                                 y=index / 1000, width=1.0, height=0.001))
    return boxes


def boxes_for(record) -> tuple[list[TextBox], bool]:
    """Returns (boxes, faithful). `faithful` is False for text-only fallbacks."""
    stored = record["boxes_json"] if "boxes_json" in record.keys() else None
    if stored:
        return boxes_from_json(stored), True
    return boxes_from_text(record["raw_text"]), False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--taken-on", help="reference date for relative days (YYYY-MM-DD)")
    ap.add_argument("--only", help="only imports whose filename contains this")
    ap.add_argument("--save", action="store_true", help="write the transactions")
    args = ap.parse_args()

    reference = date.fromisoformat(args.taken_on) if args.taken_on else date.today()

    with db.connect() as conn:
        records = conn.execute(
            "SELECT * FROM imports WHERE raw_text IS NOT NULL ORDER BY id"
        ).fetchall()
    if args.only:
        records = [r for r in records
                   if args.only.lower() in (r["original_name"] or "").lower()]
    if not records:
        print("no imports to re-read")
        return

    index = db.duplicate_index()
    to_insert: list[dict] = []
    degraded: list[str] = []

    for record in records:
        boxes, faithful = boxes_for(record)
        parsed = parse_screenshot(boxes, reference_date=reference)
        for tx in parsed:
            tx.source_image = record["original_name"]
        dedupe.annotate(parsed, index)

        warning = "" if faithful else "  (text only: no column positions)"
        if not faithful:
            degraded.append(record["original_name"] or str(record["id"]))
        print(f"\n=== {record['original_name']} (import {record['id']}): "
              f"{len(parsed)} row(s){warning}")
        for tx in parsed:
            weekday = date.fromisoformat(tx.occurred_on).strftime("%a")
            note = ""
            if tx.duplicate_kind:
                note = f"  [{tx.duplicate_kind}: {tx.duplicate_note}]"
            elif tx.date_source not in ("wallet", "exact"):
                note = f"  [date from {tx.date_source}]"
            print(f"   {tx.occurred_on} {weekday}  {tx.merchant:<26}"
                  f"{tx.amount_cents/100:>9.2f}  {tx.category:<15}{note}")

            if tx.duplicate_kind == "exact":
                continue
            to_insert.append({
                "occurred_on": tx.occurred_on,
                "occurred_time": tx.occurred_time,
                "merchant": tx.merchant,
                "amount_cents": tx.amount_cents,
                "currency": tx.currency or config.CURRENCY,
                "category": tx.category or categorize_mod.OTHER,
                "notes": None,
                "import_id": record["id"],
                "raw_line": tx.raw_line,
            })

        if args.save:
            with db.connect() as conn:
                conn.execute(
                    "UPDATE imports SET parsed_json = ?, status = 'saved' WHERE id = ?",
                    (json.dumps([tx.to_dict() for tx in parsed], ensure_ascii=False),
                     record["id"]))

    print(f"\n{len(to_insert)} row(s) after removing duplicates")
    if degraded:
        print("read from text only, so check these before trusting them: "
              + ", ".join(degraded))
    if args.save:
        db.insert_transactions(to_insert)
        print(f"saved {len(to_insert)} transaction(s)")
    else:
        print("preview only; pass --save to write them")


if __name__ == "__main__":
    main()
