"""Acute toxicity of mixtures: the rules as read, and the additivity calculation.

The bands, conversion values and rules are read by the builder out of each
regulation's own text and committed under data/acute_toxicity/. These tests
check what was read (categories 1-4 agree across every regulation, as they
must; each regulation's own differences are kept) and the arithmetic, on
synthetic sheets - a GB coolant in a real one's shape, invented product.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from lingua_oracle.keys.builders import acute_toxicity as builder
from lingua_oracle.mixture import acute, acute_table
from lingua_oracle.mixture.model import MixtureIngredient, from_codes
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf
from tests.make_fixtures import _glycol_coolant

REGULATIONS = ("eu_clp", "uk_clp", "un_ghs", "au_whs", "ca_whmis", "us_osha")


# -- reading the tables ------------------------------------------------------------

def test_bands_read_from_a_clp_shaped_table():
    text = ("Oral (mg/kg bodyweight) ATE ≤ 5 5 < ATE ≤ 50 50 < ATE ≤ 300 300 < ATE ≤ 2 000 "
            "See: Note (a) Dermal (mg/kg bodyweight) ATE ≤ 50 50 < ATE ≤ 200 "
            "200 < ATE ≤ 1 000 1 000 < ATE ≤ 2 000 See")
    bands = builder.bands_in(text)
    assert [b["high"] for b in bands["oral"]] == ["5", "50", "300", "2000"]
    assert [b["high"] for b in bands["dermal"]] == ["50", "200", "1000", "2000"]


def test_bands_read_from_an_osha_shaped_table():
    text = "Oral (mg/kg bodyweight) see: Note (a) ATE ≤5 >5 ATE ≤50 >50 ATE ≤300 >300 ATE ≤2000. Note (b)"
    assert [b["high"] for b in builder.bands_in(text)["oral"]] == ["5", "50", "300", "2000"]


def test_points_printed_after_the_ranges_are_split_by_rising_values():
    # "2 000 5 50 300 1 100": the bound, then four points, thousands spaced.
    text = ("Dermal (mg/kg bodyweight) 0 < Category 1 ≤ 50 50 < Category 2 ≤ 200 "
            "200 < Category 3 ≤ 1 000 1 000 < Category 4 ≤ 2 000 5 50 300 1 100 Gases")
    bands = {"dermal": [{"category": c, "low": "0", "high": h}
                        for c, h in (("1", "50"), ("2", "200"), ("3", "1000"), ("4", "2000"))]}
    assert builder.conversion_in(text, bands)["dermal"] == {
        "1": "5", "2": "50", "3": "300", "4": "1100"}


def test_points_interleaved_with_the_ranges():
    text = ("Oral (mg/kg bodyweight) 0 < Category 1 ≤ 5 0.5 5 < Category 2 ≤ 50 5 "
            "50 < Category 3 ≤ 300 100 300 < Category 4 ≤ 2000 500 Dermal")
    bands = {"oral": [{"category": c, "low": "0", "high": h}
                      for c, h in (("1", "5"), ("2", "50"), ("3", "300"), ("4", "2000"))]}
    assert builder.conversion_in(text, bands)["oral"] == {
        "1": "0.5", "2": "5", "3": "100", "4": "500"}


def test_categories_one_to_four_agree_across_every_regulation():
    tables = {r: acute_table.load(r) for r in REGULATIONS}
    reference = tables["eu_clp"]
    for regulation, table in tables.items():
        for form in builder.ROUTES:
            four = [(b.category, b.low, b.high) for b in table.bands[form] if b.category != "5"]
            assert four == [(b.category, b.low, b.high) for b in reference.bands[form]], (regulation, form)
            assert {c: v for c, v in table.conversion[form].items() if c != "5"} == \
                reference.conversion[form], (regulation, form)
        assert table.relevance == Decimal(1) and table.unknown_threshold == Decimal(10)
        assert all(table.citations[k] for k in ("bands", "conversion", "relevance",
                                                "unknown", "formula")), regulation


def test_each_regulation_keeps_its_own_differences():
    ghs, au = acute_table.load("un_ghs"), acute_table.load("au_whs")
    assert ghs.bands["oral"][-1].category == "5" and ghs.conversion["dermal"]["5"] == Decimal(2500)
    assert all(b.category != "5" for bands in au.bands.values() for b in bands)
    assert any("Category 5 excluded" in n for n in au.notes)
    for regulation in ("us_osha", "ca_whmis"):     # LD50 2000-5000 still counted
        assert acute_table.load(regulation).ingredient_limit["oral"] == Decimal(5000)
    assert acute_table.load("eu_clp").ingredient_limit["oral"] == Decimal(2000)


# -- the calculation ------------------------------------------------------------------

def _oral(report):
    return next(r for r in report.mixture.results if r["family"] == "Acute toxicity, oral")


def test_the_coolant_is_acute_tox_4_oral_at_both_ends():
    oral = _oral(check_pdf(pdf("pattern_glycol_coolant_gb"), ingredients=True))
    assert oral["verdict"] == "consistent"
    assert oral["calculated_class"] == "Acute Tox. (oral) 4"
    trace = " ".join(oral["trace"])
    assert "ATEmix = 1250 mg/kg" in trace          # low end: 40 % at 500
    assert "ATEmix = 800 mg/kg" in trace           # high end: 60/500 + 2.5/500
    assert "Table 3.1.2, page 145" in trace and "Table 3.1.1, page 140" in trace


def test_an_ingredient_below_the_relevance_threshold_is_left_out():
    oral = _oral(check_pdf(pdf("pattern_glycol_coolant_gb"), ingredients=True))
    low = [t for t in oral["trace"] if t.startswith("low end: 100")][0]
    assert "111-46-6" not in low and "Diethylene glycol" not in low


def test_a_section_11_ld50_is_used_before_the_category(tmp_path):
    path = _glycol_coolant(tmp_path / "coolant_ld50.pdf", section_eleven=[
        "Ethylene glycol (CAS 107-21-1)", "LD50 oral, rat: 7712 mg/kg"])
    report = check_pdf(str(path), "uk_clp", ingredients=True)
    oral = _oral(report)
    trace = " ".join(oral["trace"])
    assert "Section 11" not in trace                # 7712 is beyond Category 4: not summed
    assert oral["calculated_class"] in ("", None)   # the glycols no longer classify it
    assert oral["stated_class"] == "Acute Tox. (oral) 4"


def test_section_11_values_are_read_by_ingredient(tmp_path):
    from lingua_oracle.extract import extract
    from lingua_oracle.mixture import section_eleven

    path = _glycol_coolant(tmp_path / "coolant_s11.pdf", section_eleven=[
        "Ethylene glycol (CAS 107-21-1)", "LD50 oral, rat: 1 200 mg/kg",
        "LD50 dermal, rabbit: > 2000 mg/kg", "Acute toxicity estimate (mixture): ATE oral 2500 mg/kg"])
    found = section_eleven.read(extract(str(path)).lines,
                                [("107-21-1", "Ethylene glycol")])
    assert [(a.route, a.value) for a in found.by_cas["107-21-1"]] == [("oral", Decimal(1200))]
    assert any("limit test" in line for line in found.ignored)
    assert found.mixture and "2500" in found.mixture[0]


def test_a_code_covering_two_categories_is_converted_both_ways():
    rules = acute_table.load("eu_clp")
    fatal = from_codes(None, "fatal", Decimal(10), Decimal(10), ["H300"])
    runs = acute.calculate([fatal], rules, "liquid")["oral"]["runs"]
    assert {r.category for r in runs} == {"1", "2"}    # 100/(10/0.5)=5 and 100/(10/5)=50


def test_the_sheets_own_unknown_share_corrects_the_sum():
    rules = acute_table.load("eu_clp")
    harmful = from_codes(None, "harmful", Decimal(50), Decimal(50), ["H302"])
    plain = acute.calculate([harmful], rules, "liquid")["oral"]["runs"][0]
    corrected = acute.calculate([harmful], rules, "liquid",
                                unknown={"": Decimal(15)})["oral"]["runs"][0]
    assert plain.ate_mix == Decimal(1000)              # 100 / (50/500)
    assert corrected.ate_mix == Decimal(850)           # (100 - 15) / (50/500)
    assert "corrected for 15 % of unknown acute toxicity" in corrected.trace[0]


def test_an_unknown_share_at_or_below_the_threshold_changes_nothing():
    rules = acute_table.load("eu_clp")
    harmful = from_codes(None, "harmful", Decimal(50), Decimal(50), ["H302"])
    run = acute.calculate([harmful], rules, "liquid",
                          unknown={"": Decimal(10)})["oral"]["runs"][0]
    assert run.ate_mix == Decimal(1000)


def test_the_list_entrys_own_ate_comes_first():
    from lingua_oracle.keys.builders.annex_vi import load_table
    from lingua_oracle.mixture.limits import parse

    entry = next(e for e in load_table().entries if e.index_no == "015-134-00-5")
    ingredient = MixtureIngredient(cas="29232-93-7", name=None, low=Decimal(20),
                                   high=Decimal(20), h_codes=entry.h_codes,
                                   limits=parse(entry.limits))
    run = acute.calculate([ingredient], acute_table.load("eu_clp"), "liquid",
                          entries={"29232-93-7": entry})["oral"]["runs"][0]
    assert "list entry" in run.trace[0] and "1414" in run.trace[0]


@pytest.mark.parametrize(("regulation", "expected"), [("un_ghs", "5"), ("eu_clp", None)])
def test_category_5_only_where_the_regulation_has_it(regulation, expected):
    harmful = from_codes(None, "harmful", Decimal(15), Decimal(15), ["H302"])
    run = acute.calculate([harmful], acute_table.load(regulation), "liquid")["oral"]["runs"][0]
    assert run.ate_mix.quantize(Decimal(1)) == Decimal(3333)   # 100 / (15/500)
    assert run.category == expected


def test_the_inhalation_form_follows_the_physical_state():
    assert acute.forms("inhalation", "liquid") == ("vapours",)
    assert acute.forms("inhalation", "gas") == ("gases",)
    assert acute.forms("inhalation", None) == ("vapours", "dusts_mists")

