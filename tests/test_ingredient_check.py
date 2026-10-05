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


# -- the report ----------------------------------------------------------------


def _run_with(verdicts, name="<fictional product>"):
    from lingua_oracle.ingredients import report as R

    run = R.new_run("02008R1272-test")
    run.products.append(R.ProductResult(product_id=1, name=name,
                                        regulation="eu_clp", verdicts=verdicts))
    return run


def test_the_report_counts_what_it_shows():
    from lingua_oracle.ingredients import report as R

    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315"]),
                     entry(index_no="000-001-00-0", cas=["200-00-0"],
                           h_codes=["H319"]))
    verdicts = check_product([
        {"cas": "100-00-5", "h_codes": ["H302"]},
        {"cas": "200-00-0", "h_codes": ["H319"]},
        {"cas": "999-99-9", "h_codes": ["H302"]},
    ], table)
    counts = _run_with(verdicts).counts()
    assert counts == {"products": 1, "substances": 0, "ingredients": 3,
                      "with_entry": 2, "fix": 1, "info": 0, "ok": 1,
                      "not_checked": 1}
    assert R.headline(counts)[0] == "Fix before release"


def test_a_clean_run_says_so():
    from lingua_oracle.ingredients import report as R

    table = table_of(entry(h_codes=["H302"]))
    verdicts = check_product([{"cas": "100-00-5", "h_codes": ["H302"]}], table)
    release, tone, detail = R.headline(_run_with(verdicts).counts())
    assert release == "Matches Annex VI"
    assert tone == "ok"
    assert "1 ingredient checked" in detail


def test_a_run_with_no_reference_does_not_claim_a_pass():
    from lingua_oracle.ingredients import report as R

    verdicts = check_product([{"cas": "999-99-9", "h_codes": ["H302"]}],
                             table_of(entry()))
    release, _tone, detail = R.headline(_run_with(verdicts).counts())
    assert release == "Nothing to compare"
    assert "nothing to check against" in detail


def test_the_report_names_the_three_commonest_missing_codes():
    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315", "H319"]))
    verdicts = check_product([{"cas": "100-00-5", "h_codes": []}], table)
    patterns = _run_with(verdicts).missing_patterns()
    assert patterns[:3] == [("H302", 1), ("H315", 1), ("H319", 1)]


def test_the_data_sources_are_counted_but_not_ranked():
    """They belong in the technical block, beside nothing that judges them."""
    table = table_of(entry(h_codes=["H302"]))
    verdicts = [
        check_ingredient("100-00-5", ["H302"], table, data_source="gemini"),
        check_ingredient("100-00-5", ["H302"], table, data_source="database"),
        check_ingredient("100-00-5", ["H302"], table),
    ]
    run = _run_with(verdicts)
    assert run.sources() == {"database": 1, "gemini": 1, "not stated": 1}
    assert run.counts()["ok"] == 3


def test_the_report_writes_both_files(tmp_path):
    from lingua_oracle.ingredients import report as R

    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315"]))
    verdicts = check_product([{"cas": "100-00-5", "h_codes": ["H302"]}], table)
    json_path, html_path = R.save(_run_with(verdicts), tmp_path)
    assert json_path.exists() and html_path.exists()
    body = html_path.read_text(encoding="utf-8")
    assert "Fix before release" in body
    assert "Annex VI requires" in body
    assert "H315" in body
    assert "Index No 000-000-00-0" in body          # the source reference
    assert "<fictional product>" not in body        # escaped, not raw
    assert "&lt;fictional product&gt;" in body


def test_the_report_escapes_what_it_prints(tmp_path):
    from lingua_oracle.ingredients import report as R

    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315"]))
    verdicts = check_product([{"cas": "100-00-5", "h_codes": ["H302"]}], table)
    _json_path, html_path = R.save(
        _run_with(verdicts, name="<script>alert(1)</script>"), tmp_path)
    body = html_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in body


def test_the_check_path_holds_no_network_call():
    """compare.py is pure. The one networked module is called only by the CLI."""
    from pathlib import Path

    from lingua_oracle.ingredients import compare

    text = Path(compare.__file__).read_text(encoding="utf-8")
    for word in ("httpx", "requests", "urlopen", "fetch("):
        assert word not in text, word


def test_a_placeholder_cas_is_not_a_missing_entry():
    """The app stores "NOCAS-…" where a substance has no registry number.

    Reporting that as "no harmonised entry" would say the law is silent about
    the substance, when the truth is that we cannot look it up.
    """
    verdict = check_ingredient("NOCAS-7a45cd36dcf4", ["H302"], table_of(entry()))
    assert verdict.status is Status.NOT_CHECKED
    assert verdict.reason is Reason.NO_CAS
    assert "indexed by CAS" in verdict.findings[0].message


