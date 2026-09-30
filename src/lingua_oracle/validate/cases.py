"""Models and file locations for the validation harness.

Everything the harness reads and writes about real documents lives under
`data/validation/`, which is gitignored. Only the template is tracked.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from lingua_oracle.registry import data_dir


def validation_dir() -> Path:
    return Path(os.environ.get("LINGUA_VALIDATION_DIR", data_dir() / "validation"))


def cases_path() -> Path:
    return validation_dir() / "cases.yaml"


def triage_path() -> Path:
    return validation_dir() / "triage.yaml"


def spot_check_path() -> Path:
    return validation_dir() / "spot_check.yaml"


def template_path() -> Path:
    return data_dir() / "cases.example.yaml"


def validation_reports_dir() -> Path:
    from lingua_oracle.report.render import reports_dir

    out = reports_dir() / "validation"
    out.mkdir(parents=True, exist_ok=True)
    return out


class KnownDefect(BaseModel):
    """A defect the operator already knows the document has."""

    model_config = ConfigDict(extra="forbid")

    check: str
    code: str | None = None
    note: str = ""

    def key(self) -> tuple[str, str | None]:
        return (self.check.strip().upper(), (self.code or "").strip().upper() or None)


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    regulation: str | None = None
    language: str | None = None
    #: A drafted case is scored only once a human has checked it against the
    #: authoring UI. Everything the tool detects by itself is a guess about what
    #: the document *should* contain, and scoring against a guess measures
    #: nothing. `lingua validate` refuses to score a case while this is false.
    confirmed: bool = False
    known_good: bool = False
    expected_codes: list[str] = Field(default_factory=list)
    #: Where expected_codes came from - the authoring application, an operator
    #: declaration, or similar. Recorded so a scored case can always be traced to
    #: an authority independent of this tool.
    expected_source: str = ""
    known_defects: list[KnownDefect] = Field(default_factory=list)

    def normalised_expected(self) -> set[str]:
        from lingua_oracle.detect.codes import canonical_code

        return {canonical_code(c) for c in self.expected_codes if c and c.strip()}


class CaseFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[Case] = Field(default_factory=list)


def load_cases(path: Path | None = None) -> CaseFile:
    target = path or cases_path()
    if not target.exists():
        raise FileNotFoundError(
            f"No case file at {target}. Run `lingua validate init` to create one."
        )
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return CaseFile.model_validate(raw)


# -- triage -----------------------------------------------------------------

CLASSES = ("real_bug", "false_alarm", "key_error", "extraction_error")
#: Classes that mean the tool is at fault, not the document.
TOOL_AT_FAULT = ("false_alarm", "key_error", "extraction_error")


class TriageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    classification: str
    note: str = ""
    fixed: bool = False

    def is_tool_fault(self) -> bool:
        return self.classification in TOOL_AT_FAULT


class TriageFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[TriageEntry] = Field(default_factory=list)

    def by_id(self) -> dict[str, TriageEntry]:
        return {e.id: e for e in self.findings}


def load_triage(path: Path | None = None) -> TriageFile:
    target = path or triage_path()
    if not target.exists():
        return TriageFile()
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return TriageFile.model_validate(raw)


def save_triage(triage: TriageFile, path: Path | None = None) -> Path:
    target = path or triage_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(triage.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return target


# -- answer-key spot check ---------------------------------------------------


class SpotCheckEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regulation: str
    language: str
    code: str
    text: str
    source_ref: str = ""
    source_url: str | None = None
    verdict: str = ""  # "correct" | "wrong" | "" while unreviewed

    def is_reviewed(self) -> bool:
        return self.verdict.strip().lower() in ("correct", "wrong")

    def is_correct(self) -> bool:
        return self.verdict.strip().lower() == "correct"


class SpotCheckFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sampled_at: str = ""
    entries: list[SpotCheckEntry] = Field(default_factory=list)


def load_spot_check(path: Path | None = None) -> SpotCheckFile:
    target = path or spot_check_path()
    if not target.exists():
        return SpotCheckFile()
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return SpotCheckFile.model_validate(raw)


def save_spot_check(data: SpotCheckFile, path: Path | None = None) -> Path:
    target = path or spot_check_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(data.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return target
