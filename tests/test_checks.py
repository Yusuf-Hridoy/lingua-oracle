"""End-to-end checks against the synthetic PDFs.

Two rules drive this file:
  * each clean document must produce zero failures
  * each seeded-defect document must trigger its intended check
"""

from __future__ import annotations

import pytest

from lingua_oracle.checks import all_checks
from lingua_oracle.models import Severity
from lingua_oracle.pipeline import check_pdf, compare_pdfs
from tests.conftest import pdf

CLEAN = [
    ("clean_eu_da", "eu_clp", "da"),
    ("clean_eu_en", "eu_clp", "en"),
    ("clean_osha_en", "us_osha", "en"),
    ("clean_whmis_enfr", "ca_whmis", None),
]

# fixture -> (check that must fire, severity, other checks allowed to fire)
DEFECTS = {
    "defect_a01_signal": ("A-01", Severity.FAIL, {"B-10"}),
    "defect_a02_hazard": ("A-02", Severity.FAIL, set()),
    "defect_a03_precautionary": ("A-03", Severity.FAIL, set()),
    "defect_a04_supplemental": ("A-04", Severity.FAIL, set()),
    # An English phrase in a Danish sheet is both untranslated and wrong wording.
    "defect_a05_english": ("A-05", Severity.FAIL, {"A-02"}),
    "defect_a06_placeholder": ("A-06", Severity.FAIL, set()),
    "defect_a07_broken": ("A-07", Severity.FAIL, set()),
    "defect_b08_missing_s16": ("B-08", Severity.FAIL, set()),
    "defect_b09_label": ("B-09", Severity.FAIL, set()),
    "defect_b10_signal_fit": ("B-10", Severity.FAIL, set()),
    "defect_c12_euh_on_osha": ("C-12", Severity.FAIL, set()),
    "defect_c14_english_only": ("C-14", Severity.FAIL, set()),
    "defect_c02_inconsistent": ("C-02", Severity.WARN, set()),
}

REGULATION_FOR = {
    "defect_c12_euh_on_osha": "us_osha",
    "defect_c14_english_only": "ca_whmis",
}


def _fired(report, severity: Severity) -> set[str]:
    return {
        f.check_id
        for f in report.findings
        if f.severity is severity and not f.unverified
    }


def test_fifteen_checks_are_registered():
    assert len(all_checks()) == 15


@pytest.mark.parametrize(("name", "regulation", "language"), CLEAN)
def test_clean_documents_have_no_failures(name, regulation, language):
    report = check_pdf(pdf(name), regulation, language)
    failures = [f for f in report.findings if f.severity is Severity.FAIL and not f.unverified]
    assert failures == [], [f"{f.check_id} {f.code}: {f.message}" for f in failures]


@pytest.mark.parametrize("name", list(DEFECTS))
def test_defect_triggers_its_check(name):
    want, severity, allowed = DEFECTS[name]
    regulation = REGULATION_FOR.get(name, "eu_clp")
    report = check_pdf(pdf(name), regulation)
    fired = _fired(report, severity)
    assert want in fired, f"{name}: expected {want}, got {sorted(fired)}"
    unexpected = fired - {want} - allowed
    assert not unexpected, f"{name}: unexpected checks fired: {sorted(unexpected)}"


def test_compare_detects_a_differing_code_set():
    report = compare_pdfs(pdf("compare_b11_a"), pdf("compare_b11_b"), "eu_clp")
    b11 = [f for f in report.findings if f.check_id == "B-11"]
    assert b11
    assert {f.code for f in b11} == {"H336"}


def test_compare_is_silent_on_identical_code_sets():
    report = compare_pdfs(pdf("clean_eu_en"), pdf("clean_eu_en"), "eu_clp")
    assert [f for f in report.findings if f.check_id == "B-11"] == []


def test_regulation_flag_overrides_detection():
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    assert report.regulation == "eu_clp"
    assert report.detected_by == "flag"


def test_language_is_detected_without_a_flag():
    assert check_pdf(pdf("clean_eu_da"), "eu_clp").language == "da"
    assert check_pdf(pdf("clean_eu_en"), "eu_clp").language == "en"


def test_sections_are_found():
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    note = next(n for n in report.notes if n.startswith("Sections read"))
    for section in ("2", "3", "16"):
        assert section in note


def test_tier_c_findings_are_unverified_not_failures():
    """A regulation with no answer key may never produce a wording failure.

    Checked against jp_jis, whose key is empty because the source on file is the
    wrong document. Every code therefore falls to tier C, and tier C carries no
    wording verdict at all.
    """
    report = check_pdf(pdf("clean_eu_da"), "jp_jis")
    wording = {"A-01", "A-02", "A-03", "A-04"}
    failures = [
        f for f in report.findings
        if f.severity is Severity.FAIL and not f.unverified and f.check_id in wording
    ]
    assert failures == [], [f"{f.check_id} {f.code}" for f in failures]
    assert report.summary.unverified > 0
    assert all(f.tier is None or f.tier.value == "C"
               for f in report.findings if f.unverified)


def test_bilingual_document_accepts_either_required_language():
    """WHMIS requires English and French together; both halves are correct."""
    report = check_pdf(pdf("clean_whmis_enfr"), "ca_whmis")
    assert report.summary.fail == 0
    # the half not in the detected document language is reported as info
    assert any(f.severity is Severity.INFO and "also requires" in f.message
               for f in report.findings)


def test_coverage_is_reported():
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    assert report.coverage.codes_found > 0
    assert report.coverage.codes_checked == report.coverage.codes_found
    assert report.coverage.percent == 100.0
