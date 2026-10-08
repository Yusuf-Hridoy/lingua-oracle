"""The 23rd ATP: adopted, not yet applying, and taken into account by date.

Delegated Regulation (EU) 2025/1222 applies from 1 February 2027 and may be
followed now. Before that date a sheet meeting either Table 3 in force or Table
3 as amended meets Annex VI, and where it meets only the first it is told what
changes; from the date on, the amended entry binds. The entries here are real -
they are public law - and nothing is fetched: the amendment is committed data.
"""

from __future__ import annotations

from datetime import date

import pytest
from lxml import html as LH

from lingua_oracle.ingredients import report as ingredient_report
from lingua_oracle.ingredients.compare import Status, check_ingredient, check_ingredient_on
from lingua_oracle.ingredients.report import SubstanceResult, Use
from lingua_oracle.keys.builders import annex_vi, sources
from lingua_oracle.mixture import section as mixture
from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report.render import render_html
from lingua_oracle.substances.upcoming import for_list
from tests.conftest import pdf

BEFORE = date(2027, 1, 31)
ON = date(2027, 2, 1)

#: 015-012-00-1, tetraphosphorus trisulphide. In force: Flam. Sol. 2,
#: Water-react. 1, Acute Tox. 4 *, Aquatic Acute 1. As the ATP replaces it:
#: Flam. Sol. 1, Self-heat. 1, Acute Tox. 4*.
P4S3 = "1314-85-8"
IN_FORCE = ["H228", "H260", "H302", "H400"]
AMENDED = ["H228", "H251", "H302"]


@pytest.fixture(scope="module")
def table():
    return annex_vi.load_table()


@pytest.fixture(scope="module")
def upcoming():
    return for_list("annex_vi")


# -- the data ---------------------------------------------------------------------

def test_the_amendment_is_read_from_the_act_with_its_own_date():
    amendment = annex_vi.load_upcoming()
    assert amendment.act == "32025R1222"
    assert amendment.applies_from == ON
    assert amendment.applies_from_text == "It shall apply from 1 February 2027."
    assert (len(amendment.inserted), len(amendment.replaced)) == (22, 10)


def test_the_replacement_for_015_012_00_1_is_the_one_the_act_prints():
    amendment = annex_vi.load_upcoming()
    entry = next(e for e in amendment.replaced if e.index_no == "015-012-00-1")
    assert entry.hazard_classes == ["Flam. Sol. 1", "Self-heat. 1", "Acute Tox. 4*"]
    assert entry.h_codes == AMENDED
    assert entry.source_ref.endswith("(32025R1222)")


def test_table_3_as_amended_swaps_ten_entries_and_adds_twenty_two(table, upcoming):
    assert len(upcoming.table.entries) == len(table.entries) + 22
    entry = next(e for e in upcoming.table.entries if e.index_no == "015-012-00-1")
    assert entry.h_codes == AMENDED
    assert P4S3 in upcoming.changed_cas


SYNTHETIC_ACT = """<html><body>
<table><tr><td>(1)</td><td><p>the following entries are inserted following the
  consecutive order of the index numbers:</p>
  <table>
   <tr><td>Index No</td><td>Chemical Name</td><td>EC No</td><td>CAS No</td>
       <td>Classification</td><td>Labelling</td><td>Specific Conc. Limits</td>
       <td>Notes</td></tr>
   <tr><td><p>‘999-001-00-1</p></td><td><p>examplium</p></td>
       <td><p>900-001-1</p></td><td><p>11-22-3</p></td><td><p>Carc. 2</p></td>
       <td><p>H351</p></td><td><p>GHS08 Wng</p></td><td><p>H351</p></td>
       <td></td><td><p>M = 10’</p></td><td></td></tr>
  </table></td></tr></table>
<table><tr><td>(2)</td><td><p>the entries corresponding to index numbers
  999-002-00-7, 999-003-00-2 are replaced by the following:</p>
  <table>
   <tr><td>Index No</td><td>Chemical Name</td><td>EC No</td><td>CAS No</td>
       <td>Hazard Class</td><td>Hazard statement</td><td>Pictogram</td>
       <td>Hazard statement</td><td>Suppl.</td><td>Limits</td><td>Notes</td></tr>
   <tr><td><p>‘999-002-00-7</p></td><td><p>fictionate</p></td>
       <td><p>900-002-2</p></td><td><p>22-33-4</p></td><td><p>Repr. 1B</p></td>
       <td><p>H360FD</p></td><td><p>GHS08 Dgr</p></td><td><p>H360FD</p></td>
       <td></td><td></td><td><p>T’</p></td></tr>
  </table></td></tr></table>
<p>It shall apply from 1 February 2027. However, suppliers may ...</p>
</body></html>"""


