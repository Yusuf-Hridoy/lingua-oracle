"""B-12 to B-14 on synthetic sheets: the structure, as each regulation's text
requires it. Every sheet is built from data/sds_structure/ itself, then made
wrong in exactly one way."""

from __future__ import annotations

import pytest

from lingua_oracle.pipeline import check_pdf
from lingua_oracle.structure.reader import same_heading, tokens
from tests.make_fixtures import structured_sheet, write_sds

STRUCTURE = {"B-12", "B-13", "B-14"}
FULL = {"eu_clp": ("en", ["H225"], ["P210"]), "uk_clp": ("en", ["H225"], ["P210"]),
        "us_osha": ("en", ["H225"], ["P210"]), "ca_whmis": ("en", ["H225"], ["P210"]),
        "un_ghs": ("en", ["H225"], ["P210"]), "au_whs": ("en", ["H225"], ["P210"])}


def _structure(tmp_path, regulation="eu_clp", language="en", name="s.pdf", **wrong):
    path = structured_sheet(tmp_path / name, regulation=regulation, language=language,
                            **wrong)
    report = check_pdf(str(path), regulation, language)
    return report, [f for f in report.findings if f.check_id in STRUCTURE]


@pytest.mark.parametrize("regulation", list(FULL))
def test_a_correct_sheet_has_no_structure_findings(tmp_path, regulation):
    language, h, p = FULL[regulation]
    path = write_sds(tmp_path / f"{regulation}.pdf", regulation=regulation,
                     language=language, h_codes=h, p_codes=p)
    report = check_pdf(str(path), regulation, language)
    found = [f"{f.check_id} {f.message[:90]}" for f in report.findings
             if f.check_id in STRUCTURE]
    assert found == []
    assert len(report.structure.sections) == 16
    assert all(s.found for s in report.structure.sections)


@pytest.mark.parametrize("language", ["en", "de", "da", "fr"])
def test_eu_headings_are_correct_in_each_language_as_its_own_act_words_them(
        tmp_path, language):
    _, found = _structure(tmp_path, language=language)
    assert found == [], [f.message[:120] for f in found]


@pytest.mark.parametrize(("language", "words"), [
    ("en", "First aid"), ("de", "Erste Hilfe"), ("da", "Førstehjælp"), ("fr", "Premiers soins")])
def test_eu_heading_wording_that_differs_is_a_fault_in_each_language(
        tmp_path, language, words):
    _, found = _structure(tmp_path, language=language, headings={"4": words})
    heading = [f for f in found if f.check_id == "B-12" and f.section == "4"]
    assert [f.severity.value for f in heading] == ["fail"]
    assert heading[0].found == words and "Annex II, Part B" in heading[0].message


def test_a_missing_section_is_a_fault_quoting_the_requirement(tmp_path):
    _, found = _structure(tmp_path, omit={"7"})
    missing = [f for f in found if f.section == "7"]
    assert [(f.check_id, f.severity.value) for f in missing] == [("B-12", "fail")]
    assert missing[0].message.startswith("Section 7 is missing.")
    assert "shall include the following 16 headings" in missing[0].message


def test_a_swapped_order_is_a_fault_where_the_text_states_an_order(tmp_path):
    order = [str(n) for n in range(1, 17)]
    order[4], order[5] = order[5], order[4]               # 6 before 5
    _, found = _structure(tmp_path, regulation="au_whs", order=order)
    late = [f for f in found if "comes after" in f.message]
    assert [(f.section, f.severity.value) for f in late] == [("5", "fail")]
    assert "Schedule 7, clause 1(3)" in late[0].message


def test_eu_part_b_states_no_order_so_a_swap_is_not_a_finding(tmp_path):
    order = [str(n) for n in range(1, 17)]
    order[4], order[5] = order[5], order[4]
    _, found = _structure(tmp_path, order=order)
    assert not [f for f in found if "comes after" in f.message]


