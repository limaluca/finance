"""FastAPI application: upload screenshots, confirm what was read, save it."""

import json
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
# Starlette's multipart parser builds its own UploadFile, which is the *parent*
# of fastapi.UploadFile — checking against the subclass would never match.
from starlette.datastructures import UploadFile

from . import categorize as categorize_mod
from . import commitments, config, csv_io, db, dedupe, merchants, ocr, parsing

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Finance Tracker", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

WEEKDAYS_SHORT = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAYS_LONG = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday")


def weekday_short(iso_date: str) -> str:
    try:
        return WEEKDAYS_SHORT[date.fromisoformat(iso_date).weekday()]
    except (ValueError, TypeError):
        return ""


def weekday_long(iso_date: str) -> str:
    try:
        return WEEKDAYS_LONG[date.fromisoformat(iso_date).weekday()]
    except (ValueError, TypeError):
        return ""


def style_version() -> str:
    """Stamp for the stylesheet URL, so an edited style.css is never cached."""
    try:
        return str(int((BASE_DIR / "static/style.css").stat().st_mtime))
    except OSError:
        return "0"


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals.update(
    money=parsing.format_cents,
    categories=categorize_mod.CATEGORIES,
    currency_symbol=config.currency_symbol,
    weekday=weekday_short,
    weekday_long=weekday_long,
    style_version=style_version,
)


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    db.init_db()


def _render(request: Request, template: str, **context) -> HTMLResponse:
    context.setdefault("notice", request.query_params.get("notice"))
    context.setdefault("error", request.query_params.get("error"))
    return templates.TemplateResponse(request, template, context)


def _redirect(path: str, notice: str | None = None, error: str | None = None):
    from urllib.parse import quote_plus
    params = []
    if notice:
        params.append(f"notice={quote_plus(notice)}")
    if error:
        params.append(f"error={quote_plus(error)}")
    if params:
        path = f"{path}{'&' if '?' in path else '?'}{'&'.join(params)}"
    return RedirectResponse(path, status_code=303)


def _all_categories() -> list[str]:
    """Every category that can be assigned, for the add and edit pickers."""
    return sorted(set(categorize_mod.CATEGORIES) | set(db.known_categories()))


def _sort_links(filters: dict, sort: str, direction: str) -> dict[str, dict]:
    """Header links for each sortable column.

    The first click on a column sorts ascending; clicking the same column again
    flips it. Active filters ride along so sorting never drops them.
    """
    from urllib.parse import urlencode

    links = {}
    for column in db.SORT_COLUMNS:
        active = column == sort
        next_direction = "desc" if active and direction == "asc" else "asc"
        query = {k: v for k, v in filters.items() if v}
        query.update(sort=column, dir=next_direction)
        links[column] = {
            "url": "/?" + urlencode(query),
            "active": active,
            "arrow": ("\u25b2" if direction == "asc" else "\u25bc") if active else "",
        }
    return links


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    month = request.query_params.get("month") or None
    category = request.query_params.get("category") or None
    search = request.query_params.get("q") or None
    sort = request.query_params.get("sort") or db.DEFAULT_SORT
    if sort not in db.SORT_COLUMNS:
        sort = db.DEFAULT_SORT
    direction = "asc" if request.query_params.get("dir") == "asc" else "desc"

    transactions = db.list_transactions(month=month, category=category,
                                        search=search, sort=sort,
                                        direction=direction)
    spending = sum(t["amount_cents"] for t in transactions if t["amount_cents"] > 0)
    credits = sum(t["amount_cents"] for t in transactions if t["amount_cents"] < 0)

    from urllib.parse import urlencode
    filters = {"month": month, "category": category, "q": search}
    export_query = urlencode({k: v for k, v in filters.items() if v})

    return _render(
        request, "dashboard.html",
        transactions=transactions,
        totals=db.totals_by_category(month=month),
        months=db.available_months(),
        # The filter only offers categories that actually appear in the list,
        # while the add and edit pickers keep the full set.
        filter_categories=db.known_categories(),
        all_categories=_all_categories(),
        selected_month=month,
        selected_category=category,
        search=search or "",
        spending=spending,
        credits=credits,
        today=date.today().isoformat(),
        export_query=export_query,
        sort=sort,
        direction=direction,
        sort_links=_sort_links(filters, sort, direction),
        return_to=str(request.url.path) + (f"?{urlencode(dict(request.query_params))}"
                                           if request.query_params else ""),
    )


