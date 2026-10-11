"""The scenario matrix and the document situations as the pages show them."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lingua_oracle.api.app import app
from lingua_oracle.pipeline import check_pdf
from lingua_oracle.reference import scenarios
from lingua_oracle.report import sections
from lingua_oracle.report.render import render_html
from tests.make_fixtures import Sheet


def _scanned(tmp_path):
    import pymupdf

    picture = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), 0)
    picture.clear_with(200)
    doc = pymupdf.open()
    doc.new_page().insert_image(pymupdf.Rect(50, 50, 300, 300), pixmap=picture)
    doc.save(tmp_path / "scan.pdf")
    return check_pdf(str(tmp_path / "scan.pdf"))


def test_a_scanned_pdf_says_not_checked_and_never_ready(tmp_path):
    report = _scanned(tmp_path)
    page = sections.build(report, "", "auto")
    assert page.release == "Not checked" and page.sections == []
    html = render_html(report)
    assert "This PDF has no readable text (scanned) — not checked" in html
    assert "Ready to release" not in html


def test_several_products_lead_the_banner(tmp_path):
    sheet = Sheet(tmp_path / "two.pdf")
    for product in ("First synthetic product", "Second synthetic product"):
        sheet.line("SECTION 1: Identification of the substance/mixture", bold=True, size=11)
        sheet.line(f"Product name: {product}")
    sheet.save()
    report = check_pdf(str(tmp_path / "two.pdf"), "eu_clp", "en")
    page = sections.build(report, "EU CLP", "flag")
    assert page.detail.startswith("This PDF seems to hold 2 safety data sheets")


def test_the_coverage_page_shows_every_scenario_with_its_status():
    body = TestClient(app).get("/coverage").text
    assert "What Lingua can and cannot judge" in body
    for item in scenarios.load():
        assert f'data-scenario="{item["id"]}"' in body
    assert body.count("Partial") >= sum(1 for s in scenarios.load() if s["status"] == "partial")
    assert "OCR is a later decision." in body
