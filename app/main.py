"""FastAPI application: upload a screenshot, review what the OCR found, save it."""

import json
import uuid
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import categorize as categorize_mod
from . import config, db, ocr, parsing

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
    params = []
    if notice:
        params.append(f"notice={notice.replace(' ', '+')}")
    if error:
        params.append(f"error={error.replace(' ', '+')}")
    if params:
        path = f"{path}{'&' if '?' in path else '?'}{'&'.join(params)}"
    return RedirectResponse(path, status_code=303)


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

    return _render(
        request, "dashboard.html",
        transactions=transactions,
        totals=db.totals_by_category(month=month),
        months=db.available_months(),
        all_categories=sorted(set(categorize_mod.CATEGORIES) | set(db.known_categories())),
        selected_month=month,
        selected_category=category,
        search=search or "",
        spending=spending,
        credits=credits,
        today=date.today().isoformat(),
    )


# --------------------------------------------------------------------------
# Upload -> OCR -> review
# --------------------------------------------------------------------------


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request):
    return _render(request, "upload.html",
                   engines=ocr.available_engines(),
                   configured_engine=config.OCR_ENGINE)


@app.post("/upload")
async def upload(request: Request, screenshot: UploadFile, engine: str = "auto"):
    if not screenshot or not screenshot.filename:
        return _redirect("/upload", error="Choose a screenshot first.")

    payload = await screenshot.read()
    if not payload:
        return _redirect("/upload", error="That file was empty.")
    if len(payload) > config.MAX_UPLOAD_BYTES:
        limit = config.MAX_UPLOAD_BYTES // (1024 * 1024)
        return _redirect("/upload", error=f"File is larger than {limit} MB.")

    suffix = Path(screenshot.filename).suffix.lower() or ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"}:
        return _redirect("/upload", error="Use a PNG, JPG, WEBP or HEIC image.")

    config.ensure_dirs()
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    stored_path = config.UPLOAD_DIR / stored_name
    stored_path.write_bytes(payload)

    try:
        result = ocr.run_ocr(stored_path, engine=engine or None)
    except ocr.OcrUnavailable as exc:
        stored_path.unlink(missing_ok=True)
        return _redirect("/upload", error=str(exc))
    except Exception as exc:
        stored_path.unlink(missing_ok=True)
        return _redirect("/upload", error=f"Could not read that image: {exc}")

    parsed = parsing.parse_screenshot(result.boxes)
    for tx in parsed:
        tx.duplicate = db.transaction_exists(tx.occurred_on, tx.merchant, tx.amount_cents)

    import_id = db.create_import(
        filename=stored_name,
        original_name=screenshot.filename,
        engine=result.engine,
        raw_text=result.as_text(),
        parsed_json=json.dumps([tx.to_dict() for tx in parsed], ensure_ascii=False),
    )
    if not parsed:
        return _redirect(f"/review/{import_id}",
                        error="No transactions were recognised. Check the OCR text below.")
    return _redirect(f"/review/{import_id}")


@app.get("/review/{import_id}", response_class=HTMLResponse)
def review(request: Request, import_id: int):
    record = db.get_import(import_id)
    if record is None:
        return _redirect("/", error="That import no longer exists.")
    rows = json.loads(record["parsed_json"] or "[]")
    return _render(request, "review.html",
                   record=record,
                   rows=rows,
                   all_categories=sorted(set(categorize_mod.CATEGORIES)
                                         | set(db.known_categories())),
                   today=date.today().isoformat())


@app.post("/review/{import_id}")
async def save_review(request: Request, import_id: int):
    record = db.get_import(import_id)
    if record is None:
        return _redirect("/", error="That import no longer exists.")

    form = await request.form()
    indexes = sorted({int(key.split("_")[-1]) for key in form
                      if key.startswith("merchant_") and key.split("_")[-1].isdigit()})

    rows: list[dict] = []
    skipped = 0
    for index in indexes:
        if not form.get(f"include_{index}"):
            continue
        merchant = (form.get(f"merchant_{index}") or "").strip()
        amount_cents = parsing.parse_money_input(form.get(f"amount_{index}") or "")
        occurred_on = parsing.parse_date_input(form.get(f"date_{index}") or "")
        if not merchant or amount_cents is None or not occurred_on:
            skipped += 1
            continue

        category = (form.get(f"category_{index}") or "").strip() or categorize_mod.OTHER
        custom = (form.get(f"category_new_{index}") or "").strip()
        if custom:
            category = custom
        occurred_time = (form.get(f"time_{index}") or "").strip() or None

        rows.append({
            "occurred_on": occurred_on,
            "occurred_time": occurred_time,
            "merchant": merchant,
            "amount_cents": amount_cents,
            "currency": (form.get(f"currency_{index}") or config.CURRENCY).strip(),
            "category": category,
            "notes": (form.get(f"notes_{index}") or "").strip() or None,
            "import_id": import_id,
            "raw_line": (form.get(f"raw_{index}") or "").strip() or None,
        })

        # Learn only from genuine corrections, not from accepted guesses.
        if category != (form.get(f"suggested_{index}") or "").strip():
            categorize_mod.learn(merchant, category)

    saved = db.insert_transactions(rows)
    db.set_import_status(import_id, "saved" if saved else "discarded")

    notice = f"Saved {saved} transaction(s)."
    if skipped:
        notice += f" Skipped {skipped} incomplete row(s)."
    return _redirect("/", notice=notice)


@app.post("/imports/{import_id}/delete")
def delete_import(import_id: int):
    filename = db.delete_import(import_id)
    if filename:
        (config.UPLOAD_DIR / filename).unlink(missing_ok=True)
    return _redirect("/imports", notice="Import deleted.")


@app.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request):
    return _render(request, "imports.html", imports=db.list_imports())


@app.get("/imports/{import_id}/image")
def import_image(import_id: int):
    record = db.get_import(import_id)
    if record is None:
        return _redirect("/imports", error="Unknown import.")
    # Resolve through the DB record so no user-supplied path ever reaches disk.
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

    category = (form.get("category") or "").strip() or categorize_mod.categorize(
        merchant, amount_cents)
    db.insert_transactions([{
        "occurred_on": occurred_on,
        "occurred_time": (form.get("time") or "").strip() or None,
        "merchant": merchant,
        "amount_cents": amount_cents,
        "currency": config.CURRENCY,
        "category": category,
        "notes": (form.get("notes") or "").strip() or None,
        "import_id": None,
        "raw_line": None,
    }])
    return _redirect("/", notice="Transaction added.")


@app.get("/transactions/{tx_id}/edit", response_class=HTMLResponse)
def edit_transaction_form(request: Request, tx_id: int):
    tx = db.get_transaction(tx_id)
    if tx is None:
        return _redirect("/", error="That transaction no longer exists.")
    return _render(request, "edit.html", tx=tx,
                   all_categories=sorted(set(categorize_mod.CATEGORIES)
                                         | set(db.known_categories())))


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
        notes=(form.get("notes") or "").strip() or None,
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
