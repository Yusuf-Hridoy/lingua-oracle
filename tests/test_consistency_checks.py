"""C-16 to C-20 on synthetic sheets: each section held against another, by
the regulation's own criteria (data/label_elements, data/hazard_criteria,
data/acute_toxicity). Every sheet is invented; the official wording comes
from the answer keys."""

from __future__ import annotations

import pytest

from lingua_oracle.pipeline import check_pdf
from tests.make_fixtures import HEADINGS, Sheet, signal_text, structured_sheet, texts

EU = ("eu_clp", "en")


def _sheet(tmp_path, regulation="eu_clp", language="en", *, classes=(), codes=(),
           signal=None, pictograms="", nine=(), eleven=(), twelve=(), name="c.pdf"):
    official = texts(regulation, language, list(codes)) if codes else {}
    two = list(classes)
    if signal is not False:
        two.append(f"{HEADINGS['en']['signal']}: {signal or signal_text(regulation, language)}")
    if pictograms:
        two.append(f"Hazard pictograms: {pictograms}")
    two += [f"{c} {official[c]}" for c in codes]
    bodies = {"2": two, "3": ["Synthetic component A  CAS 000-00-0  30-60%"],
              "16": [f"{c} {official[c]}" for c in codes]}
    if nine:
        bodies["9"] = list(nine)
    if eleven:
        bodies["11"] = list(eleven)
    if twelve:
        bodies["12"] = list(twelve)
    path = structured_sheet(tmp_path / name, regulation=regulation, language=language,
                            bodies=bodies)
    return check_pdf(str(path), regulation, language)


def _rows(report, check):
    return [r for r in report.consistency if r.check == check]


def _status(report, check, key=None):
    return [(r.key, r.status) for r in _rows(report, check) if key is None or key in r.key]


# -- C-16 label elements --------------------------------------------------------------

def test_a_correct_eu_label_has_every_element_in_place(tmp_path):
    report = _sheet(tmp_path, classes=["Flam. Liq. 2", "Eye Irrit. 2"], codes=["H225", "H319"],
                    pictograms="GHS02, GHS07", nine=["Flash point: 10 °C",
                                                     "Initial boiling point: 80 °C"])
    statuses = _status(report, "C-16")
    assert all(s == "ok" for _, s in statuses), statuses
    assert ("Signal word", "ok") in statuses


def test_a_weaker_signal_word_than_the_classification_calls_for_is_a_fault(tmp_path):
    report = _sheet(tmp_path, classes=["Flam. Liq. 2"], codes=["H225"], signal="Warning",
                    nine=["Flash point: 10 °C", "Initial boiling point: 80 °C"])
    row = next(r for r in _rows(report, "C-16") if r.key == "Signal word")
    assert row.status == "fix" and row.expected == "Danger"
    assert "Annex I, Table 2.6.2" in row.citation


def test_a_classification_without_its_code_is_a_fault_and_a_stray_code_one_to_check(tmp_path):
    report = _sheet(tmp_path, classes=["Eye Irrit. 2"], codes=["H225"],
                    nine=["Flash point: 10 °C", "Initial boiling point: 80 °C"])
    statuses = dict(_status(report, "C-16"))
    assert statuses["Eye Irrit. 2"] == "fix"
    assert statuses["H225"] == "check"


def test_ghs06_with_ghs07_for_the_same_hazard_breaks_article_26(tmp_path):
    report = _sheet(tmp_path, classes=["Acute Tox. 3", "Acute Tox. 4"], codes=["H301", "H332"],
                    signal="Danger", pictograms="GHS06, GHS07")
    row = next(r for r in _rows(report, "C-16") if r.key == "Pictogram ghs07")
    assert row.status == "check" and row.citation.endswith("Article 26(1)(b)")
    assert "shall not appear" in row.quote


def test_ghs07_stays_where_another_class_still_needs_it(tmp_path):
    report = _sheet(tmp_path, classes=["Skin Corr. 1B", "STOT SE 3"], codes=["H314", "H336"],
                    signal="Danger", pictograms="GHS05, GHS07")
    assert ("Pictogram ghs07", "ok") in _status(report, "C-16")


def test_h318_beside_h314_is_a_note_not_a_fault(tmp_path):
    report = _sheet(tmp_path, classes=["Skin Corr. 1B", "Eye Dam. 1"], codes=["H314", "H318"],
                    signal="Danger")
    note = next(r for r in _rows(report, "C-16") if r.key == "H318")
    assert note.status == "info" and "may be omitted" in note.quote


def test_pictograms_shown_only_as_images_are_not_checked(tmp_path):
    report = _sheet(tmp_path, classes=["Eye Irrit. 2"], codes=["H319"])
    assert ("Pictograms", "na") in _status(report, "C-16")


