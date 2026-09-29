"""C-13: wording should match the current revision of the regulation.

A phrase that matches no current text but does match an older revision on file is
reported with its own message, so an author can tell a stale copy from a typo.
Older revisions live in data/answer_keys/{reg}@{revision}/{lang}.json; with none
on disk this check simply finds nothing.
"""

from __future__ import annotations

import functools

from lingua_oracle.checks.base import CheckContext, register
from lingua_oracle.keys.store import keys_root, load_key
from lingua_oracle.match.template import match
from lingua_oracle.models import Finding, Severity

CHECK_ID = "C-13"
TITLE = "Wording matches the current revision"


@functools.lru_cache(maxsize=16)
def _older_revisions(regulation: str, language: str) -> tuple[tuple[str, str, str], ...]:
    """(revision, code, text) for every archived revision of this regulation."""
    out: list[tuple[str, str, str]] = []
    root = keys_root()
    if not root.is_dir():
        return ()
    for directory in root.iterdir():
        if not directory.is_dir() or "@" not in directory.name:
            continue
        reg, _, revision = directory.name.partition("@")
        if reg != regulation:
            continue
        key = load_key(directory.name, language)
        if key is None:
            continue
        out.extend((revision, entry.code, entry.text) for entry in key.entries)
    return tuple(out)


@register(CHECK_ID, TITLE)
def run(ctx: CheckContext) -> list[Finding]:
    archived = _older_revisions(ctx.regulation.id, ctx.language)
    if not archived:
        return []
    by_code: dict[str, list[tuple[str, str]]] = {}
    for revision, code, text in archived:
        by_code.setdefault(code, []).append((revision, text))

    findings: list[Finding] = []
    for hit in ctx.hits:
        entry = ctx.entry(hit.code)
        if entry is None or not hit.text:
            continue
        if match(hit.text, entry.text).matched:
            continue
        for revision, text in by_code.get(hit.code, []):
            if match(hit.text, text).matched:
                findings.append(
                    Finding(
                        check_id=CHECK_ID, severity=Severity.WARN,
                        section=ctx.section_for(hit), page=hit.page, code=hit.code,
                        expected=entry.text, found=hit.text, tier=entry.tier,
                        message=(
                            f"{hit.code} matches revision {revision}, not the current "
                            f"{ctx.regulation.revision}. The document looks out of date."
                        ),
                    )
                )
                break
    return findings
