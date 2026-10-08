"""Check framework: the shared context and the check registry."""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from lingua_oracle.detect.codes import CodeHit
from lingua_oracle.detect.sections import LABEL, SectionSpan, section_of
from lingua_oracle.extract.base import Document
from lingua_oracle.keys.tierb import Borrowed
from lingua_oracle.models import (
    AnswerKeyEntry,
    Finding,
    StatementVerdict,
    StructureReport,
    Tier,
)
from lingua_oracle.registry import Regulation


@dataclass
class CheckContext:
    """Everything a check may look at. Checks never touch the network or disk."""

    document: Document
    regulation: Regulation
    language: str
    hits: list[CodeHit]
    spans: list[SectionSpan]
    reference: Borrowed
    #: References for the regulation's *other* required languages. A regulation
    #: that mandates two languages in one document (WHMIS: English and French)
    #: has both texts on the same sheet, and either is correct where it appears.
    alternates: dict[str, Borrowed] = field(default_factory=dict)
    compare_document: Document | None = None
    compare_hits: list[CodeHit] = field(default_factory=list)
    compare_language: str | None = None
    notes: list[str] = field(default_factory=list)
    #: Filled in by the statement checks: one entry per code they formed an
    #: opinion about, including the ones that were correct. Coverage and the
    #: report's statement cards are both built from this, so a code that gets
    #: no entry here is genuinely not checked.
    statements: dict[str, StatementVerdict] = field(default_factory=dict)
    #: The sheet's 16 sections against the regulation's text on SDS structure,
    #: read once by the pipeline (structure/reader.py). None for a label.
    structure: StructureReport | None = None
    #: Section against section, read once by the pipeline (consistency/runner.py).
    consistency: list = field(default_factory=list)

    def record(self, verdict: StatementVerdict) -> None:
        """Keep the strongest opinion held about a code.

        The same code appears in Section 2 and again in Section 16, and a sheet
        can get one right and the other wrong. The worse outcome is the one
        that matters."""
        rank = {"wrong": 0, "check": 1, "correct": 2, "not_checked": 3}
        held = self.statements.get(verdict.code)
        if held is None or rank[verdict.status] < rank[held.status]:
            self.statements[verdict.code] = verdict

    # -- convenience ------------------------------------------------------
    def entry(self, code: str) -> AnswerKeyEntry | None:
        return self.reference.entries.get(code)

    def internal_entries(self) -> list[AnswerKeyEntry]:
        """Entries keyed by an internal identifier rather than a regulatory code."""
        return [e for e in self.reference.entries.values() if e.internal_id]

    def match_internal(self, text: str):
        """Find an internal-ID entry whose official text this phrase matches.

        These hazards carry no regulatory code, so a document cannot cite them by
        code and they must be recognised by their wording alone.
        """
        from lingua_oracle.match.template import match as _match

        for entry in self.internal_entries():
            result = _match(text, entry.text)
            if result.matched:
                return entry, result
        return None

    def alternate_entries(self, code: str) -> list[tuple[str, AnswerKeyEntry]]:
        """The same code's text in the regulation's other required languages."""
        out = []
        for language, reference in self.alternates.items():
            entry = reference.entries.get(code)
            if entry is not None:
                out.append((language, entry))
        return out

    def tier_for(self, code: str) -> Tier:
        entry = self.entry(code)
        if entry is not None:
            return entry.tier
        return Tier.C

    def is_label(self) -> bool:
        return all(span.name == LABEL for span in self.spans)

    def section_for(self, hit: CodeHit) -> str | None:
        return hit.section or section_of(self.spans, hit.line_index)

    def section_for_line(self, index: int) -> str | None:
        return section_of(self.spans, index)

    def parallel(self, code: str, language: str | None = None) -> str | None:
        """The same code's English text in this regulation, which says which
        of its slots are conditional - None where the text being matched is
        itself English. `language` is that text's, the document's by default."""
        if (language or self.language or "").split("-")[0] == "en":
            return None
        entry = _english(self.regulation.id).entries.get(code)
        return entry.text if entry else None

    def hits_in(self, section: str) -> list[CodeHit]:
        return [h for h in self.hits if self.section_for(h) == section]

    @property
    def text(self) -> str:
        return self.document.normalized_text


class Check(Protocol):
    CHECK_ID: str
    TITLE: str

    def run(self, ctx: CheckContext) -> list[Finding]: ...


_REGISTRY: dict[str, Callable[[CheckContext], list[Finding]]] = {}
_TITLES: dict[str, str] = {}
_ORDER: list[str] = []


def register(check_id: str, title: str):
    """Decorator registering a check function under its ID."""

    def wrapper(fn: Callable[[CheckContext], list[Finding]]):
        if check_id in _REGISTRY:
            raise ValueError(f"duplicate check id {check_id}")
        _REGISTRY[check_id] = fn
        _TITLES[check_id] = title
        _ORDER.append(check_id)
        return fn

    return wrapper


def all_checks() -> list[str]:
    return list(_ORDER)


def title_of(check_id: str) -> str:
    return _TITLES.get(check_id, check_id)


def run_check(check_id: str, ctx: CheckContext) -> list[Finding]:
    return _REGISTRY[check_id](ctx)


def run_all(ctx: CheckContext, only: list[str] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for check_id in _ORDER:
        if only and check_id not in only:
            continue
        findings.extend(_REGISTRY[check_id](ctx))
    return findings


@functools.lru_cache(maxsize=16)
def _english(regulation: str):
    from lingua_oracle.keys.tierb import resolve

    return resolve(regulation, "en")
