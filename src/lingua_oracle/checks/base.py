"""Check framework: the shared context and the check registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from lingua_oracle.detect.codes import CodeHit
from lingua_oracle.detect.sections import LABEL, SectionSpan, section_of
from lingua_oracle.extract.base import Document
from lingua_oracle.keys.tierb import Borrowed
from lingua_oracle.models import AnswerKeyEntry, Finding, Tier
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
    compare_document: Document | None = None
    compare_hits: list[CodeHit] = field(default_factory=list)
    compare_language: str | None = None
    notes: list[str] = field(default_factory=list)

    # -- convenience ------------------------------------------------------
    def entry(self, code: str) -> AnswerKeyEntry | None:
        return self.reference.entries.get(code)

    def tier_for(self, code: str) -> Tier:
        entry = self.entry(code)
        if entry is not None:
            return entry.tier
        return Tier.C

    def is_label(self) -> bool:
        return all(span.name == LABEL for span in self.spans)

    def section_for(self, hit: CodeHit) -> str | None:
        return hit.section or section_of(self.spans, hit.line_index)

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
