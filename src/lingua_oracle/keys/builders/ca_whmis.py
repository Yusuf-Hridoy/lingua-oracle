"""Answer-key builder for Canada WHMIS, Hazardous Products Regulations (SOR/2015-17).

The HPR does not reproduce statements against codes - a scan of its full text
finds no H or P code at all - but it does not need to, because it says which
document its statements come from:

    "GHS means the United Nations document entitled Globally Harmonized System of
     Classification and Labelling of Chemicals (GHS), Seventh Revised Edition."

So WHMIS statements *are* GHS Rev.7 statements, and both languages are read
straight from GHS Rev.7 Annex 3 - English from the English edition, French from
the French edition - each of which is already a code-keyed table. No text is
matched, translated or inferred across languages, and no code is derived from a
position: the code comes from the table it is in.

Two documented exceptions, both recorded in the parse report rather than guessed:

* **Chemicals under pressure.** For that class the HPR points at Annex 3 of the
  *Eighth* revised edition, which is not on file. Those codes are left out with
  the reason ``needs GHS Rev.8 Annex 3``. The class is identified from the
  hazard-class column of the GHS edition on file, not from recall.
* **Canada-only classes** (biohazardous infectious materials, and the physical
  and health hazards "not otherwise classified"). The HPR defines them and sets
  classification criteria, but states no statement text for them, so nothing can
  be recorded.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf

from lingua_oracle.keys.builders.common import now
from lingua_oracle.keys.builders.pdf_tables import (
    ParseIssues,
    annex_page_range,
    harvest,
)
from lingua_oracle.keys.builders.signal_words import align_by_codes, entries_for, from_english
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Kind, Status, Tier
from lingua_oracle.registry import data_dir

REGULATION = "ca_whmis"
REVISION = "SOR-2015-17"
SOURCE_URL = "https://laws-lois.justice.gc.ca/eng/regulations/SOR-2015-17/"
GHS7_URL = "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev7-2017"

HPR_FILE = "ca-whmis/hpr_bilingual.pdf"
GHS7_FILES = {"en": "ghs-rev7/GHS_Rev7_en.pdf", "fr": "ghs-rev7/GHS_Rev7_fr.pdf"}
#: Used to find which codes belong to the class the HPR sends to Rev.8.
CLASS_SOURCE = "un-ghs/GHS_Rev11_en.pdf"
REV8_CLASS_RE = re.compile(r"chemicals?\s+under\s+pressure", re.IGNORECASE)

CANADA_ONLY_CLASSES = (
    "Biohazardous Infectious Materials",
    "Physical Hazards Not Otherwise Classified",
    "Health Hazards Not Otherwise Classified",
)


def _kind(code: str) -> Kind:
    return Kind.HAZARD if code.startswith("H") else Kind.PRECAUTIONARY


def rev8_codes(path: Path) -> set[str]:
    """Hazard codes whose class is 'chemicals under pressure', read from the source.

    The HPR sends that class to GHS Rev.8, which is not on file. Which codes the
    class covers is taken from the hazard-class column of a GHS edition that does
    name them, never from recall.
    """
    if not path.exists():
        return set()
    doc = pymupdf.open(path)
    out: set[str] = set()
    try:
        for index in range(doc.page_count):
            for table in doc[index].find_tables().tables:
                for row in table.extract():
                    if len(row) < 3:
                        continue
                    code = " ".join((row[0] or "").split())
                    hazard_class = " ".join((row[2] or "").split())
                    if re.fullmatch(r"H\d{3}", code) and REV8_CLASS_RE.search(hazard_class):
                        out.add(code)
    finally:
        doc.close()
    return out


def build(
    languages: list[str] | None = None,
    *,
    from_file: str | None = None,
    sources_root: Path | None = None,
) -> tuple[list[AnswerKey], list[ParseIssues]]:
    root = Path(sources_root) if sources_root else (data_dir() / "sources")
    wanted = languages or ["en", "fr"]
    ts = now()
    issues = ParseIssues(source=f"{REGULATION} (GHS Rev.7 per HPR definition)")
    issues.notes.append(
        'HPR: "GHS means the United Nations document entitled Globally Harmonized '
        'System of Classification and Labelling of Chemicals (GHS), Seventh Revised '
        'Edition." Statements are therefore read from GHS Rev.7 Annex 3.'
    )

    excluded = rev8_codes(root / CLASS_SOURCE)
    if excluded:
        issues.notes.append(
            f"chemicals under pressure -> the HPR points at Annex 3 of the EIGHTH "
            f"revised edition, which is not on file. Left out, reason "
            f"'needs GHS Rev.8 Annex 3': {', '.join(sorted(excluded))}"
        )
        issues.notes.append(
            "    The HPR additionally states, in both languages, the hazard statement "
            '"Chemical under pressure: May explode if heated / Produit chimique sous '
            'pression : peut exploser sous l\'effet de la chaleur". It is not recorded '
            "here because the HPR gives it no code."
        )

    english_path = root / GHS7_FILES["en"]
    keys: list[AnswerKey] = []
    for lang in wanted:
        relative = GHS7_FILES.get(lang)
        path = Path(from_file) if (from_file and len(wanted) == 1) else (
            root / relative if relative else None
        )
        if path is None or not path.exists():
            issues.notes.append(f"{lang}: no GHS Rev.7 edition on file ({path})")
            keys.append(
                AnswerKey(
                    regulation=REGULATION, language=lang, revision=REVISION,
                    status=Status.PENDING_SOURCE, status_reason="no_source_edition",
                    source_url=SOURCE_URL, retrieved_at=ts, entries=[],
                )
            )
            continue

        first, last = annex_page_range(str(path))
        found, table_issues = harvest(str(path), first_page=first, last_page=last)
        issues.tables_seen += table_issues.tables_seen
        issues.rows_seen += table_issues.rows_seen

        entries = [
            AnswerKeyEntry(
                regulation=REGULATION, revision=REVISION, language=lang, code=code,
                kind=_kind(code), text=text, tier=Tier.A, source_url=GHS7_URL,
                source_ref=f"GHS Rev.7 Annex 3 row for {code} ({path.name}); adopted by "
                           f"SOR/2015-17, which defines GHS as the Seventh Revised Edition",
                retrieved_at=ts, status=Status.OK,
            )
            for code, text in sorted(found.items())
            if code[:1] in "HP" and code not in excluded
        ]
        issues.rows_used += len(entries)

        words = (
            from_english(str(path)) if lang == "en"
            else align_by_codes(str(english_path), str(path))[0]
            if english_path.exists() else {}
        )
        entries.extend(
            entries_for(
                words, regulation=REGULATION, revision=REVISION, language=lang,
                source_url=GHS7_URL,
                source_ref=f"GHS Rev.7 Annex 1 label element tables ({path.name})"
                + ("" if lang == "en" else "; aligned to the English tables by H code"),
                retrieved_at=ts,
            )
        )
        issues.notes.append(
            f"{lang}: {len(entries)} entries from {path.name}; "
            f"signal words {sorted(words.values()) or 'none'}"
        )

        entries.sort(key=lambda e: (e.kind, e.code))
        keys.append(
            AnswerKey(
                regulation=REGULATION, language=lang, revision=REVISION,
                status=Status.PARTIAL if entries else Status.PENDING_SOURCE,
                status_reason="needs_ghs_rev8_annex3" if entries else "no_source_edition",
                source_url=SOURCE_URL, retrieved_at=ts, entries=entries,
            )
        )

    issues.notes.append(
        "Canada-only classes are not represented: the HPR defines them and sets "
        "classification criteria but states no statement text for them, so nothing "
        "can be recorded. Affected: " + "; ".join(CANADA_ONLY_CLASSES)
    )
    return keys, issues and [issues]