def test_osha_pictograms_are_names_and_its_precedence_binds(tmp_path):
    report = _sheet(tmp_path, regulation="us_osha", classes=[
        "Acute toxicity - Oral - Category 3", "Acute toxicity - Inhalation - Category 4"],
        codes=["H301", "H332"], signal="Danger", pictograms="Skull and crossbones, Exclamation mark")
    row = next(r for r in _rows(report, "C-16") if r.key == "Pictogram exclamation mark")
    assert row.status == "check" and row.citation.endswith("C.2.1.2")


def test_aquatic_hazards_on_an_osha_sheet_are_a_note(tmp_path):
    report = _sheet(tmp_path, regulation="us_osha", classes=["Flammable liquids - Category 2"],
                    codes=["H225"], signal="Danger",
                    nine=["Flash point: 10 °C", "Initial boiling point: 80 °C"])
    report_h400 = _sheet(tmp_path, regulation="un_ghs", name="g.pdf",
                         classes=["Hazardous to the aquatic environment, acute hazard Category 1"],
                         codes=["H400"], signal="Warning")
    assert ("Aquatic hazard", "info") not in _status(report, "C-16")      # none stated
    assert all(s != "fix" for _, s in _status(report_h400, "C-16"))


# -- C-17 flammable liquids -------------------------------------------------------

@pytest.mark.parametrize(("nine", "status"), [
    (["Flash point: 10 °C", "Initial boiling point: 80 °C"], "ok"),
    (["Flash point: 50 °F (closed cup)", "Initial boiling point: 176 °F"], "ok"),   # 10 °C, 80 °C
    (["Flash point: 40 °C"], "fix"),                                               # Category 3
    (["Flash point: 20 - 25 °C", "Initial boiling point: 80 °C"], "check"),        # spans 23 °C
    (["Melting point: -90 °C"], "check"),                                          # no flash point
])
def test_section_9_against_a_stated_flam_liq_2(tmp_path, nine, status):
    report = _sheet(tmp_path, classes=["Flam. Liq. 2"], codes=["H225"], signal="Danger",
                    nine=nine)
    assert [r.status for r in _rows(report, "C-17")] == [status]


def test_a_flash_point_between_60_and_93_is_category_4_only_where_it_exists(tmp_path):
    eu = _sheet(tmp_path, classes=[], codes=[], signal=False, nine=["Flash point: 75 °C"])
    us = _sheet(tmp_path, regulation="us_osha", name="us.pdf", classes=[], codes=[],
                signal=False, nine=["Flash point: 75 °C"])
    assert [r.status for r in _rows(eu, "C-17")] == ["ok"]         # not flammable under CLP
    us_row = _rows(us, "C-17")[0]
    assert us_row.status == "fix" and "Category 4" in us_row.text
    assert us_row.citation.endswith("Table B.6.1")


# -- C-18 Section 11 mixture data ----------------------------------------------------

def test_a_mixture_ld50_is_judged_and_an_ingredients_is_not(tmp_path):
    report = _sheet(tmp_path, classes=["Acute Tox. 4"], codes=["H302"], eleven=[
        "Synthetic component A (CAS 000-00-0): LD50 oral, rat: 50 mg/kg",
        "Product as a whole: LD50 oral, rat: 1200 mg/kg"])
    rows = _rows(report, "C-18")
    assert [(r.key, r.status) for r in rows] == [("Acute toxicity, oral", "ok")]
    assert "1200 mg/kg" in rows[0].text and "Category 4" in rows[0].text


def test_section_2_weaker_than_the_mixture_data_is_a_fault_stricter_one_to_check(tmp_path):
    weaker = _sheet(tmp_path, classes=["Acute Tox. 4"], codes=["H302"], name="w.pdf",
                    eleven=["Mixture: LD50 oral, rat: 150 mg/kg"])
    stricter = _sheet(tmp_path, classes=["Acute Tox. 4"], codes=["H302"], name="s.pdf",
                      eleven=["Mixture: LD50 oral, rat: 3000 mg/kg"])
    assert [r.status for r in _rows(weaker, "C-18")] == ["fix"]
    assert [r.status for r in _rows(stricter, "C-18")] == ["check"]


# -- C-19 Section 12 mixture data -----------------------------------------------------

def test_a_mixture_ec50_gives_aquatic_acute_1(tmp_path):
    report = _sheet(tmp_path, classes=[], codes=[], signal=False, twelve=[
        "Synthetic component A (CAS 000-00-0): EC50 48 h daphnia 0.01 mg/l",
        "Mixture: EC50 48 h daphnia 0.5 mg/l"])
    row = _rows(report, "C-19")[0]
    assert row.status == "fix" and "Aquatic Acute 1" in row.text
    assert "4.1.3.3.1" in row.citation or "Table 4.1.0" in row.citation


