"""Reading and writing answer keys on disk (data/answer_keys/{reg}/{lang}.json)."""

from __future__ import annotations

import json
from pathlib import Path

from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Status, Tier
from lingua_oracle.registry import data_dir


def keys_root() -> Path:
    return data_dir() / "answer_keys"


def key_path(regulation: str, language: str) -> Path:
    return keys_root() / regulation / f"{language}.json"


def _identity(entry: AnswerKeyEntry) -> tuple[str, str, str | None]:
    """What makes an entry "the same entry" for timestamp purposes."""
    return (entry.code, entry.text, entry.source_ref)


def preserve_timestamps(key: AnswerKey) -> AnswerKey:
    """Carry `retrieved_at` over from the stored key where nothing has changed.

    A builder stamps the current time on every entry it produces, so rebuilding
    an unchanged source would rewrite every timestamp and show a large diff that
    means nothing. An entry keeps its stored timestamp when its code, text and
    source_ref are all unchanged; a real change takes a fresh one. The key's own
    `retrieved_at` is kept when no entry changed at all.
    """
    existing = load_key(key.regulation, key.language)
    if existing is None:
        return key

    previous = {_identity(e): e.retrieved_at for e in existing.entries}
    entries = []
    changed = False
    for entry in key.entries:
        stamp = previous.get(_identity(entry))
        if stamp is not None and stamp != entry.retrieved_at:
            entry = entry.model_copy(update={"retrieved_at": stamp})
        elif stamp is None:
            changed = True
        entries.append(entry)

    if len(entries) != len(existing.entries):
        changed = True
    updated = key.model_copy(update={"entries": entries})
    if not changed and existing.retrieved_at is not None:
        updated = updated.model_copy(update={"retrieved_at": existing.retrieved_at})
    return updated


def save_key(key: AnswerKey, *, preserve: bool = True) -> Path:
    """Write a key. By default an unchanged rebuild produces an identical file."""
    if preserve:
        key = preserve_timestamps(key)
    path = key_path(key.regulation, key.language)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = key.model_dump(mode="json", exclude_none=False)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_key(regulation: str, language: str) -> AnswerKey | None:
    path = key_path(regulation, language)
    if not path.exists():
        return None
    return AnswerKey.model_validate_json(path.read_text(encoding="utf-8"))


def available_languages(regulation: str) -> list[str]:
    d = keys_root() / regulation
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def available_regulations() -> list[str]:
    root = keys_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def iter_all_keys():
    for reg in available_regulations():
        for lang in available_languages(reg):
            key = load_key(reg, lang)
            if key is not None:
                yield key


def empty_key(
    regulation: str,
    language: str,
    revision: str,
    *,
    reason: str,
    source_url: str | None = None,
) -> AnswerKey:
    """A placeholder key for a source we could not lawfully or technically fetch."""
    return AnswerKey(
        regulation=regulation,
        language=language,
        revision=revision,
        status=Status.PENDING_SOURCE,
        source_url=source_url,
        entries=[],
    )


__all__ = [
    "AnswerKey",
    "preserve_timestamps",
    "AnswerKeyEntry",
    "Status",
    "Tier",
    "available_languages",
    "available_regulations",
    "empty_key",
    "iter_all_keys",
    "key_path",
    "keys_root",
    "load_key",
    "save_key",
]