def test_an_amending_act_is_parsed_point_by_point_without_its_quotation_marks():
    doc = LH.fromstring(SYNTHETIC_ACT)
    inserted, replaced, issues = annex_vi.parse_amendment(doc, celex="3TEST")
    assert [e.index_no for e in inserted] == ["999-001-00-1"]
    assert inserted[0].limits == ["M = 10"]
    assert [e.index_no for e in replaced] == ["999-002-00-7"]
    assert replaced[0].h_codes == ["H360FD"]
    assert replaced[0].notes == ["T"]
    # Point (2) names an entry it gives no row for: said, not guessed.
    assert issues == ["999-003-00-2: named as replaced, but no row given for it"]
    assert annex_vi.applies_from(doc) == (ON, "It shall apply from 1 February 2027.")


# -- the ingredient check, 015-012-00-1, before and on 1 February 2027 ------------

def test_before_the_date_the_entry_in_force_passes_and_the_change_is_said(table, upcoming):
    verdict = check_ingredient_on(P4S3, IN_FORCE, table, upcoming=upcoming, on=BEFORE)
    assert verdict.status is Status.OK
    note = "From 1 February 2027 Annex VI requires H251 for this substance (23rd ATP)."
    assert verdict.upcoming == [note]
    assert any(f.status is Status.INFO and f.message == note for f in verdict.findings)


def test_before_the_date_the_amended_entry_passes_too(table, upcoming):
    verdict = check_ingredient_on(P4S3, AMENDED, table, upcoming=upcoming, on=BEFORE)
    assert verdict.status is Status.OK
    assert verdict.source_ref.endswith("(32025R1222)")
    assert verdict.upcoming and verdict.upcoming[0].startswith(
        "Meets Annex VI as amended by the 23rd ATP")
    # Without the amendment taken into account, the same sheet is a fault.
    assert check_ingredient(P4S3, AMENDED, table).status is Status.FIX


def test_on_the_date_the_amended_entry_binds(table, upcoming):
    old = check_ingredient_on(P4S3, IN_FORCE, table, upcoming=upcoming, on=ON)
    assert old.status is Status.FIX
    assert old.missing_codes == ["H251"]
    new = check_ingredient_on(P4S3, AMENDED, table, upcoming=upcoming, on=ON)
    assert new.status is Status.OK
    assert new.upcoming == []


def test_a_sheet_meeting_neither_is_judged_by_the_entry_in_force(table, upcoming):
    verdict = check_ingredient_on(P4S3, ["H228"], table, upcoming=upcoming, on=BEFORE)
    assert verdict.status is Status.FIX
    assert verdict.missing_codes == ["H260", "H302", "H400"]
    assert "requires H251, H302" in verdict.upcoming[0]


def test_a_substance_the_atp_adds_is_not_checked_until_it_applies(table, upcoming):
    ozone = "10028-15-6"
    before = check_ingredient_on(ozone, [], table, upcoming=upcoming, on=BEFORE)
    assert before.status is Status.NOT_CHECKED
    assert before.upcoming[0].startswith("From 1 February 2027 Annex VI requires H270")
    after = check_ingredient_on(ozone, [], table, upcoming=upcoming, on=ON)
    assert after.status is Status.FIX
    assert "H270" in after.missing_codes


def test_a_substance_the_atp_does_not_touch_is_checked_once(table, upcoming):
    trimethyl_borate = "121-43-7"
    plain = check_ingredient(trimethyl_borate, ["H226"], table)
    dated = check_ingredient_on(trimethyl_borate, ["H226"], table,
                                upcoming=upcoming, on=BEFORE)
    assert (dated.status, dated.missing_codes, dated.upcoming) == (
        plain.status, plain.missing_codes, [])


# -- the mixture --------------------------------------------------------------------

