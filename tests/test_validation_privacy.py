"""Guards on the validation directory.

Real SDS and label PDFs are company data. They live only in data/validation/,
and nothing from that directory may ever reach the repository - not the PDFs,
and not the case, triage or spot-check files, which quote product names.

These tests are the enforcement. If one fails, do not "fix" it by editing the
test: remove whatever got tracked and restore the ignore rule.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VALIDATION = "data/validation"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout


def test_validation_directory_is_never_tracked():
    """Not one file under data/validation/ may be in the index."""
    tracked = [line for line in _git("ls-files", VALIDATION).splitlines() if line.strip()]
    assert tracked == [], f"company data is tracked: {tracked}"


def test_validation_directory_is_ignored_including_nested_paths():
    """A new PDF dropped anywhere under the directory must be ignored."""
    for candidate in (
        f"{VALIDATION}/sheet.pdf",
        f"{VALIDATION}/cases.yaml",
        f"{VALIDATION}/triage.yaml",
        f"{VALIDATION}/spot_check.yaml",
        f"{VALIDATION}/batch-2026/label.pdf",
    ):
        result = subprocess.run(
            ["git", "check-ignore", "-q", candidate],
            cwd=REPO, capture_output=True, check=False,
        )
        assert result.returncode == 0, f"{candidate} is NOT ignored"


def test_no_validation_paths_anywhere_in_history():
    """The directory must never have been committed, even in an earlier commit."""
    logged = _git("log", "--all", "--name-only", "--pretty=format:", "--", VALIDATION)
    assert logged.strip() == "", f"company data appears in history: {logged[:300]}"


def test_reports_directory_is_ignored():
    """Validation reports quote document content, so they stay local too."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "reports/validation/summary.html"],
        cwd=REPO, capture_output=True, check=False,
    )
    assert result.returncode == 0, "reports/ must stay untracked"


def test_example_case_file_is_tracked_and_carries_no_real_data():
    """The template is tracked; it must be obviously fictional."""
    example = REPO / "data" / "cases.example.yaml"
    assert example.exists(), "cases.example.yaml should be tracked as the template"
    assert _git("ls-files", "data/cases.example.yaml").strip(), "template is not tracked"
    body = example.read_text(encoding="utf-8").lower()
    for marker in ("example", "fictional"):
        assert marker in body, f"the template should say it is {marker}"
