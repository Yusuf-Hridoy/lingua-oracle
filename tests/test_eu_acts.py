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


# -- what the comparison does with a carried defect ---------------------------


GERMAN_P280 = ("Schutzhandschuhe/Schutzkleidung/Augenschutz/Gesichtsschutz/"
               "Gehörschutz/… tragen")


@pytest.mark.parametrize("document", [
    # The official German text stops without a full stop, in the act as well as
    # the consolidation. An author who writes the sentence out ends it normally.
    "Schutzhandschuhe/Augenschutz tragen",
    "Schutzhandschuhe/Augenschutz tragen.",
    "Schutzhandschuhe/Schutzkleidung/Augenschutz/Gesichtsschutz tragen",
    "Schutzhandschuhe/Schutzkleidung/Augenschutz/Gesichtsschutz tragen.",
    GERMAN_P280,
    GERMAN_P280 + ".",
])
def test_a_full_stop_the_official_text_lacks_is_never_a_failure(document):
    from lingua_oracle.match.template import match

    result = match(document, GERMAN_P280, language="de")
    assert result.matched, document


def test_the_full_stop_is_still_reported_as_something_to_check():
    """Never wrong wording - but not silent either."""
    from lingua_oracle.match.template import MatchKind, match

    with_stop = match("Schutzhandschuhe/Augenschutz tragen.", GERMAN_P280)
    without = match("Schutzhandschuhe/Augenschutz tragen", GERMAN_P280)
    assert with_stop.kind is MatchKind.PUNCTUATION
    assert without.kind is MatchKind.TEMPLATE


def test_a_real_wording_difference_still_fails_with_a_full_stop_on_it():
    from lingua_oracle.match.template import match

    assert not match("Schutzhandschuhe/Augenschutz anlegen.", GERMAN_P280).matched


def test_a_document_that_drops_a_full_stop_the_act_has_is_still_reported():
    """The tolerance runs one way: this is the case it must not swallow."""
    from lingua_oracle.match.template import MatchKind, match

    result = match("Read label before use", "Read label before use.")
    assert result.matched
    assert result.kind is MatchKind.PUNCTUATION


# -- homoglyphs ---------------------------------------------------------------


GREEK_KEY = ("Aποφεύγετε να αναπνέετε σκόνη/αναθυμιάσεις/αέρια/σταγονίδια/"
             "ατμούς/εκνεφώματα.")          # opens with LATIN CAPITAL A - the act's own
GREEK_DOC = ("Αποφεύγετε να αναπνέετε σκόνη/αναθυμιάσεις/αέρια/σταγονίδια/"
             "ατμούς/εκνεφώματα.")          # opens with GREEK CAPITAL ALPHA


def test_a_greek_document_matches_the_acts_latin_a():
    from lingua_oracle.match.template import match

    assert match(GREEK_DOC, GREEK_KEY, language="el").matched


def test_and_the_other_way_round():
    """A document carrying the same slip is not failed for it either."""
    from lingua_oracle.match.template import match

    assert match(GREEK_KEY, GREEK_DOC, language="el").matched


def test_the_fold_is_not_applied_to_languages_that_do_not_need_it():
    from lingua_oracle.match.template import match

    for language in (None, "en", "de", "ru"):
        assert not match(GREEK_DOC, GREEK_KEY, language=language).matched


def test_folding_never_hides_a_real_difference():
    from lingua_oracle.match.template import match

    assert not match("Αποφεύγετε να πίνετε νερό.", GREEK_KEY, language="el").matched


def test_bulgarian_folds_against_cyrillic():
    from lingua_oracle.match.template import match

    latin = "Избягвайте вдишване на прах. 50 °C"      # C is LATIN CAPITAL C
    cyrillic = "Избягвайте вдишване на прах. 50 °С"   # C is CYRILLIC CAPITAL ES
    assert match(latin, cyrillic, language="bg").matched
    assert match(cyrillic, latin, language="bg").matched
    assert not match(latin, cyrillic, language="el").matched


def test_the_text_itself_is_never_rewritten():
    """Folding is for comparing. The key keeps what the act printed."""
    from lingua_oracle.keys.store import load_key

    entry = load_key("eu_clp", "el").by_code()["P261"]
    assert entry.text.startswith("A")          # U+0041, as the act prints it
    assert ord(entry.text[0]) == 0x41


def test_without_the_recorded_defect_the_full_stop_is_still_only_a_check():
    """The allowance belongs to the entry, not to the matcher.

    Everywhere else an added full stop stays what it was: reported, matched,
    and not a clean pass.
    """
    from lingua_oracle.match.template import MatchKind, match

    plain = match("Schutzhandschuhe/Augenschutz tragen.", GERMAN_P280)
    allowed = match("Schutzhandschuhe/Augenschutz tragen.", GERMAN_P280,
                    optional_terminator=True)
    assert plain.kind is MatchKind.PUNCTUATION
    assert allowed.kind is MatchKind.TEMPLATE


def test_an_option_the_author_chose_is_not_a_filled_in_value():
    """German puts the verb behind the open option: ".../Gehörschutz/… tragen".

    Read naively the whole of "Augenschutz" lands in the open slot, and the
    report asks a person to check a value the act itself supplies. The trailing
    literal is split off the open option, so picking two of the listed options
    fills nothing in.
    """
    from lingua_oracle.match.template import match

    assert match("Schutzhandschuhe/Augenschutz tragen", GERMAN_P280).fillins == []
    # Something the author really did write into the slot is still reported.
    assert match("Schutzhandschuhe/eine Gummischürze tragen",
                 GERMAN_P280).fillins == ["eine Gummischürze"]
    # And the placeholder left in the sheet is still an unfilled blank.
    assert match(GERMAN_P280, GERMAN_P280).fillins == ["…"]
