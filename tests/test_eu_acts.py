"""The rule that decides which Part of Annex IV is the law.

These are pure-logic tests over the decision and the defect checks: no network,
no key files. The data they would read is pinned separately in test_keys.py.
"""

from __future__ import annotations

import json

import pytest

from lingua_oracle.keys.builders.defects import (
    defects,
    dropped_words,
    missing_blank,
    missing_degree_sign,
    missing_terminator,
    wrong_script,
)
from lingua_oracle.keys.builders.eu_acts import act_rank, celex_for, decide
from lingua_oracle.registry import data_dir

#: {marker: {Part: {code: operation}}} in the shape the builder reads from acts.
SCOPE = {
    "M4": {"Part 1": {"P210": "replaced"}, "Part 2": {"P210": "replaced"}},
    "M12": {"Part 1": {"P413": "replaced"}, "Part 2": {}},
    "M19": {"Part 1": {"P103": "replaced", "P210": "replaced"}, "Part 2": {}},
}


# -- ordering the acts --------------------------------------------------------


@pytest.mark.parametrize(("marker", "rank"), [("B", 0), ("M1", 1), ("M19", 19)])
def test_an_act_ranks_by_its_place_in_the_consolidation(marker, rank):
    assert act_rank(marker) == rank


@pytest.mark.parametrize("marker", ["C3", "A1", "", None])
def test_a_corrigendum_has_no_place_in_the_sequence(marker):
    """C3 is not 'after M2': it corrects some act, and which is not in its name."""
    assert act_rank(marker) is None


@pytest.mark.parametrize(("title", "celex"), [
    ("COMMISSION REGULATION (EU) No 487/2013 of 8 May 2013", "32013R0487"),
    ("COMMISSION REGULATION (EU) 2016/918 of 19 May 2016", "32016R0918"),
    ("COMMISSION REGULATION (EC) No 790/2009 of 10 August 2009", "32009R0790"),
    ("COMMISSION DELEGATED REGULATION (EU) 2020/1182 of 19 May 2020", "32020R1182"),
])
def test_an_act_title_gives_its_celex_id(title, celex):
    assert celex_for(title) == celex


def test_a_title_with_no_number_gives_nothing():
    assert celex_for("Notice concerning the classification of pitch") is None


def test_a_corrigendum_gets_no_celex_of_its_own():
    """Its line names the act it corrects; that is a different document."""
    assert celex_for("Corrigendum, OJ L 117, 3.5.2019, p. 8 (No 1272/2008)") is None


# -- which Part is in force ---------------------------------------------------


def test_the_later_act_wins():
    d = decide("P103", "en", "M19", "B", SCOPE)
    assert (d.part, d.act, d.corroborated) == ("Part 1", "M19", True)


def test_part_2_wins_when_it_is_the_one_amended_later():
    scope = {"M12": {"Part 1": {}, "Part 2": {"P9": "replaced"}}}
    d = decide("P9", "en", "B", "M12", scope)
    assert (d.part, d.act) == ("Part 2", "M12")


def test_the_same_act_in_both_parts_leaves_part_2_standing():
    """Then the difference is a rendering, not a change in the law."""
    scope = {"M4": {"Part 1": {"P244": "replaced"}, "Part 2": {"P244": "replaced"}}}
    d = decide("P244", "en", "M4", "M4", scope)
    assert d.part == "Part 2"
    assert "same act" in d.note
    assert d.corroborated


def test_a_code_no_act_ever_touched_stays_with_part_2():
    d = decide("P336", "en", "B", "B", SCOPE)
    assert (d.part, d.act) == ("Part 2", "B")


def test_markers_disagreeing_with_the_acts_decides_nothing():
    """Two sources, and a decision only where they agree."""
    d = decide("P103", "en", "M12", "B", SCOPE)  # the act says M19
    assert d.part == "Part 2"
    assert not d.corroborated
    assert "disagree" in d.note


def test_a_corrigendum_in_the_way_decides_nothing():
    d = decide("P261", "el", "C5", "C5", {})
    assert d.part == "Part 2"
    assert not d.corroborated


def test_a_decision_always_says_which_act_made_it():
    for code in ("P103", "P210", "P413", "P336"):
        d = decide(code, "en", "M19", "B", SCOPE)
        assert d.act
        assert d.note


