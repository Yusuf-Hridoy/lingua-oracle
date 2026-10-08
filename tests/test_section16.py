"""B-08: Section 16 against each regulation's own rule.

REACH Annex II, Section 16(e): "Write out the full text of any statements,
which are not written out in full under sections 2 to 15". A regulation whose
text has no such rule gets no finding.
"""

from __future__ import annotations

from lingua_oracle.pipeline import check_pdf
from tests.make_fixtures import HEADINGS, PRODUCT, SUPPLIER, Sheet, texts


def _sheet(path, regulation="eu_clp"):
    head = HEADINGS["en"]
    # OSHA has no environmental statements; H400 only where the key has it.
    extra = [] if regulation == "us_osha" else ["H400"]
    official = texts(regulation, "en", ["H225", "H319", *extra])
    sheet = Sheet(path)
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Signal word: Danger")
    sheet.line(f"H225 {official['H225']}")
    sheet.line(f"H319 {official['H319']}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%  Flam. Liq. 2; H225  STOT SE 3; H336")
    sheet.line("Synthetic component B  CAS 000-00-1  1-5%  Acute Tox. 4; H302")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    sheet.line(f"H225 {official['H225']}")
    for code in extra:
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path


def _b08(tmp_path, regulation="eu_clp"):
    path = _sheet(tmp_path / f"s16_{regulation}.pdf", regulation)
    report = check_pdf(str(path), regulation, "en")
    return {f.code: (f.severity.value, f.message) for f in report.findings
            if f.check_id == "B-08"}


def test_a_code_written_out_in_section_2_needs_nothing_in_section_16(tmp_path):
    assert "H319" not in _b08(tmp_path)      # written out in Section 2 only


def test_a_code_written_out_in_both_raises_nothing(tmp_path):
    assert "H225" not in _b08(tmp_path)


def test_a_code_given_only_as_a_code_and_missing_from_16_is_a_fault(tmp_path):
    found = _b08(tmp_path)
    for code in ("H336", "H302"):            # bare in Section 3, nowhere written
        severity, message = found[code]
        assert severity == "fail"
        assert "only as a code" in message
        assert "REACH" in message and "Annex II, Part A, Section 16(e)" in message
        assert "not written out in full under sections 2 to 15" in message


def test_a_code_only_in_section_16_is_a_note(tmp_path):
    severity, message = _b08(tmp_path)["H400"]
    assert severity == "info" and "nowhere in Sections 2 to 15" in message


def test_a_regulation_with_no_such_rule_gets_no_finding(tmp_path):
    for regulation in ("un_ghs", "us_osha"):
        assert _b08(tmp_path, regulation) == {}, regulation


def test_a_regulation_whose_rule_is_not_on_file_gets_no_finding(tmp_path):
    assert _b08(tmp_path, "uk_clp") == {}


def _summary(tmp_path, regulation):
    from lingua_oracle.report import sections

    path = _sheet(tmp_path / f"row_{regulation}.pdf", regulation)
    page = sections.build(check_pdf(str(path), regulation, "en"), regulation, "flag")
    sixteen = next(s for s in page.sections if s.number == "16")
    return next(r for sub in sixteen.subs for r in sub.rows
                if r.key == "Full text of H-statements")


def test_the_report_says_when_a_regulation_asks_nothing_of_section_16(tmp_path):
    row = _summary(tmp_path, "un_ghs")
    assert row.status == "na"
    assert "Not required: UN GHS Rev.11 (2025), Annex 4, A4.3.16" in row.text


def test_the_report_says_when_the_rule_is_not_on_file(tmp_path):
    row = _summary(tmp_path, "uk_clp")
    assert row.status == "na" and "not on file" in row.text


# -- precautionary statements, where the rule's sentence names them --------------

def _p_sheet(path):
    head = HEADINGS["en"]
    official = texts("eu_clp", "en", ["H225", "P210", "P280", "P403+P235"])
    sheet = Sheet(path)
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Signal word: Danger")
    sheet.line(f"H225 {official['H225']}")
    sheet.line(f"P210 {official['P210']}")
    sheet.line("Precautionary statements: P280, P403+P235")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%  Flam. Liq. 2; H225")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    sheet.line(f"H225 {official['H225']}")
    sheet.line(f"P403+P235 {official['P403+P235']}")
    sheet.save()
    return path


def _p_findings(tmp_path):
    report = check_pdf(str(_p_sheet(tmp_path / "p16.pdf")), "eu_clp", "en")
    return {f.code: f.severity.value for f in report.findings if f.check_id == "B-08"}


def test_a_p_code_given_only_as_a_code_and_missing_from_16_is_a_fault(tmp_path):
    assert _p_findings(tmp_path).get("P280") == "fail"


def test_a_p_code_written_out_in_section_2_needs_nothing_in_16(tmp_path):
    assert "P210" not in _p_findings(tmp_path)


def test_a_bare_p_combination_written_out_in_16_raises_nothing(tmp_path):
    found = _p_findings(tmp_path)
    assert "P403" not in found and "P235" not in found


def test_p_codes_are_covered_only_where_the_rule_names_them():
    from lingua_oracle.checks.b08_section16 import _covered
    from lingua_oracle.keys.builders.section16 import Section16Rule, load

    assert "P" in _covered(load("eu_clp"))
    hazard_only = Section16Rule("x", "rule", "Act", "16",
                                "Write out the full text of any hazard statements")
    assert _covered(hazard_only) == ("H", "EUH")
