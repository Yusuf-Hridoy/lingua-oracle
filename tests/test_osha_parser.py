"""Unit tests for the OSHA Appendix C parser.

Each case below is taken from a line that actually appeared in
data/answer_keys/us_osha/_parse_issues.txt, so these pin real defects rather
than imagined ones.
"""

from __future__ import annotations

import pytest
from lxml import html as LH

from lingua_oracle.keys.builders.us_osha import (
    _core_key,
    _node_text,
    _resolve_code,
    split_two_statements,
    strip_condition,
)

# A miniature reference table, in the shape _resolve_code expects.
REFERENCE = {
    "H222": "Extremely flammable aerosol",
    "H223": "Flammable aerosol",
    "H229": "Pressurised container: may burst if heated",
    "H220": "Extremely flammable gas",
    "P210": "Keep away from heat",
    "P260": "Do not breathe dusts or mists",
    "P243": "Ground and bond container and receiving equipment",
    "P501": "Dispose of contents/container to …",
}
CANDIDATES = [(c, _core_key(t), _core_key(t)) for c, t in REFERENCE.items()]


# -- (a) two statements in one cell ------------------------------------------


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("Extremely flammable aerosol Pressurized container: may burst if heated",
         {"H222", "H229"}),
        ("Flammable aerosol Pressurized container: may burst if heated.",
         {"H223", "H229"}),
    ],
)
def test_splits_a_cell_holding_two_statements(cell, expected):
    pair = split_two_statements(cell, CANDIDATES)
    assert pair is not None, cell
    assert {code for _text, code, _how in pair} == expected


def test_does_not_split_a_single_statement():
    """A split is only accepted when both halves resolve, so this must not split."""
    assert split_two_statements("Extremely flammable aerosol", CANDIDATES) is None
    assert split_two_statements("Keep away from heat", CANDIDATES) is None


# -- (b) usage-condition suffixes --------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Do not breathe dusts or mists. - if inhalable particles of dusts or mists",
         "Do not breathe dusts or mists."),
        ("Ground and bond container and receiving equipment. - if electrostatically sensitive",
         "Ground and bond container and receiving equipment."),
        ("Ground and bond container and receiving equipment. if the explosive is sensitive",
         "Ground and bond container and receiving equipment."),
        ("Do not allow contact with air. - if emphasis of the hazard statement is needed",
         "Do not allow contact with air."),
    ],
)
def test_strips_usage_conditions(raw, expected):
    assert strip_condition(raw) == expected


def test_keeps_a_conditional_that_is_part_of_the_statement():
    """'if you feel unwell' is statement text, not a usage condition."""
    text = "If swallowed: Call a poison center/doctor/…/ if you feel unwell."
    assert strip_condition(text) == text


# -- (c) text nodes joined with a space ---------------------------------------


def test_joins_text_nodes_with_a_space():
    """text_content() would glue these into 'whenfire'."""
    cell = LH.fromstring("<td>DO NOT fight fire when<i>fire</i> reaches explosives.</td>")
    assert _node_text(cell) == "DO NOT fight fire when fire reaches explosives."


# -- (d) runs of ellipses collapse to one fill-in -----------------------------


@pytest.mark.parametrize(
    "variant",
    [
        "Dispose of contents/container to… … in accordance with local",
        "Dispose of contents/container to … …in accordance with local",
        "Dispose of contents/container to … … in accordance with local",
        "Dispose of contents/container to…… in accordance with local",
    ],
)
def test_ellipsis_runs_collapse_to_one_slot(variant):
    canonical = _core_key("Dispose of contents/container to … in accordance with local")
    assert _core_key(variant) == canonical


def test_resolve_is_exact_and_refuses_a_near_miss():
    code, _how = _resolve_code("Keep away from heat", CANDIDATES)
    assert code == "P210"
    code, _how = _resolve_code("Keep well away from heat sources", CANDIDATES)
    assert code is None
