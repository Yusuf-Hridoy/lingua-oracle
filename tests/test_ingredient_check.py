"""The ingredient check: H codes against the harmonised entry.

Synthetic ingredients throughout - fictional products, fictional CAS numbers
where the test is about shape. Annex VI entries are real: they are public law.
"""

from __future__ import annotations

import pytest

from lingua_oracle.ingredients.compare import (
    Reason,
    Status,
    check_ingredient,
    check_minimum_classification,
    check_product,
    compare_categories,
    parse_class,
)
from lingua_oracle.keys.builders.annex_vi import table_path
from lingua_oracle.models import AnnexVIEntry, AnnexVITable


def entry(**kwargs) -> AnnexVIEntry:
    base = {
        "index_no": "000-000-00-0",
        "name": "<synthetic substance>",
        "cas": ["100-00-5"],
        "hazard_classes": ["Acute Tox. 4"],
        "h_codes": ["H302"],
        "source_ref": "Annex VI, Table 3, Index No 000-000-00-0 (test)",
    }
    base.update(kwargs)
    return AnnexVIEntry(**base)


def table_of(*entries: AnnexVIEntry) -> AnnexVITable:
    return AnnexVITable(source="test", note="synthetic", entries=list(entries))


# -- the floor ----------------------------------------------------------------


def test_a_missing_harmonised_code_is_a_fix():
    table = table_of(entry(h_codes=["H302", "H315"]))
    verdict = check_ingredient("100-00-5", ["H302"], table)
    assert verdict.status is Status.FIX
    assert verdict.missing_codes == ["H315"]
    assert "Annex VI requires H315" in verdict.findings[0].message


def test_everything_the_entry_requires_present_is_ok():
    table = table_of(entry(h_codes=["H302", "H315"]))
    verdict = check_ingredient("100-00-5", ["H315", "H302"], table)
    assert verdict.status is Status.OK
    assert verdict.findings == []


def test_order_and_spacing_do_not_matter():
    table = table_of(entry(h_codes=["H302"]))
    assert check_ingredient("100-00-5", [" h302 "], table).status is Status.OK


def test_a_sub_coded_statement_satisfies_its_base():
    """Annex VI says H360F; a sheet saying H360 carries the same statement."""
    table = table_of(entry(h_codes=["H360F"]))
    assert check_ingredient("100-00-5", ["H360"], table).status is Status.OK


def test_extra_codes_are_information_not_a_failure():
    """Annex VI is a floor. A supplier classifies for what it leaves to them."""
    table = table_of(entry(h_codes=["H302"]))
    verdict = check_ingredient("100-00-5", ["H302", "H319"], table)
    assert verdict.status is Status.INFO
    assert verdict.missing_codes == []
    assert "H319" in verdict.findings[0].message
    assert "ordinary" in verdict.findings[0].message


def test_a_missing_code_outranks_an_extra_one():
    table = table_of(entry(h_codes=["H302", "H315"]))
    verdict = check_ingredient("100-00-5", ["H302", "H319"], table)
    assert verdict.status is Status.FIX
    assert verdict.missing_codes == ["H315"]


# -- where nothing can be checked ---------------------------------------------


def test_a_substance_with_no_harmonised_entry_is_not_checked():
    verdict = check_ingredient("999-99-9", ["H302"], table_of(entry()))
    assert verdict.status is Status.NOT_CHECKED
    assert verdict.reason is Reason.NO_ENTRY
    assert "no official reference" in verdict.findings[0].message


def test_an_ingredient_with_no_cas_is_not_checked():
    verdict = check_ingredient(None, ["H302"], table_of(entry()))
    assert verdict.status is Status.NOT_CHECKED
    assert verdict.reason is Reason.NO_CAS


def test_a_cas_in_two_entries_is_not_checked_and_names_both():
    table = table_of(entry(index_no="001-000-00-0"),
                     entry(index_no="002-000-00-0"))
    verdict = check_ingredient("100-00-5", ["H302"], table)
    assert verdict.status is Status.NOT_CHECKED
    assert verdict.reason is Reason.SEVERAL_ENTRIES
    assert "001-000-00-0" in verdict.findings[0].message
    assert "002-000-00-0" in verdict.findings[0].message


def test_a_group_entry_is_not_checked():
    """One row covering several substances says nothing about any one of them."""
    table = table_of(entry(cas=["100-00-5 [1]", "200-00-0 [2]"]))
    verdict = check_ingredient("100-00-5", ["H302"], table)
    assert verdict.status is Status.NOT_CHECKED
    assert verdict.reason is Reason.GROUP_ENTRY
    assert verdict.entry_index_no == "000-000-00-0"


def test_nothing_is_guessed_when_nothing_is_checked():
    verdict = check_ingredient("999-99-9", ["H302"], table_of(entry()))
    assert verdict.missing_codes == []
    assert verdict.entry_index_no is None


# -- minimum classification ---------------------------------------------------


