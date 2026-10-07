"""`lingua sources check-updates`, against publishers that answer from a dict.

Offline like the rest of the suite: every publisher here is a canned response,
shaped like what the real one returned when the command was written.
"""

from __future__ import annotations

import json
from datetime import date

from typer.testing import CliRunner

from lingua_oracle.cli import app as cli_app
from lingua_oracle.keys.builders import freshness as F

TODAY = date(2026, 10, 7)
OK_HEADERS = {"content-type": "text/html"}


def answers(mapping: dict[str, F.Response]):
    """A fetch that answers by URL prefix and refuses anything else."""
    def fetch(url: str) -> F.Response:
        for prefix, resp in mapping.items():
            if url.startswith(prefix):
                return resp
        raise ConnectionError(url)
    return fetch


def page(text: str) -> F.Response:
    return F.Response(200, OK_HEADERS, text.encode())


def as_json(payload: dict) -> F.Response:
    return F.Response(200, {"content-type": "application/json"},
                      json.dumps(payload).encode())


WAF = F.Response(202, {"x-amzn-waf-action": "challenge"}, b"")
FORBIDDEN = F.Response(403, OK_HEADERS, b"<h1>403 ERROR</h1>")


def sparql(*celex: str) -> F.Response:
    return as_json({"results": {"bindings": [{"celex": {"value": c}} for c in celex]}})


# -- refusals ----------------------------------------------------------------------

def test_a_waf_challenge_is_named_as_one():
    assert F.refusal(WAF) == "bot challenge (HTTP 202, AWS WAF)"


def test_a_403_is_a_refusal_and_a_200_is_not():
    assert "HTTP 403" in F.refusal(FORBIDDEN)
    assert F.refusal(page("<p>hello</p>")) is None


# -- EU ----------------------------------------------------------------------------

def test_the_current_eu_version_is_the_latest_not_after_today():
    fetch = answers({F.CELLAR_SPARQL: sparql(
        "02008R1272-20260501", "02008R1272-20260701", "02008R1272-20270101",
        "32008R1272")})
    rows = F.check_eu(fetch, TODAY)
    assert [r.up_to_date for r in rows] == [F.YES, F.YES]
    assert "current consolidated version 01/07/2026" in rows[0].publisher
    assert "applying later: 01/01/2027" in rows[0].publisher
    assert "already published" in rows[0].note


def test_a_newer_eu_version_than_ours_is_not_up_to_date():
    fetch = answers({F.CELLAR_SPARQL: sparql("02008R1272-20260701",
                                             "02008R1272-20260901")})
    rows = F.check_eu(fetch, TODAY)
    assert rows[0].up_to_date == F.NO
    assert "01/09/2026" in rows[0].publisher


def test_an_unreadable_eu_list_is_checked_by_hand_on_eur_lex():
    rows = F.check_eu(answers({F.CELLAR_SPARQL: WAF}), TODAY)
    assert rows[0].up_to_date == F.BY_HAND
    assert rows[0].url == F.EUR_LEX_CLP
    assert "bot challenge" in rows[0].publisher


# -- GB MCL ------------------------------------------------------------------------

LOG = [
    {},
    {"A": "Version", "B": "Changes", "C": "Date"},
    {"A": "1", "B": "First edition", "C": "44196"},
    {"A": "1.1000000000000001", "B": "Update to correct errors"},
    {"B": "Entry added: Index no. 000-000-00-0"},
    {"A": "7", "B": "Seventh edition. Updated.", "C": "45916"},
    {"B": "Eighth version. Note deleted."},
]


def test_the_version_log_names_its_last_version_in_words():
    assert F.latest_mcl_version(LOG) == "8th version"


def test_a_numbered_version_is_read_from_column_a():
    assert F.latest_mcl_version(LOG[:4]) == "version 1.1"
    assert F.latest_mcl_version(LOG[:6]) == "7th version"


def test_the_hse_page_links_its_spreadsheet():
    html = '<a href="../assets/docs/mcl-list.xlsx">The GB MCL List</a>'
    assert F.mcl_link(html) == ("https://www.hse.gov.uk/chemical-classification/"
                                "assets/docs/mcl-list.xlsx")


