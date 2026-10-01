"""What the upload page says about the keys and about recent checks.

Both panels are built from data the tool already holds - the committed keys and
the reports on disk - so neither can drift from what a check would actually do.
"""

from __future__ import annotations

import json
from pathlib import Path

from lingua_oracle.detect.language import language_name
from lingua_oracle.keys.store import available_languages, load_key
from lingua_oracle.registry import load_registry
from lingua_oracle.report import labels


def key_coverage() -> list[dict]:
    """One row per regulation: display name and the languages on file."""
    registry = load_registry()
    rows = []
    for reg_id in registry.ids():
        languages = [
            lang for lang in available_languages(reg_id)
            if (key := load_key(reg_id, lang)) is not None and key.entries
        ]
        rows.append({
            "name": registry.get(reg_id).display_name,
            "languages": ", ".join(language_name(lang) for lang in languages)
                         if len(languages) <= 3 else f"{len(languages)} languages",
            "pending": not languages,
        })
    rows.sort(key=lambda r: (r["pending"], r["name"]))
    return rows


_RELEASE_PILL = {labels.FIX: "fix", labels.REVIEW: "check", labels.READY: "ok"}


def recent_reports(limit: int = 10) -> list[dict]:
    """The most recent saved reports, newest first."""
    from lingua_oracle.report.render import reports_dir

    out = []
    for path in sorted(reports_dir().glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        summary = data.get("summary", {})
        if summary.get("fail"):
            release = labels.FIX
        elif summary.get("warn") or summary.get("info"):
            release = labels.REVIEW
        else:
            release = labels.READY
        registry = load_registry()
        try:
            display = registry.get(data.get("regulation", "")).display_name
        except KeyError:
            display = data.get("regulation", "")
        out.append({
            "id": data.get("id", Path(path).stem),
            "file_name": data.get("file_name", ""),
            "regulation": display,
            "language": language_name(data.get("language", "")),
            "release": release,
            "pill": _RELEASE_PILL[release],
            "created_at": data.get("created_at", ""),
        })
        if len(out) >= limit:
            break
    return out