# --------------------------------------------------------------------------
# Upload -> OCR -> confirm
# --------------------------------------------------------------------------


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request):
    return _render(request, "upload.html",
                   engines=ocr.available_engines(),
                   configured_engine=config.OCR_ENGINE,
                   today=date.today().isoformat())


@app.post("/upload")
async def upload(request: Request):
    """Reads one or many screenshots into a single batch awaiting confirmation."""
    form = await request.form()
    uploads = [f for f in form.getlist("screenshot")
               if isinstance(f, UploadFile) and f.filename]
    if not uploads:
        return _redirect("/upload", error="Choose at least one screenshot.")

    engine = (form.get("engine") or "auto").strip()
    reference = parsing.parse_date_input(form.get("taken_on") or "")

    batch_id = uuid.uuid4().hex
    index = db.duplicate_index()
    failures: list[str] = []
    total_rows = 0
    created_any = False

    for upload_file in uploads:
        payload = await upload_file.read()
        if not payload:
            failures.append(f"{upload_file.filename}: file was empty")
            continue
        if len(payload) > config.MAX_UPLOAD_BYTES:
            limit = config.MAX_UPLOAD_BYTES // (1024 * 1024)
            failures.append(f"{upload_file.filename}: larger than {limit} MB")
            continue

        suffix = Path(upload_file.filename).suffix.lower() or ".png"
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"}:
            failures.append(f"{upload_file.filename}: not a PNG/JPG/WEBP/HEIC image")
            continue

        config.ensure_dirs()
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        stored_path = config.UPLOAD_DIR / stored_name
        stored_path.write_bytes(payload)

        try:
            result = ocr.run_ocr(stored_path, engine=engine or None)
        except Exception as exc:
            stored_path.unlink(missing_ok=True)
            failures.append(f"{upload_file.filename}: {exc}")
            continue

        reference_date = (date.fromisoformat(reference) if reference
                          else parsing.image_taken_on(stored_path) or date.today())
        parsed = parsing.parse_screenshot(result.boxes, reference_date=reference_date)
        for tx in parsed:
            tx.source_image = upload_file.filename
        # Flags rows already in the system and repeats within this same batch.
        dedupe.annotate(parsed, index)
        total_rows += len(parsed)

        db.create_import(
            filename=stored_name,
            original_name=upload_file.filename,
            engine=result.engine,
            raw_text=result.as_text(),
            parsed_json=json.dumps([tx.to_dict() for tx in parsed], ensure_ascii=False),
            batch_id=batch_id,
            boxes_json=result.as_json(),
        )
        created_any = True

    if not created_any:
        return _redirect("/upload", error="; ".join(failures) or "Nothing could be read.")

    error = "; ".join(failures) if failures else None
    if total_rows == 0:
        error = ((error + "; ") if error else "") + \
            "No purchases were recognised. The raw OCR text is on the confirm page."
    return _redirect(f"/confirm/{batch_id}", error=error)


