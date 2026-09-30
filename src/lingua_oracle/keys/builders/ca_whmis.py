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
  *Eighth* revised edition. Rev.8 is on file in English, so those statements are
  overlaid there (see ``keys/builders/ghs_editions.py``); the class's other codes
  are identical in Rev.7 and stay there. No French edition of Rev.8 is on file, so
  the French key keeps that gap with reason ``needs_ghs_rev8_french`` rather than
  borrowing Rev.7, another revision, or the English text.
* **Canada-only classes** (biohazardous infectious materials, and the physical
  and health hazards "not otherwise classified"). The HPR defines them and sets
  classification criteria, but states no statement text for them, so nothing can
  be recorded.
"""

from __future__ import annotations

from pathlib import Path

from lingua_oracle.keys.builders.common import now
from lingua_oracle.keys.builders.ghs_editions import (
    pressure_overlay,
    recover_damaged_cells,
    rev8_name,
)
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
GHS8_URL = "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev8-2019"

HPR_FILE = "ca-whmis/hpr_bilingual.pdf"
GHS7_FILES = {"en": "ghs-rev7/GHS_Rev7_en.pdf", "fr": "ghs-rev7/GHS_Rev7_fr.pdf"}

CANADA_ONLY_CLASSES = (
    "Biohazardous Infectious Materials",
    "Physical Hazards Not Otherwise Classified",
    "Health Hazards Not Otherwise Classified",
)


def _kind(code: str) -> Kind:
    return Kind.HAZARD if code.startswith("H") else Kind.PRECAUTIONARY




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

    # The HPR points chemicals under pressure at Annex 3 of the EIGHTH revised
    # edition. The overlay is resolved per language, so each language's statements
    # come from its own Rev.8 edition; only the set of codes is shared.
    issues.notes.append(
        "    The HPR additionally states, in both languages, the hazard statement "
        '"Chemical under pressure: May explode if heated / Produit chimique sous '
        "pression : peut exploser sous l'effet de la chaleur\". It is not recorded "
        "here because the HPR gives it no code."
    )

    english_path = root / GHS7_FILES["en"]
    keys: list[AnswerKey] = []
    missing_rev8: list[str] = []
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
                source_ref=f"GHS Rev.7 Annex 3 row for {code} ({path.name}"
                           + (f", p{table_issues.code_pages[code]}"
                              if code in table_issues.code_pages else "")
                           + "); adopted by SOR/2015-17, which defines GHS as the "
                             "Seventh Revised Edition",
                retrieved_at=ts, status=Status.OK,
            )
            for code, text in sorted(found.items())
            if code[:1] in "HP"
        ]
        # A few Rev.7 code cells are unreadable in one edition's PDF. Where
        # another language proves the statement is unchanged between Rev.7 and
        # Rev.8, the text is recovered from Rev.8 rather than dropped.
        proof_lang = "fr" if lang == "en" else "en"
        recovered = recover_damaged_cells(root, lang, proof_lang)
        if recovered:
            entries.extend(
                AnswerKeyEntry(
                    regulation=REGULATION, revision=REVISION, language=lang, code=code,
                    kind=_kind(code), text=text, tier=Tier.A, source_url=GHS8_URL,
                    source_ref=(
                        f"{rev8_name(lang)} row for {code}. The GHS Rev.7 {lang} PDF "
                        f"renders this row's code cell unreadably, so the text is "
                        f"taken from Rev.8; the {proof_lang} edition proves the "
                        f"statement is unchanged between Rev.7 and Rev.8, being "
                        f"word-for-word identical apart from the French typographic "
                        f"space before ':'. That spacing licence applies to this "
                        f"edition-proof comparison only - document-vs-key matching "
                        f"stays exact."
                    ),
                    retrieved_at=ts, status=Status.OK,
                )
                for code, text in sorted(recovered.items())
                if code not in {e.code for e in entries}
            )
            issues.notes.append(
                f"{lang}: recovered from {rev8_name(lang)} where the Rev.7 cell is "
                f"unreadable and the {proof_lang} edition proves the statement "
                f"unchanged: {', '.join(sorted(recovered))}"
            )

        overlay, unchanged = pressure_overlay(root, lang)
        if overlay:
            entries.extend(
                AnswerKeyEntry(
                    regulation=REGULATION, revision=REVISION, language=lang, code=code,
                    kind=_kind(code), text=text, tier=Tier.A, source_url=GHS8_URL,
                    source_ref=f"{rev8_name(lang)} row for {code}; SOR/2015-17 points "
                               "chemicals under pressure at the Eighth Revised Edition",
                    retrieved_at=ts, status=Status.OK,
                )
                for code, text in sorted(overlay.items())
            )
            issues.notes.append(
                f"{lang}: chemicals under pressure overlaid from {rev8_name(lang)} "
                f"for {', '.join(sorted(overlay))}; the class's other codes "
                f"({', '.join(sorted(unchanged))}) are identical in Rev.7 and stay there."
            )
        else:
            missing_rev8.append(lang)
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
        gap = not overlay
        notes = []
        if gap:
            notes.append(
                "Chemicals under pressure are absent: the HPR points them at GHS "
                f"Rev.8 Annex 3 and no {lang} edition of Rev.8 is on file. They are "
                "not filled from Rev.7, from another revision, or from another "
                "language's text."
            )
        keys.append(
            AnswerKey(
                regulation=REGULATION, language=lang, revision=REVISION,
                status=(Status.PARTIAL if gap else Status.OK) if entries
                else Status.PENDING_SOURCE,
                status_reason=(f"needs_ghs_rev8_{lang}" if gap else None) if entries
                else "no_source_edition",
                source_url=SOURCE_URL, retrieved_at=ts, notes=notes, entries=entries,
            )
        )

    issues.notes.append(
        "Canada-only classes are not represented: the HPR defines them and sets "
        "classification criteria but states no statement text for them, so nothing "
        "can be recorded. Affected: " + "; ".join(CANADA_ONLY_CLASSES)
    )
    return keys, issues and [issues]
