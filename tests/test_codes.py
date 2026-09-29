"""Unit tests for code detection, including combined codes."""

from __future__ import annotations

import pytest

from lingua_oracle.detect.codes import (
    CODE_RE,
    canonical_code,
    extract_hits,
    find_codes_in_text,
    split_combined,
)
from lingua_oracle.extract.base import Line


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("H225", "H225"),
        ("h225", "H225"),
        ("EUH 066", "EUH066"),
        ("euh066", "EUH066"),
        ("AUH044", "AUH044"),
        ("P303 + P361 + P353", "P303+P361+P353"),
        ("H300+H310", "H300+H310"),
        ("P305 +P351+ P338", "P305+P351+P338"),
    ],
)
def test_canonical_code(raw, expected):
    assert canonical_code(raw) == expected


def test_finds_all_families():
    text = "H225 a EUH 066 b P303 + P361 + P353 c H300+H310 d AUH044 e"
    codes = [c for c, _s, _e in find_codes_in_text(text)]
    assert codes == ["H225", "EUH066", "P303+P361+P353", "H300+H310", "AUH044"]


def test_split_combined():
    assert split_combined("P303 + P361 + P353") == ["P303", "P361", "P353"]
    assert split_combined("H225") == ["H225"]


def test_does_not_match_random_letters():
    assert not CODE_RE.findall("PH 7.0 and H2O and P 12")


def test_extract_hits_takes_text_up_to_next_code():
    lines = [Line(text="H225 Highly flammable liquid and vapour. H319 Causes eye irritation.",
                  page=1)]
    hits = extract_hits(lines)
    assert [h.code for h in hits] == ["H225", "H319"]
    assert hits[0].text == "Highly flammable liquid and vapour."
    assert hits[1].text == "Causes eye irritation."


def test_extract_hits_stops_at_a_heading():
    lines = [
        Line(text="H241 Heating may cause a fire or explosion", page=1),
        Line(text="SECTION 3: Composition", page=1),
    ]
    hits = extract_hits(lines)
    assert hits[0].text == "Heating may cause a fire or explosion"


def test_extract_hits_joins_a_wrapped_statement():
    lines = [
        Line(text="H225 Highly flammable liquid", page=1),
        Line(text="and vapour.", page=1),
    ]
    hits = extract_hits(lines)
    assert hits[0].text == "Highly flammable liquid and vapour."


def test_bare_code_in_a_classification_list_has_no_text():
    lines = [
        Line(text="Classification: H225, H319, H336", page=1),
        Line(text="SECTION 16: Other information", page=1),
    ]
    hits = extract_hits(lines)
    assert hits[-1].code == "H336"
    assert hits[-1].text == ""
