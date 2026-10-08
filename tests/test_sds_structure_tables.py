"""The structure each regulation requires of an SDS, as read from its own text.

data/sds_structure/<reg>.json is built by `lingua keys build sds_structure`;
these tests read the committed files and never the network or the sources.
"""

from __future__ import annotations

import json

import pytest

from lingua_oracle.keys.builders import sds_structure
from lingua_oracle.registry import data_dir


def _load(regulation):
    return json.loads((data_dir() / "sds_structure" / f"{regulation}.json")
                      .read_text(encoding="utf-8"))


@pytest.mark.parametrize("regulation", sds_structure.REGULATIONS)
def test_every_table_has_sixteen_sections_and_quoted_rules(regulation):
    table = _load(regulation)
    assert [s["number"] for s in table["sections"]] == [str(n) for n in range(1, 17)]
    assert table["headings"]["quote"] and table["headings"]["citation"]
    for item in table["items"]:
        assert item["rule"]["quote"] and item["rule"]["citation"], item["id"]


def test_eu_headings_come_from_every_language_with_its_own_act():
    table = _load("eu_clp")
    assert len(table["languages"]) == 23 and "ga" in table["pending_languages"]
    one, sixteen = table["sections"][0], table["sections"][15]
    assert one["heading"]["en"] == ("Identification of the substance/mixture and of the "
                                    "company/undertaking")
    assert one["label"]["de"] == "ABSCHNITT {n}:" and sixteen["heading"]["de"] == "Sonstige Angaben"
    assert one["label"]["da"] == "PUNKT {n}:" and sixteen["heading"]["da"] == "Andre oplysninger"
    assert one["label"]["fr"] == "RUBRIQUE {n} —" and sixteen["heading"]["fr"] == "Autres informations"
    assert one["label"]["et"] == "{n}. JAGU."
    for section in table["sections"]:
        for sub in section["subsections"]:
            assert set(sub["heading"]) == set(table["languages"]), sub["number"]
    assert sum(len(s["subsections"]) for s in table["sections"]) == 51
    assert table["one_of"] == [["3.1", "3.2"]]


def test_the_eu_rules_are_quoted_and_bind():
    table = _load("eu_clp")
    assert table["headings"]["binding"] and table["headings"]["citation"] == "Annex II, Part B"
    assert table["order"] is None                       # Part B states no order
    assert table["empty"]["quote"] == "The safety data sheet shall not contain blank subsections."
    items = {i["id"]: i for i in table["items"]}
    assert items["supplier_email"]["scope"] == "1.3"
    assert "e-mail address for a competent person" in items["supplier_email"]["rule"]["quote"] \
        or "email address for a competent person" in items["supplier_email"]["rule"]["quote"]
    assert items["emergency_telephone"]["scope"] == "1.4"
    assert items["date_of_compilation"]["scope"] == "first_page"


def test_gb_is_its_own_text_not_the_eus():
    gb = {s["number"]: s for s in _load("uk_clp")["sections"]}
    assert [x["number"] for x in gb["11"]["subsections"]] == ["11.1"]
    assert gb["12"]["subsections"][-1]["heading"]["en"] == "Other adverse effects"
    assert gb["14"]["subsections"][-1]["heading"]["en"].startswith("Transport in bulk")


def test_osha_makes_12_to_15_optional_and_states_no_order():
    table = _load("us_osha")
    optional = [s["number"] for s in table["sections"] if not s["required"]]
    assert optional == ["12", "13", "14", "15"]
    assert table["optional"]["quote"] == ("Sections 12-15 may be included in the SDS, but "
                                          "are not mandatory.")
    assert table["order"] is None
    assert table["sections"][15]["heading"]["en"] == (
        "Other information, including date of preparation or last revision")
    items = {i["id"]: i for i in table["items"]}
    assert items["date_of_revision"]["scope"] == "16"


def test_canada_reads_both_languages_and_states_the_order():
    table = _load("ca_whmis")
    two = table["sections"][1]
    assert two["heading"] == {"en": "Hazard identification", "fr": "Identification des dangers"}
    assert table["order"]["citation"].startswith(
        "Hazardous Products Regulations (SOR/2015-17), section 4(1)(a)")
    assert [s["number"] for s in table["sections"] if s["content_optional"]] == [
        "12", "13", "14", "15"]


def test_the_ghs_says_should_and_so_does_not_bind():
    table = _load("un_ghs")
    assert table["headings"]["binding"] is False and table["order"]["binding"] is False
    assert all(not item["rule"]["binding"] for item in table["items"])


def test_australia_states_headings_and_order_but_nothing_on_empty_parts():
    table = _load("au_whs")
    assert table["headings"]["binding"] and table["order"]
    assert table["empty"] is None
    assert table["sections"][1]["heading"]["en"] == "Hazard(s) identification"
    assert {i["scope"] for i in table["items"]} == {"document"}


@pytest.mark.parametrize(("title", "label", "heading"), [
    ("SECTION 1: Identification of the mixture", "SECTION {n}:", "Identification of the mixture"),
    ("1. JAGU. Aine identifitseerimine", "{n}. JAGU.", "Aine identifitseerimine"),
    ("1 SKIRSNIS. Medžiagos", "{n} SKIRSNIS.", "Medžiagos"),
    ("ODJELJAK 1.: Identifikacija", "ODJELJAK {n}.:", "Identifikacija"),
])
def test_a_title_splits_into_its_label_and_its_heading(title, label, heading):
    found_label, found_heading = sds_structure._split_title(title, "1")
    assert " ".join(found_label.split()) == label and found_heading == heading


def test_a_rule_binds_by_its_own_verb():
    assert sds_structure._verb("The SDS shall not contain blank subsections.") is True
    assert sds_structure._verb("The SDS must use the headings.") is True
    assert sds_structure._verb("The SDS should not contain any blanks.") is False
