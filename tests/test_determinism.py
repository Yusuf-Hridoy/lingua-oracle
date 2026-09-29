"""Rebuilding an unchanged source must produce no diff.

Builders stamp `retrieved_at` on every entry they create, so without care a
rebuild of an unchanged source would rewrite every timestamp and produce a huge
diff that means nothing - which in turn hides the small diffs that do matter.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from lingua_oracle.keys.store import (
    available_languages,
    available_regulations,
    key_path,
    load_key,
    preserve_timestamps,
    save_key,
)
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Kind, Tier

LATER = datetime(2030, 1, 1, tzinfo=UTC)


def _entry(code: str, text: str, *, ref: str = "ref", stamp: datetime | None = None):
    return AnswerKeyEntry(
        regulation="eu_clp", revision="r", language="en", code=code, kind=Kind.HAZARD,
        text=text, tier=Tier.A, source_url="u", source_ref=ref, retrieved_at=stamp,
    )


def test_unchanged_entry_keeps_its_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUA_DATA_DIR", str(tmp_path))
    original = datetime(2024, 5, 1, tzinfo=UTC)
    save_key(
        AnswerKey(regulation="eu_clp", language="en", revision="r", retrieved_at=original,
                  entries=[_entry("H225", "Highly flammable.", stamp=original)]),
        preserve=False,
    )
    rebuilt = AnswerKey(
        regulation="eu_clp", language="en", revision="r", retrieved_at=LATER,
        entries=[_entry("H225", "Highly flammable.", stamp=LATER)],
    )
    merged = preserve_timestamps(rebuilt)
    assert merged.entries[0].retrieved_at == original
    assert merged.retrieved_at == original  # nothing changed at all


def test_changed_text_takes_a_fresh_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUA_DATA_DIR", str(tmp_path))
    original = datetime(2024, 5, 1, tzinfo=UTC)
    save_key(
        AnswerKey(regulation="eu_clp", language="en", revision="r", retrieved_at=original,
                  entries=[_entry("H225", "Old wording.", stamp=original)]),
        preserve=False,
    )
    rebuilt = AnswerKey(
        regulation="eu_clp", language="en", revision="r", retrieved_at=LATER,
        entries=[_entry("H225", "New wording.", stamp=LATER)],
    )
    merged = preserve_timestamps(rebuilt)
    assert merged.entries[0].retrieved_at == LATER
    assert merged.retrieved_at == LATER


def test_changed_source_ref_takes_a_fresh_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUA_DATA_DIR", str(tmp_path))
    original = datetime(2024, 5, 1, tzinfo=UTC)
    save_key(
        AnswerKey(regulation="eu_clp", language="en", revision="r", retrieved_at=original,
                  entries=[_entry("H225", "Same.", ref="annex III", stamp=original)]),
        preserve=False,
    )
    merged = preserve_timestamps(
        AnswerKey(regulation="eu_clp", language="en", revision="r", retrieved_at=LATER,
                  entries=[_entry("H225", "Same.", ref="annex IV", stamp=LATER)])
    )
    assert merged.entries[0].retrieved_at == LATER


def test_a_new_entry_marks_the_key_as_changed(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUA_DATA_DIR", str(tmp_path))
    original = datetime(2024, 5, 1, tzinfo=UTC)
    save_key(
        AnswerKey(regulation="eu_clp", language="en", revision="r", retrieved_at=original,
                  entries=[_entry("H225", "A", stamp=original)]),
        preserve=False,
    )
    merged = preserve_timestamps(
        AnswerKey(regulation="eu_clp", language="en", revision="r", retrieved_at=LATER,
                  entries=[_entry("H225", "A", stamp=LATER), _entry("H226", "B", stamp=LATER)])
    )
    assert merged.entries[0].retrieved_at == original  # unchanged entry keeps its stamp
    assert merged.entries[1].retrieved_at == LATER     # the new one is new
    assert merged.retrieved_at == LATER                # the key did change


def test_rewriting_every_stored_key_is_byte_identical():
    """The real guard: re-saving each committed key must not change the file.

    This is what makes `lingua keys build` safe to re-run - a rebuild that found
    nothing new leaves the working tree clean, so any diff is a real change.
    """
    checked = 0
    for regulation in available_regulations():
        for language in available_languages(regulation):
            path = key_path(regulation, language)
            before = path.read_bytes()
            key = load_key(regulation, language)
            assert key is not None
            # Stamp every entry as if freshly built, then save through the
            # normal path; preservation must undo it.
            rebuilt = key.model_copy(
                update={
                    "retrieved_at": LATER,
                    "entries": [e.model_copy(update={"retrieved_at": LATER})
                                for e in key.entries],
                }
            )
            save_key(rebuilt)
            after = path.read_bytes()
            if after != before:
                path.write_bytes(before)  # restore before failing
                pytest.fail(f"{regulation}/{language} changed on an unchanged rebuild")
            checked += 1
    assert checked > 10, "expected to check many keys"
