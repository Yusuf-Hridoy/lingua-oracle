"""What the page tells a reader: the shortest valid text to use, the list
each regulation's ingredients are held against, and how much was judged."""

from __future__ import annotations

import pytest

from lingua_oracle.report import labels, sections, suggest
from tests.make_fixtures import texts


@pytest.mark.parametrize("regulation", ["au_whs", "eu_clp", "us_osha", "un_ghs"])
def test_h373_is_suggested_without_its_optional_slots(regulation):
    official = texts(regulation, "en", ["H373"])["H373"]
    use, note = suggest.shortest(official)
    assert use.rstrip(".") == "May cause damage to organs through prolonged or repeated exposure"
    assert note == "all organs affected / route of exposure may be added"
    assert "(" not in use and "<" not in use and "state" not in use


def test_an_optional_group_is_left_out_and_named():
    use, note = suggest.shortest(texts("un_ghs", "en", ["P264+P265"])["P264+P265"])
    assert use == "Wash hands thoroughly after handling. Do not touch eyes."
    assert note == "“and…” may be added"


def test_a_required_slot_is_shown_as_a_blank_with_what_goes_in_it():
    use, note = suggest.shortest("Contains <name of sensitising substance>. May produce an "
                                 "allergic reaction.")
    assert use.startswith("Contains …") and "<" not in use
    assert note == "fill in “…”: name of sensitising substance"


def test_official_text_is_shown_without_stray_spaces():
    assert suggest.tidy("organs ( state all organs affected, if known) through") == \
        "organs (state all organs affected, if known) through"
    assert suggest.tidy("[and … ]") == "[and …]"


@pytest.mark.parametrize("regulation, named, text", [
    ("au_whs", "HCIS", "no entry in HCIS"), ("uk_clp", "GB MCL", "no entry in GB MCL"),
    ("eu_clp", "Annex VI", "no harmonised entry in Annex VI"),
    ("us_osha", "EU Annex VI (reference)", "no entry in EU Annex VI (reference)")])
def test_section_3_names_the_list_actually_used(regulation, named, text):
    from lingua_oracle.models import Report

    report = Report.model_construct(regulation=regulation)
    assert sections._list_name(report) == named
    assert sections._reason("no_harmonised_entry", named) == text
    expected = ("No substance had a harmonised entry in Annex VI Table 3."
                if named == "Annex VI" else f"No substance had an entry in {named}.")
    assert sections._named_message("No substance had a harmonised entry in Annex VI Table 3.",
                                    named) == expected


def test_ranges_are_written_as_a_reader_would():
    assert labels._ranges([1, 2, 9, 14]) == "1, 2, 9 and 14"
    assert labels._ranges([3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 15, 16]) == \
        "3–8, 10–13, 15 and 16"


def test_a_structure_only_section_says_so_and_a_judged_one_does_not():
    structure = sections.Section("5", "Firefighting measures", subs=[
        sections.Sub("Structure", [sections.Row("Number", "ok")], structure=True)])
    judged = sections.Section("9", "Physical and chemical properties", subs=[
        sections.Sub("Structure", [sections.Row("Number", "ok")], structure=True),
        sections.Sub("Physical state", [sections.Row("Physical state", "ok")])])
    assert (structure.pill, judged.pill) == ("structure", "ok")
    assert sections.PILL["structure"][0] == "Structure correct"
    detail = sections._detail([structure, judged])
    assert detail == "Section 9 is correct. Section 5 has correct structure."
