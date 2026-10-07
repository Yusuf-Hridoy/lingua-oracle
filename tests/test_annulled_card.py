"""A sheet that still prints EUH211 or EUH212 is told why it was not checked.

Not "our records are incomplete", which is what not checked otherwise means:
the statement was annulled with Delegated Regulation (EU) 2020/217 as regards
titanium dioxide, and the law no longer requires it.
"""

from __future__ import annotations

from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report.render import render_html
from tests.make_fixtures import EU_H, EU_P, write_sds

ANNULLED = ("Not checked: annulled by the General Court (titanium dioxide "
            "ruling) — no longer required.")


def _sheet(tmp_path, supplemental):
    return str(write_sds(tmp_path / "titanium_dioxide_mixture.pdf",
                         regulation="eu_clp", language="en", h_codes=EU_H,
                         p_codes=EU_P, supplemental=supplemental))


def test_euh211_and_euh212_say_they_were_annulled_and_cite_the_notice(tmp_path):
    report = check_pdf(_sheet(tmp_path, ["EUH211", "EUH212"]), "eu_clp", "en")
    for code in ("EUH211", "EUH212"):
        finding = next(f for f in report.findings if f.code == code)
        assert finding.message.startswith(ANNULLED)
        assert "C/2025/6670" in finding.message
        assert "C-71/23 P" in finding.message
        assert "records are incomplete" not in finding.message
        verdict = next(v for v in report.statements if v.code == code)
        assert verdict.status == "not_checked"
        assert verdict.why.startswith(ANNULLED)


def test_the_card_shows_it(tmp_path):
    page = render_html(check_pdf(_sheet(tmp_path, ["EUH211"]), "eu_clp", "en"))
    assert "annulled by the General Court (titanium dioxide ruling)" in page
    assert "records are incomplete" not in page


def test_another_supplemental_statement_is_unaffected(tmp_path):
    report = check_pdf(_sheet(tmp_path, ["EUH066"]), "eu_clp", "en")
    assert not any("annulled" in f.message for f in report.findings)
