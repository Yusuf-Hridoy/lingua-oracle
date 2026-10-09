"""C-21 and C-22 on synthetic sheets: Section 14 against the dangerous goods
list, Sections 3, 2 and 15 against the ECHA Candidate List. Every sheet is
invented; list entries are read from data/lists, never written here."""

from __future__ import annotations

import pytest

from lingua_oracle.consistency import svhc
from lingua_oracle.keys.builders import lists
from lingua_oracle.pipeline import check_pdf
from tests.make_fixtures import flash_lines, structured_sheet

_COMPONENT = "Synthetic component A  CAS 000-00-0  30-60%"


def _sheet(tmp_path, regulation, *, two=(), three=(_COMPONENT,), fourteen=(), fifteen=(),
           nine=(), name="t.pdf"):
    bodies = {"2": list(two) or ["Not classified."], "3": list(three)}
    for number, lines in (("9", nine), ("14", fourteen), ("15", fifteen)):
        if lines:
            bodies[number] = list(lines)
    path = structured_sheet(tmp_path / name, regulation=regulation, language="en", bodies=bodies)
    return check_pdf(str(path), regulation, "en")


def _rows(report, check):
    return [r for r in report.consistency if r.check == check]


def _findings(report, check):
    return [f for f in report.findings if f.check_id == check]


# -- C-21 Section 14 ------------------------------------------------------------------

_ACETONE = ["UN number: UN1090", "UN proper shipping name: Acetone",
            "Transport hazard class(es): 3", "Packing group: II"]


def test_a_dot_entry_as_the_table_gives_it_is_ok(tmp_path):
    report = _sheet(tmp_path, "us_osha", fourteen=["DOT"] + _ACETONE)
    rows = _rows(report, "C-21")
    assert [(r.key, r.status) for r in rows] == [("DOT UN1090", "ok")]
    assert "49 CFR 172.101" in rows[0].citation


@pytest.mark.parametrize("change, key, expected", [
    (("UN proper shipping name: Acetone", "UN proper shipping name: Ethanol"), "name",
     "Acetone"),
    (("Transport hazard class(es): 3", "Transport hazard class(es): 8"), "class", "3"),
    (("Packing group: II", "Packing group: III"), "packing group", "II"),
])
def test_a_name_class_or_packing_group_the_table_does_not_give_is_a_fault(
        tmp_path, change, key, expected):
    block = [change[1] if line == change[0] else line for line in _ACETONE]
    report = _sheet(tmp_path, "us_osha", fourteen=["DOT"] + block)
    row = next(r for r in _rows(report, "C-21") if r.key == f"DOT UN1090 {key}")
    assert row.status == "fix" and row.expected == expected
    assert any(f.severity.value == "fail" for f in _findings(report, "C-21"))


def test_a_number_not_in_the_table_is_a_fault(tmp_path):
    report = _sheet(tmp_path, "us_osha", fourteen=["UN number: UN0000",
                                                   "UN proper shipping name: Synthetic liquid"])
    row = _rows(report, "C-21")[0]
    assert row.status == "fix" and row.found == "UN0000" and "not in the" in row.text


def test_a_dot_block_printed_inline_is_read(tmp_path):
    report = _sheet(tmp_path, "us_osha", fourteen=["DOT", "UN1993, Flammable liquids, n.o.s. "
                                                   "(synthetic solvent), 3, PG II"])
    assert [(r.key, r.status) for r in _rows(report, "C-21")] == [("DOT UN1993", "ok")]


def test_a_number_on_the_line_below_its_label_is_read(tmp_path):
    report = _sheet(tmp_path, "us_osha", fourteen=["UN ID Number:", "1090", "Shipping Name:",
                                                   "ACETONE", "Class or Division:", "3",
                                                   "Packaging Group:", "II"])
    assert [(r.key, r.status) for r in _rows(report, "C-21")] == [("Transport UN1090", "ok")]


def test_not_regulated_against_flam_liq_on_a_us_sheet_quotes_173_120(tmp_path):
    codes = ["H225"]
    report = _sheet(tmp_path, "us_osha", two=["Flammable liquids - Category 2",
                                              "Signal word: Danger", "H225"],
                    nine=flash_lines("en", codes), fourteen=["DOT: Not regulated."])
    row = _rows(report, "C-21")[0]
    assert row.status == "check" and row.citation.startswith("49 CFR 173.120(a)")
    assert "flammable liquid (Class 3)" in row.quote


