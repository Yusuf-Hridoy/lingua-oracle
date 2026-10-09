"""C-16 on Section 2 as the app prints it for Australia - each code above
its category - and C-25, Section 9's physical state. Every sheet is
invented; the classes, criteria and quotes come from the keys on file."""

from __future__ import annotations

import json

import pytest

from lingua_oracle.pipeline import check_pdf
from lingua_oracle.registry import data_dir
from tests.make_fixtures import structured_sheet

# Section 2 as the app prints it: the code, then its category on the next line.
_APP_TWO = ["Classification", "H301", "Category 3", "H310", "Category 1, 2", "H315",
            "Category 2", "H318", "Category 1", "H331", "Category 3", "H335", "Category 3",
            "H350", "Category 1, 1A, 1B", "H373", "Category 2", "AUH071", "Signal Word",
            "Danger", "H301", "H310", "H315", "H318", "H331", "H335", "H350", "H373", "AUH071"]


def _report(tmp_path, regulation="au_whs", *, two=_APP_TWO, nine=None):
    bodies = {"2": list(two), "3": ["Synthetic component A  CAS 000-00-0  30-60%"]}
    if nine is not None:
        bodies["9"] = list(nine)
    path = structured_sheet(tmp_path / "t.pdf", regulation=regulation, language="en",
                            bodies=bodies)
    return check_pdf(str(path), regulation, "en")


def _rows(report, check):
    return {r.key: r for r in report.consistency if r.check == check}


def test_every_code_above_its_category_is_read_as_a_classification(tmp_path):
    rows = _rows(_report(tmp_path), "C-16")
    for key in ("H335 Category 3", "H350 Category 1", "H373 Category 2"):
        assert rows[key].status == "ok", key
    assert not [k for k, r in rows.items() if r.status in ("fix", "check")]


def test_auh071_beside_an_inhalation_toxicity_classification_is_ok(tmp_path):
    row = _rows(_report(tmp_path), "C-16")["AUH071"]
    assert row.status == "ok" and "H331 Category 3" in row.text
    assert "in addition to classification for inhalation toxicity" in row.quote


def test_auh071_without_inhalation_toxicity_is_one_to_check(tmp_path):
    two = ["Classification", "H301", "Category 3", "AUH071", "Signal Word", "Danger", "H301",
           "AUH071"]
    row = _rows(_report(tmp_path, two=two), "C-16")["AUH071"]
    assert row.status == "check" and "acute toxicity (inhalation)" in row.text
    assert row.citation.startswith("Safe Work Australia, Guidance on the classification")


def test_a_hazard_statement_the_table_does_not_know_is_one_to_check(tmp_path):
    two = ["Classification", "H301", "Category 3", "Signal Word", "Danger", "H301", "H399"]
    row = _rows(_report(tmp_path, two=two), "C-16")["H399"]
    assert row.status == "check" and "no classification read" in row.text


def test_a_class_the_regulation_leaves_out_is_a_note(tmp_path):
    two = ["Skin corrosion/irritation Category 3", "Signal Word", "Warning", "H316"]
    rows = _rows(_report(tmp_path, two=two), "C-16")
    note = rows["skin corrosion/irritation – category 3"]
    assert note.status == "info" and "not part of" in note.text


@pytest.mark.parametrize("regulation", ["au_whs", "ca_whmis", "un_ghs"])
def test_the_ghs_label_tables_hold_the_health_classes_and_say_what_they_miss(regulation):
    held = json.loads((data_dir() / "label_elements" / f"{regulation}.json").read_text())
    by_code = {h: e for e in held["entries"] for h in e["h_codes"]}
    assert by_code["H350"]["hazard_class"] == "carcinogenicity"
    assert by_code["H340"]["hazard_class"] == "germ cell mutagenicity"
    assert (by_code["H335"]["subclass"], by_code["H373"]["subclass"]) == (
        "single exposure", "repeated exposure")
    assert by_code["H260"]["hazard_class"].startswith("substances and mixtures which, in contact")
    # Whatever is not read is said: every code is an entry or an unparsed line.
    # (Rev.11 replaced H200-H203 with H209-H211.)
    unread = " ".join(held["unparsed"])
    explosives = ("H209", "H210") if regulation == "un_ghs" else ("H200", "H201")
    assert all(code in by_code or code in unread
               for code in (*explosives, "H220", "H250", "H280", "H400"))


