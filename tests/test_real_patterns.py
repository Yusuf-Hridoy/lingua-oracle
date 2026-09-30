"""Patterns found on real documents, reproduced with fictional data.

Each test here pins a false alarm that a real SDS produced during Phase 1.5
validation. The documents themselves are company data and cannot be committed,
so every pattern is rebuilt as a synthetic fixture with invented product data.

Findings are described in docs/validation-findings.md.
"""

from __future__ import annotations

import pytest

from lingua_oracle.checks.a01_signal_word import _NEGATIVE_RE, _candidates
from lingua_oracle.models import Severity
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf

# -- finding #2: a negative declaration read as a signal word -----------------


def test_negative_declaration_produces_no_findings():
    """"No ... signal word ... required" declares the absence of one."""
    report = check_pdf(pdf("pattern_negative_declaration"), "eu_clp")
    failures = [f for f in report.findings
                if f.severity is Severity.FAIL and not f.unverified]
    assert failures == [], [f"{f.check_id}: {f.message}" for f in failures]


@pytest.mark.parametrize(
    "line",
    [
        "No hazard pictogram, no signal word, no hazard statement(s), "
        "no precautionary statement(s) required.",
        "Signal word: None assigned",
        "Not classified according to Regulation (EC) No 1272/2008",
        "Not a hazardous substance or mixture.",
        "Ingen signalord",
        "Kein Signalwort",
        "Pas de mention d'avertissement",
        "Sin palabra de advertencia",
    ],
)
def test_negative_phrases_are_recognised(line):
    assert _NEGATIVE_RE.search(line), f"should read as a negative declaration: {line}"


@pytest.mark.parametrize(
    "line",
    ["Signal word: Danger", "Signalord: Fare", "Signalwort: Achtung",
     "Mention d'avertissement: Attention"],
)
def test_real_signal_word_declarations_are_not_swallowed(line):
    assert not _NEGATIVE_RE.search(line), f"this states a signal word: {line}"


def test_signal_word_capture_stops_at_the_value():
    """The capture must take the word, not the rest of the sentence."""
    class _Line:
        def __init__(self, text): self.text, self.page = text, 1

    class _Ctx:
        class document:  # noqa: N801
            lines = [_Line("Signal word: Danger, and other prose follows here")]

    values = [v for v, _page in _candidates(_Ctx())]
    assert values == ["Danger"]


def test_a01_still_catches_a_wrong_signal_word():
    """The fix must not blunt the check it protects."""
    report = check_pdf(pdf("defect_a01_signal"), "eu_clp")
    fired = {f.check_id for f in report.findings if f.severity is Severity.FAIL}
    assert "A-01" in fired
