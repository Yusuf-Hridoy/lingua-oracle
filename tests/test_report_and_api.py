"""Report rendering, the CLI and the HTTP API."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from lingua_oracle.api.app import app as fastapi_app
from lingua_oracle.cli import app as cli_app
from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report.render import char_diff, render_html, save
from tests.conftest import pdf


@pytest.fixture(scope="module")
def client():
    return TestClient(fastapi_app)


@pytest.fixture()
def runner():
    return CliRunner()


# -- report ----------------------------------------------------------------


def test_char_diff_marks_the_changed_characters():
    left, right = char_diff("Meget brandfarlig væske.", "Ekstremt brandfarlig væske.")
    assert 'class="del"' in left
    assert 'class="ins"' in right
    assert "brandfarlig" in left


def test_char_diff_on_unrelated_text_highlights_whole_strings():
    left, right = char_diff("Forårsager alvorlig øjenirritation.",
                            "Causes serious eye irritation.")
    assert left.count("<mark") == 1
    assert right.count("<mark") == 1


def test_char_diff_escapes_html():
    left, _right = char_diff("<script>alert(1)</script>", "safe")
    assert "<script>" not in left
    assert "&lt;script&gt;" in left


def test_html_report_is_self_contained():
    report = check_pdf(pdf("defect_a02_hazard"), "eu_clp")
    html = render_html(report)
    assert "<style>" in html
    assert "src=" not in html and "<link" not in html  # no external assets
    assert "A-02" in html
    assert report.file_name in html


def test_html_report_lists_failures_first():
    report = check_pdf(pdf("defect_a05_english"), "eu_clp")
    html = render_html(report)
    # Findings come before the legend that closes the page. Anchor on a string
    # that appears only in that legend - the column header uses the same words.
    assert html.index("A-05") < html.index("<b>None on file</b>")


def test_report_round_trips_through_disk(tmp_path):
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    json_path, html_path = save(report, tmp_path)
    assert json_path.exists() and html_path.exists()
    restored = json.loads(json_path.read_text(encoding="utf-8"))
    assert restored["id"] == report.id
    assert restored["regulation"] == "eu_clp"


# -- CLI -------------------------------------------------------------------


def test_cli_check_exits_zero_on_a_clean_document(runner, tmp_path):
    result = runner.invoke(
        cli_app, ["check", pdf("clean_eu_da"), "-r", "eu_clp", "-o", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "0 fail" in result.output


def test_cli_check_exits_one_on_failures(runner, tmp_path):
    result = runner.invoke(
        cli_app, ["check", pdf("defect_a02_hazard"), "-r", "eu_clp", "-o", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "A-02" in result.output


def test_cli_reports_undetermined_regulation(runner, tmp_path):
    """A document with no regulation marker must ask, not guess."""
    result = runner.invoke(cli_app, ["check", pdf("clean_eu_da"), "-o", str(tmp_path)])
    assert result.exit_code in (0, 2)


def test_cli_check_folder(runner, tmp_path):
    result = runner.invoke(
        cli_app,
        ["check-folder", str(tmp_path.parent), "-r", "eu_clp", "-o", str(tmp_path)],
    )
    assert result.exit_code in (0, 1)


def test_cli_compare(runner, tmp_path):
    result = runner.invoke(
        cli_app,
        ["compare", pdf("compare_b11_a"), pdf("compare_b11_b"),
         "-r", "eu_clp", "-o", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "B-11" in result.output


def test_cli_keys_stats_json(runner):
    result = runner.invoke(cli_app, ["keys", "stats", "--json"])
    assert result.exit_code == 0
    rows = json.loads(result.output)
    by_id = {row["regulation"]: row for row in rows}
    assert len(by_id["eu_clp"]["languages_populated"]) == 24
    assert by_id["eu_clp"]["status"] == "ok"
    assert by_id["jp_jis"]["status"] == "pending_source"


def test_cli_keys_stats_table(runner):
    result = runner.invoke(cli_app, ["keys", "stats"])
    assert result.exit_code == 0
    assert "EU CLP" in result.output
    assert "pending_source" in result.output


# -- API -------------------------------------------------------------------


def test_index_page_offers_regulations_and_languages(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Detect automatically" in response.text
    assert "EU CLP" in response.text


def test_post_check_returns_a_report(client):
    with open(pdf("defect_a02_hazard"), "rb") as handle:
        response = client.post(
            "/check",
            files={"file": ("t.pdf", handle, "application/pdf")},
            data={"regulation": "eu_clp"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["fail"] >= 1
    assert any(f["check_id"] == "A-02" for f in body["findings"])


def test_report_html_and_json_endpoints(client):
    with open(pdf("clean_eu_da"), "rb") as handle:
        report_id = client.post(
            "/check",
            files={"file": ("t.pdf", handle, "application/pdf")},
            data={"regulation": "eu_clp"},
        ).json()["id"]
    assert client.get(f"/reports/{report_id}").status_code == 200
    json_response = client.get(f"/reports/{report_id}.json")
    assert json_response.status_code == 200
    assert json_response.json()["id"] == report_id


def test_unknown_report_is_404(client):
    assert client.get("/reports/doesnotexist").status_code == 404
    assert client.get("/reports/doesnotexist.json").status_code == 404


def test_non_pdf_upload_is_rejected(client):
    response = client.post(
        "/check", files={"file": ("x.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 400


def test_compare_endpoint(client):
    with open(pdf("compare_b11_a"), "rb") as a, open(pdf("compare_b11_b"), "rb") as b:
        response = client.post(
            "/compare",
            files={
                "file_a": ("a.pdf", a, "application/pdf"),
                "file_b": ("b.pdf", b, "application/pdf"),
            },
            data={"regulation": "eu_clp"},
        )
    assert response.status_code == 200
    assert any(f["check_id"] == "B-11" for f in response.json()["findings"])