@pytest.mark.parametrize(("raw", "name", "category", "minimum"), [
    ("Acute Tox. 4 *", "Acute Tox.", "4", True),
    ("Acute Tox. 4", "Acute Tox.", "4", False),
    ("Skin Corr. 1B", "Skin Corr.", "1B", False),
    ("Aquatic Chronic 3", "Aquatic Chronic", "3", False),
    ("Press. Gas", "Press. Gas", None, False),
])
def test_a_class_splits_into_name_category_and_the_asterisk(raw, name, category,
                                                            minimum):
    parsed = parse_class(raw)
    assert (parsed.name, parsed.category, parsed.minimum) == (name, category,
                                                              minimum)


@pytest.mark.parametrize(("stated", "harmonised", "verdict"), [
    ("Acute Tox. 3", "Acute Tox. 4 *", "stricter"),
    ("Acute Tox. 4", "Acute Tox. 4 *", "equal"),
    ("Acute Tox. 5", "Acute Tox. 4 *", "weaker"),
    ("Skin Corr. 1A", "Skin Corr. 1B", "stricter"),
    ("Skin Corr. 1C", "Skin Corr. 1B", "weaker"),
    ("Eye Dam. 1", "Acute Tox. 4 *", "incomparable"),
])
def test_categories_compare_within_one_class(stated, harmonised, verdict):
    assert compare_categories(stated, harmonised) == verdict


def test_a_stricter_category_passes_a_minimum_classification():
    e = entry(hazard_classes=["Acute Tox. 4 *"], h_codes=["H302"])
    assert check_minimum_classification(["Acute Tox. 3"], e) == []


def test_an_equal_category_passes():
    e = entry(hazard_classes=["Acute Tox. 4 *"], h_codes=["H302"])
    assert check_minimum_classification(["Acute Tox. 4"], e) == []


def test_a_weaker_category_is_a_fix():
    e = entry(hazard_classes=["Acute Tox. 4 *"], h_codes=["H302"])
    findings = check_minimum_classification(["Acute Tox. 5"], e)
    assert len(findings) == 1
    assert findings[0].status is Status.FIX
    assert "Acute Tox. 4 *" in findings[0].message
    assert "Acute Tox. 5" in findings[0].message


def test_a_class_without_the_asterisk_is_not_a_minimum():
    e = entry(hazard_classes=["Acute Tox. 4"], h_codes=["H302"])
    assert check_minimum_classification(["Acute Tox. 5"], e) == []


# -- a whole product -----------------------------------------------------------


def test_a_product_is_checked_ingredient_by_ingredient():
    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315"]),
                     entry(index_no="000-001-00-0", cas=["200-00-0"],
                           h_codes=["H319"]))
    verdicts = check_product([
        {"cas": "100-00-5", "h_codes": "H302"},
        {"cas": "200-00-0", "h_codes": ["H319"]},
        {"cas": "999-99-9", "h_codes": ["H302"]},
    ], table)
    assert [v.status for v in verdicts] == [Status.FIX, Status.OK,
                                            Status.NOT_CHECKED]


def test_the_data_source_is_carried_but_never_weighed():
    """It is metadata for the technical block, not an input to the verdict."""
    table = table_of(entry(h_codes=["H302"]))
    for source in ("gemini", "database", None):
        verdict = check_ingredient("100-00-5", ["H302"], table,
                                   data_source=source)
        assert verdict.status is Status.OK
        assert verdict.data_source == source


def test_the_same_ingredient_always_gets_the_same_verdict():
    table = table_of(entry(h_codes=["H302", "H315"]))
    first = check_ingredient("100-00-5", ["H302"], table)
    second = check_ingredient("100-00-5", ["H302"], table)
    assert first.missing_codes == second.missing_codes == ["H315"]


# -- against the real table ----------------------------------------------------


@pytest.fixture(scope="module")
def real() -> AnnexVITable:
    if not table_path().exists():
        pytest.skip("no Annex VI table; run `lingua keys build annex_vi`")
    return AnnexVITable.model_validate_json(
        table_path().read_text(encoding="utf-8"))


def test_a_known_harmonised_substance_checks_out(real):
    """Hydrogen, Index 001-001-00-9: Flam. Gas 1, Press. Gas, H220."""
    verdict = check_ingredient("1333-74-0", ["H220"], real)
    assert verdict.status is Status.OK
    assert verdict.entry_index_no == "001-001-00-9"
    assert "001-001-00-9" in verdict.source_ref


def test_dropping_a_harmonised_code_is_caught_on_the_real_table(real):
    verdict = check_ingredient("16853-85-3", ["H260"], real)   # H260 + H314
    assert verdict.status is Status.FIX
    assert verdict.missing_codes == ["H314"]


def test_a_substance_outside_annex_vi_is_not_checked_on_the_real_table(real):
    verdict = check_ingredient("7732-18-5", [], real)          # water
    assert verdict.status is Status.NOT_CHECKED
    assert verdict.reason is Reason.NO_ENTRY
