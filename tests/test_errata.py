"""The reviewed errata table: narrow, evidenced, and visible when used."""

from __future__ import annotations

import json

import pytest

from lingua_oracle.keys.errata import Erratum, correct, errata_root, load_errata
from lingua_oracle.keys.store import load_key
from lingua_oracle.keys.tierb import resolve
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Kind

TYPO = "Thaw frosted parts with lukewarm water. Do no rub affected area."
FIXED = "Thaw frosted parts with lukewarm water. Do not rub affected area."


def test_the_stored_key_still_holds_the_sources_own_text():
    """The key is what the act says. The correction happens on the way out."""
    assert load_key("eu_clp", "en").by_code()["P336"].text == TYPO


def test_the_correction_is_what_reaches_a_comparison():
    assert resolve("eu_clp", "en").entries["P336"].text == FIXED


def test_a_corrected_entry_says_so_where_the_report_prints_it():
    """source_ref is what the report shows under "Where each wording came from"."""
    ref = resolve("eu_clp", "en").entries["P336"].source_ref
    assert "corrected by reviewed erratum" in ref
    assert "Table 6.3" in ref  # the evidence travels with it


def test_the_resolution_names_the_errata_it_used():
    assert [e.code for e in resolve("eu_clp", "en").errata] == ["P336"]


def test_nothing_else_is_touched():
    """Per code and per language, and nothing wider."""
    corrected = resolve("eu_clp", "en").entries
    stored = load_key("eu_clp", "en").by_code()
    changed = {c for c, e in corrected.items() if stored[c].text != e.text}
    assert changed == {"P336"}
    for lang in ("de", "fr", "da"):
        other = resolve("eu_clp", lang)
        assert other.errata == ()


def test_every_erratum_on_file_carries_its_evidence():
    for erratum in load_errata("eu_clp"):
        assert erratum.evidence.strip()
        assert erratum.evidence_url.startswith("http")
        assert erratum.reason.strip()
        assert erratum.reviewed_on


def test_every_erratum_on_file_matches_a_real_entry():
    """An erratum that matches nothing is either stale or a typo of its own."""
    for erratum in load_errata("eu_clp"):
        key = load_key("eu_clp", erratum.language)
        assert key is not None, erratum.language
        entry = key.by_code().get(erratum.code)
        assert entry is not None, erratum.code
        assert entry.text in (erratum.wrong, erratum.corrected)


def test_the_tables_on_file_parse():
    for path in sorted(errata_root().glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["regulation"] == path.stem
        assert payload["corrections"]


def _key(text: str) -> AnswerKey:
    return AnswerKey(
        regulation="eu_clp", revision="test", language="en",
        entries=[AnswerKeyEntry(regulation="eu_clp", revision="test", language="en",
                                code="P336", kind=Kind.PRECAUTIONARY, text=text)],
    )


def test_an_erratum_stops_applying_once_the_source_is_fixed():
    """If the regulator corrects the typo, the erratum must not fight it."""
    entries, applied = correct(_key(FIXED))
    assert entries["P336"].text == FIXED
    assert applied == []


def test_an_erratum_does_not_apply_to_text_it_was_not_reviewed_against():
    entries, applied = correct(_key("Thaw frosted parts with hot water."))
    assert entries["P336"].text == "Thaw frosted parts with hot water."
    assert applied == []


@pytest.mark.parametrize("field", ["wrong", "corrected", "reason", "evidence"])
def test_an_erratum_needs_all_of_its_parts(field):
    parts = {"code": "P336", "language": "en", "wrong": TYPO, "corrected": FIXED,
             "reason": "r", "evidence": "e"}
    parts.pop(field)
    with pytest.raises(TypeError):
        Erratum(**parts)


def test_the_correction_is_one_word_not_a_rewrite():
    """A reviewed erratum fixes a typing error. It is not a place to re-draft."""
    for erratum in load_errata("eu_clp"):
        wrong, right = erratum.wrong.split(), erratum.corrected.split()
        assert len(wrong) == len(right), erratum.code
        differing = [i for i, (a, b) in enumerate(zip(wrong, right, strict=True)) if a != b]
        assert len(differing) == 1, erratum.code
