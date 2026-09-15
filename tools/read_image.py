"""Reads a screenshot from the command line without touching the database.

    python tools/read_image.py ~/Desktop/statement.png
    python tools/read_image.py ~/Desktop/statement.png --raw

Useful for checking why a particular screenshot parsed badly before you go
fixing anything in the web UI.
"""

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ocr, parsing  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a statement screenshot.")
    parser.add_argument("image", type=Path, help="path to a PNG/JPG/HEIC screenshot")
    parser.add_argument("--engine", default="auto",
                        help="auto (default), apple-vision or tesseract")
    parser.add_argument("--raw", action="store_true",
                        help="also print the raw OCR text")
    parser.add_argument("--taken-on", metavar="YYYY-MM-DD",
                        help="day the screenshot was taken; notification"
                             " timestamps like 'Sun, 19:26' are resolved from it")
    args = parser.parse_args()

    if not args.image.exists():
        print(f"No such file: {args.image}")
        return 1

    print(f"Engines available: {', '.join(ocr.available_engines()) or 'none'}")
    result = ocr.run_ocr(args.image, engine=args.engine)
    print(f"Read {args.image.name} with {result.engine}: {len(result.boxes)} text boxes\n")

    if args.raw:
        print("--- raw OCR text " + "-" * 40)
        print(result.as_text())
        print()

    reference = (date.fromisoformat(args.taken_on) if args.taken_on
                 else parsing.image_taken_on(args.image))
    if reference:
        print(f"Resolving notification weekdays against {reference}\n")

    transactions = parsing.parse_screenshot(result.boxes, reference_date=reference)
    if not transactions:
        print("No transactions recognised. Re-run with --raw to see what the OCR saw.")
        return 0

    print(f"--- {len(transactions)} transaction(s) " + "-" * 34)
    total = 0
    for tx in transactions:
        total += tx.amount_cents
        amount = parsing.format_cents(tx.amount_cents, tx.currency)
        time_part = tx.occurred_time or "  -  "
        print(f"{tx.occurred_on} {time_part}  {tx.merchant[:30]:<30}"
              f" {amount:>13}  {tx.category}")
    print("-" * 55)
    print(f"{'net total':<48}{parsing.format_cents(total):>13}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