@app.get("/confirm/{batch_id}", response_class=HTMLResponse)
def confirm(request: Request, batch_id: str):
    records = db.get_batch(batch_id)
    if not records:
        return _redirect("/", error="That upload no longer exists.")

    rows = []
    for record in records:
        for row in json.loads(record["parsed_json"] or "[]"):
            row["import_id"] = record["id"]
            row["source_image"] = row.get("source_image") or record["original_name"]
            rows.append(row)

    blocked = sum(1 for r in rows if r.get("duplicate_kind") == "exact")
    likely = sum(1 for r in rows if r.get("duplicate_kind") == "likely")
    undated = sum(1 for r in rows if r.get("date_source") in ("guess", "fallback"))
    ready = [r for r in rows if r.get("duplicate_kind") != "exact"
             and r.get("date_source") not in ("guess", "fallback")]

    return _render(request, "confirm.html",
                   batch_id=batch_id,
                   records=records,
                   rows=rows,
                   blocked=blocked,
                   likely=likely,
                   undated=undated,
                   ready_count=len(ready),
                   ready_total=sum(r["amount_cents"] for r in ready),
                   all_categories=_all_categories(),
                   today=date.today().isoformat())


@app.post("/confirm/{batch_id}")
async def save_batch(request: Request, batch_id: str):
    records = db.get_batch(batch_id)
    if not records:
        return _redirect("/", error="That upload no longer exists.")

    form = await request.form()
    indexes = sorted({int(key.rsplit("_", 1)[-1]) for key in form
                      if key.startswith("merchant_") and key.rsplit("_", 1)[-1].isdigit()})

    # Re-checked against the database at save time, not just at display time, so
    # a stale page cannot slip a duplicate through. Rows from one screenshot
    # are counted together: two 99 rides at the same price on the same day are
    # kept; extra copies of those rides on a later overlapping screenshot are not.
    index = db.duplicate_index()

    prepared: list[dict] = []
    skipped_incomplete = 0
    skipped_duplicate = 0

    for position in indexes:
        if not form.get(f"include_{position}"):
            continue
        merchant = (form.get(f"merchant_{position}") or "").strip()
        amount_cents = parsing.parse_money_input(form.get(f"amount_{position}") or "")
        occurred_on = parsing.parse_date_input(form.get(f"date_{position}") or "")
        if not merchant or amount_cents is None or not occurred_on:
            skipped_incomplete += 1
            continue

        category = (form.get(f"category_{position}") or "").strip() or categorize_mod.OTHER
        import_id = form.get(f"import_{position}")
        prepared.append({
            "occurred_on": occurred_on,
            "occurred_time": (form.get(f"time_{position}") or "").strip() or None,
            "merchant": merchant,
            "amount_cents": amount_cents,
            "currency": (form.get(f"currency_{position}") or config.CURRENCY).strip(),
            "category": category,
            "notes": None,
            "import_id": int(import_id) if import_id and str(import_id).isdigit() else None,
            "raw_line": (form.get(f"raw_{position}") or "").strip() or None,
            "suggested": (form.get(f"suggested_{position}") or "").strip(),
            "date_source": (form.get(f"date_source_{position}") or "").strip(),
        })

    groups: dict[object, list[dict]] = defaultdict(list)
    order: list[object] = []
    for row in prepared:
        # Rows typed in by hand on the confirm page have no screenshot, so each
        # one is its own group — occupancy blocking is for overlapping images.
        key = row["import_id"] if row["import_id"] is not None else id(row)
        if key not in groups:
            order.append(key)
        groups[key].append(row)

    rows: list[dict] = []
    for key in order:
        group = groups[key]
        matches = index.cover(
            [(r["occurred_on"], r["merchant"], r["amount_cents"], r["date_source"])
             for r in group])
        for row, match in zip(group, matches):
            if match is not None and match.is_blocking:
                skipped_duplicate += 1
                continue
            if row["category"] != row["suggested"]:
                categorize_mod.learn(row["merchant"], row["category"])
            row.pop("suggested", None)
            row.pop("date_source", None)
            rows.append(row)

    saved = db.insert_transactions(rows)
    db.set_batch_status(batch_id, "saved" if saved else "discarded")

    notice = f"Saved {saved} transaction(s)."
    if skipped_duplicate:
        notice += f" Blocked {skipped_duplicate} duplicate(s)."
    if skipped_incomplete:
        notice += f" Skipped {skipped_incomplete} incomplete row(s)."
    return _redirect("/", notice=notice)


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------


