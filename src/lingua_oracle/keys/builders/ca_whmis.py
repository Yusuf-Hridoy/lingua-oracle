"""Answer-key builder for Canada WHMIS, from a local copy of the HPR.

The Hazardous Products Regulations (SOR/2015-17) are supplied under
data/sources/ca-whmis/ as one bilingual PDF, English and French side by side.

The regulations set out classification criteria and label requirements, but they
do **not** reproduce the hazard and precautionary statements against their codes:
a scan of the full text finds no H or P code anywhere. So no entry can be derived
without inventing the code-to-text mapping, and the key stays `pending_source`.
The scan is run rather than assumed, so that a future edition that does carry the
statements is picked up automatically.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from lingua_oracle.keys.builders.common import now
from lingua_oracle.keys.builders.pdf_tables import ParseIssues, harvest
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Kind, Status, Tier
from lingua_oracle.registry import data_dir

REGULATION = "ca_whmis"
REVISION = "SOR-2015-17"
SOURCE_URL = "https://laws-lois.justice.gc.ca/eng/regulations/SOR-2015-17/"
DEFAULT_FILE = "ca-whmis/hpr_bilingual.pdf"

_CODE_RE = re.compile(r"\b(?:H|P)\d{3}\b")


def _count_codes(path: Path) -> int:
    doc = pymupdf.open(path)
    try:
        return len({m.group(0) for i in range(doc.page_count)
                    for m in _CODE_RE.finditer(doc[i].get_text())})
    finally:
        doc.close()


def build(
    languages: list[str] | None = None,
    *,
    from_file: str | None = None,
    sources_root: Path | None = None,
) -> tuple[list[AnswerKey], list[ParseIssues]]:
    root = sources_root or (data_dir() / "sources")
    path = Path(from_file) if from_file else root / DEFAULT_FILE
    ts = now()
    wanted = languages or ["en", "fr"]
    issues = ParseIssues(source=f"{REGULATION} ({path.name if path.exists() else 'missing'})")

    if not path.exists():
        issues.notes.append(f"source file not found: {path}")
        codes = 0
        found: dict[str, str] = {}
    else:
        codes = _count_codes(path)
        issues.notes.append(f"distinct H/P codes found anywhere in the text: {codes}")
        found, table_issues = harvest(str(path)) if codes else ({}, issues)
        if codes:
            issues.tables_seen += table_issues.tables_seen
            issues.rows_seen += table_issues.rows_seen
            issues.rows_used += table_issues.rows_used

    if not found:
        issues.notes.append(
            "The HPR states classification criteria and label rules but does not "
            "reproduce statements against their codes, so nothing can be derived "
            "without inventing the mapping. Left pending_source; fill with "
            "`lingua keys import-csv`."
        )
        return (
            [
                AnswerKey(
                    regulation=REGULATION, language=lang, revision=REVISION,
                    status=Status.PENDING_SOURCE, source_url=SOURCE_URL,
                    retrieved_at=ts, entries=[],
                )
                for lang in wanted
            ],
            [issues],
        )

    # Reached only if a future edition does carry code-keyed statements.
    keys = []
    for lang in wanted:
        entries = [
            AnswerKeyEntry(
                regulation=REGULATION, revision=REVISION, language=lang, code=code,
                kind=Kind.HAZARD if code.startswith("H") else Kind.PRECAUTIONARY,
                text=text, tier=Tier.A, source_url=SOURCE_URL,
                source_ref=f"SOR/2015-17 row for {code} ({path.name})",
                retrieved_at=ts, status=Status.OK,
            )
            for code, text in sorted(found.items())
        ]
        keys.append(
            AnswerKey(
                regulation=REGULATION, language=lang, revision=REVISION,
                status=Status.OK, source_url=SOURCE_URL, retrieved_at=ts, entries=entries,
            )
        )
    return keys, [issues]
