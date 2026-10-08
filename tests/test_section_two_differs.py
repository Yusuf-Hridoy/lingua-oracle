"""Section 2 against the calculation, when they differ.

The calculation from the regulation's own rules stays the reference. A
Section 2 stricter than it is one to check - it may rest on bridging, test
data or expert judgement. A Section 2 weaker than it is a fault to fix,
unless the sheet itself cites test data or bridging, in Section 2 or in
Section 11 about the mixture; then it is one to check, with that text shown.
"""

from __future__ import annotations

from lingua_oracle.mixture.calculate import calculate
from lingua_oracle.mixture.classes import parse_class
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf
from tests.make_fixtures import _glycol_coolant
from tests.test_mixture_calculation import _about, ing

TAIL = ("is based on bridging principles, test data or expert judgement, the SDS "
        "must be able to justify it — confirm which principle and which "
        "reference mixture.")


def _family(report, name):
    return next(r for r in report.mixture.results if r["family"] == name)


def test_a_stricter_section_two_is_one_to_check_in_these_words():
    stot = _family(check_pdf(pdf("pattern_glycol_coolant_gb"), ingredients=True),
                   "Target organ toxicity, repeated exposure")
    assert stot["verdict"] == "cannot_tell"
    assert stot["message"] == ("Section 2 states STOT RE 2; calculated from the "
                               "ingredients: no classification. If STOT RE 2 " + TAIL)


def test_a_weaker_section_two_is_a_fault():
    results, _ = calculate([ing(30, 30, "H314")], [parse_class("Skin Irrit. 2")],
                           "eu_clp")
    result = _about(results, "Skin Corr. 1")
    assert result.verdict == "inconsistent"
    assert result.message == ("Section 2 states Skin Irrit. 2; calculated from the "
                              "ingredients: Skin Corr. 1. If Skin Irrit. 2 " + TAIL)


def test_a_weaker_section_two_citing_test_data_is_one_to_check():
    quoted = ["Classification based on test data on the mixture."]
    results, _ = calculate([ing(30, 30, "H314")], [parse_class("Skin Irrit. 2")],
                           "eu_clp", justification=quoted)
    result = _about(results, "Skin Corr. 1")
    assert result.verdict == "cannot_tell"
    assert result.justification == quoted


def _without_acute(tmp_path, **extra):
    path = _glycol_coolant(tmp_path / "coolant.pdf",
                           section_two=[("STOT RE 2", "H373")], **extra)
    return _family(check_pdf(str(path), "uk_clp", ingredients=True),
                   "Acute toxicity, oral")


def test_a_hazard_section_two_leaves_out_is_a_fault(tmp_path):
    oral = _without_acute(tmp_path)
    assert oral["verdict"] == "inconsistent"
    assert oral["message"] == ("Section 2 states nothing for this hazard; calculated "
                               "from the ingredients: Acute Tox. (oral) 4. If leaving "
                               "it out " + TAIL)
    assert oral["justification"] == []


def test_section_two_citing_test_data_makes_it_one_to_check(tmp_path):
    line = "Classification based on test data on the mixture."
    oral = _without_acute(tmp_path, extra_s2=[line])
    assert oral["verdict"] == "cannot_tell"
    assert oral["justification"] == [line]


def test_section_11_citing_bridging_for_the_mixture_makes_it_one_to_check(tmp_path):
    line = "The mixture was classified using bridging principles (dilution)."
    oral = _without_acute(tmp_path, section_eleven=[line])
    assert oral["verdict"] == "cannot_tell"
    assert oral["justification"] == [line]


def test_a_test_on_one_ingredient_is_no_reason_for_the_mixture(tmp_path):
    oral = _without_acute(tmp_path, section_eleven=[
        "Ethylene glycol (CAS 107-21-1): tested according to OECD 401."])
    assert oral["verdict"] == "inconsistent"
    assert oral["justification"] == []


def test_agreement_needs_no_justification():
    results, _ = calculate([ing(30, 30, "H314")], [parse_class("Skin Corr. 1")],
                           "eu_clp", justification=["Based on test data."])
    assert _about(results, "Skin Corr. 1").verdict == "consistent"