def _mixture(rows, upcoming, table, on, stated=None):
    return mixture.build(rows, [], [], "eu_clp", table, stated_override=stated,
                         upcoming=upcoming, on=on)


def test_a_class_the_atp_removes_passes_before_the_date(table, upcoming):
    rows = [{"cas": P4S3, "name": None, "h_codes": [], "concentration": "50 %"}]
    before = _mixture(rows, upcoming, table, BEFORE)
    aquatic = [r for r in before.results
               if r["family"] == "Hazardous to the aquatic environment, short-term"]
    assert all(r["verdict"] != "inconsistent" for r in aquatic)
    assert before.upcoming[0].startswith(
        "Hazardous to the aquatic environment, short-term: consistent with "
        "Annex VI as amended by the 23rd ATP")


def test_a_lower_specific_limit_is_said_before_and_binds_after(table, upcoming):
    # 615-008-00-5: Skin Sens. 1; H317: C >= 0,5 %  ->  Skin Sens. 1A: C >= 0,001 %
    rows = [{"cas": "4098-71-9", "name": None, "h_codes": [], "concentration": "0.1 %"}]
    before = _mixture(rows, upcoming, table, BEFORE)
    assert before.counts["inconsistent"] == 0
    assert before.upcoming == [
        "From 1 February 2027 (23rd ATP): Skin sensitisation - the calculation "
        "gives Skin Sens. 1A, inconsistent with Section 2."]
    after = _mixture(rows, upcoming, table, ON)
    assert after.counts["inconsistent"] == 1
    assert after.upcoming == []


def test_a_higher_m_factor_is_said_before_and_binds_after(table, upcoming):
    # 616-212-00-7: chronic M-factor 1 -> 10. At 3 %: Chronic 2 -> Chronic 1.
    rows = [{"cas": "55406-53-6", "name": None, "h_codes": [], "concentration": "3 %"}]
    stated = ["Aquatic Chronic 2"]
    family = "Hazardous to the aquatic environment, long-term"
    before = _mixture(rows, upcoming, table, BEFORE, stated)
    chronic = next(r for r in before.results if r["family"] == family)
    assert chronic["verdict"] == "consistent"
    assert any("gives Aquatic Chronic 1" in n for n in before.upcoming)
    after = _mixture(rows, upcoming, table, ON, stated)
    chronic = next(r for r in after.results if r["family"] == family)
    assert (chronic["verdict"], chronic["calculated_class"]) == (
        "inconsistent", "Aquatic Chronic 1")


# -- what a reader sees ---------------------------------------------------------------

def test_the_library_report_shows_what_is_coming(table, upcoming):
    verdict = check_ingredient_on(P4S3, IN_FORCE, table, upcoming=upcoming, on=BEFORE)
    run = ingredient_report.new_run(table.source)
    run.substances = [SubstanceResult(cas=P4S3, name="tetraphosphorus trisulphide",
                                      uses=[Use(product_id=1, codes=tuple(IN_FORCE),
                                                verdict=verdict)])]
    page = ingredient_report.render_html(run)
    assert "Changes coming to Annex VI" in page
    assert "From 1 February 2027 Annex VI requires H251" in page
    assert "Delegated Regulation (EU) 2025/1222 (23rd ATP), amending Annex VI " \
           "Table 3 from 01/02/2027" in page


def test_the_report_shows_the_mixture_change(table, upcoming):
    report = check_pdf(pdf("clean_eu_da"))
    rows = [{"cas": "4098-71-9", "name": None, "h_codes": [], "concentration": "0.1 %"}]
    report.mixture = _mixture(rows, upcoming, table, BEFORE)
    page = render_html(report)
    assert "Changes coming to Annex VI" in page
    assert "gives Skin Sens. 1A" in page


def test_the_sources_name_the_amendment_with_its_date(upcoming):
    lines = sources.used("eu_clp", "en", "02008R1272-20260701",
                         ingredient_list="annex_vi",
                         annex_vi_source="02008R1272-20260701", upcoming=upcoming)
    assert lines[-1] == ("Upcoming: Delegated Regulation (EU) 2025/1222 (23rd ATP), "
                         "amending Annex VI Table 3 from 01/02/2027, read from the "
                         "act (CELEX 32025R1222)")
