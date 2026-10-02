"""Reviewed corrections to typing errors in an official source's own text.

A consolidated act is typed by people, and CLP states every statement twice:
once in Annex IV Part 1, beside the hazard class it is selected for, and once in
Part 2, in all languages. Where the two disagree over a single letter, one of
them is a typing error - `Do no rub` against `Do not rub` - and a document that
writes the sentence properly would be failed against the broken rendering.

This is the one place such a correction may be made, and it is narrow by design:

* it names the code and the language, and applies to nothing else;
* it applies only while the stored text still matches `wrong` exactly, so a
  correction made upstream ends the erratum instead of being overwritten by it;
* it records the evidence - where in the act the intended sentence is printed -
  because a correction with no source is an invention, which this tool does not
  make;
* every entry it touches says so in `source_ref`, which the report prints under
  "Where each wording came from", so a reader can see the text was corrected and
  check the evidence themselves.

It is not a general repair mechanism. Wording that merely looks wrong, or that
differs between editions, is not an erratum: that is the regulator's text and the
answer to it is a new build, not a patch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from lingua_oracle.models import AnswerKey, AnswerKeyEntry
from lingua_oracle.registry import data_dir


@dataclass(frozen=True)
class Erratum:
    code: str
    language: str
    wrong: str
    corrected: str
    reason: str
    evidence: str
    evidence_url: str = ""
    reviewed_on: str = ""

    def note(self) -> str:
        """The sentence appended to the entry's source_ref."""
        return (f"corrected by reviewed erratum ({self.reason} Evidence: "
                f"{self.evidence})")


def errata_root() -> Path:
    return data_dir() / "errata"


@cache
def load_errata(regulation: str) -> tuple[Erratum, ...]:
    path = errata_root() / f"{regulation}.json"
    if not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(Erratum(**row) for row in payload.get("corrections", []))


def correct(key: AnswerKey | None) -> tuple[dict[str, AnswerKeyEntry], list[Erratum]]:
    """Return the key's entries by code, with any erratum for them applied."""
    entries: dict[str, AnswerKeyEntry] = dict(key.by_code()) if key else {}
    if key is None:
        return entries, []
    applied: list[Erratum] = []
    for erratum in load_errata(key.regulation):
        if erratum.language != key.language:
            continue
        entry = entries.get(erratum.code)
        if entry is None or entry.text != erratum.wrong:
            continue  # already right, or no longer the text we reviewed
        source = entry.source_ref or ""
        entries[erratum.code] = entry.model_copy(update={
            "text": erratum.corrected,
            "source_ref": f"{source}; {erratum.note()}" if source else erratum.note(),
        })
        applied.append(erratum)
    return entries, applied
