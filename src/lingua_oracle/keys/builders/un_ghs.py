"""Answer-key builder for UN GHS, from a local copy of the published text.

unece.org refuses programmatic requests, so this builder reads a PDF supplied by
hand under data/sources/un-ghs/. Annex 3 codifies the hazard and precautionary
statements in a table whose first column is the code and second the statement;
that shape is identical across the UN language editions, so one parser serves
English, French and Spanish.

Arabic, Russian and Chinese stay `pending_source`: no copy is on file, and their
text is not derivable from the editions that are.
"""

from __future__ import annotations

from pathlib import Path

from lingua_oracle.keys.builders.common import SourceUnavailable, is_deleted_marker, now
from lingua_oracle.keys.builders.pdf_tables import (
    ParseIssues,
    annex_page_range,
    harvest,
)
from lingua_oracle.keys.builders.signal_words import (
    align_by_codes,
    entries_for,
    from_english,
)
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Kind, Status, Tier
from lingua_oracle.registry import data_dir

REGULATION = "un_ghs"
REVISION = "Rev.11"
SOURCE_URL = "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025"

FILES = {
    "en": "un-ghs/GHS_Rev11_en.pdf",
    "fr": "un-ghs/GHS_Rev11_fr.pdf",
    "es": "un-ghs/GHS_Rev11_es.pdf",
}
# Official UN languages with no copy on file.
WITHOUT_SOURCE = ("ar", "ru", "zh")


def _kind(code: str) -> Kind:
    return Kind.HAZARD if code.startswith("H") else Kind.PRECAUTIONARY


def build(
    languages: list[str] | None = None,
    *,
    from_file: str | None = None,
    sources_root: Path | None = None,
) -> tuple[list[AnswerKey], list[ParseIssues]]:
    root = sources_root or (data_dir() / "sources")
    wanted = languages or [*FILES, *WITHOUT_SOURCE]
    ts = now()
    keys: list[AnswerKey] = []
    reports: list[ParseIssues] = []

    for lang in wanted:
        relative = FILES.get(lang)
        path = Path(from_file) if (from_file and len(wanted) == 1) else (
            root / relative if relative else None
        )
        if path is None or not path.exists():
            keys.append(
                AnswerKey(
                    regulation=REGULATION, language=lang, revision=REVISION,
                    status=Status.PENDING_SOURCE,
                    status_reason="no_source_edition",
                    source_url=SOURCE_URL, retrieved_at=ts, entries=[],
                )
            )
            issues = ParseIssues(source=f"{REGULATION}/{lang}")
            issues.notes.append(
                "no source file on record; left pending_source"
                if path is None
                else f"source file not found: {path}"
            )
            reports.append(issues)
            continue

        first, last = annex_page_range(str(path))
        if last <= first:
            raise SourceUnavailable(f"{path}: could not locate the statement annex")
        found, issues = harvest(str(path), first_page=first, last_page=last)
        issues.source = f"{REGULATION}/{lang} ({path.name})"
        issues.notes.append(f"annex pages {first}-{last}")

        entries = [
            AnswerKeyEntry(
                regulation=REGULATION, revision=REVISION, language=lang, code=code,
                kind=_kind(code), text=text, tier=Tier.A, source_url=SOURCE_URL,
                source_ref=f"GHS {REVISION} Annex 3, table row for {code} "
                           f"({path.name}"
                           + (f", p{issues.code_pages[code]}" if code in issues.code_pages else "")
                           + ")",
                retrieved_at=ts, status=Status.OK,
            )
            for code, text in sorted(found.items())
            if code[0] in "HP" and not is_deleted_marker(text)
        ]
        withdrawn = sorted(c for c, t in found.items()
                           if c[0] in "HP" and is_deleted_marker(t))
        if withdrawn:
            # "[Deleted]" is what the edition says ABOUT a code, not a statement
            # to put on a label. Storing it made the key assert that a sheet
            # should print the word "[Deleted]".
            issues.notes.append(
                f"withdrawn in {REVISION}, not stored as statements "
                f"({len(withdrawn)}): " + ", ".join(withdrawn)
            )
        # English states the words outright; the other editions are aligned to the
        # English tables by their H codes, which are identical in every language.
        english_path = root / FILES["en"]
        if lang == "en":
            words, detail = from_english(str(path)), {}
        elif english_path.exists():
            words, detail = align_by_codes(str(english_path), str(path))
        else:
            words, detail = {}, {"note": "English edition absent; cannot align"}
        entries.extend(
            entries_for(
                words, regulation=REGULATION, revision=REVISION, language=lang,
                source_url=SOURCE_URL,
                source_ref=f"GHS {REVISION} Annex 1 label element tables ({path.name})"
                + ("" if lang == "en" else "; aligned to the English tables by H code"),
                retrieved_at=ts,
            )
        )
        issues.notes.append(f"signal words found: {sorted(words.values()) or 'none'}")
        if detail.get("rejected"):
            issues.notes.append(
                f"signal words rejected for lack of a supermajority: {detail['rejected']}"
            )
        entries.sort(key=lambda e: (e.kind, e.code))
        keys.append(
            AnswerKey(
                regulation=REGULATION, language=lang, revision=REVISION,
                status=Status.OK if entries else Status.PENDING_SOURCE,
                source_url=SOURCE_URL, retrieved_at=ts, entries=entries,
            )
        )
        reports.append(issues)
    return keys, reports