@app.get("/export.csv")
def export_csv(request: Request):
    month = request.query_params.get("month") or None
    category = request.query_params.get("category") or None
    search = request.query_params.get("q") or None

    transactions = db.list_transactions(month=month, category=category, search=search)
    body = csv_io.export_rows(transactions)

    stamp = month or date.today().isoformat()
    filename = f"spending-{stamp}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/import-csv", response_class=HTMLResponse)
def import_csv_form(request: Request):
    return _render(request, "import_csv.html", columns=csv_io.COLUMNS)


@app.post("/import-csv")
async def import_csv(request: Request):
    form = await request.form()
    upload_file = form.get("file")
    if not isinstance(upload_file, UploadFile) or not upload_file.filename:
        return _redirect("/import-csv", error="Choose a CSV file first.")

    payload = await upload_file.read()
    if not payload:
        return _redirect("/import-csv", error="That file was empty.")
    if len(payload) > config.MAX_UPLOAD_BYTES:
        return _redirect("/import-csv", error="That file is too large.")

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = payload.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        return _redirect("/import-csv", error="Could not decode that file as text.")

    try:
        parsed, problems = csv_io.parse_csv(text)
    except csv_io.CsvFormatError as exc:
        return _redirect("/import-csv", error=str(exc))

    if not parsed:
        detail = problems[0] if problems else "no usable rows found"
        return _redirect("/import-csv", error=f"Nothing to import: {detail}")

    for tx in parsed:
        tx.source_image = upload_file.filename
        tx.merchant = merchants.canonical(tx.merchant)
        if not tx.category:
            tx.category = categorize_mod.categorize(tx.merchant, tx.amount_cents)

    dedupe.annotate(parsed, db.duplicate_index())

    batch_id = uuid.uuid4().hex
    db.create_import(
        filename="",
        original_name=upload_file.filename,
        engine="csv",
        raw_text="\n".join(problems) if problems else text[:20000],
        parsed_json=json.dumps([tx.to_dict() for tx in parsed], ensure_ascii=False),
        batch_id=batch_id,
    )
    error = f"{len(problems)} row(s) had problems, listed on this page." if problems else None
    return _redirect(f"/confirm/{batch_id}", error=error)


# --------------------------------------------------------------------------
# Import history
# --------------------------------------------------------------------------


@app.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request):
    return _render(request, "imports.html", imports=db.list_imports())


@app.get("/review/{import_id}")
def review_redirect(import_id: int):
    """Re-reviewing a single import means opening the batch it belongs to."""
    record = db.get_import(import_id)
    if record is None:
        return _redirect("/imports", error="That import no longer exists.")
    return _redirect(f"/confirm/{record['batch_id'] or ('single-' + str(import_id))}")


@app.post("/imports/{import_id}/delete")
def delete_import(import_id: int):
    filename = db.delete_import(import_id)
    if filename:
        (config.UPLOAD_DIR / filename).unlink(missing_ok=True)
    return _redirect("/imports", notice="Import deleted.")


@app.get("/imports/{import_id}/image")
def import_image(import_id: int):
    record = db.get_import(import_id)
    if record is None or not record["filename"]:
        return _redirect("/imports", error="That import has no image.")
    # Resolved through the DB record, so no user-supplied path reaches disk.
    path = config.UPLOAD_DIR / record["filename"]
    if not path.exists():
        return _redirect("/imports", error="The image file is missing.")
    return FileResponse(path)


# --------------------------------------------------------------------------
# Manual transaction editing
# --------------------------------------------------------------------------


