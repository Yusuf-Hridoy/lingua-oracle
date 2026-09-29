"""Answer-key builder for Australia (WHS), from local copies.

safeworkaustralia.gov.au does not answer programmatic requests, so this builder
reads files supplied by hand under data/sources/.

Australia adopts GHS for its H and P statements and adds its own AUH supplemental
statements. Both halves come from their own source and are never mixed:

* **H and P** from the GHS Rev.7 English text, which is the revision Australian
  WHS adopts (data/sources/ghs-rev7/).
* **AUH** from the Safe Work Australia classification guidance, which states each
  code and its text in one cell, "AUH001 - Explosive when dry".
"""

from __future__ import annotations

from pathlib import Path

from lingua_oracle.keys.builders.common import now
from lingua_oracle.keys.builders.pdf_tables import (
    ParseIssues,
    annex_page_range,
    harvest,
    harvest_inline,
)
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Kind, Status, Tier
from lingua_oracle.registry import data_dir

REGULATION = "au_whs"
REVISION = "GHS-Rev7-AU"
SWA_URL = "https://www.safeworkaustralia.gov.au/doc/ghs-classification-and-labelling-chemicals"
GHS7_URL = "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev7-2017"

GHS7_FILE = "ghs-rev7/GHS_Rev7_en.pdf"
SWA_FILE = "australia/swa_classification_guidance.pdf"


def _kind(code: str) -> Kind:
    if code.startswith("AUH"):
        return Kind.SUPPLEMENTAL
    return Kind.HAZARD if code.startswith("H") else Kind.PRECAUTIONARY


def build(
    languages: list[str] | None = None,
    *,
    from_file: str | None = None,
    sources_root: Path | None = None,
) -> tuple[list[AnswerKey], list[ParseIssues]]:
    root = sources_root or (data_dir() / "sources")
    ghs7 = Path(from_file) if from_file else root / GHS7_FILE
    swa = root / SWA_FILE
    ts = now()
    issues = ParseIssues(source=f"{REGULATION}/en")
    found: dict[str, tuple[str, str, str]] = {}  # code -> (text, url, ref)

    if ghs7.exists():
        first, last = annex_page_range(str(ghs7))
        base, ghs_issues = harvest(str(ghs7), first_page=first, last_page=last)
        for code, text in base.items():
            if code[0] in "HP":
                found[code] = (text, GHS7_URL, f"GHS Rev.7 Annex 3 row for {code}")
        issues.pages_scanned += ghs_issues.pages_scanned
        issues.tables_seen += ghs_issues.tables_seen
        issues.rows_seen += ghs_issues.rows_seen
        issues.rows_used += ghs_issues.rows_used
        issues.duplicate_conflict.extend(ghs_issues.duplicate_conflict)
        issues.notes.append(f"GHS Rev.7 pages {first}-{last}: {len(found)} H/P codes")
    else:
        issues.notes.append(f"GHS Rev.7 source not found: {ghs7}; no H/P statements")

    if swa.exists():
        auh, swa_issues = harvest_inline(str(swa))
        added = 0
        for code, text in auh.items():
            if code.startswith("AUH"):
                found[code] = (text, SWA_URL, f"Safe Work Australia guidance, row for {code}")
                added += 1
        issues.tables_seen += swa_issues.tables_seen
        issues.duplicate_conflict.extend(swa_issues.duplicate_conflict)
        issues.notes.append(f"Safe Work Australia guidance: {added} AUH codes")
    else:
        issues.notes.append(f"Safe Work Australia source not found: {swa}; no AUH statements")

    entries = [
        AnswerKeyEntry(
            regulation=REGULATION, revision=REVISION, language="en", code=code,
            kind=_kind(code), text=text, tier=Tier.A, source_url=url,
            source_ref=ref, retrieved_at=ts, status=Status.OK,
        )
        for code, (text, url, ref) in sorted(found.items())
    ]
    entries.sort(key=lambda e: (e.kind, e.code))
    return (
        [
            AnswerKey(
                regulation=REGULATION, language="en", revision=REVISION,
                status=Status.OK if entries else Status.PENDING_SOURCE,
                source_url=SWA_URL, retrieved_at=ts, entries=entries,
            )
        ],
        [issues],
    )