def test_not_regulated_against_flam_liq_elsewhere_says_the_list_does_not_decide(tmp_path):
    report = _sheet(tmp_path, "eu_clp", two=["Flam. Liq. 2", "Signal word: Danger", "H225"],
                    nine=flash_lines("en", ["H225"]),
                    fourteen=["Not classified as dangerous goods for transport."])
    row = _rows(report, "C-21")[0]
    assert row.status == "check" and "does not decide it" in row.text and not row.quote


def test_not_regulated_with_nothing_against_it_is_ok(tmp_path):
    report = _sheet(tmp_path, "eu_clp", fourteen=["Not regulated for transport."])
    assert [(r.key, r.status) for r in _rows(report, "C-21")] == [("Not regulated", "ok")]


def test_a_un_number_off_us_sheets_is_not_checked_while_the_un_list_is_not_on_file(tmp_path):
    report = _sheet(tmp_path, "eu_clp", fourteen=["ADR/RID"] + _ACETONE)
    row = _rows(report, "C-21")[0]
    assert row.status == "na" and row.text.startswith("Not checked (list not on file)")
    assert _findings(report, "C-21") == []


def test_an_imdg_block_on_a_us_sheet_is_held_against_the_un_list(tmp_path):
    report = _sheet(tmp_path, "us_osha", fourteen=["DOT"] + _ACETONE + ["IMDG"] + _ACETONE)
    assert [(r.key, r.status) for r in _rows(report, "C-21")] == [
        ("DOT UN1090", "ok"), ("IMDG UN1090", "na")]


# -- C-22 Candidate List --------------------------------------------------------------

def _entry(endocrine: bool):
    """A Candidate List entry with one CAS number, read from the list."""
    held = lists.load("svhc_candidate")
    return next(e for e in held["entries"] if len(e["cas"]) == 1
                and ("endocrine" in e["reason"].lower()) == endocrine
                and not svhc._hazard_reason(e["reason"]) and len(e["name"]) < 60)


def _svhc_sheet(tmp_path, regulation="eu_clp", *, endocrine=False, share="1-5%", two=(),
                fifteen=()):
    entry = _entry(endocrine)
    three = [_COMPONENT, f"Synthetic component B  CAS {entry['cas'][0]}  {share}"]
    return entry, _sheet(tmp_path, regulation, two=two, three=three, fifteen=fifteen)


def test_a_candidate_list_substance_named_in_3_and_15_is_ok(tmp_path):
    entry = _entry(False)
    _, report = _svhc_sheet(tmp_path, fifteen=[
        "Substances of very high concern (Candidate List, REACH Article 59): "
        f"CAS {entry['cas'][0]}"])
    assert {(r.section, r.status) for r in _rows(report, "C-22")} == {("3", "ok"), ("15", "ok")}


def test_section_15_silent_on_a_candidate_list_substance_is_one_to_check(tmp_path):
    _, report = _svhc_sheet(tmp_path, fifteen=["No further regulatory information."])
    row = next(r for r in _rows(report, "C-22") if r.section == "15")
    assert row.status == "check" and row.citation.endswith("Annex II, 15.1")
    assert row.quote.startswith("15.1.")


def test_below_0_1_percent_the_list_asks_nothing(tmp_path):
    _, report = _svhc_sheet(tmp_path, share="0.01-0.05%")
    assert _rows(report, "C-22") == []


def test_listed_for_endocrine_disruption_and_section_2_silent_is_a_fault(tmp_path):
    _, report = _svhc_sheet(tmp_path, endocrine=True, fifteen=["SVHC: Candidate List."])
    row = next(r for r in _rows(report, "C-22") if r.section == "2")
    assert row.status == "fix" and row.citation.endswith("Annex II, 2.3")
    assert "0,1 % by weight" in row.quote


def test_listed_for_endocrine_disruption_and_section_2_saying_so_is_ok(tmp_path):
    entry = _entry(True)
    _, report = _svhc_sheet(tmp_path, endocrine=True, two=[
        "Not classified.", f"Contains CAS {entry['cas'][0]}: on the Candidate List for "
        "endocrine disrupting properties."], fifteen=["SVHC: Candidate List."])
    assert next(r for r in _rows(report, "C-22") if r.section == "2").status == "ok"


