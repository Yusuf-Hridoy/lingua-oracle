"""Unit tests for the template matcher: slash subsets, fill-ins, optional groups."""

from __future__ import annotations

import pytest

from lingua_oracle.keys.store import load_key
from lingua_oracle.match.template import MatchKind, has_template_syntax, match

GLOVES = "Wear protective gloves/protective clothing/eye protection/face protection."
BREATHE = "Do not breathe dust/fume/gas/mist/vapours/spray."
ADVICE = "Get medical advice/attention."
ORGANS = (
    "Causes damage to organs <or state all organs affected, if known> "
    "<state route of exposure if it is conclusively proven that no other routes "
    "of exposure cause the hazard>."
)
WASH = "Wash … thoroughly after handling."
EXPLOSION = "Use explosion-proof [electrical/ventilating/lighting/…] equipment."
H225 = "Highly flammable liquid and vapour."


@pytest.mark.parametrize(
    "found",
    [
        GLOVES,
        "Wear protective gloves.",
        "Wear protective clothing.",
        "Wear face protection.",
        "Wear protective gloves/eye protection.",
        "Wear protective gloves, eye protection.",
        "Wear protective gloves/protective clothing/face protection.",
    ],
)
def test_slash_subsets_pass(found):
    assert match(found, GLOVES).matched


@pytest.mark.parametrize(
    "found",
    [
        "Wear eye protection/protective gloves.",  # official order broken
        "Wear protective gloves/safety boots.",  # not an official alternative
        "Wear.",  # empty selection
    ],
)
def test_slash_subsets_fail(found):
    assert not match(found, GLOVES).matched


def test_single_word_alternatives():
    assert match("Do not breathe dust.", BREATHE).matched
    assert match("Do not breathe dust/vapours/spray.", BREATHE).matched
    assert not match("Do not breathe fumes.", BREATHE).matched


def test_ambiguous_split_accepts_both_readings():
    """'Get medical advice/attention' may mean advice+attention or medical advice."""
    assert match("Get medical advice.", ADVICE).matched
    assert match("Get medical attention.", ADVICE).matched
    assert match(ADVICE, ADVICE).matched


def test_fillins_are_reported():
    result = match("Wash hands and face thoroughly after handling.", WASH)
    assert result.matched
    assert result.fillins == ["hands and face"]


def test_unfilled_fillin_fails():
    assert not match("Wash thoroughly after handling.", WASH).matched


def test_angle_bracket_fillins():
    result = match("Causes damage to organs (liver) through inhalation.", ORGANS)
    assert result.matched
    assert result.fillins


def test_optional_bracket_group():
    assert match("Use explosion-proof electrical equipment.", EXPLOSION).matched
    assert match("Use explosion-proof equipment.", EXPLOSION).matched


def test_exact_case_and_punctuation_kinds():
    assert match(H225, H225).kind is MatchKind.EXACT
    assert match(H225.lower(), H225).kind is MatchKind.CASE
    assert match(H225.rstrip("."), H225).kind is MatchKind.PUNCTUATION
    assert not match("Extremely flammable liquid and vapour.", H225).matched


def test_empty_found_is_a_mismatch():
    assert not match("", H225).matched


def test_has_template_syntax():
    assert has_template_syntax(GLOVES)
    assert has_template_syntax(WASH)
    assert not has_template_syntax(H225)


@pytest.mark.parametrize("language", ["en", "da", "de", "fr", "pl"])
def test_every_official_text_matches_itself(language):
    """The strongest guard there is: official wording must never fail its own key."""
    key = load_key("eu_clp", language)
    assert key is not None and key.entries
    for entry in key.entries:
        assert match(entry.text, entry.text).matched, f"{language} {entry.code}"


# -- a template must never compile to "anything at all" -----------------------


@pytest.mark.parametrize(
    "template",
    [
        "IF ON SKIN: Wash with plenty of water/…",
        "Dispose of contents/container to…",
        "Wear protective gloves/protective clothing/eye protection/face protection.",
        "Use explosion-proof [electrical/ventilating/lighting/…] equipment.",
        "Store in a well-ventilated place. Keep container tightly closed.",
    ],
)
def test_no_template_matches_unrelated_text(template):
    """Found in Phase 1.5: some templates matched every sentence ever written.

    Splitting "a/b" into alternatives could cut the leading literal away and
    then pick a subset that was nothing but the fill-in, leaving a bare `.*?`
    between the anchors. A-03 could not fail a wrong statement for any code
    whose official text ends in "/…".
    """
    from lingua_oracle.match.template import match

    for unrelated in ("Completely unrelated sentence here.",
                      "The quick brown fox jumps over the lazy dog.",
                      "Section 4: First aid measures"):
        assert not match(unrelated, template).matched, (
            f"{template!r} matched unrelated text {unrelated!r}"
        )


def test_every_official_text_still_matches_itself_after_the_guard():
    """The guard must not drop a variant a real statement needs."""
    from lingua_oracle.keys.store import load_key
    from lingua_oracle.match.template import match

    for reg, lang in (("eu_clp", "en"), ("un_ghs", "en"), ("us_osha", "en")):
        for entry in load_key(reg, lang).entries:
            if not entry.text:
                continue
            assert match(entry.text, entry.text).matched, f"{reg}/{entry.code}"
