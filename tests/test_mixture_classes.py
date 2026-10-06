"""The code-to-class table, checked against Annex VI's own rows.

The table in `mixture/classes.py` is written out rather than derived, because a
derivation is only as good as the row alignment and some of Annex VI's rows do
not align. These tests verify it against the law all the same: for every code
the table maps, the class it gives has to be the class Annex VI's own entries
show for that code.
"""

from __future__ import annotations

import pathlib
import re
from collections import Counter, defaultdict

import pytest

from lingua_oracle.keys.builders.annex_vi import table_path
from lingua_oracle.mixture.classes import (
    CODE_TO_CLASS,
    STOT_SE_3_EFFECT,
    class_of,
    parse_class,
)
from lingua_oracle.models import AnnexVITable


@pytest.fixture(scope="module")
def annex_vi() -> AnnexVITable:
    if not table_path().exists():
        pytest.skip("no Annex VI table; run `lingua keys build annex_vi`")
    return AnnexVITable.model_validate_json(
        table_path().read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def observed(annex_vi) -> dict[str, Counter]:
    """{code: Counter of the classes Annex VI pairs it with}.

    Only rows whose class and code columns have the same number of entries are
    used: where they do not, which class goes with which code is not knowable
    from the row.
    """
    pairs: dict[str, Counter] = defaultdict(Counter)
    for entry in annex_vi.entries:
        if len(entry.hazard_classes) != len(entry.h_codes):
            continue
        for raw, code in zip(entry.hazard_classes, entry.h_codes, strict=True):
            cleaned = re.sub(r"\s*\*+$", "", raw).strip()
            pairs[code][cleaned] += 1
    return pairs


def test_every_mapped_code_agrees_with_annex_vi(observed):
    """The class this table gives must be the one the law shows for that code."""
    disagreements = []
    for code, hazard_class in CODE_TO_CLASS.items():
        seen = observed.get(code)
        if not seen:
            continue                      # a code Annex VI never uses
        best = parse_class(seen.most_common(1)[0][0])
        if best is None:
            continue
        if best.name != hazard_class.name:
            disagreements.append((code, hazard_class.name, best.name))
    assert disagreements == [], disagreements


def test_the_category_is_never_more_specific_than_the_code_allows(observed):
    """H314 is Skin Corr. 1 - which of 1A, 1B, 1C is not in the code.

    Where Annex VI shows a code against more than one sub-category, this table
    must give the category without one.
    """
    for code, hazard_class in CODE_TO_CLASS.items():
        seen = observed.get(code)
        if not seen:
            continue
        categories = {parse_class(c).category for c in seen
                      if parse_class(c) and parse_class(c).name == hazard_class.name}
        categories.discard(None)
        if len({c for c in categories if c}) > 1:
            assert hazard_class.sub_category is None, (code, categories)


@pytest.mark.parametrize(("code", "expected"), [
    ("H314", "Skin Corr. 1"),
    ("H315", "Skin Irrit. 2"),
    ("H318", "Eye Dam. 1"),
    ("H319", "Eye Irrit. 2"),
    ("H317", "Skin Sens. 1"),
    ("H334", "Resp. Sens. 1"),
    ("H350", "Carc. 1"),
    ("H351", "Carc. 2"),
    ("H340", "Muta. 1"),
    ("H360", "Repr. 1"),
    ("H361", "Repr. 2"),
    ("H372", "STOT RE 1"),
    ("H373", "STOT RE 2"),
    ("H400", "Aquatic Acute 1"),
    ("H410", "Aquatic Chronic 1"),
    ("H411", "Aquatic Chronic 2"),
    ("H412", "Aquatic Chronic 3"),
    ("H413", "Aquatic Chronic 4"),
])
def test_the_codes_the_rules_rely_on(code, expected):
    assert str(class_of(code)) == expected


def test_a_code_the_table_does_not_map_contributes_nothing():
    assert class_of("H200") is None
    assert class_of("") is None
    assert class_of("not a code") is None


def test_the_two_stot_se_3_effects_are_distinguished():
    """They are summed separately, so the code has to say which it is."""
    assert STOT_SE_3_EFFECT["H335"] == "respiratory irritation"
    assert STOT_SE_3_EFFECT["H336"] == "narcotic effects"
    assert set(STOT_SE_3_EFFECT) == {"H335", "H336"}


@pytest.mark.parametrize(("raw", "name", "category", "generic"), [
    ("Skin Corr. 1B", "Skin Corr.", "1B", "1"),
    ("Skin Corr. 1B *", "Skin Corr.", "1B", "1"),
    ("Aquatic Chronic 3", "Aquatic Chronic", "3", "3"),
    ("Press. Gas", "Press. Gas", None, None),
])
def test_a_class_splits_into_its_parts(raw, name, category, generic):
    parsed = parse_class(raw)
    assert parsed.name == name
    assert parsed.category == category
    assert parsed.generic.category == generic


def test_the_mapping_lives_in_one_file():
    """So it can be reviewed as a table rather than hunted for."""
    text = pathlib.Path(
        "src/lingua_oracle/mixture/classes.py").read_text(encoding="utf-8")
    assert "CODE_TO_CLASS" in text
    for module in ("rules.py", "model.py", "calculate.py"):
        other = pathlib.Path(f"src/lingua_oracle/mixture/{module}").read_text()
        assert "CODE_TO_CLASS: dict" not in other