@app.post("/transactions/new")
async def create_transaction(request: Request):
    form = await request.form()
    merchant = merchants.canonical((form.get("merchant") or "").strip())
    amount_cents = parsing.parse_money_input(form.get("amount") or "")
    occurred_on = parsing.parse_date_input(form.get("date") or "")
    if not merchant or amount_cents is None or not occurred_on:
        return _redirect("/", error="Merchant, amount and date are all required.")

    category = (form.get("category") or "").strip() or categorize_mod.categorize(
        merchant, amount_cents)
    db.insert_transactions([{
        "occurred_on": occurred_on,
        "occurred_time": (form.get("time") or "").strip() or None,
        "merchant": merchant,
        "amount_cents": amount_cents,
        "currency": config.CURRENCY,
        "category": category,
        "notes": None,
        "import_id": None,
        "raw_line": None,
    }])
    return _redirect("/", notice="Transaction added.")


@app.get("/transactions/{tx_id}/edit", response_class=HTMLResponse)
def edit_transaction_form(request: Request, tx_id: int):
    tx = db.get_transaction(tx_id)
    if tx is None:
        return _redirect("/", error="That transaction no longer exists.")
    return _render(request, "edit.html", tx=tx, all_categories=_all_categories())


@app.post("/transactions/{tx_id}/edit")
async def edit_transaction(request: Request, tx_id: int):
    tx = db.get_transaction(tx_id)
    if tx is None:
        return _redirect("/", error="That transaction no longer exists.")

    form = await request.form()
    merchant = merchants.canonical((form.get("merchant") or "").strip())
    amount_cents = parsing.parse_money_input(form.get("amount") or "")
    occurred_on = parsing.parse_date_input(form.get("date") or "")
    if not merchant or amount_cents is None or not occurred_on:
        return _redirect(f"/transactions/{tx_id}/edit",
                         error="Merchant, amount and date are all required.")

    category = (form.get("category") or "").strip() or categorize_mod.OTHER
    db.update_transaction(
        tx_id,
        merchant=merchant,
        amount_cents=amount_cents,
        occurred_on=occurred_on,
        occurred_time=(form.get("time") or "").strip() or None,
        category=category,
    )
    if category != tx["category"]:
        categorize_mod.learn(merchant, category)
    return _redirect("/", notice="Transaction updated.")


@app.post("/transactions/{tx_id}/delete")
def remove_transaction(tx_id: int):
    db.delete_transaction(tx_id)
    return _redirect("/", notice="Transaction deleted.")


@app.post("/transactions/bulk-category")
async def bulk_category(request: Request):
    """Recategorises every ticked row in one go."""
    form = await request.form()
    back = (form.get("return_to") or "/").strip() or "/"
    if not back.startswith("/"):
        back = "/"

    tx_ids = [int(v) for v in form.getlist("tx_ids") if str(v).isdigit()]
    category = (form.get("bulk_category") or "").strip()
    if not tx_ids:
        return _redirect(back, error="Tick at least one transaction first.")
    if not category:
        return _redirect(back, error="Pick the category to apply.")

    changed = db.set_category(tx_ids, category)
    # Teach the categoriser from the correction, so the next import of the same
    # merchant lands in the right place on its own.
    for tx_id in tx_ids:
        tx = db.get_transaction(tx_id)
        if tx is not None:
            categorize_mod.learn(tx["merchant"], category)

    return _redirect(back, notice=f"Moved {changed} transaction(s) to {category}.")


# --------------------------------------------------------------------------
# Learned rules
# --------------------------------------------------------------------------


@app.get("/rules", response_class=HTMLResponse)
def rules_page(request: Request):
    return _render(request, "rules.html", rules=db.list_merchant_rules())


@app.post("/rules/delete")
async def delete_rule(request: Request):
    form = await request.form()
    pattern = (form.get("pattern") or "").strip()
    if pattern:
        db.delete_merchant_rule(pattern)
    return _redirect("/rules", notice="Rule removed.")


# --------------------------------------------------------------------------
# Installment plans
# --------------------------------------------------------------------------


