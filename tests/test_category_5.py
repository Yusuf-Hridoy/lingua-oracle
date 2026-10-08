"""Acute toxicity Category 5, by each regulation's own text.

OSHA Appendix A (A.1.2.1, "one of four hazard categories"; Table A.1.1) and
the HPR (section 8.1.1(3), Tables 1-3) stop at Category 4, as do CLP's and
GB CLP's Table 3.1.1; Australia excludes Category 5 in terms. Only the GHS
itself has it. On a sheet under the others, H303/H313/H333 are a note, not a
classification the mixture is judged on.

Both OSHA (A.1.3.6.1(a)) and the HPR (8.1.5(b)) let an ingredient with an
oral or dermal LD50 of 2000-5000 into the ATEmix formula; that is unchanged.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from lingua_oracle.mixture import acute, acute_table
from lingua_oracle.mixture.acute import Section11Ate
from lingua_oracle.mixture.calculate import calculate
from lingua_oracle.mixture.classes import HazardClass
from lingua_oracle.mixture.model import from_codes
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf


@pytest.mark.parametrize(("regulation", "where"), [
    ("us_osha", "29 CFR 1910.1200 Appendix A, Table A.1.1"),
    ("ca_whmis", "Hazardous Products Regulations (SOR/2015-17), section 8.1.1(3)"),
    ("eu_clp", "Annex I, Table 3.1.1"),
    ("uk_clp", "Annex I, Table 3.1.1"),
    ("au_whs", "Safe Work Australia"),
])
def test_five_regulations_have_no_category_5_and_say_where(regulation, where):
    assert where in acute_table.load(regulation).without_category_5()


def test_the_ghs_itself_has_category_5():
    assert acute_table.load("un_ghs").without_category_5() is None


def test_h303_on_an_osha_sheet_is_a_note():
    report = check_pdf(pdf("pattern_out_of_scope"), ingredients=True)
    notes = [f for f in report.findings if f.code == "H303"]
    assert [(f.check_id, f.severity.value) for f in notes] == [("C-12", "info")]
    assert notes[0].message == (
        "Category 5 is not part of US OSHA HazCom; this code is outside its "
        "classification (29 CFR 1910.1200 Appendix A, Table A.1.1).")


def _oral(regulation):
    harmful = from_codes(None, "harmful", Decimal(50), Decimal(50), ["H303"])
    results, _ = calculate(
        [harmful], [HazardClass("Acute Tox. (oral)", "5")], regulation,
        "liquid", acute_inputs={"ingredients": [harmful]})
    return [r for r in results if r.family == "Acute toxicity, oral"]


def test_a_stated_category_5_gets_no_mixture_verdict_where_there_is_none():
    for regulation in ("us_osha", "ca_whmis", "eu_clp", "uk_clp", "au_whs"):
        assert _oral(regulation) == [], regulation


def test_under_the_ghs_category_5_is_calculated_and_judged():
    oral = _oral("un_ghs")
    assert [(r.verdict, r.calculated_class) for r in oral] == [
        ("consistent", "Acute Tox. (oral) 5")]              # 100 / (50/2500)


@pytest.mark.parametrize(("regulation", "counted"), [
    ("us_osha", True), ("ca_whmis", True), ("eu_clp", False)])
def test_an_ld50_of_2000_to_5000_enters_atemix_only_where_the_text_says(
        regulation, counted):
    rules = acute_table.load(regulation)
    toxic = from_codes("100-00-1", "toxic", Decimal(10), Decimal(10), ["H301"])
    mild = from_codes("100-00-2", "mild", Decimal(50), Decimal(50), [])
    run = acute.calculate(
        [toxic, mild], rules, "liquid",
        section_11={"100-00-2": [Section11Ate("oral", None, Decimal(3000), "LD50 3000")]},
    )["oral"]["runs"][0]
    assert ("LD50 3000" in run.trace[0]) is counted