@pytest.mark.parametrize("cas", ["", None, "NOCAS-abc", "not a cas", "1-2-3-4"])
def test_anything_that_is_not_a_cas_number_is_treated_as_none(cas):
    verdict = check_ingredient(cas, ["H302"], table_of(entry()))
    assert verdict.reason is Reason.NO_CAS


def test_the_harmonised_codes_are_read_out_of_the_packed_column(real):
    """The act prints "H361d *** H304" on one line, asterisks and all.

    Matching the whole line against a code pattern dropped every line that was
    not a single bare code, and with it 951 harmonised classifications.
    """
    toluene = real.by_cas()["108-88-3"][0]
    assert toluene.h_codes == ["H225", "H361d", "H304", "H373", "H315", "H336"]
    assert len(toluene.hazard_classes) == len(toluene.h_codes)


def test_a_sub_code_is_reported_with_the_letter_the_act_prints():
    """H361d and H361f are different hazards. The letter is not decoration."""
    table = table_of(entry(h_codes=["H361d"]))
    verdict = check_ingredient("100-00-5", [], table)
    assert verdict.missing_codes == ["H361d"]
    assert "requires H361d" in verdict.findings[0].message


def test_case_still_does_not_decide_whether_a_code_is_present():
    table = table_of(entry(h_codes=["H361d"]))
    assert check_ingredient("100-00-5", ["h361D"], table).status is Status.OK


def test_an_extra_code_keeps_the_spelling_the_app_used():
    table = table_of(entry(h_codes=["H302"]))
    verdict = check_ingredient("100-00-5", ["H302", "H361f"], table)
    assert verdict.status is Status.INFO
    assert "H361f" in verdict.findings[0].message


# -- one check per substance, not per product ---------------------------------


def _substance_run(results):
    from lingua_oracle.ingredients import report as R

    run = R.new_run("02008R1272-test")
    run.products_scanned = 42
    run.substances = results
    return run


def test_a_substance_run_counts_substances_not_uses():
    """The same discrepancy in forty products is one discrepancy."""
    from lingua_oracle.ingredients import report as R

    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315"]))
    verdict = check_ingredient("100-00-5", ["H302"], table)
    run = _substance_run([R.SubstanceResult(cas="100-00-5", name="<x>",
                                            verdict=verdict, product_count=40)])
    counts = run.counts()
    assert counts["substances"] == 1
    assert counts["ingredients"] == 1
    assert counts["fix"] == 1
    assert counts["products"] == 42          # read, not checked


def test_a_substance_run_reports_how_far_each_problem_reaches():
    from lingua_oracle.ingredients import report as R

    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315"]),
                     entry(index_no="000-001-00-0", cas=["200-00-0"],
                           h_codes=["H319"]))
    results = [
        R.SubstanceResult("100-00-5", "<a>",
                          check_ingredient("100-00-5", ["H302"], table), 40),
        R.SubstanceResult("200-00-0", "<b>",
                          check_ingredient("200-00-0", ["H319"], table), 7),
    ]
    run = _substance_run(results)
    assert run.reach() == [("100-00-5", 40)]      # only the ones to fix


def test_the_reach_list_is_ordered_by_how_many_products_are_affected():
    from lingua_oracle.ingredients import report as R

    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315"]),
                     entry(index_no="000-001-00-0", cas=["200-00-0"],
                           h_codes=["H319", "H335"]))
    run = _substance_run([
        R.SubstanceResult("100-00-5", "<a>",
                          check_ingredient("100-00-5", [], table), 3),
        R.SubstanceResult("200-00-0", "<b>",
                          check_ingredient("200-00-0", [], table), 19),
    ])
    assert run.reach() == [("200-00-0", 19), ("100-00-5", 3)]


def test_a_substance_run_writes_its_own_shape(tmp_path):
    from lingua_oracle.ingredients import report as R

    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315"]))
    run = _substance_run([R.SubstanceResult(
        cas="100-00-5", name="<fictional substance>",
        verdict=check_ingredient("100-00-5", ["H302"], table),
        product_count=12)])
    json_path, html_path = R.save(run, tmp_path)
    import json as _json

    payload = _json.loads(json_path.read_text())
    assert payload["substances"][0]["product_count"] == 12
    assert payload["under_classified_reach"] == [["100-00-5", 12]]
    body = html_path.read_text(encoding="utf-8")
    assert "in 12 products" in body
    assert "H315" in body


def test_one_product_reads_as_one_product(tmp_path):
    from lingua_oracle.ingredients import report as R

    table = table_of(entry(cas=["100-00-5"], h_codes=["H302", "H315"]))
    run = _substance_run([R.SubstanceResult(
        cas="100-00-5", name="<x>",
        verdict=check_ingredient("100-00-5", ["H302"], table),
        product_count=1)])
    _json_path, html_path = R.save(run, tmp_path)
    assert "in 1 product<" in html_path.read_text(encoding="utf-8")