# -- visible defects ----------------------------------------------------------


def test_a_latin_letter_in_a_greek_sentence_is_a_defect():
    found = wrong_script("Aποφεύγετε να αναπνέετε σκόνη.")
    assert found and "U+0041" in found


def test_the_same_sentence_in_its_own_alphabet_is_not():
    assert wrong_script("Αποφεύγετε να αναπνέετε σκόνη.") is None


@pytest.mark.parametrize("text", [
    "При насипни количества … kg/… фунта при … °C/…°F.",
    "Αποθηκεύεται σε θερμοκρασία που δεν υπερβαίνει τους … °C/… °F.",
])
def test_units_are_not_mistaken_for_stray_letters(text):
    """kg and °C are Latin in every language; they are not a defect."""
    assert wrong_script(text) is None


def test_a_unit_that_lost_its_degree_sign_is_a_defect():
    assert missing_degree_sign("… a temperature non superiori a … C/…°F.")


def test_both_units_spelled_the_same_way_is_not():
    assert missing_degree_sign("… a temperature non superiori a … °C/…°F.") is None


def test_a_sentence_that_simply_stops_is_a_defect():
    assert missing_terminator("Lue huolellisesti ja noudata kaikkia ohjeita",
                              "Lue merkinnät ennen käyttöä.")


def test_an_open_option_is_not_a_missing_full_stop():
    """A statement ending in "/…" is meant to be continued by the author."""
    assert missing_terminator(
        "Wear protective gloves/protective clothing/hearing protection/…",
        "Wear protective gloves/protective clothing.") is None


def test_a_statement_that_introduces_the_next_one_is_not_either():
    assert missing_terminator("IF SWALLOWED:", "IF SWALLOWED:") is None


def test_a_dropped_blank_is_a_defect():
    assert missing_blank("Gesinimui naudoti.", "Gesinimui naudoti …")


def test_a_blank_the_other_part_also_lacks_is_not():
    assert missing_blank("Use … to extinguish.", "Use … to extinguish.") is None


def test_different_wording_is_not_a_dropped_blank():
    """An amendment may rewrite a sentence; that is not a defect."""
    assert missing_blank("Read carefully and follow all instructions.",
                         "Read label before use.") is None


def test_a_dropped_unit_is_a_defect():
    found = dropped_words("Bulk, meer dan … kg, bewaren.",
                          "Bulk, meer dan … kg/… lbs, bewaren.")
    assert found and "lbs" in found


def test_a_shorter_sentence_without_a_unit_is_not():
    assert dropped_words("Wear protective gloves.",
                         "Wear protective gloves/eye protection.") is None


def test_a_clean_statement_has_no_defects():
    assert defects("Read carefully and follow all instructions.",
                   "Read label before use.") == []


def test_a_defect_is_never_reported_twice():
    found = defects("Gesinimui naudoti.", "Gesinimui naudoti …")
    assert len(found) == 1


# -- the act record the build writes ------------------------------------------


def _act_audit():
    path = data_dir() / "audits" / "eu_clp_amending_acts.json"
    if not path.exists():
        pytest.skip("no act record; rebuild eu_clp to produce one")
    return json.loads(path.read_text(encoding="utf-8"))["acts"]


def test_the_acts_that_amended_annex_iv_are_on_record():
    acts = _act_audit()
    assert {"M4", "M12", "M19"} <= set(acts)
    for marker, act in acts.items():
        assert act["celex"], marker
        assert act["title"], marker
        assert act["annex_iv"]["Part 1"] or act["annex_iv"]["Part 2"], marker


def test_the_2019_act_amended_part_1_and_barely_touched_part_2():
    """The whole reason the two Parts disagree on P103 and P280."""
    m19 = _act_audit()["M19"]
    assert "2019/521" in m19["title"]
    assert {"P103", "P280"} <= set(m19["annex_iv"]["Part 1"])
    assert set(m19["annex_iv"]["Part 2"]) == {"P212"}


def test_the_2013_act_amended_both_parts():
    m4 = _act_audit()["M4"]["annex_iv"]
    assert "P210" in m4["Part 1"]
    assert "P210" in m4["Part 2"]
