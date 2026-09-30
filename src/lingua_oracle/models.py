"""Core Pydantic models shared across Lingua Oracle."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Kind(StrEnum):
    """What sort of phrase an answer-key entry holds."""

    HAZARD = "hazard"
    PRECAUTIONARY = "precautionary"
    SUPPLEMENTAL = "supplemental"
    SIGNAL = "signal"


class Tier(StrEnum):
    """Provenance of the reference text backing a verdict."""

    A = "A"  # official text for this regulation and language
    B = "B"  # borrowed official text (identical English -> EU CLP translation)
    C = "C"  # no official source; consistency-only


class Status(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    PENDING_SOURCE = "pending_source"


class Severity(StrEnum):
    FAIL = "fail"
    WARN = "warn"
    INFO = "info"


SignalWord = Literal["Danger", "Warning", "Either", "None"]

# Pseudo-codes used for signal-word entries in the answer keys.
SIGNAL_DANGER = "SIGNAL_DANGER"
SIGNAL_WARNING = "SIGNAL_WARNING"


class AnswerKeyEntry(BaseModel):
    """One official phrase for one regulation, language and code."""

    model_config = ConfigDict(extra="forbid")

    regulation: str
    revision: str
    language: str  # BCP-47
    code: str
    kind: Kind
    text: str
    signal_word: SignalWord | None = None
    tier: Tier = Tier.A
    #: True when `code` is an internal identifier invented by this tool, not a
    #: regulatory code. Used for hazards a regulation defines without giving them
    #: a GHS code (OSHA's combustible dust and simple asphyxiant). These are
    #: matched by TEXT, never by code, and must never be written onto a document
    #: or reported as though the regulator had assigned them.
    internal_id: bool = False
    source_url: str | None = None
    source_ref: str | None = None
    retrieved_at: datetime | None = None
    status: Status = Status.OK

    @field_validator("code")
    @classmethod
    def _strip_code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("text")
    @classmethod
    def _strip_text(cls, v: str) -> str:
        return v.strip()


class AnswerKey(BaseModel):
    """All entries for one regulation x language, as stored on disk."""

    model_config = ConfigDict(extra="forbid")

    regulation: str
    language: str
    revision: str
    status: Status = Status.OK
    # Why a key is not `ok`, in machine-readable form, e.g. "wrong_source" or
    # "needs_class_category_mapping". Free text lives in _parse_issues.txt.
    status_reason: str | None = None
    source_url: str | None = None
    retrieved_at: datetime | None = None
    entries: list[AnswerKeyEntry] = Field(default_factory=list)

    def by_code(self) -> dict[str, AnswerKeyEntry]:
        return {e.code: e for e in self.entries}


class Finding(BaseModel):
    """A single check result worth showing to a human."""

    model_config = ConfigDict(extra="forbid")

    check_id: str
    severity: Severity
    section: str | None = None
    page: int | None = None
    code: str | None = None
    expected: str | None = None
    found: str | None = None
    tier: Tier | None = None
    message: str = ""
    unverified: bool = False


class Coverage(BaseModel):
    codes_found: int = 0
    codes_checked: int = 0
    unverified: int = 0

    @property
    def percent(self) -> float:
        if self.codes_found == 0:
            return 0.0
        return round(100.0 * self.codes_checked / self.codes_found, 1)


class Summary(BaseModel):
    fail: int = 0
    warn: int = 0
    info: int = 0
    passed: int = 0
    unverified: int = 0


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    file_name: str
    regulation: str
    language: str
    detected_by: Literal["flag", "auto"]
    created_at: datetime
    summary: Summary = Field(default_factory=Summary)
    findings: list[Finding] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    compared_with: str | None = None
    notes: list[str] = Field(default_factory=list)

    def recount(self) -> None:
        s = Summary()
        for f in self.findings:
            if f.unverified:
                s.unverified += 1
                continue
            match f.severity:
                case Severity.FAIL:
                    s.fail += 1
                case Severity.WARN:
                    s.warn += 1
                case Severity.INFO:
                    s.info += 1
        self.summary = s