def test_a_misnumbered_section_is_a_fault(tmp_path):
    _, found = _structure(tmp_path, printed={"4": "5"}, omit={"5"})
    numbered = [f for f in found if f.section == "4" and "numbered 5" in f.message]
    assert [f.severity.value for f in numbered] == ["fail"]


def test_a_missing_sub_section_1_4_is_a_fault(tmp_path):
    _, found = _structure(tmp_path, omit={"1.4"})
    sub = [f for f in found if f.check_id == "B-13" and "1.4" in f.message]
    assert [f.severity.value for f in sub] == ["fail"]
    # Its emergency number goes with it: not judged twice.
    assert not [f for f in found if f.check_id == "B-14" and "1.4" in f.message
                and f.severity.value == "fail"]


def test_a_missing_supplier_email_in_1_3_is_a_fault_quoting_1_3(tmp_path):
    _, found = _structure(tmp_path, omit={"supplier_email"})
    email = [f for f in found if f.check_id == "B-14"]
    assert [(f.section, f.severity.value) for f in email] == [("1", "fail")]
    assert "No e-mail address found in sub-section 1.3." in email[0].message
    assert "Annex II, Part A, 1.3" in email[0].message


def test_a_missing_us_section_16_date_is_a_fault_quoting_table_d1(tmp_path):
    _, found = _structure(tmp_path, regulation="us_osha", omit={"date_of_revision"})
    date = [f for f in found if f.check_id == "B-14"]
    assert [(f.section, f.severity.value) for f in date] == [("16", "fail")]
    assert "Table D.1, 16" in date[0].message
    assert "date of preparation or last revision" in date[0].message


def test_osha_sections_12_to_15_may_be_left_out(tmp_path):
    _, found = _structure(tmp_path, regulation="us_osha", omit={"12", "13", "14", "15"})
    assert found == []


def test_under_the_ghs_a_missing_section_is_one_to_check(tmp_path):
    _, found = _structure(tmp_path, regulation="un_ghs", omit={"8"})
    assert [(f.section, f.severity.value) for f in found] == [("8", "warn")]


def test_a_blank_eu_sub_section_is_a_fault_quoting_0_4(tmp_path):
    _, found = _structure(tmp_path, blank={"7.3"})
    blank = [f for f in found if "blank" in f.message]
    assert [(f.section, f.severity.value) for f in blank] == [("7", "fail")]
    assert "The safety data sheet shall not contain blank subsections." in blank[0].message


def test_an_empty_us_section_is_a_fault_and_australia_says_nothing_of_it(tmp_path):
    _, us = _structure(tmp_path, regulation="us_osha", blank={"7"}, name="us.pdf")
    assert [(f.section, f.severity.value) for f in us] == [("7", "fail")]
    assert "shall clearly indicate that no applicable information is available" in us[0].message
    _, au = _structure(tmp_path, regulation="au_whs", blank={"7"}, name="au.pdf")
    assert au == []


@pytest.mark.parametrize("language", ["en", "fr", "en+fr"])
def test_canada_accepts_either_language_or_both(tmp_path, language):
    path = structured_sheet(tmp_path / "ca.pdf", regulation="ca_whmis", language=language)
    report = check_pdf(str(path), "ca_whmis", "fr" if language == "fr" else "en")
    assert [f.message[:80] for f in report.findings if f.check_id in STRUCTURE] == []


def test_hazards_takes_both_forms_where_the_text_writes_hazard_s():
    assert same_heading("Hazard identification", "Hazard(s) identification")
    assert same_heading("Hazards identification", "Hazard(s) identification")
    assert not same_heading("Hazard identification", "Hazards identification")
    assert tokens("Fire-fighting measures") == tokens("Firefighting measures")


def test_a_sheet_printing_the_texts_own_s_in_brackets_matches_it():
    assert same_heading("Utilisation(s) finale(s) particulière(s)",
                        "Utilisation(s) finale(s) particulière(s)")
    assert same_heading("Specific end uses", "Specific end use(s)")