@pytest.mark.parametrize(("degradable", "status"), [
    (["The product is readily biodegradable."], "fix"),     # rapid: Chronic 2, stated none
    ([], "check"),                                          # Chronic 1 or 2: not said which
])
def test_long_term_categories_follow_what_section_12_says_of_degradability(
        tmp_path, degradable, status):
    report = _sheet(tmp_path, classes=[], codes=[], signal=False,
                    twelve=["Mixture: NOEC 21 d daphnia 0.05 mg/l", *degradable])
    rows = [r for r in _rows(report, "C-19") if "long-term" in r.key]
    assert [r.status for r in rows] == [status]


def test_aquatic_data_is_not_judged_where_the_regulation_has_no_aquatic_class(tmp_path):
    report = _sheet(tmp_path, regulation="us_osha", classes=[], codes=[], signal=False,
                    twelve=["Mixture: EC50 48 h daphnia 0.5 mg/l"])
    assert _rows(report, "C-19") == []


# -- C-20 the sheet against itself ------------------------------------------------------

def test_revision_dates_that_differ_are_one_to_check(tmp_path):
    sheet = Sheet(tmp_path / "dates.pdf", structure=("eu_clp", "en"))
    sheet.line("Synthetic Test Solvent - Revision date: 2026-01-15")
    sheet.line("SECTION 1: Identification", bold=True, size=11)
    sheet.page_break()
    sheet.line("Synthetic Test Solvent - Revision date: 2026-01-15")
    sheet.line("SECTION 16: Other information", bold=True, size=11)
    sheet.line("Revision date: 2025-03-01")
    sheet.save()
    report = check_pdf(str(tmp_path / "dates.pdf"), "eu_clp", "en")
    row = next(r for r in report.consistency if r.check == "C-20" and r.key == "Revision date")
    assert row.status == "check" and "not a requirement in the regulation" in row.citation


# -- Section 2 as real sheets print it ----------------------------------------------

def _lines_sheet(tmp_path, regulation, two, nine=(), name="r.pdf"):
    bodies = {"2": list(two), "3": ["Synthetic component A  CAS 000-00-0  30-60%"]}
    if nine:
        bodies["9"] = list(nine)
    path = structured_sheet(tmp_path / name, regulation=regulation, language="en", bodies=bodies)
    return check_pdf(str(path), regulation, "en")


def test_a_signal_word_on_the_line_below_its_label_is_read(tmp_path):
    report = _lines_sheet(tmp_path, "eu_clp", ["Flam. Liq. 2", "Signal word", "Danger",
                                               "H225"], nine=["Flash point: 10 °C",
                                                              "Initial boiling point: 80 °C"])
    assert ("Signal word", "ok") in _status(report, "C-16")


def test_a_statement_printed_in_words_without_its_code_is_printed(tmp_path):
    official = texts("us_osha", "en", ["H372"])["H372"]
    words = official.split("<")[0].strip() + " through prolonged or repeated ingestion exposure"
    report = _lines_sheet(tmp_path, "us_osha", [
        "Specific Target Organ Toxicity (repeated exposure): Category 1.", "Signal word: Danger",
        words])
    row = next(r for r in _rows(report, "C-16") if r.key.startswith("Specific"))
    assert row.status == "ok" and "printed in words" in row.text


def test_a_code_beside_its_category_names_the_class(tmp_path):
    report = _lines_sheet(tmp_path, "eu_clp", ["Classification", "H319", "Category 2",
                                               "Signal word: Warning", "H319"])
    assert ("H319 Category 2", "ok") in _status(report, "C-16")


def test_a_category_the_regulation_does_not_have_is_one_to_check(tmp_path):
    report = _lines_sheet(tmp_path, "eu_clp", ["Serious eye damage/eye irritation Category 2A",
                                               "Signal word: Warning", "H319"])
    row = next(r for r in _rows(report, "C-16") if "2A" in r.key)
    assert row.status == "check" and "no such category" in row.text
    assert not [r for r in _rows(report, "C-16") if r.key == "H319"]


def test_a_class_name_containing_a_pictogram_name_is_not_a_pictogram(tmp_path):
    report = _lines_sheet(tmp_path, "us_osha", ["Skin Corrosion/Irritation Category 2",
                                                "Signal word: Warning", "H315"])
    assert ("Pictograms", "na") in _status(report, "C-16")


def test_a_flash_point_with_an_ordinal_degree_sign_is_read(tmp_path):
    report = _lines_sheet(tmp_path, "us_osha", ["Flammable liquids - Category 2",
                                                "Signal word: Danger", "H225"],
                          nine=["Flash point: 6 ºC [Test Method: Closed Cup]",
                                "Initial boiling point: 80 ºC"])
    assert [r.status for r in _rows(report, "C-17")] == ["ok"]
