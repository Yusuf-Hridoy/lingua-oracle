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


@pytest.fixture(scope="module")
def un():
    return lists.load("un_dangerous_goods")


def _by_id(held):
    out = {}
    for e in held["entries"]:
        out.setdefault(e["id"], []).append(e)
    return out


def test_every_un_number_is_four_digits_and_in_order(un):
    assert un["status"] == "ok" and "Rev.24" in un["version"]
    ids = [e["id"] for e in un["entries"]]
    assert all(re.fullmatch(r"UN\d{4}", i) for i in ids)
    assert ids == sorted(ids) and len(set(ids)) > 2300
    assert all(set(e["packing_groups"]) <= {"I", "II", "III"} for e in un["entries"])
    assert all(re.fullmatch(r"(?:\d(?:\.\d)?[A-S]?)?", e["class"]) for e in un["entries"])


def test_known_un_entries(un):
    by_id = _by_id(un)
    assert [(e["proper_shipping_names"], e["class"], e["packing_groups"])
            for e in by_id["UN1090"]] == [(["ACETONE"], "3", ["II"])]
    assert [e["packing_groups"] for e in by_id["UN1993"]] == [["I"], ["II"], ["III"]]
    assert all(e["proper_shipping_names"] == ["FLAMMABLE LIQUID, N.O.S."]
               for e in by_id["UN1993"])
    assert [(e["proper_shipping_names"], e["class"]) for e in by_id["UN1001"]] == [
        (["ACETYLENE, DISSOLVED"], "2.1")]
    assert by_id["UN1045"][0]["subsidiary_hazards"] == ["5.1", "8"]


def test_un_names_are_the_upper_case_with_3_1_2_2s_own_examples(un):
    by_id = _by_id(un)
    assert by_id["UN1057"][0]["proper_shipping_names"] == ["LIGHTERS", "LIGHTER REFILLS"]
    ferrous = set(by_id["UN2793"][0]["proper_shipping_names"])
    assert {"FERROUS METAL BORINGS", "FERROUS METAL SHAVINGS", "FERROUS METAL TURNINGS",
            "FERROUS METAL CUTTINGS"} <= ferrous and "CUTTINGS" not in ferrous
    # 3.1.2.1: "An alternative proper shipping name may be shown in brackets".
    assert {"ETHANOL", "ETHYL ALCOHOL"} <= set(by_id["UN1170"][0]["proper_shipping_names"])
    for role, key in (("what", "3.1.2.1"), ("choices", "3.1.2.2"), ("spelling", "3.1.2.3")):
        assert un["name_rules"][role]["quote"].startswith(key), role
        assert un["name_rules"][role]["citation"].endswith(key)


def test_proper_shipping_names_are_the_roman_type_with_italic_or_as_a_choice(hmt):
    """172.101(c)(2)'s own examples: "Carbon dioxide, solid or Dry ice" and
    "Articles, pressurized pneumatic or hydraulic"."""
    names = {e["name"]: e["proper_shipping_names"] for e in hmt["entries"]}
    dry = next(v for k, v in names.items() if k.startswith("Carbon dioxide, solid"))
    assert dry == ["Carbon dioxide, solid", "Dry ice"]
    articles = next(v for k, v in names.items() if k.startswith("Articles, pressurized"))
    assert {"Articles, pressurized pneumatic", "Articles, pressurized hydraulic"} <= set(articles)
    assert all(e["proper_shipping_names"] for e in hmt["entries"])
    for role in ("what", "spelling", "choices"):
        assert hmt["name_rules"][role]["quote"], role
    assert "Roman type (not italics)" in hmt["name_rules"]["what"]["quote"]


def test_class_2_and_class_3_are_quoted_with_the_flash_point_limits_from_the_text(un):
    rules = un["class_rules"]
    assert rules["2.2.1.1"]["quote"].startswith("2.2.1.1 A gas is a substance which")
    assert rules["2.3.1.1"]["quote"].startswith("2.3.1.1 Class 3 includes")
    assert "not more than 60 °C, closed-cup test" in rules["2.3.1.2"]["quote"]
    assert rules["flash_point_limit"] == {"closed_cup": 60.0, "open_cup": 65.6}
