"""Read the sheet once; every cross-section comparison, as rows."""

from __future__ import annotations

from lingua_oracle.consistency import classification, data, document, label, physical
from lingua_oracle.detect.codes import split_combined
from lingua_oracle.models import ConsistencyRow


def run(ctx, display: str) -> list[ConsistencyRow]:
    from lingua_oracle.checks.a01_signal_word import _candidates
    from lingua_oracle.ingredients.matching import product_name_in
    from lingua_oracle.mixture.state import physical_state
    from lingua_oracle.structure.reader import section_spans

    doc = ctx.document
    regulation = ctx.regulation.id
    raw = [line.text or "" for line in doc.raw_lines]
    spans = section_spans(doc, regulation, ctx.language)

    def lines_of(number: str) -> list[str]:
        if number in spans:
            start, end = spans[number]
            return raw[start:end]
        return []

    two = lines_of("2") or [line.text for line in doc.lines
                            if ctx.section_for_line(doc.lines.index(line)) == "2"]
    codes = {c for hit in ctx.hits_in("2") for c in split_combined(hit.code)}
    stated = classification.read(two, regulation)
    state = physical_state(doc.lines, ctx.spans)
    bucket = {"liquid": "liquid", "solid": "solid", "gas": "gas"}.get(state or "")
    criteria = physical.criteria(regulation)
    rows = label.run(two, stated, codes, [v for v, _ in _candidates(ctx)], regulation, display,
                     criteria)
    rows += physical.run(lines_of("9"), stated, codes, regulation, bucket)
    rows += data.acute(lines_of("11"), stated, codes, regulation, bucket)
    rows += data.aquatic(lines_of("12"), stated, codes, criteria)
    rows += document.run(doc, lines_of("16"), product_name_in(doc.lines))
    return rows
