"""Annex VI Table 3: the harmonised classifications, as committed data.

This is the reference a substance is judged against, so the tests are about
integrity rather than behaviour: an entry that is wrong here would be reported
to a reader as law.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingua_oracle.keys.builders.annex_vi import (
    base_code,
    cas_digits_valid,
    table_path,
)
from lingua_oracle.keys.store import load_key
from lingua_oracle.models import AnnexVIEntry, AnnexVITable


@pytest.fixture(scope="module")
def table() -> AnnexVITable:
    path = table_path()
    if not path.exists():
        pytest.skip("no Annex VI table; run `lingua keys build annex_vi`")
    return AnnexVITable.model_validate_json(path.read_text(encoding="utf-8"))


def test_the_table_is_the_whole_table(table):
    assert len(table.entries) > 4000
    assert table.source.startswith("02008R1272")


def test_no_entry_is_without_a_classification(table):
    """An entry with neither a class nor an H code says nothing and is not law."""
    for entry in table.entries:
        assert entry.hazard_classes or entry.h_codes, entry.index_no


def test_every_entry_names_where_it_came_from(table):
    for entry in table.entries:
        assert entry.index_no in entry.source_ref
        assert table.source in entry.source_ref
        assert "Table 3" in entry.source_ref


def test_every_cas_number_passes_its_check_digit(table):
    """A mistyped CAS number would attach a classification to the wrong substance."""
    wrong = [cas for cas in table.by_cas() if not cas_digits_valid(cas)]
    assert wrong == [], wrong[:10]


def test_every_hazard_statement_code_is_one_we_hold_the_text_of(table):
    """Table 3 may only cite statements we can put words to.

    Three sources between them cover it. The EU CLP key holds Annex III's
    statements. The GHS index holds the codes the act prints in its Annex I
    label tables but not in Annex III - H220, H221 and H222 among them. And
    Annex VI uses sub-coded forms the statement tables do not list separately,
    H350i and H360D for instance, whose base code carries the wording.
    """
    import json

    from lingua_oracle.registry import data_dir

    known = set(load_key("eu_clp", "en").by_code())
    known |= set(json.loads(
        (data_dir() / "ghs_index" / "en.json").read_text(encoding="utf-8"))["codes"])

    unknown: dict[str, str] = {}
    for entry in table.entries:
        for code in (*entry.h_codes, *entry.label_h_codes,
                     *entry.supplemental_h_codes):
            if code in known or base_code(code) in known:
                continue
            unknown.setdefault(code, entry.index_no)
    assert unknown == {}, unknown


def test_a_sub_coded_statement_resolves_to_its_base(table):
    """H350i is H350 for a specific route; the wording lives on the base code."""
    assert base_code("H350i") == "H350"
    assert base_code("H360FD") == "H360"
    assert base_code("H361d") == "H361"
    assert base_code("H302") == "H302"
    sub = {c for e in table.entries for c in e.h_codes if c != base_code(c)}
    assert {"H350i", "H360D", "H360F", "H361d", "H361f"} <= sub


def test_the_asterisk_of_a_minimum_classification_is_kept(table):
    """It changes what a sheet is allowed to say, so it may not be tidied away."""
    starred = [e for e in table.entries if e.minimum_classification]
    assert len(starred) > 1000
    assert any("*" in cls for cls in starred[0].hazard_classes)


def test_an_entry_covering_several_substances_says_so(table):
    """Which classification belongs to which substance is not ours to infer."""
    several = [e for e in table.entries if e.covers_several_substances]
    assert len(several) > 100
    for entry in several[:20]:
        assert entry.cas or entry.ec


def test_cas_numbers_are_read_out_of_the_text_not_assumed_to_be_it():
    """The act sometimes packs two numbers onto one line, or ends one with a stop."""
    entry = AnnexVIEntry(
        index_no="000-000-00-0", name="<synthetic>",
        cas=["3648-18-8 [1] 91648-39-4", "7697-37-2."],
        hazard_classes=["Acute Tox. 4"], h_codes=["H302"],
        source_ref="Annex VI, Table 3, Index No 000-000-00-0 (test)",
    )
    assert entry.cas_numbers() == ["3648-18-8", "91648-39-4", "7697-37-2"]
    assert entry.covers_several_substances


def test_the_table_round_trips_byte_for_byte(table):
    """Rebuilding from the same source must not rewrite the file."""
    written = json.dumps(table.model_dump(mode="json", exclude_none=False),
                         ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    assert written == table_path().read_text(encoding="utf-8")


def test_entries_are_in_index_order(table):
    """A stable order is what makes a rebuild a no-op."""
    order = [e.index_no for e in table.entries]
    assert order == sorted(order)


@pytest.mark.parametrize(("cas", "valid"), [
    ("1333-74-0", True),     # hydrogen
    ("7439-93-2", True),     # lithium
    ("50-85-1", True),
    ("1333-74-1", False),    # check digit off by one
    ("not-a-cas", False),
    ("", False),
])
def test_the_check_digit_rule(cas, valid):
    assert cas_digits_valid(cas) is valid


def test_an_unchanged_rebuild_keeps_its_timestamp(table):
    """What makes the rebuild a no-op: the stamp moves only when an entry does."""
    from lingua_oracle.keys.builders.annex_vi import preserve_timestamp

    same = preserve_timestamp(table.model_copy(update={"retrieved_at": None}))
    assert same.retrieved_at == table.retrieved_at

    changed = table.model_copy(update={
        "retrieved_at": None,
        "entries": table.entries[:-1],
    })
    assert preserve_timestamp(changed).retrieved_at is None


def test_check_time_reads_the_file_and_never_the_act():
    """The table is committed data. Nothing in the check path may fetch it."""
    import ast

    from lingua_oracle.keys.builders import annex_vi

    text = Path(annex_vi.__file__).read_text(encoding="utf-8")
    # Every fetch is inside a build function - build() for the table,
    # build_upcoming() for the amending act - via the EU CLP builder's _doc().
    fetching = [
        function.name
        for function in ast.walk(ast.parse(text))
        if isinstance(function, ast.FunctionDef)
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_doc"
    ]
    assert sorted(fetching) == ["build", "build_upcoming"]
    assert "def load_table()" in text
    assert "def load_upcoming()" in text


def test_the_supplemental_column_is_parsed_into_its_own_field(table):
    """Acetone carries EUH066, and the entry has to say so.

    The supplemental column was being read into `supplemental_h_codes` and then
    ignored by the comparison, so a sheet missing a EUH code the law requires
    looked complete.
    """
    acetone = table.by_cas()["67-64-1"][0]
    assert acetone.index_no == "606-001-00-8"
    assert acetone.euh_codes == ["EUH066"]
    assert "EUH066" not in acetone.h_codes


def test_every_euh_code_comes_from_the_supplemental_column(table):
    for entry in table.entries:
        assert set(entry.euh_codes) <= set(entry.supplemental_h_codes)
        assert all(code.startswith("EUH") for code in entry.euh_codes)


def test_the_supplemental_column_holds_nothing_but_euh_codes(table):
    """If that ever stops being true, the split above is hiding something."""
    other = {c for e in table.entries for c in e.supplemental_h_codes
             if not c.startswith("EUH")}
    assert other == set()


def test_enough_entries_carry_one_to_be_worth_checking(table):
    assert sum(1 for e in table.entries if e.euh_codes) > 100


# -- reproductive toxicity codes with two letters ---------------------------------

def test_a_code_naming_two_effects_is_read_whole():
    from lingua_oracle.keys.builders.annex_vi import _codes

    assert _codes(["H360FD", "H360Df H361fd", "H360Fd"]) == [
        "H360FD", "H360Df", "H361fd", "H360Fd"]
    # Still found inside a line, and one letter or none still works.
    assert _codes(["H361d *** H304", "H350i", "H373 **"]) == [
        "H361d", "H304", "H350i", "H373"]


def test_every_reproductive_toxicant_carries_its_code(table):
    # 114 entries once had a Repr. class and no H360/H361/H362 at all.
    missing = [e.index_no for e in table.entries
               if any(c.startswith("Repr.") for c in e.hazard_classes)
               and not any(h.startswith(("H360", "H361", "H362")) for h in e.h_codes)]
    assert missing == []


def test_a_sheet_without_h360fd_for_trimethyl_borate_is_under_classified(table):
    from lingua_oracle.ingredients.compare import Status, check_ingredient

    verdict = check_ingredient("121-43-7", ["H226", "H312"], table)
    assert verdict.status is Status.FIX
    assert verdict.missing_codes == ["H360FD"]
