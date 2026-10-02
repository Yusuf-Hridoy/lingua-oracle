"""Deciding which regulation a document is written against.

A flag always wins. Otherwise the sheet's own words are scored: markers that
name an instrument, and evidence from the codes and languages it carries. The
tool decides only when one reading is clearly ahead; where two are close it
asks, because a confident wrong answer here sends every statement to the wrong
key and fails a correct sheet from top to bottom.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lingua_oracle.detect.country import country_hint
from lingua_oracle.registry import load_registry

#: How far ahead the leader has to be. One weight-3 marker against another
#: regulation's weight-1 context is a decision; two instruments named at once
#: is a question for the reader.
_MARGIN = 2

#: Weight at which a marker names an instrument rather than hinting at one.
_INSTRUMENT = 3

_EUH_RE = re.compile(r"\bEUH\s?\d{3}\b", re.IGNORECASE)
_AUH_RE = re.compile(r"\bAUH\s?\d{3}\b", re.IGNORECASE)

#: Section headings a French half of a bilingual Canadian sheet will carry.
_FRENCH_SECTION_RE = re.compile(
    r"\bRUBRIQUE\s*\d|\bIdentification\s+des\s+dangers\b"
    r"|\bMentions?\s+de\s+danger\b|\bConseils?\s+de\s+prudence\b",
    re.IGNORECASE,
)
_ENGLISH_SECTION_RE = re.compile(
    r"\bSECTION\s*\d|\bHazards?\s+identification\b|\bHazard\s+statements?\b",
    re.IGNORECASE,
)


class RegulationUndetermined(RuntimeError):
    """Raised when no regulation can be determined from the document.

    May carry a suggestion drawn from where the sheet appears to come from.
    A suggestion is somewhere to start, never an answer: the caller offers it
    and the reader confirms it.
    """

    def __init__(self, candidates: list[str], *, suggestion: str = "",
                 reason: str = "", only_says_ghs: bool = False):
        self.candidates = candidates
        self.suggestion = suggestion
        self.reason = reason
        self.only_says_ghs = only_says_ghs
        super().__init__(
            "Could not determine the regulation from the document. "
            "Re-run with --regulation set to one of: " + ", ".join(candidates)
        )


@dataclass
class RegulationDetection:
    regulation: str
    detected_by: str  # "flag" | "auto"
    scores: dict[str, int]
    #: What was found, per regulation, in the sheet's own words. Shown in the
    #: report's technical details so a reader can see why.
    evidence: dict[str, list[str]] = field(default_factory=dict)


def _content_evidence(text: str) -> dict[str, list[tuple[str, int]]]:
    """Evidence from what the sheet carries rather than what it says it is."""
    out: dict[str, list[tuple[str, int]]] = {}
    euh = _EUH_RE.search(text)
    if euh:
        found = " ".join(euh.group(0).split())
        # EUH codes are EU CLP's own. GB CLP retained them, so they support a
        # UK reading too - but only where the sheet also says it is GB.
        out.setdefault("eu_clp", []).append((f"{found} supplemental code", 2))
        if re.search(r"\bGB\s*CLP\b|\bUK\s*REACH\b|\bGreat\s+Britain\b", text,
                     re.IGNORECASE):
            out.setdefault("uk_clp", []).append((f"{found} with a GB marker", 2))
    auh = _AUH_RE.search(text)
    if auh:
        found = " ".join(auh.group(0).split())
        out.setdefault("au_whs", []).append((f"{found} supplemental code", 3))
    if _FRENCH_SECTION_RE.search(text) and _ENGLISH_SECTION_RE.search(text):
        out.setdefault("ca_whmis", []).append(("English and French together", 2))
    return out


def _drop_bare_ghs(evidence: dict[str, list[tuple[str, int]]]) -> None:
    """"GHS" alone means UN GHS only when nothing more specific is present.

    Every sheet in the world mentions GHS. It identifies the UN text only when
    no other regulation has been named.
    """
    specific = any(
        weight >= 2
        for rid, found in evidence.items() if rid != "un_ghs"
        for _, weight in found
    )
    if not specific:
        return
    evidence["un_ghs"] = [
        (what, weight) for what, weight in evidence.get("un_ghs", [])
        if what.strip().upper() != "GHS"
    ]


def detect_regulation(text: str, flag: str | None = None) -> RegulationDetection:
    registry = load_registry()
    if flag:
        registry.get(flag)  # validates, raises KeyError with a helpful message
        return RegulationDetection(regulation=flag, detected_by="flag", scores={})

    evidence: dict[str, list[tuple[str, int]]] = {
        rid: reg.found_markers(text) for rid, reg in registry.regulations.items()
    }
    for rid, found in _content_evidence(text).items():
        evidence.setdefault(rid, []).extend(found)
    _drop_bare_ghs(evidence)

    scores = {rid: sum(w for _, w in found) for rid, found in evidence.items()}
    shown = {rid: [what for what, _ in found] for rid, found in evidence.items() if found}

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    best, best_score = ranked[0]

    # "GHS" on its own is not a regulation. Nearly every sheet in the world
    # says it, and taking it for the UN text sent Australian and Canadian
    # sheets to the wrong key. Where it is all we have, ask - and offer the
    # country the sheet seems to come from as somewhere to start.
    said = {what.strip().upper() for found in evidence.values() for what, _ in found}
    only_ghs = said == {"GHS"}
    if best_score == 0 or only_ghs:
        hint = country_hint(text)
        raise RegulationUndetermined(
            registry.ids(),
            suggestion=hint.regulation if hint else "",
            reason=hint.reason if hint else "",
            only_says_ghs=only_ghs,
        )

    # A sheet that names one instrument and no other has said which regulation
    # it follows. Codes and languages are weaker evidence - an EU supplemental
    # code on an OSHA sheet is a finding, not a second candidate - so a single
    # named instrument settles it without going to the margin.
    named = [rid for rid, found in evidence.items()
             if any(w >= _INSTRUMENT for _, w in found)]
    if len(named) == 1:
        return RegulationDetection(regulation=named[0], detected_by="auto",
                                   scores=scores, evidence=shown)

    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if best_score - runner_up < _MARGIN:
        close = [rid for rid, s in ranked if best_score - s < _MARGIN]
        hint = country_hint(text)
        raise RegulationUndetermined(
            close,
            suggestion=hint.regulation if hint and hint.regulation in close else "",
            reason=hint.reason if hint else "",
        )
    return RegulationDetection(regulation=best, detected_by="auto",
                               scores=scores, evidence=shown)
