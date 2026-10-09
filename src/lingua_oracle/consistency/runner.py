"""Read the sheet once; every cross-section comparison, as rows."""

from __future__ import annotations

from lingua_oracle.consistency import (
    classification,
    data,
    document,
    label,
    physical,
    state_stated,
    svhc,
    transport,
    transport_class,
    transport_fields,
)
from lingua_oracle.detect.codes import split_combined
from lingua_oracle.models import ConsistencyRow


def _norm(text: str) -> str:
    import re

    text = re.sub(r"<<[^>]*>>|<[^>]*>|\[[^\]]*\]|…", " ", text or "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _in_words(statement: str, text: str) -> bool:
    """The statement's words, in order, in the text - a filled-in blank
    ("repeated ingestion exposure") may sit between them."""
    import re

    words = statement.split()
    if len(words) < 2:
        return False
    pattern = r"\b" + r"\b(?:\s+\w+){0,6}?\s+".join(re.escape(w) for w in words) + r"\b"
    return re.search(pattern, text) is not None


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
    import re

    codes = {c for hit in ctx.hits_in("2") for c in split_combined(hit.code)}
    codes |= set(re.findall(r"\b(?:EUH|H)\d{3}[A-Za-z]*\b", "\n".join(two)))
    # A statement printed in words without its code is printed all the same.
    flat = _norm(" ".join(two))
    by_text = {code for code in {h for e in (classification.table(regulation) or {})
                                 .get("entries", []) for h in e["h_codes"]}
               if (entry := ctx.entry(code)) is not None and entry.text
               and _in_words(_norm(entry.text), flat)}
    stated = classification.read(two, regulation)
    signal = [v for v, _ in _candidates(ctx)]
    for k, line in enumerate(two[:-1]):
        # "Signal word" on its line, the word itself on the next.
        if re.fullmatch(r"\s*signal\s*words?\s*:?\s*", line or "", re.IGNORECASE):
            signal.append((two[k + 1] or "").strip(" :"))
    state = physical_state(doc.lines, ctx.spans)
    bucket = {"liquid": "liquid", "solid": "solid", "gas": "gas"}.get(state or "")
    criteria = physical.criteria(regulation)
    rows = label.run(two, stated, codes, signal, regulation, display, criteria,
                     printed_as_text=by_text)
    rows += state_stated.run(regulation, ctx.language, lines_of("9"))
    rows += physical.run(lines_of("9"), stated, codes, regulation, bucket)
    rows += data.acute(lines_of("11"), stated, codes, regulation, bucket)
    rows += data.aquatic(lines_of("12"), stated, codes, criteria)
    rows += document.run(doc, lines_of("16"), product_name_in(doc.lines))
    flammable = sorted({c for s in stated for e in s.entries
                        if e["hazard_class"].startswith("flammable liquid")
                        for c in e["category"][:1]} | {{"H224": "1", "H225": "2", "H226": "3"}[c]
                                                       for c in codes
                                                       if c in ("H224", "H225", "H226")})
    rows += transport.run(lines_of("14"), regulation, flammable)
    rows += transport_class.run(lines_of("14"), lines_of("9"), two, regulation, state, flammable)
    rows += transport_fields.run(lines_of("14"), regulation, product_name_in(doc.lines))
    rows += svhc.run(regulation, lines_of("3"), two, lines_of("15"),
                     _section_3(doc.path, lines_of("3")))
    return rows


def _section_3(path: str, lines: list[str]) -> list[tuple[str, str, float | None]]:
    """(CAS, name, highest share in %) for each ingredient Section 3 prints:
    from its table where one is read, and from its lines - a substance with
    no hazard code beside it (one listed for endocrine disruption, say) is
    printed all the same. A share stated strictly below 0,1 % ("< 0,1 %") is
    below it: Annex II asks for "equal to or greater than 0,1 %"."""
    import re

    from lingua_oracle.ingredients.from_pdf import ingredients_in_section_three
    from lingua_oracle.keys.builders.lists import cas_valid
    from lingua_oracle.mixture.concentration import parse

    def high(text: str) -> float | None:
        share = parse(text) if text else None
        if share is None or share.high is None:
            return None
        strict = re.match(r"\s*<(?!=)", share.raw) and float(share.high) <= 0.1
        return 0.0 if strict else float(share.high)

    out: dict[str, tuple[str, str, float | None]] = {}
    try:
        found = ingredients_in_section_three(path)
    except Exception:  # noqa: BLE001 - a sheet whose Section 3 cannot be read
        found = []
    for item in found:
        out.setdefault(item.cas, (item.cas, getattr(item, "name", "") or "",
                                  high(item.concentration)))
    percent = re.compile(r"(?:[<>]=?|≤|≥)?\s*\d+(?:[.,]\d+)?\s*%?\s*(?:[-–—]|to)\s*"
                         r"(?:[<>]=?|≤|≥)?\s*\d+(?:[.,]\d+)?\s*%|(?:[<>]=?|≤|≥)?\s*"
                         r"\d+(?:[.,]\d+)?\s*%")
    for line in lines:
        for cas in re.findall(r"(?<![\d-])\d{2,7}-\d{2}-\d(?![\d-])", line or ""):
            if cas in out or not cas_valid(cas):
                continue
            share = percent.search((line or "")[line.index(cas) + len(cas):])
            out[cas] = (cas, "", high(share.group(0)) if share else None)
    return list(out.values())
