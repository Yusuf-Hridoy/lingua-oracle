"""The check pipeline: PDF in, Report out. Deterministic and offline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from lingua_oracle.checks import CheckContext, run_all
from lingua_oracle.detect.codes import extract_document_hits
from lingua_oracle.detect.language import detect_language
from lingua_oracle.detect.regulation import detect_regulation
from lingua_oracle.detect.sections import detect_sections, section_of
from lingua_oracle.extract import extract
from lingua_oracle.keys.tierb import resolve
from lingua_oracle.models import Coverage, Report, Tier
from lingua_oracle.registry import load_registry


def _official_texts(reg, language: str) -> dict[str, list[str]]:
    """Every wording we hold for each code, for the plausibility check.

    The regulation's own text in this language, the other languages it
    requires, and the GHS editions on file. A code with nothing on file gets an
    empty list, which the check reads as "keep whatever the document says".
    """
    from lingua_oracle.keys import ghs_index

    out: dict[str, list[str]] = {}
    references = [resolve(reg.id, language)]
    references += [resolve(reg.id, other) for other in reg.required_languages
                   if other != language]
    for reference in references:
        for code, entry in reference.entries.items():
            if entry.text:
                out.setdefault(code, []).append(entry.text)
    for code, texts in ghs_index.all_texts().items():
        out.setdefault(code, []).extend(texts)
    return out


def _prepare(path: str, regulation: str | None, language: str | None, backend: str | None):
    document = extract(path, backend=backend)
    detection = detect_regulation(document.normalized_text, regulation)
    reg = load_registry().get(detection.regulation)
    # The regulation's official languages are a tie-break only. Restricting the
    # detector to them once turned a Danish UN GHS sheet into an English one.
    preferred = tuple(reg.official_languages) or None
    lang, lang_by = detect_language(document.normalized_text, language, preferred)
    spans = detect_sections(document, lang)
    hits = extract_document_hits(document, _official_texts(reg, lang))
    for hit in hits:
        hit.section = section_of(spans, hit.line_index)
    return document, reg, lang, lang_by, spans, hits, detection


def check_pdf(
    path: str,
    regulation: str | None = None,
    language: str | None = None,
    *,
    backend: str | None = None,
    compare_with: str | None = None,
    only: list[str] | None = None,
) -> Report:
    """Run every check against one PDF, optionally comparing against another."""
    document, reg, lang, lang_by, spans, hits, detection = _prepare(
        path, regulation, language, backend
    )

    compare_doc = compare_hits = None
    compare_lang = None
    if compare_with:
        compare_doc, _reg2, compare_lang, _lb, spans2, compare_hits, _d2 = _prepare(
            compare_with, regulation, None, backend
        )

    reference = resolve(reg.id, lang)
    alternates = {
        other: resolve(reg.id, other)
        for other in reg.required_languages
        if other != lang
    }
    ctx = CheckContext(
        document=document,
        regulation=reg,
        language=lang,
        hits=hits,
        spans=spans,
        reference=reference,
        alternates=alternates,
        compare_document=compare_doc,
        compare_hits=compare_hits or [],
        compare_language=compare_lang,
    )
    findings = run_all(ctx, only=only)

    codes = {hit.code for hit in hits}
    # Coverage is what the tool actually formed an opinion about, not what it
    # holds a key entry for. Those are different numbers, and the second one
    # flatters the tool: a code can have an entry and still never be compared,
    # because the document gave it no text.
    statements = sorted(ctx.statements.values(), key=lambda v: v.code)
    verified = {v.code for v in statements if v.checked}
    report = Report(
        id=uuid.uuid4().hex[:12],
        file_name=Path(path).name,
        regulation=reg.id,
        language=lang,
        detected_by=detection.detected_by if regulation else lang_by,
        created_at=datetime.now(UTC),
        findings=findings,
        statements=statements,
        coverage=Coverage(
            codes_found=len(codes),
            codes_checked=len(verified),
            unverified=len(codes - verified),
        ),
        compared_with=Path(compare_with).name if compare_with else None,
    )
    report.recount()
    # Anything a check wants a reviewer to know but that is not a finding about
    # the document - an allowance made for the official text, say.
    report.notes.extend(ctx.notes)

    # Notes are shown to a reviewer, so they say what happened rather than
    # naming the tiers. The tier letters stay in the JSON and in the table's
    # "Source of official text" column.
    if not verified:
        report.notes.append(
            "None of the codes in this document could be matched to official "
            "wording we hold."
        )
    if reference.borrowed_codes:
        report.notes.append(
            f"{len(reference.borrowed_codes)} statement(s) were compared against "
            "EU CLP's published translation, borrowed because this regulation's "
            "English wording is identical."
        )
    no_source = sorted(codes - verified)
    if no_source:
        report.notes.append(
            "No official wording on file for: " + ", ".join(no_source[:20])
            + ("…" if len(no_source) > 20 else "")
            + " - these were not checked."
        )
    report.notes.append(
        "Sections read: "
        + (", ".join(sorted({span.name for span in spans})) or "none")
    )
    report.notes.append(f"PDF text read with {document.backend}.")
    if detection.detected_by == "flag":
        report.notes.append("Regulation chosen by you, not read from the sheet.")
    elif detection.evidence.get(reg.id):
        report.notes.append(
            "Regulation read from the sheet's own words: "
            + ", ".join(detection.evidence[reg.id])
        )
    return report


def compare_pdfs(
    path_a: str,
    path_b: str,
    regulation: str | None = None,
    language: str | None = None,
    *,
    backend: str | None = None,
) -> Report:
    return check_pdf(
        path_a, regulation, language, backend=backend, compare_with=path_b
    )


__all__ = ["Tier", "check_pdf", "compare_pdfs"]
