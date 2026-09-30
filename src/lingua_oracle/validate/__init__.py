"""Validation harness for running the checker against real documents.

Real PDFs are company data and live only in `data/validation/`, which is
gitignored; so is everything derived from them under `reports/validation/`.
Nothing here writes document content into the repository.
"""

from lingua_oracle.validate.cases import (
    CLASSES,
    Case,
    CaseFile,
    SpotCheckEntry,
    SpotCheckFile,
    TriageEntry,
    TriageFile,
    TriagePattern,
    cases_path,
    load_cases,
    load_spot_check,
    load_triage,
    save_spot_check,
    save_triage,
    spot_check_path,
    template_path,
    triage_path,
    validation_dir,
    validation_reports_dir,
)
from lingua_oracle.validate.runner import Summary, finding_id, run

__all__ = [
    "CLASSES",
    "Case",
    "CaseFile",
    "SpotCheckEntry",
    "SpotCheckFile",
    "Summary",
    "TriageEntry",
    "TriageFile",
    "TriagePattern",
    "cases_path",
    "finding_id",
    "load_cases",
    "load_spot_check",
    "load_triage",
    "run",
    "save_spot_check",
    "save_triage",
    "spot_check_path",
    "template_path",
    "triage_path",
    "validation_dir",
    "validation_reports_dir",
]
