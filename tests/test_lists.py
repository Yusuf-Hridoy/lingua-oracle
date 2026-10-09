"""The official lists in data/lists: built from their own sources, and
whole - every number in the form its list uses, every CAS number's check
digit right, and entries everyone knows where they belong."""

from __future__ import annotations

import re

import pytest

from lingua_oracle.keys.builders import lists


@pytest.fixture(scope="module")
def hmt():
    return lists.load("us_dot_hmt")


@pytest.fixture(scope="module")
def svhc():
    return lists.load("svhc_candidate")


def test_the_cas_check_digit():
    assert lists.cas_valid("7732-18-5")              # water
    assert lists.cas_valid("67-64-1")                # acetone
    assert not lists.cas_valid("67-64-2")
    assert not lists.cas_valid("not a number")


def test_every_hmt_identification_number_is_un_or_na_and_four_digits(hmt):
    assert hmt["status"] == "ok" and len(hmt["entries"]) > 2000
    assert all(re.fullmatch(r"(?:UN|NA)\d{4}", e["id"]) for e in hmt["entries"])
    assert all(set(e["packing_groups"]) <= {"I", "II", "III"} for e in hmt["entries"])


def test_known_hmt_entries(hmt):
    by_id = {}
    for e in hmt["entries"]:
        by_id.setdefault(e["id"], []).append(e)
    acetone = by_id["UN1090"]
    assert [(e["name"], e["class"], e["packing_groups"]) for e in acetone] == [
        ("Acetone", "3", ["II"])]
    assert any(e["name"].startswith("Flammable liquids, n.o.s.") and e["class"] == "3"
               and e["packing_groups"] == ["I", "II", "III"] for e in by_id["UN1993"])


def test_the_class_3_criterion_is_quoted_from_173_120(hmt):
    assert hmt["class_3"]["quote"].startswith("(a) Flammable liquid.")
    assert "60 °C (140 °F)" in hmt["class_3"]["quote"]
    assert hmt["class_3"]["citation"].startswith("49 CFR 173.120(a)")


def test_every_candidate_list_cas_number_has_a_right_check_digit(svhc):
    assert svhc["status"] == "ok" and svhc["invalid_cas"] == []
    numbers = [c for e in svhc["entries"] for c in e["cas"]]
    assert numbers and all(lists.cas_valid(c) for c in numbers)
    assert all(re.fullmatch(r"\d{3}-\d{3}-\d", ec) for e in svhc["entries"] for ec in e["ec"])


def test_the_candidate_list_entries_and_annex_ii_quotes(svhc):
    assert len(svhc["entries"]) == 507
    assert all(e["name"] and e["reason"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"])
               for e in svhc["entries"])
    for key in ("3.2.1(a)", "3.2.1(c)", "2.3", "15.1"):
        assert svhc["annex_ii"][key]["quote"], key
        assert svhc["annex_ii"][key]["citation"].endswith(f"Annex II, {key}")
    assert "0,1 %" in svhc["annex_ii"]["3.2.1(c)"]["quote"]


def test_the_un_list_is_pending_until_its_source_is_on_file():
    un = lists.load("un_dangerous_goods")
    assert un["status"] == "pending_source" and un["entries"] == []
    assert "not on file" in un["why"]


def test_proper_shipping_names_are_the_roman_type_with_italic_or_as_a_choice(hmt):
    """172.101(c)(2)'s own examples: "Carbon dioxide, solid or Dry ice" and
    "Articles, pressurized pneumatic or hydraulic"."""
    names = {e["name"]: e["proper_shipping_names"] for e in hmt["entries"]}
    dry = next(v for k, v in names.items() if k.startswith("Carbon dioxide, solid"))
    assert dry == ["Carbon dioxide, solid", "Dry ice"]
    articles = next(v for k, v in names.items() if k.startswith("Articles, pressurized"))
    assert {"Articles, pressurized pneumatic", "Articles, pressurized hydraulic"} <= set(articles)
    assert all(e["proper_shipping_names"] for e in hmt["entries"])
    for key in ("c", "c1", "c2"):
        assert hmt["name_rules"][key]["quote"], key
    assert "Roman type (not italics)" in hmt["name_rules"]["c"]["quote"]
