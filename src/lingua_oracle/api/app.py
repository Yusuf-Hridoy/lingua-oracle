"""FastAPI app: an upload page plus the check/compare/report endpoints.

Reports are stored as files under reports/. There is no database.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from lingua_oracle.api.coverage import key_coverage, recent_reports
from lingua_oracle.detect.language import language_name
from lingua_oracle.detect.regulation import RegulationUndetermined
from lingua_oracle.models import Report
from lingua_oracle.pipeline import check_pdf, compare_pdfs
from lingua_oracle.registry import load_registry
from lingua_oracle.report.render import load as load_report
from lingua_oracle.report.render import render_html, save

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).resolve().parents[1] / "report" / "static"

app = FastAPI(title="Lingua Oracle", version="0.1.0")
templates = Jinja2Templates(directory=str(TEMPLATES))
# One stylesheet for both pages. The upload page links it from here; the report
# inlines it, because a saved report has to render as a single file.
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def _languages() -> list[tuple[str, str]]:
    """Every language any regulation publishes in, as (tag, name)."""
    seen: set[str] = set()
    for reg in load_registry().regulations.values():
        seen.update(reg.official_languages)
    return [(tag, language_name(tag)) for tag in sorted(seen)]


def _save_upload(upload: UploadFile) -> Path:
    if not (upload.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    tmp = Path(tempfile.mkdtemp(prefix="lingua-")) / Path(upload.filename).name
    with tmp.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return tmp


class _Explained(Exception):
    """An error with something a person can read and act on."""

    def __init__(self, message: str, *, focus: str = "", suggest: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.focus = focus
        #: A regulation to preselect. Offered, never applied: the reader has to
        #: press the button before anything is checked against it.
        self.suggest = suggest


def _run(fn, *args, **kwargs) -> Report:
    try:
        return fn(*args, **kwargs)
    except RegulationUndetermined as undetermined:
        # The detail on this exception names regulation ids and a CLI flag.
        # Neither means anything in a browser.
        raise _Explained(
            _ask_message(undetermined),
            focus="regulation",
            suggest=undetermined.suggestion,
        ) from None
    except Exception as exc:  # noqa: BLE001 - the page must never show a stack
        raise _Explained(
            f"We couldn\u2019t read that file: {exc}" if str(exc)
            else "We couldn\u2019t read that file."
        ) from None


def _ask_message(undetermined: RegulationUndetermined) -> str:
    """What to tell a reader when the sheet does not say which regulation.

    Where the address points somewhere, say so and say it is the address
    talking - the reader can then confirm or correct it in one look.
    """
    if undetermined.only_says_ghs:
        opening = "This sheet only says \u2018GHS\u2019, which every sheet does."
    else:
        opening = "We couldn\u2019t tell which regulation this sheet follows."
    if not undetermined.suggestion:
        return f"{opening} Choose one and check again."
    try:
        name = load_registry().get(undetermined.suggestion).display_name
    except KeyError:
        return f"{opening} Choose one and check again."
    return (f"{opening} It looks like {name} "
            f"({undetermined.reason}). Confirm the regulation and check again.")


def _upload_page(request: Request, *, error: str = "", focus: str = "",
                 suggest: str = "") -> HTMLResponse:
    registry = load_registry()
    return templates.TemplateResponse(
        request=request,
        name="index.html.j2",
        status_code=422 if error else 200,
        context={
            "regulations": [
                (rid, registry.get(rid).display_name) for rid in registry.ids()
            ],
            "languages": _languages(),
            "coverage": key_coverage(),
            "recent": recent_reports(),
            "error": error,
            "focus": focus,
            "suggest": suggest,
        },
    )


@app.exception_handler(_Explained)
def _explained_handler(request: Request, exc: _Explained) -> HTMLResponse:
    """Every failure a person can hit comes back as the page, not as JSON."""
    return _upload_page(request, error=exc.message, focus=exc.focus,
                        suggest=exc.suggest)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return _upload_page(request)


def _ingredient_runs() -> list[dict]:
    """Ingredient runs, shown in History beside the wording checks."""
    from lingua_oracle.api import ingredients as ing

    return ing.recent_runs(limit=50)


@app.get("/history", response_class=HTMLResponse)
def history(request: Request) -> HTMLResponse:
    """Placeholder: every saved report, newest first."""
    return templates.TemplateResponse(
        request=request, name="list.html.j2",
        context={"title": "History", "nav": "history",
                 "lede": "Every document checked on this installation.",
                 "recent": recent_reports(limit=200) + _ingredient_runs(),
                 "coverage": None},
    )


@app.get("/ingredients", response_class=HTMLResponse)
def ingredients_page(request: Request, error: str = "") -> HTMLResponse:
    """Start an ingredient check, or open a previous one."""
    from lingua_oracle.api import ingredients as ing

    return templates.TemplateResponse(
        request=request, name="ingredients.html.j2",
        context={"nav": "ingredients", "runs": ing.recent_runs(), "error": error},
    )


@app.post("/ingredients/run", response_class=HTMLResponse)
def ingredients_run(request: Request,
                    scope: str = Form("product"),
                    product_id: str = Form("")) -> HTMLResponse:
    """Begin a check on a worker thread and show its progress."""
    from lingua_oracle.api import ingredients as ing

    wanted: int | None = None
    if scope == "product":
        if not product_id.strip().isdigit():
            return ingredients_page(request, error="Give a product ID, or "
                                                   "choose the whole library.")
        wanted = int(product_id)
    progress = ing.start(scope, wanted)
    return templates.TemplateResponse(
        request=request, name="ingredients_progress.html.j2",
        context={"nav": "ingredients", "progress": progress},
    )


@app.get("/ingredients/runs/{run_id}/status")
def ingredients_status(run_id: str) -> JSONResponse:
    from lingua_oracle.api import ingredients as ing

    progress = ing.RUNS.get(run_id)
    if progress is None:
        return JSONResponse({"state": "unknown"}, status_code=404)
    return JSONResponse(progress.as_dict())


@app.get("/ingredients/runs/{run_id}", response_class=HTMLResponse)
def ingredients_report(run_id: str) -> HTMLResponse:
    from lingua_oracle.api import ingredients as ing
    from lingua_oracle.ingredients.report import render_html

    data = ing.load_run(run_id)
    if data is None:
        raise HTTPException(status_code=404, detail="no such run")
    return HTMLResponse(render_html(data, nav=True))


@app.get("/coverage", response_class=HTMLResponse)
def coverage(request: Request) -> HTMLResponse:
    """Placeholder: which official texts are on file."""
    return templates.TemplateResponse(
        request=request, name="list.html.j2",
        context={"title": "Coverage", "nav": "coverage",
                 "lede": "The official texts this installation holds.",
                 "recent": None, "coverage": key_coverage()},
    )


@app.post("/check")
def check(
    file: UploadFile = File(...),
    regulation: str | None = Form(None),
    language: str | None = Form(None),
) -> JSONResponse:
    path = _save_upload(file)
    try:
        report = _run(check_pdf, str(path), regulation or None, language or None)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    save(report)
    return JSONResponse(report.model_dump(mode="json"))


@app.post("/check/html")
def check_html(
    file: UploadFile = File(...),
    regulation: str | None = Form(None),
    language: str | None = Form(None),
) -> RedirectResponse:
    """Browser form target: check, then redirect to the HTML report."""
    path = _save_upload(file)
    try:
        report = _run(check_pdf, str(path), regulation or None, language or None)
    finally:
        shutil.rmtree(path.parent, ignore_errors=True)
    save(report)
    return RedirectResponse(url=f"/reports/{report.id}", status_code=303)


def _compare(file_a, file_b, regulation, language) -> Report:
    path_a = _save_upload(file_a)
    path_b = _save_upload(file_b)
    try:
        return _run(
            compare_pdfs, str(path_a), str(path_b), regulation or None, language or None
        )
    finally:
        shutil.rmtree(path_a.parent, ignore_errors=True)
        shutil.rmtree(path_b.parent, ignore_errors=True)


@app.post("/compare")
def compare(
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    regulation: str | None = Form(None),
    language: str | None = Form(None),
) -> RedirectResponse:
    """Browser form target: compare, then redirect to the HTML report.

    This used to answer with raw JSON, so the one flow a person was most
    likely to reach through the page was also the only one that dropped them
    into a wall of machine output. The JSON is still available at
    /compare.json for anything calling the API.
    """
    report = _compare(file_a, file_b, regulation, language)
    save(report)
    return RedirectResponse(url=f"/reports/{report.id}", status_code=303)


@app.post("/compare.json")
def compare_json(
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    regulation: str | None = Form(None),
    language: str | None = Form(None),
) -> JSONResponse:
    report = _compare(file_a, file_b, regulation, language)
    save(report)
    return JSONResponse(report.model_dump(mode="json"))


# Declared before the HTML route: Starlette matches in declaration order, and
# '/reports/{report_id}' would otherwise swallow the '.json' suffix.
@app.get("/reports/{report_id}.json")
def report_json(report_id: str) -> JSONResponse:
    report = load_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No such report.")
    return JSONResponse(report.model_dump(mode="json"))


@app.get("/reports/{report_id}", response_class=HTMLResponse)
def report_html(report_id: str) -> HTMLResponse:
    report = load_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No such report.")
    return HTMLResponse(render_html(report))
