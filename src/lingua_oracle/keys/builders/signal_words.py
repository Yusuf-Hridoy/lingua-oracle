"""Reading signal words out of official PDFs.

Signal words are not in the statement annexes; they sit in the label-element
tables, which name a signal word per hazard class and category. Two problems
follow, and each has its own strategy here.

**Finding the cell.** In an English source the cell says "Danger" or "Warning"
outright, so it can be found by value. In a translated source it does not, and a
heading cannot be matched without knowing the translation in advance - which
would mean supplying regulatory text from memory.

**Aligning translations.** The label-element tables carry H codes, and codes are
identical in every language. So a translated table is matched to its English
counterpart by having the *same set of codes*, and the signal word is then read
from the same cell position. Nothing is translated or guessed; the value comes
from the document.

A word is only accepted on a two-thirds supermajority of aligned cells. Where the
source itself is inconsistent - the Greek consolidated CLP uses two different
words - the caller supplies a tie-break drawn from other official text.
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path

import pymupdf

from lingua_oracle.keys.builders.common import cache_dir
from lingua_oracle.match.normalize import normalize

_CODE_RE = re.compile(r"\bH\d{3}\b")
ENGLISH_WORDS = ("Danger", "Warning")
MIN_VOTES = 2
SUPERMAJORITY = (2, 3)  # numerator, denominator


def _cell(value: str | None) -> str:
    return " ".join((value or "").replace("\n", " ").split())


def _cache_path(path: str, tag: str) -> Path:
    stat = Path(path).stat()
    key = hashlib.sha256(
        f"{path}|{stat.st_size}|{int(stat.st_mtime)}|{tag}|v1".encode()
    ).hexdigest()[:24]
    return cache_dir() / f"signals-{key}.json"


def _code_tables(path: str, min_codes: int = 2) -> dict[frozenset[str], list[list[list[str]]]]:
    """Tables that carry at least `min_codes` H codes, keyed by their code set.

    Table detection is the expensive part of a build, so the result is cached on
    the file's size and mtime.
    """
    cached = _cache_path(path, f"tables{min_codes}")
    if cached.exists():
        blob = json.loads(cached.read_text(encoding="utf-8"))
        return {frozenset(entry["codes"]): entry["tables"] for entry in blob}

    doc = pymupdf.open(path)
    out: dict[frozenset[str], list[list[list[str]]]] = {}
    try:
        for index in range(doc.page_count):
            for table in doc[index].find_tables().tables:
                rows = [[_cell(c) for c in row] for row in table.extract()]
                codes = frozenset(_CODE_RE.findall(" ".join(c for r in rows for c in r)))
                if len(codes) >= min_codes:
                    out.setdefault(codes, []).append(rows)
    finally:
        doc.close()
    cached.write_text(
        json.dumps([{"codes": sorted(k), "tables": v} for k, v in out.items()],
                   ensure_ascii=False),
        encoding="utf-8",
    )
    return out


def _accept(counter: collections.Counter) -> str | None:
    total = sum(counter.values())
    if total < MIN_VOTES:
        return None
    best, votes = counter.most_common(1)[0]
    num, den = SUPERMAJORITY
    return best if votes * den >= total * num else None


def from_english(path: str) -> dict[str, str]:
    """Signal words stated in an English source, confirmed present in its tables."""
    cached = _cache_path(path, "english")
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    doc = pymupdf.open(path)
    seen: collections.Counter = collections.Counter()
    try:
        for index in range(doc.page_count):
            for table in doc[index].find_tables().tables:
                for row in table.extract():
                    for value in row or []:
                        text = _cell(value)
                        if text in ENGLISH_WORDS:
                            seen[text] += 1
    finally:
        doc.close()
    result = {word: word for word in ENGLISH_WORDS if seen[word] >= MIN_VOTES}
    cached.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def align_by_codes(english_path: str, translated_path: str) -> tuple[dict[str, str], dict]:
    """Read a translated source's signal words by aligning tables on their codes."""
    english = _code_tables(english_path)
    translated = _code_tables(translated_path)
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    aligned = 0
    for codes in set(english) & set(translated):
        aligned += 1
        for en_rows in english[codes]:
            for other_rows in translated[codes]:
                for ri, en_row in enumerate(en_rows):
                    if ri >= len(other_rows):
                        continue
                    for ci, en_value in enumerate(en_row):
                        if en_value not in ENGLISH_WORDS or ci >= len(other_rows[ri]):
                            continue
                        value = other_rows[ri][ci]
                        if value:
                            votes[en_value][value] += 1
    result = {word: chosen for word, counter in votes.items()
              if (chosen := _accept(counter)) is not None}
    detail = {
        "tables_aligned": aligned,
        "votes": {k: dict(v.most_common(4)) for k, v in votes.items()},
        "rejected": sorted(set(votes) - set(result)),
    }
    return result, detail


def leading_word(text: str) -> str | None:
    """The word a statement opens with, before '!' - e.g. EUH206's 'Warning!'.

    Used only as a tie-break where a source contradicts itself, and only after the
    rule has been validated against languages whose signal word is already known.
    """
    match = re.match(r"\s*([^\s!.,;:]+)\s*!", normalize(text))
    return match.group(1) if match else None


def entries_for(
    words: dict[str, str],
    *,
    regulation: str,
    revision: str,
    language: str,
    source_url: str,
    source_ref: str,
    retrieved_at,
):
    """Turn {"Danger": text, "Warning": text} into answer-key signal entries."""
    from lingua_oracle.models import (
        SIGNAL_DANGER,
        SIGNAL_WARNING,
        AnswerKeyEntry,
        Kind,
        Status,
        Tier,
    )

    codes = {"Danger": SIGNAL_DANGER, "Warning": SIGNAL_WARNING}
    return [
        AnswerKeyEntry(
            regulation=regulation, revision=revision, language=language,
            code=codes[word], kind=Kind.SIGNAL, text=text, signal_word=word,
            tier=Tier.A, source_url=source_url, source_ref=source_ref,
            retrieved_at=retrieved_at, status=Status.OK,
        )
        for word, text in sorted(words.items())
        if word in codes and text
    ]
