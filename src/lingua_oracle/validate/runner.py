"""Running the validation cases and scoring them against the targets."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lingua_oracle.detect.regulation import RegulationUndetermined
from lingua_oracle.models import Report, Severity
from lingua_oracle.validate.cases import (
    Case,
    TriageFile,
    load_cases,
    load_spot_check,
    load_triage,
    validation_dir,
)

#: The targets this harness is measured against.
TARGETS = {
    "code_recall": 0.98,
    "false_alarms_on_known_good": 0,
    "known_defects_caught": 1.0,
    "spot_check_correct": 20,
}


def finding_id(case_file: str, check_id: str, code: str | None, message: str) -> str:
    """A stable id for one finding, so a triage verdict survives a re-run.

    The document's own text is not part of the id - only its file name, the
    check, the code and a hash of the message - so triage.yaml never has to
    quote product data to identify a finding.
    """
    digest = hashlib.sha256(f"{check_id}|{code}|{message}".encode()).hexdigest()[:8]
    return f"{Path(case_file).stem}:{check_id}:{code or '-'}:{digest}"


@dataclass
class CaseResult:
    case: Case
    report: Report | None = None
    error: str = ""
    expected: set[str] = field(default_factory=set)
    found: set[str] = field(default_factory=set)
    missed: set[str] = field(default_factory=set)
    extra: set[str] = field(default_factory=set)
    defects_caught: list[dict] = field(default_factory=list)
    defects_missed: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)

    @property
    def recall(self) -> float | None:
        if not self.expected:
            return None
        return len(self.expected & self.found) / len(self.expected)

    @property
    def counts(self) -> dict[str, int]:
        if self.report is None:
            return {"fail": 0, "warn": 0, "info": 0, "unverified": 0}
        s = self.report.summary
        return {"fail": s.fail, "warn": s.warn, "info": s.info, "unverified": s.unverified}


def run_case(case: Case, root: Path, triage: TriageFile) -> CaseResult:
    from lingua_oracle.pipeline import check_pdf

    result = CaseResult(case=case, expected=case.normalised_expected())
    path = root / case.file
    if not path.exists():
        result.error = f"file not found: {path}"
        return result
    try:
        report = check_pdf(str(path), case.regulation, case.language)
    except RegulationUndetermined as exc:
        result.error = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001 - a crash on a real PDF is a result
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    result.report = report
    result.found = {f.code for f in report.findings if f.code} | _codes_seen(str(path), report)
    result.missed = result.expected - result.found
    result.extra = result.found - result.expected if result.expected else set()

    known = {d.key() for d in case.known_defects}
    fired = {
        (f.check_id.upper(), (f.code or "").upper() or None)
        for f in report.findings
        if f.severity in (Severity.FAIL, Severity.WARN) and not f.unverified
    }
    for defect in case.known_defects:
        entry = {"check": defect.check, "code": defect.code, "note": defect.note}
        (result.defects_caught if defect.key() in fired else result.defects_missed).append(entry)

    seen = triage.by_id()
    for f in report.findings:
        if f.severity not in (Severity.FAIL, Severity.WARN) or f.unverified:
            continue
        fid = finding_id(case.file, f.check_id, f.code, f.message)
        entry = seen.get(fid)
        result.findings.append(
            {
                "id": fid,
                "check_id": f.check_id,
                "code": f.code,
                "severity": f.severity.value,
                "section": f.section,
                "page": f.page,
                "message": f.message,
                "classification": entry.classification if entry else "",
                "triage_note": entry.note if entry else "",
                "fixed": bool(entry and entry.fixed),
                "known_defect": (f.check_id.upper(), (f.code or "").upper() or None) in known,
            }
        )
    return result


def _codes_seen(path: str, report: Report) -> set[str]:
    """Every code the extractor found in the document, not only ones with findings.

    Recall is about what the tool can *see*, so a code that parsed cleanly and
    produced no finding still counts as found.
    """
    from lingua_oracle.detect.codes import extract_document_hits
    from lingua_oracle.extract import extract

    try:
        return {hit.code for hit in extract_document_hits(extract(path))}
    except Exception:  # noqa: BLE001
        return set()


@dataclass
class Summary:
    results: list[CaseResult]
    created_at: datetime
    spot_check_total: int = 0
    spot_check_correct: int = 0
    spot_check_reviewed: int = 0

    # -- metrics ----------------------------------------------------------
    @property
    def code_recall(self) -> float | None:
        expected = sum(len(r.expected) for r in self.results)
        if not expected:
            return None
        hit = sum(len(r.expected & r.found) for r in self.results)
        return hit / expected

    @property
    def false_alarms(self) -> list[dict]:
        """Findings on known_good documents that are the tool's fault.

        Anything unclassified counts too: an unreviewed finding on a document
        believed correct is a false alarm until someone shows otherwise.
        """
        out = []
        for r in self.results:
            if not r.case.known_good:
                continue
            for f in r.findings:
                if f["fixed"]:
                    continue
                if f["classification"] in ("", "false_alarm", "key_error", "extraction_error"):
                    out.append({"file": r.case.file, **f})
        return out

    @property
    def defects_expected(self) -> int:
        return sum(len(r.case.known_defects) for r in self.results)

    @property
    def defects_caught(self) -> int:
        return sum(len(r.defects_caught) for r in self.results)

    @property
    def defect_rate(self) -> float | None:
        return self.defects_caught / self.defects_expected if self.defects_expected else None

    @property
    def triage_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {"unclassified": 0}
        for r in self.results:
            for f in r.findings:
                key = f["classification"] or "unclassified"
                counts[key] = counts.get(key, 0) + 1
        return counts

    def targets(self) -> list[dict]:
        recall = self.code_recall
        rate = self.defect_rate
        return [
            {
                "name": "Code recall",
                "target": "≥ 98%",
                "actual": "n/a" if recall is None else f"{recall * 100:.1f}%",
                "passed": recall is None or recall >= TARGETS["code_recall"],
                "skipped": recall is None,
            },
            {
                "name": "False alarms on known_good documents",
                "target": "0",
                "actual": str(len(self.false_alarms)),
                "passed": len(self.false_alarms) == 0,
                "skipped": False,
            },
            {
                "name": "Known defects caught",
                "target": "100%",
                "actual": "n/a" if rate is None else f"{self.defects_caught}/{self.defects_expected}",
                "passed": rate is None or rate >= TARGETS["known_defects_caught"],
                "skipped": rate is None,
            },
            {
                "name": "Answer-key spot check",
                "target": "20/20",
                "actual": f"{self.spot_check_correct}/{self.spot_check_total or 0}"
                + ("" if self.spot_check_reviewed == self.spot_check_total
                   else f" ({self.spot_check_reviewed} reviewed)"),
                "passed": (
                    self.spot_check_total >= TARGETS["spot_check_correct"]
                    and self.spot_check_correct >= TARGETS["spot_check_correct"]
                ),
                "skipped": self.spot_check_total == 0,
            },
        ]

    @property
    def passed(self) -> bool:
        """Overall pass requires every target to be measured AND met.

        A target that could not be measured - no expected_codes given, or the
        answer-key spot check not done - is deliberately NOT treated as a pass.
        The definition of done is that every target shows PASS, and "not measured"
        is not the same as "met".
        """
        return all(t["passed"] and not t["skipped"] for t in self.targets())


def run(root: Path | None = None) -> Summary:
    base = root or validation_dir()
    case_file = load_cases(base / "cases.yaml" if root else None)
    triage = load_triage(base / "triage.yaml" if root else None)
    results = [run_case(c, base, triage) for c in case_file.cases]
    spot = load_spot_check(base / "spot_check.yaml" if root else None)
    return Summary(
        results=results,
        created_at=datetime.now(UTC),
        spot_check_total=len(spot.entries),
        spot_check_reviewed=sum(1 for e in spot.entries if e.is_reviewed()),
        spot_check_correct=sum(1 for e in spot.entries if e.is_correct()),
    )