def _gb_mcl(monkeypatch, tmp_path, published_version):
    # No local file, as on a fresh clone: the recorded version stands in.
    monkeypatch.setenv("LINGUA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(F, "mcl_version_of", lambda path: published_version)
    fetch = answers({
        F.HSE_MCL_PAGE: page('<a href="../assets/docs/mcl-list.xlsx">list</a>'),
        "https://www.hse.gov.uk/chemical-classification/assets/": page("xlsx"),
    })
    return F.check_gb_mcl(fetch)


def test_the_same_mcl_version_is_up_to_date(monkeypatch, tmp_path):
    row = _gb_mcl(monkeypatch, tmp_path, "8th version")
    assert (row.held, row.up_to_date) == ("8th version", F.YES)


def test_a_newer_mcl_version_is_not(monkeypatch, tmp_path):
    row = _gb_mcl(monkeypatch, tmp_path, "9th version")
    assert row.up_to_date == F.NO
    assert row.publisher.startswith("9th version")


def test_an_hse_page_without_a_spreadsheet_is_checked_by_hand():
    row = F.check_gb_mcl(answers({F.HSE_MCL_PAGE: page("<p>moved</p>")}))
    assert row.up_to_date == F.BY_HAND
    assert "links no spreadsheet" in row.publisher


# -- Australia ---------------------------------------------------------------------

def test_hcis_is_flagged_after_ninety_days():
    assert F.check_hcis(TODAY).up_to_date == F.YES
    assert F.check_hcis(date(2027, 1, 5)).up_to_date == F.YES
    late = F.check_hcis(date(2027, 1, 6))
    assert late.up_to_date == F.NO
    assert "91 days old" in late.publisher


# -- Canada ------------------------------------------------------------------------

HPR_HTML = ("<p>Regulations are current to 2026-09-21 and last amended on "
            "<span>2022-12-15</span>. Previous Versions</p>")


def test_the_hpr_dates_are_read_from_the_page():
    assert F.hpr_dates(HPR_HTML) == ("2026-09-21", "2022-12-15")


def test_a_later_current_to_date_alone_is_not_a_change():
    html = HPR_HTML.replace("2026-09-21", "2026-12-01")
    row = F.check_hpr(answers({F.HPR_PAGE: page(html)}))
    assert row.up_to_date == F.YES


def test_a_new_hpr_amendment_is_not_up_to_date():
    html = HPR_HTML.replace("2022-12-15", "2026-11-30")
    row = F.check_hpr(answers({F.HPR_PAGE: page(html)}))
    assert row.up_to_date == F.NO
    assert "2026-11-30" in row.publisher


# -- OSHA --------------------------------------------------------------------------

def ecfr(*days: str) -> F.Response:
    return as_json({"content_versions": [
        {"identifier": "1910.1200", "amendment_date": d} for d in days]})


def test_osha_is_up_to_date_when_our_copy_postdates_the_last_amendment():
    rows = F.check_osha(answers({F.ECFR_VERSIONS: ecfr("2024-05-20", "2026-02-13")}))
    assert [r.up_to_date for r in rows] == [F.YES, F.YES]
    assert "last amended 2026-02-13" in rows[0].publisher


def test_an_amendment_after_our_copy_is_not():
    rows = F.check_osha(answers({F.ECFR_VERSIONS: ecfr("2026-12-01")}))
    assert [r.up_to_date for r in rows] == [F.NO, F.NO]


def test_osha_unreachable_gives_the_osha_page_to_check():
    rows = F.check_osha(answers({}))
    assert rows[0].up_to_date == F.BY_HAND
    assert rows[0].url.startswith("https://www.osha.gov/")


# -- all of it ---------------------------------------------------------------------

def test_nothing_reachable_still_gives_every_row_and_a_page_for_each():
    rows = F.check_updates(answers({}), TODAY)
    assert len(rows) == 11
    for row in rows:
        assert row.url.startswith("https://"), row.source
        if row.up_to_date == F.BY_HAND:
            assert row.publisher.startswith("not checked automatically"), row.source


def test_a_readable_unece_page_reports_the_newest_revision_it_mentions():
    html = "<p>GHS Rev.10 (2023)</p><p>GHS Rev.11 (2025)</p>"
    rows = F.check_updates(answers({F.UNECE_GHS_PAGE: page(html)}), TODAY)
    ghs = next(r for r in rows if r.source.startswith("UN GHS (un_ghs"))
    assert ghs.publisher == "newest revision mentioned: Rev.11"
    assert ghs.up_to_date == F.BY_HAND


def test_the_table_has_the_four_columns_and_the_pages_under_it():
    text = F.table([F.Row("Some source", "v1", "v2", F.NO,
                          "https://example.org/", "a note")])
    assert text.splitlines()[0] == ("| | source | we hold | publisher shows "
                                    "| up to date? |")
    assert "| [1] | Some source | v1 | v2 | NO |" in text
    assert "[1] Some source: https://example.org/" in text
    assert "    a note" in text


def test_the_command_prints_the_table(monkeypatch):
    monkeypatch.setattr(F, "check_updates", lambda: [
        F.Row("Some source", "v1", "v1", F.YES, "https://example.org/")])
    result = CliRunner().invoke(cli_app, ["sources", "check-updates"])
    assert result.exit_code == 0
    assert "| [1] | Some source | v1 | v1 | yes |" in result.output
