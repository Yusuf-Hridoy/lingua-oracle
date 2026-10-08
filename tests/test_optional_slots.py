"""Conditional slots are optional in every key, in every language.

"<state specific effect if known>" and "<state route of exposure if it is
conclusively proven ...>" say in English that they are conditional. The same
act in the other 23 EU languages puts the same slots in the same order, and
the English parallel decides - nothing is translated from memory.
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import pytest

from lingua_oracle.keys.store import load_key
from lingua_oracle.match.template import _FILLIN_RE, match, with_optional_slots
from lingua_oracle.pipeline import check_pdf
from tests.make_fixtures import write_sds

#: The act's own rendering defeats the alignment: a slot that has lost its
#: opening bracket, in a reordered sentence. Left as it is rather than guessed.
SOURCE_DEFECTS = {("eu_clp", "hu", "H373")}


def _english() -> dict[str, dict[str, str]]:
    out = {}
    for path in glob.glob("data/answer_keys/*/en.json"):
        key = json.loads(Path(path).read_text(encoding="utf-8"))
        out[key["regulation"]] = {e["code"]: e.get("text") for e in key["entries"]}
    return out


def test_every_conditional_slot_in_every_key_may_be_left_out():
    english, failing = _english(), []
    for path in sorted(glob.glob("data/answer_keys/*/*.json")):
        key = json.loads(Path(path).read_text(encoding="utf-8"))
        regulation, language = key["regulation"], key["language"]
        for entry in key["entries"]:
            text = entry.get("text") or ""
            if (entry.get("status") != "ok" or entry["code"] == "EUH208"
                    or "…" in text or not _FILLIN_RE.search(text)):
                continue
            bare = re.sub(r"\s+", " ", _FILLIN_RE.sub("", text)).replace(" .", ".").strip()
            parallel = None if language == "en" else english.get(regulation, {}).get(entry["code"])
            if not match(bare, text, language=language, parallel=parallel).matched:
                failing.append((regulation, language, entry["code"]))
    assert set(failing) == SOURCE_DEFECTS, failing


def test_h361_without_its_slots_passes_under_gb_clp():
    official = load_key("uk_clp", "en").by_code()["H361"].text
    result = match("Suspected of damaging fertility or the unborn child.", official,
                   language="en")
    assert result.matched and result.is_clean


def test_a_missing_full_stop_after_a_slot_is_punctuation_not_a_mismatch():
    official = load_key("uk_clp", "en").by_code()["H361"].text
    result = match("Suspected of damaging fertility or the unborn child", official,
                   language="en")
    assert result.matched and result.kind.value == "punctuation"


@pytest.mark.parametrize("language", ["en", "de", "fr"])
def test_a_required_slot_stays_required(language):
    official = load_key("eu_clp", language).by_code()["EUH208"].text
    english = load_key("eu_clp", "en").by_code()["EUH208"].text
    bare = re.sub(r"\s*<[^>]*>", "", official)
    assert not match(bare, official, language=language,
                     parallel=None if language == "en" else english).matched


def test_slots_are_marked_one_by_one_and_only_where_they_align():
    english = "Damage to organs <or state all organs affected, if known> <state route if it is conclusively proven that no other>."
    two = "Schade aan organen <alle organen> veroorzaken <route>."
    marked = with_optional_slots(two, english)
    assert marked.count("⁣") == 2
    assert with_optional_slots("Text <one only>.", english) == "Text <one only>."


def test_a_german_sheet_printing_h361_without_its_slots_is_correct(tmp_path):
    official = load_key("eu_clp", "de").by_code()["H361"].text
    bare = re.sub(r"\s+", " ", _FILLIN_RE.sub("", official)).replace(" .", ".").strip()
    path = write_sds(tmp_path / "de_h361.pdf", regulation="eu_clp", language="de",
                     h_codes=["H361"], p_codes=["P201"], overrides={"H361": bare})
    report = check_pdf(str(path), "eu_clp", "de")
    verdict = next(v for v in report.statements if v.code == "H361")
    assert verdict.status == "correct", verdict.why
