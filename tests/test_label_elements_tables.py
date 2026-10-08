"""Label elements and criteria per regulation, as read from each text.

data/label_elements/ and data/hazard_criteria/ are built by `lingua keys
build label_elements` and `... hazard_criteria`; these tests read the files.
"""

from __future__ import annotations

import json

import pytest

from lingua_oracle.registry import data_dir


def _label(regulation):
    return json.loads((data_dir() / "label_elements" / f"{regulation}.json").read_text("utf-8"))


def _criteria(regulation):
    return json.loads((data_dir() / "hazard_criteria" / f"{regulation}.json").read_text("utf-8"))


def _entry(table, code, category=None):
    return next(e for e in table["entries"] if code in e["h_codes"]
                and (category is None or category in e["category"]))


@pytest.mark.parametrize(("regulation", "pictogram"), [
    ("eu_clp", "GHS02"), ("uk_clp", "GHS02"), ("un_ghs", "Flame"), ("au_whs", "Flame"),
    ("ca_whmis", "Flame"), ("us_osha", "Flame")])
def test_flammable_liquid_2_is_danger_h225_and_its_pictogram(regulation, pictogram):
    entry = _entry(_label(regulation), "H225")
    assert entry["signal"] == "Danger" and "2" in entry["category"]
    assert [p.lower() for p in entry["pictograms"]] == [pictogram.lower()]


def test_eu_reads_codes_from_annex_vi_and_pictograms_from_annex_v():
    table = _label("eu_clp")
    assert _entry(table, "H225")["codes"] == ["Flam. Liq. 2"]
    assert _entry(table, "H302")["pictograms"] == ["GHS07"]
    assert _entry(table, "H412")["pictograms"] == []          # Chronic 3: none
    stot = _entry(table, "H335")
    assert set(stot["h_codes"]) == {"H335", "H336"} and stot["codes"] == ["STOT SE 3"]


def test_precedence_is_quoted_from_each_text_with_its_force():
    eu = _label("eu_clp")
    rule = next(r for r in eu["pictogram_rules"] if r["when"] == ["GHS06"])
    assert rule["drop"] == "GHS07" and rule["effect"] == "not_appear"
    assert rule["rule"]["citation"].endswith("Article 26(1)(b)") and rule["rule"]["binding"]
    assert eu["signal_rule"]["citation"].endswith("Article 20(3)")
    h318 = next(r for r in eu["statement_rules"] if r["drop"] == "H318")
    assert h318["effect"] == "may_omit" and not h318["rule"]["binding"]
    ghs = _label("un_ghs")
    assert all(not r["rule"]["binding"] for r in ghs["pictogram_rules"])   # "should"
    osha = _label("us_osha")
    assert osha["signal_rule"]["citation"].endswith("C.2.1.1") and osha["signal_rule"]["binding"]


def test_australia_records_what_it_leaves_out():
    out = [x["what"] for x in _label("au_whs")["not_adopted"]]
    assert any("category 5" in x for x in out) and any("aquatic" in x for x in out)


@pytest.mark.parametrize(("regulation", "categories"), [
    ("eu_clp", ["1", "2", "3"]), ("uk_clp", ["1", "2", "3"]), ("un_ghs", ["1", "2", "3", "4"]),
    ("au_whs", ["1", "2", "3", "4"]), ("ca_whmis", ["1", "2", "3", "4"]),
    ("us_osha", ["1", "2", "3", "4"])])
def test_flammable_liquid_categories_are_each_texts_own(regulation, categories):
    rows = _criteria(regulation)["flammable_liquids"]["categories"]
    assert [r["category"] for r in rows] == categories
    assert rows[0]["flash"] == [["<", "23"]] and rows[0]["boiling"] == ["<=", "35"]


@pytest.mark.parametrize(("regulation", "status"), [
    ("eu_clp", "ok"), ("uk_clp", "ok"), ("un_ghs", "ok"), ("au_whs", "not_adopted"),
    ("ca_whmis", "not_adopted"), ("us_osha", "not_adopted")])
def test_aquatic_criteria_or_why_there_are_none(regulation, status):
    aquatic = _criteria(regulation)["aquatic"]
    assert aquatic["status"] == status
    if status == "ok":
        acute = [r for r in aquatic["categories"] if r["kind"] == "acute"]
        assert acute[0]["upper"] == "1"
