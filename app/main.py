"""FastAPI application: upload screenshots, confirm what was read, save it."""

import json
import uuid
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
from . import config, csv_io, db, dedupe, ocr, parsing

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Finance Tracker", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals.update(
    money=parsing.format_cents,
    categories=categorize_mod.CATEGORIES,
    currency_symbol=config.currency_symbol,
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
    return sorted(set(categorize_mod.CATEGORIES) | set(db.known_categories()))


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    month = request.query_params.get("month") or None
    category = request.query_params.get("category") or None
    search = request.query_params.get("q") or None

    transactions = db.list_transactions(month=month, category=category, search=search)
    spending = sum(t["amount_cents"] for t in transactions if t["amount_cents"] > 0)
    credits = sum(t["amount_cents"] for t in transactions if t["amount_cents"] < 0)

    from urllib.parse import urlencode
    export_query = urlencode({k: v for k, v in
                              (("month", month), ("category", category), ("q", search))
                              if v})

    return _render(
        request, "dashboard.html",
        transactions=transactions,
        totals=db.totals_by_category(month=month),
        months=db.available_months(),
        all_categories=_all_categories(),
        selected_month=month,
        selected_category=category,
        search=search or "",
        spending=spending,
        credits=credits,
        today=date.today().isoformat(),
        export_query=export_query,
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
    # a stale page cannot slip a duplicate through.
    index = db.duplicate_index()

    rows: list[dict] = []
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

        match = index.find(occurred_on, merchant, amount_cents)
        if match is not None and match.is_blocking:
            skipped_duplicate += 1
            continue

        category = (form.get(f"category_{position}") or "").strip() or categorize_mod.OTHER
        import_id = form.get(f"import_{position}")

        rows.append({
            "occurred_on": occurred_on,
            "occurred_time": (form.get(f"time_{position}") or "").strip() or None,
            "merchant": merchant,
            "amount_cents": amount_cents,
            "currency": (form.get(f"currency_{position}") or config.CURRENCY).strip(),
            "category": category,
            "notes": None,
            "import_id": int(import_id) if import_id and str(import_id).isdigit() else None,
            "raw_line": (form.get(f"raw_{position}") or "").strip() or None,
        })
        # Keep the index current so two identical rows in one submission cannot
        # both be written.
        index.add(occurred_on, merchant, amount_cents)

        if category != (form.get(f"suggested_{position}") or "").strip():
            categorize_mod.learn(merchant, category)

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
    merchant = (form.get("merchant") or "").strip()
    amount_cents = parsing.parse_money_input(form.get("amount") or "")
    occurred_on = parsing.parse_date_input(form.get("date") or "")
    if not merchant or amount_cents is None or not occurred_on:
        return _redirect("/", error="Merchant, amount and date are all required.")

    match = db.duplicate_index().find(occurred_on, merchant, amount_cents)
    if match is not None and match.is_blocking:
        return _redirect("/", error=f"Not added: {match.describe().lower()}.")

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
    merchant = (form.get("merchant") or "").strip()
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


@app.get("/health")
def health():
    return {"status": "ok", "ocr_engines": ocr.available_engines()}
