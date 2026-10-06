"""Nothing a document says may become markup in the report.

The report prints text taken out of an uploaded PDF, and a PDF is a file
somebody else wrote. Jinja's `select_autoescape(["html"])` looks at the final
suffix, and every template here is named "x.html.j2" - so autoescaping never
fired and that text went out raw.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lingua_oracle.api.app import app
from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report.render import render_html, save
from tests.conftest import pdf

SCRIPT = "<script>alert(1)</script>"
BOLD = "<b>x</b>"


@pytest.fixture(scope="module")
def report():
    return check_pdf(pdf("pattern_markup_in_text"), "eu_clp")


def test_the_document_really_does_carry_markup(report):
    """If the fixture stops carrying it, the tests below prove nothing."""
    found = " ".join(s.found for s in report.statements)
    assert SCRIPT in found
    assert BOLD in found


def test_the_rendered_report_shows_it_as_text(report):
    body = render_html(report)
    assert SCRIPT not in body
    assert BOLD not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "&lt;b&gt;x&lt;/b&gt;" in body


def test_the_saved_file_shows_it_as_text(report, tmp_path):
    _json_path, html_path = save(report, tmp_path)
    body = html_path.read_text(encoding="utf-8")
    assert SCRIPT not in body
    assert BOLD not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


def test_the_report_still_renders_its_own_markup(report):
    """Escaping everything would also kill the diff highlighting."""
    body = render_html(report)
    assert '<mark class="diff">' in body
    assert "<style>" in body
    assert ".verdict" in body          # the stylesheet survived unescaped


def test_the_served_report_shows_it_as_text(report):
    from lingua_oracle.report.render import save as save_report

    save_report(report)
    client = TestClient(app)
    body = client.get(f"/reports/{report.id}").text
    assert SCRIPT not in body
    assert "&lt;script&gt;" in body


def test_a_file_name_is_escaped_in_the_history_list():
    """The name of an uploaded file is text somebody else chose."""
    from lingua_oracle.api import app as app_module

    client = TestClient(app)
    rows = [{"id": "x", "file_name": SCRIPT, "regulation": "EU CLP",
             "language": "English", "release": "Ready to release",
             "pill": "ok", "created_at": "2026-01-01T00:00"}]
    original = app_module.recent_reports
    app_module.recent_reports = lambda limit=10: rows
    try:
        body = client.get("/history").text
    finally:
        app_module.recent_reports = original
    assert SCRIPT not in body
    assert "&lt;script&gt;" in body


@pytest.mark.parametrize("name", [
    "report.html.j2", "ingredients.html.j2",
])
def test_every_report_template_escapes(name):
    from lingua_oracle.report.render import _environment

    environment = _environment()
    autoescape = environment.autoescape
    assert (autoescape is True or autoescape(name)), name


@pytest.mark.parametrize("name", [
    "index.html.j2", "list.html.j2", "ingredients.html.j2",
    "ingredients_progress.html.j2",
])
def test_every_application_template_escapes(name):
    from lingua_oracle.api.app import templates

    autoescape = templates.env.autoescape
    assert (autoescape is True or autoescape(name)), name