def _installment_form(form, month: str) -> tuple[dict | None, str | None]:
    """Reads the plan form, which is worded the way the spreadsheet was.

    You say which installment is being billed in `month` and how long the plan
    is; the stored anchor is the month installment 1 fell in, worked back from
    that. Storing the anchor is what lets the screens move on by themselves.
    """
    description = (form.get("description") or "").strip()
    bank = (form.get("bank_other") or "").strip() or (form.get("bank") or "").strip()
    monthly_cents = parsing.parse_money_input(form.get("monthly") or "")
    current_raw = (form.get("current") or "").strip()
    total_raw = (form.get("total") or "").strip()

    if not description or not bank:
        return None, "Give the expense a name and a bank."
    if monthly_cents is None or monthly_cents <= 0:
        return None, "The installment amount must be a positive number."
    if not current_raw.lstrip("-").isdigit() or not total_raw.isdigit():
        return None, "The installment numbers must be whole numbers."

    current, total = int(current_raw), int(total_raw)
    if total < 1:
        return None, "A plan needs at least one installment."
    if current > total:
        return None, (f"This month cannot be installment {current} of a "
                      f"{total}-installment plan.")

    return {
        "description": description,
        "monthly_cents": monthly_cents,
        "total": total,
        # current = 1 means this month holds installment 1; 0 means it starts next
        # month, and negatives push it further out.
        "first_month": db.shift_month(month, -(current - 1)),
        "bank": bank,
    }, None


def _view_month(request: Request) -> str:
    """The month the commitment screens are showing. Defaults to the real one."""
    asked = (request.query_params.get("month") or "").strip()
    if len(asked) == 7 and asked[4] == "-" and asked[:4].isdigit():
        return asked
    return commitments.this_month()


@app.get("/installments", response_class=HTMLResponse)
def installments_page(request: Request):
    bank = request.query_params.get("bank") or None
    month = _view_month(request)
    show_finished = request.query_params.get("finished") == "1"

    rows = db.list_installments()
    shown = [r for r in rows if not bank or r["bank"] == bank]
    visible = commitments.plans(shown, month)
    if not show_finished:
        visible = [p for p in visible if not p.finished]

    return _render(
        request, "installments.html",
        plans=visible,
        totals=commitments.installment_totals(shown, month),
        by_bank=commitments.by_bank(rows, month=month),
        banks=db.installment_banks(),
        selected_bank=bank,
        overall=commitments.installment_totals(rows, month),
        month=month,
        is_current_month=month == commitments.this_month(),
        prev_month=db.shift_month(month, -1),
        next_month=db.shift_month(month, 1),
        show_finished=show_finished,
    )


@app.post("/installments/new")
async def create_installment(request: Request):
    form = await request.form()
    month = (form.get("month") or "").strip() or commitments.this_month()
    values, error = _installment_form(form, month)
    if error:
        return _redirect("/installments", error=error)
    db.create_installment(**values)
    return _redirect("/installments", notice=f"Added {values['description']}.")


@app.get("/installments/{item_id}/edit", response_class=HTMLResponse)
def edit_installment_form(request: Request, item_id: int):
    row = db.get_installment(item_id)
    if row is None:
        return _redirect("/installments", error="That plan no longer exists.")
    month = commitments.this_month()
    return _render(request, "installment_edit.html", item=row,
                   plan=commitments.Plan.from_row(row, month), month=month,
                   banks=db.all_banks())


@app.post("/installments/{item_id}/edit")
async def edit_installment(request: Request, item_id: int):
    if db.get_installment(item_id) is None:
        return _redirect("/installments", error="That plan no longer exists.")
    form = await request.form()
    month = (form.get("month") or "").strip() or commitments.this_month()
    values, error = _installment_form(form, month)
    if error:
        return _redirect(f"/installments/{item_id}/edit", error=error)
    db.update_installment(
        item_id, description=values["description"],
        monthly_cents=values["monthly_cents"],
        total_installments=values["total"],
        first_month=values["first_month"], bank=values["bank"])
    return _redirect("/installments", notice="Plan updated.")


@app.post("/installments/{item_id}/delete")
def remove_installment(item_id: int):
    db.delete_installment(item_id)
    return _redirect("/installments", notice="Plan removed.")