def test_a_candidate_list_substance_section_3_does_not_name_is_a_fault():
    entry = _entry(False)
    rows = svhc.run("eu_clp", ["Synthetic component A  CAS 000-00-0  30-60%"], [], [],
                    [(entry["cas"][0], "", 2.0)])
    row = next(r for r in rows if r.section == "3")
    assert row.status == "fix" and row.citation.endswith("Annex II, 3.2.1(c)")
    assert "0,1 %" in row.quote


def test_gb_sheets_are_not_checked_without_a_gb_list(tmp_path):
    _, report = _svhc_sheet(tmp_path, "uk_clp")
    assert [(r.status, r.text) for r in _rows(report, "C-22")] == [
        ("na", "Not checked (list not on file): no GB Candidate List is on file.")]


def test_the_candidate_list_is_not_asked_of_other_regulations(tmp_path):
    _, report = _svhc_sheet(tmp_path, "us_osha")
    assert _rows(report, "C-22") == []


# -- C-21 proper shipping names, as 49 CFR 172.101(c) defines them ---------------------

def _dot(tmp_path, number, name, hazard_class="", group=""):
    block = ["DOT", f"UN number: {number}", f"UN proper shipping name: {name}"]
    block += [f"Transport hazard class(es): {hazard_class}"] if hazard_class else []
    block += [f"Packing group: {group}"] if group else []
    return _rows(_sheet(tmp_path, "us_osha", fourteen=block), "C-21")


def test_the_roman_type_name_is_the_proper_shipping_name(tmp_path):
    # "Aerosols, flammable, (each not exceeding 1 L capacity)": Roman "Aerosols".
    assert [r.status for r in _dot(tmp_path, "UN1950", "Aerosols, flammable", "2.1")] == ["ok"]


def test_an_italic_or_offers_either_name(tmp_path):
    assert [r.status for r in _dot(tmp_path, "UN1219", "Isopropyl alcohol", "3", "II")] == ["ok"]


def test_singular_or_plural_and_any_case(tmp_path):
    assert [r.status for r in _dot(tmp_path, "UN1950", "AEROSOL", "2.1")] == ["ok"]


def test_inflammable_for_flammable_is_a_fault_as_c1_says(tmp_path):
    row = _dot(tmp_path, "UN1993", "Inflammable liquids, n.o.s.", "3", "II")[0]
    assert row.status == "fix" and row.citation.startswith("49 CFR 172.101(c)(1)")
    assert "“inflammable” may not be used" in row.quote


def test_a_spelling_difference_is_one_to_check(tmp_path):
    row = _dot(tmp_path, "UN1090", "Acetonne", "3", "II")[0]
    assert row.status == "check" and row.citation.startswith("49 CFR 172.101(c)(1)")


def test_a_wrong_name_quotes_the_roman_type_rule(tmp_path):
    row = _dot(tmp_path, "UN1090", "Ethanol", "3", "II")[0]
    assert row.status == "fix" and "Roman type" in row.quote


def test_section_14_as_a_table_with_a_column_per_mode(tmp_path):
    fourteen = ["DOT Classification", "IMDG", "IATA", "UN number", "UN1950", "UN1950", "UN1950",
                "UN proper", "Aerosols", "AEROSOLS", "Aerosols, flammable", "shipping name",
                "Transport", "2.1", "2.1", "2.1", "hazard class(es)", "Packing group", "-", "-",
                "-"]
    report = _sheet(tmp_path, "us_osha", fourteen=fourteen)
    assert [(r.key, r.status) for r in _rows(report, "C-21")] == [
        ("DOT UN1950", "ok"), ("IMDG UN1950", "na"), ("IATA UN1950", "na")]


def test_a_column_table_with_a_wrong_dot_class_is_a_fault(tmp_path):
    fourteen = ["DOT", "IATA", "UN number", "UN1090", "UN1090", "UN proper shipping name",
                "Acetone", "Acetone", "Transport hazard class(es)", "8", "3"]
    report = _sheet(tmp_path, "us_osha", fourteen=fourteen)
    row = next(r for r in _rows(report, "C-21") if r.key == "DOT UN1090 class")
    assert row.status == "fix" and row.found == "8"


def test_section_14_saying_neither_is_not_checked(tmp_path):
    report = _sheet(tmp_path, "us_osha", fourteen=["See the shipping papers."])
    assert [(r.key, r.status) for r in _rows(report, "C-21")] == [("Transport", "na")]
