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


def _prepare(path: str, regulation: str | None, language: str | None, backend: str | None):
    document = extract(path, backend=backend)
    detection = detect_regulation(document.normalized_text, regulation)
    reg = load_registry().get(detection.regulation)
    candidates = tuple(reg.official_languages) or None
    lang, lang_by = detect_language(document.normalized_text, language, candidates)
    spans = detect_sections(document, lang)
    hits = extract_document_hits(document)
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
    verified = {code for code in codes if reference.entries.get(code) is not None}
    report = Report(
        id=uuid.uuid4().hex[:12],
        file_name=Path(path).name,
        regulation=reg.id,
        language=lang,
        detected_by=detection.detected_by if regulation else lang_by,
        created_at=datetime.now(UTC),
        findings=findings,
        coverage=Coverage(
            codes_found=len(codes),
            codes_checked=len(verified),
            unverified=len(codes - verified),
        ),
        compared_with=Path(compare_with).name if compare_with else None,
    )
    report.recount()

    key_status = "" if verified else "no answer key entries matched this document"
    if key_status:
        report.notes.append(key_status)
    if reference.borrowed_codes:
        report.notes.append(
            f"{len(reference.borrowed_codes)} code(s) used tier B text borrowed from EU CLP."
        )
    tier_c = sorted(codes - verified)
    if tier_c:
        report.notes.append(
            "Tier C (no reference text, consistency only): " + ", ".join(tier_c[:20])
            + ("…" if len(tier_c) > 20 else "")
        )
    report.notes.append(f"Extraction backend: {document.backend}.")
    report.notes.append(
        "Sections found: "
        + (", ".join(sorted({span.name for span in spans})) or "none")
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
