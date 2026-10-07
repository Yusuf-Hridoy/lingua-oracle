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
    ingredients: bool = False,
    client_factory=None,
) -> Report:
    """Run every check against one PDF, optionally comparing against another.

    `ingredients` also checks the document's ingredients against CLP Annex VI -
    against the product's record in ExactSDS where the sheet is one of ours, and
    against the sheet's own Section 3 where it is not. Off by default: it is the
    one part of this that reads from the network, and the wording check must
    work without it.
    """
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
    if ingredients:
        # Never allowed to cost the wording result. Whatever happens here, the
        # report that has already been built is what the reader gets.
        try:
            from lingua_oracle.ingredients.section import check as check_ingredients

            report.ingredients = check_ingredients(
                path, Path(path).name, document.lines,
                client_factory=client_factory, regulation=reg.id)
            report.mixture = _mixture_section(
                report, path, document, spans, reg.id,
                client_factory=client_factory)
        except Exception as exc:  # noqa: BLE001
            from lingua_oracle.models import IngredientSection

            report.ingredients = IngredientSection(
                source="skipped",
                message=f"Ingredient check skipped: {exc}"[:200])
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


def _mixture_section(report, path, document, spans, regulation,
                     *, client_factory=None):
    """The mixture half, from whichever composition the ingredient half used.

    Never allowed to cost the rest of the report: a calculation that cannot be
    made is reported as one that was not made.
    """
    from lingua_oracle.mixture import section as mixture_section
    from lingua_oracle.models import MixtureSection
    from lingua_oracle.substances.load import for_check

    try:
        section = report.ingredients
        matched = (section is not None and section.source == "app"
                   and section.product_id)
        if matched:
            # A product we hold has a composition we hold. Section 3 of its own
            # PDF is a rendering of that composition, and a worse one: it loses
            # the ingredients below the disclosure threshold and whatever the
            # layout could not carry. Where the two differ the record is right,
            # so the record is used and the sheet is not consulted at all.
            # The same client the ingredient half used, so one report cannot
            # end up asking two different applications.
            from lingua_oracle.ingredients.client import session

            client = client_factory() if client_factory else session()
            rows = mixture_section.rows_from_app(
                client.ingredients(section.product_id))
        elif section is not None and section.match_state == "ambiguous":
            # A choice is pending. Calculating from Section 3 now would answer
            # a question the reader is still being asked.
            from lingua_oracle.mixture.state import physical_state
            from lingua_oracle.mixture.stated import stated_classes

            return MixtureSection(
                state="nothing",
                message="Choose the product above to calculate the mixture.",
                stated=[str(c) for c in
                        stated_classes(document.lines, spans)],
                physical_state=physical_state(document.lines, spans) or "")
        else:
            from lingua_oracle.ingredients.from_pdf import (
                ingredients_in_section_three,
            )

            rows = mixture_section.rows_from_pdf(
                ingredients_in_section_three(path))
        return mixture_section.build(rows, document.lines, spans, regulation,
                                     for_check(regulation)[1])
    except Exception as exc:  # noqa: BLE001
        return MixtureSection(state="skipped",
                              message=f"Mixture check skipped: {exc}"[:200])