# -- C-25 Section 9's physical state ---------------------------------------------------

def test_a_stated_state_is_shown_as_printed(tmp_path):
    report = _report(tmp_path, two=["Not classified."],
                     nine=["State :", "aerosol", "Flash point :", "Not specified"])
    row = _rows(report, "C-25")["Physical state"]
    assert row.status == "ok" and row.text.startswith("“aerosol”")
    assert report.physical_state_printed == "aerosol"
    assert any("neither solid nor liquid" in n for n in report.notes)


@pytest.mark.parametrize("regulation, cited, said", [
    ("eu_clp", "Annex II, 9.1(a)", "shall generally be indicated"),
    ("uk_clp", "Annex II, 9.1(a)", "shall be clearly identified"),
    ("un_ghs", "Table A4.3.9.1", "should be indicated"),
    ("ca_whmis", "Schedule 1, item 9(a)", "(a) physical state;"),
    ("us_osha", "Appendix D, Table D.1, 9(a)", "must contain all of the specified information")])
def test_no_stated_state_is_one_to_check_quoting_the_item(tmp_path, regulation, cited, said):
    report = _report(tmp_path, regulation, two=["Not classified."],
                     nine=["Flash point: Not available"])
    row = _rows(report, "C-25")["Physical state"]
    assert row.status == "check" and row.text.startswith("Physical state not stated in Section 9")
    assert row.citation.endswith(cited) and said in row.quote
    assert any("does not state the physical state" in n for n in report.notes)


def test_australia_lists_no_section_9_items_so_there_is_nothing_to_quote(tmp_path):
    report = _report(tmp_path, two=["Not classified."], nine=["Flash point: Not available"])
    row = _rows(report, "C-25")["Physical state"]
    assert row.status == "check" and not row.quote
    assert "Schedule 7 names Section 9 but lists none of its items" in row.text


def test_a_heading_labelled_in_another_language_is_found():
    from lingua_oracle.mixture.state import read_section

    assert read_section(["Fysisk tilstand: Væske", "Flammepunkt: 10 °C"]) == ("liquid", "Væske")


def test_a_language_the_state_labels_do_not_cover_is_not_checked(tmp_path):
    hungarian = check_pdf(str(structured_sheet(tmp_path / "hu.pdf", regulation="eu_clp",
                                               language="hu", bodies={})), "eu_clp", "hu")
    row = _rows(hungarian, "C-25")["Physical state"]
    assert row.status == "na" and "is read in" in row.text
    english = _report(tmp_path, "eu_clp", two=["Not classified."], nine=["Flash point: 10 °C"])
    assert _rows(english, "C-25")["Physical state"].status == "check"


def test_each_regulation_names_its_own_list():
    from lingua_oracle.substances.lists import LISTS

    assert {k: v.short for k, v in LISTS.items()} == {
        "eu_clp": "Annex VI", "uk_clp": "GB MCL", "au_whs": "HCIS",
        "us_osha": "EU Annex VI (reference)", "ca_whmis": "EU Annex VI (reference)",
        "un_ghs": "EU Annex VI (reference)"}


def test_a_code_printed_with_its_letter_in_another_case_is_the_same_code(tmp_path):
    two = ["Repr. 2", "Signal word: Warning", "H361D"]
    report = check_pdf(str(structured_sheet(tmp_path / "eu.pdf", regulation="eu_clp",
                                            language="en", bodies={"2": two})), "eu_clp", "en")
    rows = _rows(report, "C-16")
    assert "H361D" not in rows and rows["Repr. 2"].status == "ok"


def test_a_label_with_its_value_below_and_no_colon_is_read():
    from lingua_oracle.mixture.state import read_section

    assert read_section(["Appearance", "Physical state", "Liquid"]) == ("liquid", "Liquid")
    assert read_section(["Physical state", ":", "solid"]) == ("solid", "solid")
    assert read_section(["Physical state ", ": liquid"]) == ("liquid", "liquid")
