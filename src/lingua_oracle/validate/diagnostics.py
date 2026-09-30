"""Extraction diagnostics for documents where a code was missed.

When recall is below 100% the question is always the same: did the checker
mis-judge the text, or never see it? This dumps what the extractor actually got
for sections 2, 3 and 16, plus every code span it found, so the cause - layout,
hyphenation, column order, encoding - is visible without opening the PDF.

The dump quotes the document, so it lands in reports/validation/, which is
gitignored along with everything else derived from real files.
"""

from __future__ import annotations

from pathlib import Path

from lingua_oracle.detect.codes import extract_document_hits
from lingua_oracle.detect.sections import detect_sections, section_of
from lingua_oracle.extract import extract

SECTIONS = ("2", "3", "16")


def write_extraction_report(
    pdf_path: Path, language: str, out_dir: Path, missed: set[str] | None = None
) -> Path:
    document = extract(str(pdf_path))
    spans = detect_sections(document, language)
    hits = extract_document_hits(document)
    for hit in hits:
        hit.section = section_of(spans, hit.line_index)

    lines: list[str] = [
        f"EXTRACTION DIAGNOSTIC — {pdf_path.name}",
        "=" * 72,
        f"backend       : {document.backend}",
        f"pages         : {len(document.pages)}",
        f"lines         : {len(document.lines)}",
        f"language used : {language}",
        f"sections found: {', '.join(sorted({s.name for s in spans})) or 'none'}",
        "",
    ]
    if missed:
        lines += [
            "CODES EXPECTED BUT NOT FOUND",
            "-" * 72,
            "  " + ", ".join(sorted(missed)),
            "",
            "  Look for these in the section dumps below. If a code is absent from the",
            "  text entirely the extractor never saw it (layout, column order or an",
            "  encoding problem). If it is present but not listed under CODE SPANS, the",
            "  code regex or the line rejoining is at fault.",
            "",
        ]

    lines += ["CODE SPANS FOUND", "-" * 72]
    if hits:
        for hit in hits:
            text = hit.text or "(no text after the code)"
            lines.append(
                f"  p{hit.page} §{hit.section or '-':<5} {hit.code:<18} {text[:90]}"
            )
    else:
        lines.append("  (none)")
    lines.append("")

    for name in SECTIONS:
        span_lines = [
            ln for span in spans if span.name == name
            for ln in document.lines[span.start : span.end]
        ]
        lines += [f"SECTION {name} — RAW EXTRACTED TEXT", "-" * 72]
        if not span_lines:
            lines.append("  (section not detected)")
        else:
            for ln in span_lines:
                lines.append(f"  p{ln.page} | {ln.text}")
        lines.append("")

    others = sorted({s.name for s in spans} - set(SECTIONS))
    if others:
        lines += [f"OTHER SECTIONS DETECTED: {', '.join(others)}", ""]

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{pdf_path.stem}_extraction.txt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target
