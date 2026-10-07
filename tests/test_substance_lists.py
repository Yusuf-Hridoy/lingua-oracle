"""The published substance lists, checked against what they publish.

Two lists beside Annex VI: Great Britain's mandatory classification and
labelling list, and Safe Work Australia's HCIS export. Both are read into the
same model Annex VI uses, so what is tested is that the reading kept the
publisher's own content - identifiers that are identifiers, codes that exist
in that regulation's key, and two substances whose classification is known
independently.
"""

from __future__ import annotations

import json
import re

import pytest

from lingua_oracle.keys.builders import substance_lists as lists
from lingua_oracle.models import AnnexVITable

NAMES = ("gb_mcl", "au_hcis")
CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")


def load(name: str) -> AnnexVITable:
    return AnnexVITable.model_validate(
        json.loads(lists.path_for(name).read_text(encoding="utf-8")))


@pytest.fixture(scope="module", params=NAMES)
def table(request):
    """One list, with the name it was loaded by.

    The name is carried beside the table rather than inside it: the model is
    Annex VI's, the file it already writes is committed, and adding a field to
    it would rewrite 4 420 entries to say something the file name says.
    """
    path = lists.path_for(request.param)
    if not path.exists():
        pytest.skip(f"{path} not built: run `lingua keys build substance_lists`")
    found = load(request.param)
    return _Named(request.param, found)


class _Named:
    def __init__(self, name, table):
        self.name = name
        self._table = table

    def __getattr__(self, item):
        return getattr(self._table, item)


# -- what a list has to be -----------------------------------------------------


def test_a_list_says_where_it_came_from(table):
    assert table.source
    assert table.note
    assert table.entries


def test_every_entry_cites_its_own_row(table):
    for entry in table.entries:
        assert entry.source_ref, entry.name


def test_every_entry_has_a_classification(table):
    """An entry with neither a class nor a code is not a classification, and
    the builder leaves it out rather than carrying an empty one."""
    for entry in table.entries:
        assert entry.hazard_classes or entry.h_codes, entry.name


def test_every_cas_number_is_one(table):
    """Shape and check digit both: the last digit of a CAS number is computed
    from the others, so a transcription error is detectable rather than
    plausible."""
    for entry in table.entries:
        for cas in entry.cas_numbers():
            assert CAS.match(cas), f"{entry.name}: {cas}"
            assert _check_digit_ok(cas), f"{entry.name}: {cas} fails its check digit"


def _check_digit_ok(cas: str) -> bool:
    digits = cas.replace("-", "")
    body, check = digits[:-1], int(digits[-1])
    total = sum((len(body) - i) * int(d) for i, d in enumerate(body))
    return total % 10 == check


def test_every_code_is_one_the_regulation_publishes(table):
    """A code in a list that its own regulation has no wording for would be a
    code this tool could never check a sheet against.

    A code with a route or an effect on the end - H350i, H360FD - is the same
    statement with its blank filled, and the key holds the statement; the base
    code is what has to exist. EUH codes are the exception and are tested
    separately: they are EU supplemental statements, and an Australian list
    carries them from the EU data it was built on.
    """
    from lingua_oracle.keys.store import load_key

    regulation = "uk_clp" if table.name == "gb_mcl" else "au_whs"
    known = {entry.code for entry in load_key(regulation, "en").entries}
    unknown: dict[str, int] = {}
    for entry in table.entries:
        for code in entry.h_codes:
            base = re.match(r"^((?:EU)?H\d{3})", code)
            if code not in known and (base is None or base.group(1) not in known):
                unknown[code] = unknown.get(code, 0) + 1
    if not unknown:
        return
    # A code the list uses and this tool has no wording for is either an
    # invented code - which would be a defect in the reading - or a gap in the
    # answer key. Every one of these is in the EU key, so it is the second,
    # and it is pinned here so it cannot grow unnoticed.
    eu = {entry.code for entry in load_key("eu_clp", "en").entries}
    assert set(unknown) <= eu, f"{table.name}: codes in no key at all: {unknown}"
    assert set(unknown) == {"H200", "H250", "H290", "H318"}, (
        f"{regulation}'s key is missing wording for {sorted(unknown)}")


def test_an_eu_supplemental_code_in_a_non_eu_list_is_known_to_be_one(table):
    """HCIS lists EUH codes; Australia publishes no wording for them. That is
    worth knowing rather than hiding, and worth failing on if it ever spreads
    beyond the EUH codes."""
    from lingua_oracle.keys.store import load_key

    regulation = "uk_clp" if table.name == "gb_mcl" else "au_whs"
    known = {entry.code for entry in load_key(regulation, "en").entries}
    absent = {c for e in table.entries for c in e.euh_codes if c not in known}
    if table.name == "gb_mcl":
        assert not absent, absent
    else:
        assert all(c.startswith("EUH") for c in absent), absent


# -- two substances whose classification is known ------------------------------


def _entry(table: AnnexVITable, cas: str):
    return next((e for e in table.entries if cas in e.cas_numbers()), None)


def test_acetone_is_classified_as_the_list_publishes_it(table):
    entry = _entry(table, "67-64-1")
    assert entry is not None, "acetone is in both lists"
    assert {"H225", "H319", "H336"} <= set(entry.h_codes)
    assert any("Flam. Liq. 2" in c for c in entry.hazard_classes)
    assert any("STOT SE 3" in c for c in entry.hazard_classes)


def test_toluene_is_classified_as_the_list_publishes_it(table):
    entry = _entry(table, "108-88-3")
    assert entry is not None, "toluene is in both lists"
    assert {"H225", "H304", "H315", "H336", "H373"} <= set(entry.h_codes)
    assert any("Asp." in c for c in entry.hazard_classes)


def test_the_two_lists_are_not_assumed_to_agree():
    """They do not. Australia classifies toluene for reproductive toxicity in
    category 1A where Great Britain has category 2, and a tool that quietly
    used one for the other would report the difference as a defect in
    somebody's sheet."""
    gb = _entry(load("gb_mcl"), "108-88-3")
    au = _entry(load("au_hcis"), "108-88-3")
    assert "H361d" in gb.h_codes
    assert "H360" in au.h_codes
    assert "H360" not in gb.h_codes


# -- the GB list keeps what Annex VI's columns carry ---------------------------


def test_specific_limits_and_m_factors_survive():
    table = load("gb_mcl")
    with_limits = [e for e in table.entries if e.limits]
    assert len(with_limits) > 100
    kinds = {k for e in table.entries for k in e.limit_kinds}
    assert {"scl", "m_factor", "ate"} <= kinds
    thiram = _entry(table, "137-26-8")
    assert thiram.limits == ["M = 10"]
    assert thiram.limit_kinds == ["m_factor"]


def test_an_index_number_is_kept_where_the_publisher_gives_one():
    gb = _entry(load("gb_mcl"), "67-64-1")
    assert gb.index_no == "606-001-00-8"
    # HCIS publishes no index numbers, and an invented one would be worse.
    au = _entry(load("au_hcis"), "67-64-1")
    assert au.index_no == ""


def test_the_build_is_deterministic():
    """Same file in, same entries out, in the same order.

    Needs the published spreadsheet, which is not committed - it is a source
    document like the rest of data/sources - so a clone without it skips.
    """
    from lingua_oracle.keys.builders.common import SourceUnavailable

    try:
        first, _ = lists.build("gb_mcl")
        second, _ = lists.build("gb_mcl")
    except SourceUnavailable as exc:
        pytest.skip(str(exc))
    assert first.model_dump() == second.model_dump()