# --------------------------------------------------------------------------
# Subscriptions
# --------------------------------------------------------------------------


def _subscription_form(form) -> tuple[dict | None, str | None]:
    description = (form.get("description") or "").strip()
    bank = (form.get("bank_other") or "").strip() or (form.get("bank") or "").strip()
    monthly_cents = parsing.parse_money_input(form.get("monthly") or "")

    if not description or not bank:
        return None, "Give the subscription a name and a bank."
    if monthly_cents is None or monthly_cents <= 0:
        return None, "The monthly amount must be a positive number."
    return {"description": description, "monthly_cents": monthly_cents,
            "bank": bank}, None


@app.get("/subscriptions", response_class=HTMLResponse)
def subscriptions_page(request: Request):
    bank = request.query_params.get("bank") or None
    rows = db.list_subscriptions()
    shown = [r for r in rows if not bank or r["bank"] == bank]

    per_bank = {}
    for row in rows:
        entry = per_bank.setdefault(row["bank"], {"bank": row["bank"], "count": 0,
                                                  "monthly_cents": 0})
        entry["count"] += 1
        entry["monthly_cents"] += row["monthly_cents"]

    return _render(
        request, "subscriptions.html",
        subscriptions=shown,
        totals=commitments.subscription_totals(shown),
        overall=commitments.subscription_totals(rows),
        by_bank=sorted(per_bank.values(), key=lambda e: -e["monthly_cents"]),
        banks=db.subscription_banks(),
        all_banks=db.all_banks(),
        selected_bank=bank,
    )


@app.post("/subscriptions/new")
async def create_subscription(request: Request):
    form = await request.form()
    values, error = _subscription_form(form)
    if error:
        return _redirect("/subscriptions", error=error)
    db.create_subscription(**values)
    return _redirect("/subscriptions", notice=f"Added {values['description']}.")


@app.get("/subscriptions/{item_id}/edit", response_class=HTMLResponse)
def edit_subscription_form(request: Request, item_id: int):
    row = db.get_subscription(item_id)
    if row is None:
        return _redirect("/subscriptions", error="That subscription no longer exists.")
    return _render(request, "subscription_edit.html", item=row, banks=db.all_banks())


@app.post("/subscriptions/{item_id}/edit")
async def edit_subscription(request: Request, item_id: int):
    if db.get_subscription(item_id) is None:
        return _redirect("/subscriptions", error="That subscription no longer exists.")
    form = await request.form()
    values, error = _subscription_form(form)
    if error:
        return _redirect(f"/subscriptions/{item_id}/edit", error=error)
    db.update_subscription(item_id, description=values["description"],
                           monthly_cents=values["monthly_cents"], bank=values["bank"])
    return _redirect("/subscriptions", notice="Subscription updated.")


@app.post("/subscriptions/{item_id}/delete")
def remove_subscription(item_id: int):
    db.delete_subscription(item_id)
    return _redirect("/subscriptions", notice="Subscription removed.")


# --------------------------------------------------------------------------
# Fixed monthly expenses
# --------------------------------------------------------------------------


def _fixed_form(form) -> tuple[dict | None, str | None]:
    description = (form.get("description") or "").strip()
    monthly_cents = parsing.parse_money_input(form.get("monthly") or "")
    due_raw = (form.get("due_day") or "").strip()

    if not description:
        return None, "Give the expense a name."
    if monthly_cents is None or monthly_cents <= 0:
        return None, "The amount must be a positive number."
    due_day = None
    if due_raw:
        if not due_raw.isdigit() or not 1 <= int(due_raw) <= 31:
            return None, "The due day must be a number between 1 and 31."
        due_day = int(due_raw)

    return {"description": description, "monthly_cents": monthly_cents,
            "due_day": due_day}, None


