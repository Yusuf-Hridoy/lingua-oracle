"""Substance or mixture, and a substance's Section 2 against its own entry.

2-propanol is Annex VI 603-117-00-0 (CAS 67-63-0): Flam. Liq. 2, Eye Irrit. 2,
STOT SE 3 - H225, H319, H336. The substance and its entry are public law; the
sheets are synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from lingua_oracle.ingredients import substance
from lingua_oracle.ingredients.composition import MIXTURE, SUBSTANCE, UNKNOWN, detect
from lingua_oracle.keys.builders.annex_vi import load_table
from lingua_oracle.mixture import section as mixture
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf


@dataclass
class Line:
    text: str


@dataclass
class Span:
    name: str
    start: int
    end: int


@dataclass
class Row:
    cas: str
    concentration: str | None = None
    h_codes: tuple = ()
    raw: str = ""


def _three(*text):
    lines = [Line("SECTION 3: Composition/information on ingredients"),
             *(Line(t) for t in text)]
    return lines, [Span("3", 0, len(lines))]


# -- substance or mixture -------------------------------------------------------

@pytest.mark.parametrize(("heading", "kind"), [
    ("3.1 Substances", SUBSTANCE), ("3.1. Substance", SUBSTANCE),
    ("3.2 Mixtures", MIXTURE), ("3.2. Mixture", MIXTURE)])
def test_the_subsection_heading_decides(heading, kind):
    lines, spans = _three(heading)
    found = detect(lines, spans, [Row("67-63-0", "60 %"), Row("64-17-5", "40 %")])
    assert found.kind == kind
    assert heading in found.evidence


def test_a_sentence_saying_so_decides_where_there_is_no_heading():
    lines, spans = _three("This product is a substance.")
    assert detect(lines, spans, []).kind == SUBSTANCE


@pytest.mark.parametrize(("share", "kind"), [
    ("100 %", SUBSTANCE), ("≥ 99 %", SUBSTANCE), ("95 - 100 %", SUBSTANCE),
    ("90 - 100 %", UNKNOWN), ("60 %", UNKNOWN)])
def test_one_cas_number_at_about_100_percent_is_a_substance(share, kind):
    lines, spans = _three("Chemical name  CAS No  Concentration")
    assert detect(lines, spans, [Row("67-63-0", share)]).kind == kind


def test_several_ingredients_are_a_mixture():
    lines, spans = _three()
    assert detect(lines, spans, [Row("67-63-0", "50 %"),
                                 Row("64-17-5", "50 %")]).kind == MIXTURE


# -- the 2-propanol sheet ---------------------------------------------------------

def test_a_correct_2_propanol_sheet_passes():
    report = check_pdf(pdf("pattern_substance_2_propanol"), ingredients=True)
    assert report.composition == SUBSTANCE
    found = report.substance
    assert (found.status, found.cas, found.entry_index_no) == (
        "ok", "67-63-0", "603-117-00-0")
    assert [r["result"] for r in found.classes] == ["ok", "ok", "ok"]
    assert [(r["code"], r["result"]) for r in found.codes] == [
        ("H225", "ok"), ("H319", "ok"), ("H336", "ok")]
    assert found.list_binding is True


def test_a_2_propanol_sheet_missing_h336_fails():
    found = check_pdf(pdf("pattern_substance_missing_h336"),
                      ingredients=True).substance
    assert found.status == "fix"
    assert {"code": "H336", "result": "fix",
            "note": "The entry requires H336; Section 2 does not carry it."} in found.codes
    assert {"stated": "", "official": "STOT SE 3", "result": "fix",
            "note": "Section 2 does not state STOT SE 3."} in found.classes


def test_a_substance_has_no_mixture_to_calculate():
    report = check_pdf(pdf("pattern_substance_2_propanol"), ingredients=True)
    assert report.mixture.state == "not_applicable"
    assert report.mixture.message == "Not applicable: this is a substance."


def test_a_class_stated_in_the_wrong_category_is_a_fault():
    rows = substance._class_rows(["Flam. Liq. 3"], ["Flam. Liq. 2"])
    assert rows[0]["result"] == "fix"


def test_a_stricter_category_meets_a_minimum_classification():
    rows = substance._class_rows(["Acute Tox. 3"], ["Acute Tox. 4 *"])
    assert rows[0]["result"] == "ok"


def test_a_class_the_entry_does_not_cover_is_information():
    rows = substance._class_rows(["Flam. Liq. 2", "Skin Irrit. 2"], ["Flam. Liq. 2"])
    assert [r["result"] for r in rows] == ["ok", "info"]


def test_the_cas_number_can_come_from_section_one():
    lines = [Line("Product name: something"), Line("CAS number: 67-63-0"),
             Line("SECTION 2: Hazards identification")]
    assert substance.cas_before_section_two(lines, [Span("2", 2, 3)]) == "67-63-0"


def test_a_substance_without_an_entry_says_so():
    found = substance.check("000-00-0", regulation="eu_clp", sheet_codes=["H225"],
                            stated_classes=[])
    assert found.state == "no_entry"
    assert found.status == "not_checked"


def test_a_reference_list_difference_is_to_check_not_to_fix():
    found = substance.check("67-63-0", regulation="un_ghs", sheet_codes=["H225"],
                            stated_classes=[])
    assert found.status == "check"


# -- a mixture whose Section 3 gives no concentrations ------------------------------

def test_without_concentrations_the_mixture_cannot_be_calculated():
    report = check_pdf(pdf("pattern_mixture_no_concentrations"), ingredients=True)
    assert report.composition == MIXTURE
    assert report.mixture.state == "cannot_calculate"
    assert report.mixture.message == "Can't calculate: Section 3 gives no concentrations."


def test_without_codes_each_ingredient_is_still_looked_up():
    section = check_pdf(pdf("pattern_mixture_no_concentrations"),
                        ingredients=True).ingredients
    found = {s["cas"]: s for s in section.substances}
    assert found["67-64-1"]["reason"] == "sheet_gives_no_codes"
    assert found["67-64-1"]["harmonised_codes"] == ["H225", "H319", "H336", "EUH066"]
    assert found["64-17-5"]["harmonised_codes"] == ["H225"]
    assert section.counts["fix"] == 0
    assert "nothing to check" not in section.message.lower()


def test_rows_without_concentrations_and_classes_say_why():
    built = mixture.build([{"cas": "67-63-0", "name": None, "h_codes": [],
                            "concentration": None}], [], [], "eu_clp",
                          table=load_table())
    assert built.message == "Can't calculate: Section 3 gives no concentrations."
