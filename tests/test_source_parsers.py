"""Unit tests for the local-source parsers (pdf_tables).

These cover the parsing rules themselves. They are fast because they exercise
the regexes and helpers rather than opening the multi-hundred-page PDFs; the
built keys are checked in test_keys.py.
"""

from __future__ import annotations

import pytest

from lingua_oracle.keys.builders.pdf_tables import (
    CODE_CELL_RE,
    ParseIssues,
    clean_statement,
    strip_amendment,
)


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("H225", "H225"),
        ("P303 + P361 + P353", "P303 + P361 + P353"),
        ("EUH 066", "EUH 066"),
        ("AUH044", "AUH044"),
        ("P280 (cont'd)", "P280"),          # continuation marker
        ("H350i", "H350i"),
    ],
)
def test_code_cell_matches(cell, expected):
    m = CODE_CELL_RE.match(cell)
    assert m is not None, cell
    assert m.group(1).strip() == expected


@pytest.mark.parametrize(
    "cell",
    ["Some prose about H225", "", "Hazard class (GHS chapter)", "1, 1A, 1B", "Danger"],
)
def test_code_cell_rejects_non_codes(cell):
    assert CODE_CELL_RE.match(cell) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("[F50P312", "P312"),      # legislation.gov.uk amendment marker
        ("[F149EUH018", "EUH018"),
        ("F12H225", "H225"),
        ("H225", "H225"),
        ("", ""),
    ],
)
def test_strip_amendment(raw, expected):
    assert strip_amendment(raw) == expected


def test_strip_amendment_then_match():
    assert CODE_CELL_RE.match(strip_amendment("[F50P312")).group(1) == "P312"


def test_clean_statement_drops_footnote_marker():
    assert clean_statement("Highly flammable liquid and vapour (2)") == (
        "Highly flammable liquid and vapour"
    )


def test_clean_statement_collapses_wrapped_lines():
    assert clean_statement("Wear protective\ngloves/protective\nclothing") == (
        "Wear protective gloves/protective clothing"
    )


def test_parse_issues_render_is_readable():
    issues = ParseIssues(source="x", pages_scanned=3, tables_seen=2, rows_seen=9, rows_used=4)
    issues.empty_statement.append("P317")
    issues.duplicate_conflict.append("P332")
    issues.notes.append("annex pages 1-3")
    out = issues.render()
    assert "pages=3" in out
    assert "P317" in out
    assert "P332" in out
    assert "annex pages 1-3" in out


def test_parse_issues_render_is_quiet_when_clean():
    out = ParseIssues(source="x", pages_scanned=1).render()
    assert "empty statement" not in out
    assert "different text" not in out
