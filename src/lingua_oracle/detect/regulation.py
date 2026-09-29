"""Deciding which regulation a document is written against.

A flag always wins. Otherwise heuristics score the document text. If nothing
scores, the caller is told to choose - the tool never guesses silently.
"""

from __future__ import annotations

from dataclasses import dataclass

from lingua_oracle.registry import load_registry


class RegulationUndetermined(RuntimeError):
    """Raised when no regulation can be determined from the document."""

    def __init__(self, candidates: list[str]):
        self.candidates = candidates
        super().__init__(
            "Could not determine the regulation from the document. "
            "Re-run with --regulation set to one of: " + ", ".join(candidates)
        )


@dataclass
class RegulationDetection:
    regulation: str
    detected_by: str  # "flag" | "auto"
    scores: dict[str, int]


def detect_regulation(text: str, flag: str | None = None) -> RegulationDetection:
    registry = load_registry()
    if flag:
        registry.get(flag)  # validates, raises KeyError with a helpful message
        return RegulationDetection(regulation=flag, detected_by="flag", scores={})

    scores = {rid: reg.matches(text) for rid, reg in registry.regulations.items()}
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    best, best_score = ranked[0]
    if best_score == 0:
        raise RegulationUndetermined(registry.ids())
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    if best_score == runner_up:
        tied = [rid for rid, s in ranked if s == best_score]
        raise RegulationUndetermined(tied)
    return RegulationDetection(regulation=best, detected_by="auto", scores=scores)