@app.get("/fixed", response_class=HTMLResponse)
def fixed_page(request: Request):
    month = _view_month(request)
    rows = db.list_fixed_expenses(month)

    return _render(
        request, "fixed.html",
        expenses=rows,
        totals=commitments.fixed_totals(rows),
        month=month,
        is_current_month=month == commitments.this_month(),
        prev_month=db.shift_month(month, -1),
        next_month=db.shift_month(month, 1),
        today=date.today().isoformat(),
    )


@app.post("/fixed/new")
async def create_fixed(request: Request):
    form = await request.form()
    month = (form.get("month") or "").strip() or commitments.this_month()
    values, error = _fixed_form(form)
    if error:
        return _redirect(f"/fixed?month={month}", error=error)
    db.create_fixed_expense(**values)
    return _redirect(f"/fixed?month={month}",
                     notice=f"Added {values['description']}.")


@app.post("/fixed/{item_id}/toggle")
async def toggle_fixed(request: Request, item_id: int):
    """Ticks a bill off for one month, or un-ticks it."""
    row = db.get_fixed_expense(item_id)
    if row is None:
        return _redirect("/fixed", error="That expense no longer exists.")

    form = await request.form()
    month = (form.get("month") or "").strip() or commitments.this_month()
    paid = bool(form.get("paid"))
    db.set_fixed_expense_paid(item_id, month, paid)

    state = "paid" if paid else "pending"
    return _redirect(f"/fixed?month={month}",
                     notice=f"{row['description']} marked {state} for {month}.")


@app.get("/fixed/{item_id}/edit", response_class=HTMLResponse)
def edit_fixed_form(request: Request, item_id: int):
    row = db.get_fixed_expense(item_id)
    if row is None:
        return _redirect("/fixed", error="That expense no longer exists.")
    return _render(request, "fixed_edit.html", item=row,
                   month=_view_month(request),
                   months_paid=db.fixed_expense_months())


@app.post("/fixed/{item_id}/edit")
async def edit_fixed(request: Request, item_id: int):
    if db.get_fixed_expense(item_id) is None:
        return _redirect("/fixed", error="That expense no longer exists.")
    form = await request.form()
    values, error = _fixed_form(form)
    if error:
        return _redirect(f"/fixed/{item_id}/edit", error=error)
    db.update_fixed_expense(item_id, **values)
    return _redirect("/fixed", notice="Expense updated.")


@app.post("/fixed/{item_id}/delete")
def remove_fixed(item_id: int):
    db.delete_fixed_expense(item_id)
    return _redirect("/fixed", notice="Expense removed.")


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------


@app.get("/summary", response_class=HTMLResponse)
def summary_page(request: Request):
    month = _view_month(request)
    months = sorted(set(db.available_months()) | {month}, reverse=True)

    transactions = db.list_transactions(month=month)
    card_spending = sum(t["amount_cents"] for t in transactions
                        if t["amount_cents"] > 0)

    installment_rows = db.list_installments()
    subscription_rows = db.list_subscriptions()
    fixed_rows = db.list_fixed_expenses(month)

    installments = commitments.installment_totals(installment_rows, month)
    subscriptions = commitments.subscription_totals(subscription_rows)
    fixed = commitments.fixed_totals(fixed_rows)

    committed = (installments["monthly_cents"] + subscriptions["monthly_cents"]
                 + fixed["monthly_cents"])

    return _render(
        request, "summary.html",
        month=month,
        months=months,
        is_current_month=month == commitments.this_month(),
        prev_month=db.shift_month(month, -1),
        next_month=db.shift_month(month, 1),
        card_spending=card_spending,
        card_count=len(transactions),
        installments=installments,
        subscriptions=subscriptions,
        fixed=fixed,
        monthly_total=card_spending + committed,
        committed_total=committed,
        by_bank=commitments.by_bank(installment_rows, subscription_rows,
                                    month=month),
        top_categories=db.totals_by_category(month=month)[:5],
        top_merchants=db.top_merchants(month=month, limit=5),
    )


@app.get("/health")
def health():
    return {"status": "ok", "ocr_engines": ocr.available_engines()}
