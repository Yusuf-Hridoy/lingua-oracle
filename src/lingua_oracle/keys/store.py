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


def save_key(key: AnswerKey) -> Path:
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
