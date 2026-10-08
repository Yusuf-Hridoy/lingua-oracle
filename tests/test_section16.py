"""Section 16 against the codes Section 2 uses, and Section 3 where it prints them."""

from __future__ import annotations

from lingua_oracle.pipeline import check_pdf
from tests.make_fixtures import HEADINGS, PRODUCT, SUPPLIER, Sheet, texts


def _sheet(path):
    head = HEADINGS["en"]
    official = texts("eu_clp", "en", ["H225", "H319", "H336", "H400"])
    sheet = Sheet(path)
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Prepared according to Regulation (EC) No 1272/2008.", size=8)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Signal word: Danger")
    sheet.line(f"H225 {official['H225']}")
    sheet.line(f"H319 {official['H319']}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%  Flam. Liq. 2; H225  STOT SE 3; H336")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    sheet.line(f"H225 {official['H225']}")
    sheet.line(f"H400 {official['H400']}")
    sheet.save()
    return path


def _b08(tmp_path):
    report = check_pdf(str(_sheet(tmp_path / "s16.pdf")), "eu_clp", "en")
    return {f.code: (f.severity.value, f.message) for f in report.findings
            if f.check_id == "B-08"}


def test_a_section_3_code_missing_from_section_16_is_a_fault(tmp_path):
    severity, message = _b08(tmp_path)["H336"]
    assert severity == "fail" and "used in Section 3" in message


def test_a_section_2_code_missing_from_section_16_is_one_to_check(tmp_path):
    severity, message = _b08(tmp_path)["H319"]
    assert severity == "warn" and "used in Section 2" in message


def test_a_code_only_in_section_16_is_said_as_information(tmp_path):
    severity, message = _b08(tmp_path)["H400"]
    assert severity == "info" and "neither Section 2 nor Section 3" in message


def test_a_code_written_out_in_section_16_raises_nothing(tmp_path):
    assert "H225" not in _b08(tmp_path)
