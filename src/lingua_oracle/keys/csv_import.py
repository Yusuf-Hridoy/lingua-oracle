"""Importing answer-key entries from a CSV glossary.

Expected columns (header row required, order free):

    code, text            - required
    kind                  - hazard|precautionary|supplemental|signal; inferred
                            from the code prefix when absent
    signal_word           - Danger|Warning|Either|None
    source_url, source_ref, revision

Imported entries default to tier C, which means "no official source": they carry
no wording verdict and are only used for the consistency check.
"""

from __future__ import annotations

import csv
from pathlib import Path

from lingua_oracle.keys.builders.common import normalise_code, now
from lingua_oracle.keys.store import load_key, save_key
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Kind, Status, Tier
from lingua_oracle.registry import load_registry

REQUIRED = {"code", "text"}


def infer_kind(code: str) -> Kind:
    if code.startswith("SIGNAL"):
        return Kind.SIGNAL
    if code.startswith(("EUH", "AUH")):
        return Kind.SUPPLEMENTAL
    if code.startswith("H"):
        return Kind.HAZARD
    return Kind.PRECAUTIONARY


def import_csv(
    path: str | Path,
    regulation: str,
    language: str,
    tier: Tier = Tier.C,
    *,
    replace: bool = False,
) -> AnswerKey:
    """Merge a CSV into the key for `regulation` x `language`."""
    reg = load_registry().get(regulation)
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path}: no data rows")
    missing = REQUIRED - {(k or "").strip().lower() for k in rows[0]}
    if missing:
        raise ValueError(f"{path}: missing required column(s): {', '.join(sorted(missing))}")

    existing = load_key(regulation, language)
    entries = {} if replace or existing is None else existing.by_code()
    ts = now()

    for row in rows:
        clean = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        code = normalise_code(clean["code"])
        text = clean["text"]
        if not code or not text:
            continue
        kind_raw = clean.get("kind", "")
        entries[code] = AnswerKeyEntry(
            regulation=regulation,
            revision=clean.get("revision") or reg.revision,
            language=language,
            code=code,
            kind=Kind(kind_raw) if kind_raw in set(Kind) else infer_kind(code),
            text=text,
            signal_word=clean.get("signal_word") or None,  # type: ignore[arg-type]
            tier=tier,
            source_url=clean.get("source_url") or None,
            source_ref=clean.get("source_ref") or f"CSV import from {Path(path).name}",
            retrieved_at=ts,
            status=Status.OK,
        )

    key = AnswerKey(
        regulation=regulation,
        language=language,
        revision=reg.revision,
        status=Status.OK if entries else Status.PENDING_SOURCE,
        source_url=existing.source_url if existing else None,
        retrieved_at=ts,
        entries=sorted(entries.values(), key=lambda e: (e.kind, e.code)),
    )
    save_key(key)
    return key
