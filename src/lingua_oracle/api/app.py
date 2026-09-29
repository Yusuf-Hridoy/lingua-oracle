"""FastAPI app: an upload page plus the check/compare/report endpoints.

Reports are stored as files under reports/. There is no database.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from lingua_oracle.detect.regulation import RegulationUndetermined
from lingua_oracle.models import Report
from lingua_oracle.pipeline import check_pdf, compare_pdfs
from lingua_oracle.registry import load_registry
from lingua_oracle.report.render import load as load_report
from lingua_oracle.report.render import render_html, save

TEMPLATES = Path(__file__).parent / "templates"

app = FastAPI(title="Lingua Oracle", version="0.1.0")
templates = Jinja2Templates(directory=str(TEMPLATES))


def _languages() -> list[str]:
    seen: set[str] = set()
    for reg in load_registry().regulations.values():
        seen.update(reg.official_languages)
    return sorted(seen)


def _save_upload(upload: UploadFile) -> Path:
    if not (upload.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")
    tmp = Path(tempfile.mkdtemp(prefix="lingua-")) / Path(upload.filename).name
    with tmp.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return tmp


def _run(fn, *args, **kwargs) -> Report:
    try:
        return fn(*args, **kwargs)
    except RegulationUndetermined as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    registry = load_registry()
    return templates.TemplateResponse(
        request=request,
        name="index.html.j2",
        context={
            "regulations": [
                (rid, registry.get(rid).display_name) for rid in registry.ids()
            ],
            "languages": _languages(),
        },
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


@app.post("/compare")
def compare(
    file_a: UploadFile = File(...),
    file_b: UploadFile = File(...),
    regulation: str | None = Form(None),
    language: str | None = Form(None),
) -> JSONResponse:
    path_a = _save_upload(file_a)
    path_b = _save_upload(file_b)
    try:
        report = _run(
            compare_pdfs, str(path_a), str(path_b), regulation or None, language or None
        )
    finally:
        shutil.rmtree(path_a.parent, ignore_errors=True)
        shutil.rmtree(path_b.parent, ignore_errors=True)
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
