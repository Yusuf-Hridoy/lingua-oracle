"""Rendering reports to JSON and to a single self-contained HTML file."""

from __future__ import annotations

import difflib
import html
import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from lingua_oracle.checks import title_of
from lingua_oracle.models import Report, Severity
from lingua_oracle.registry import load_registry
from lingua_oracle.report import labels

TEMPLATES = Path(__file__).parent / "templates"

_SEVERITY_ORDER = {Severity.FAIL: 0, Severity.WARN: 1, Severity.INFO: 2}


def reports_dir() -> Path:
    import os

    d = Path(os.environ.get("LINGUA_REPORTS_DIR", Path.cwd() / "reports"))
    d.mkdir(parents=True, exist_ok=True)
    return d


_TOKEN_RE = re.compile(r"\s+")


def _tokens(text: str) -> list[str]:
    """Words with their trailing space, so joining restores the original."""
    out, pos = [], 0
    for match in _TOKEN_RE.finditer(text):
        out.append(text[pos : match.end()])
        pos = match.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


def word_diff(expected: str | None, found: str | None) -> tuple[str, str]:
    """Both texts in full, with only the differing words marked.

    The previous rendering struck through the official wording, which reads as
    "this text is wrong" - the exact opposite of what the column means. Neither
    side is deleted here: both are shown whole, and the highlight says only
    "these are the words that differ".

    Word-level rather than character-level, because a character diff of two
    sentences aligns on stray letters and reads as confetti.
    """
    if expected is None and found is None:
        return "", ""
    a, b = _tokens(expected or ""), _tokens(found or "")
    left: list[str] = []
    right: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, [t.strip() for t in a], [t.strip() for t in b], autojunk=False
    ).get_opcodes():
        piece_a = html.escape("".join(a[i1:i2]))
        piece_b = html.escape("".join(b[j1:j2]))
        if tag == "equal":
            left.append(piece_a)
            right.append(piece_b)
            continue
        if piece_a:
            left.append(f'<mark class="diff">{piece_a}</mark>')
        if piece_b:
            right.append(f'<mark class="diff">{piece_b}</mark>')
    return "".join(left), "".join(right)


#: Kept under the old name so nothing outside has to change.
char_diff = word_diff


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["word_diff"] = lambda pair: word_diff(pair[0], pair[1])
    return env


def _grouped(report: Report, display: str = "") -> list[dict]:
    """Findings grouped by check, failures first."""
    groups: dict[str, list] = {}
    for finding in report.findings:
        groups.setdefault(finding.check_id, []).append(finding)

    rendered = []
    for check_id, findings in groups.items():
        findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 3), f.code or ""))
        rows = []
        for f in findings:
            left, right = word_diff(f.expected, f.found)
            rows.append({
                "finding": f,
                "expected_html": left,
                "found_html": right,
                "result": labels.result_of(check_id, f.severity, f.unverified),
                "action": labels.action_for(f, display),
                "source": labels.SOURCE.get(f.tier) if f.tier else None,
                "code_label": labels.code_label(f.code),
                "section_label": labels.section_label(f.section),
            })
        rendered.append(
            {
                "check_id": check_id,
                "title": title_of(check_id),
                "expected_column": (labels.NEWER_GHS_EXPECTED_COLUMN
                                    if check_id == "C-15"
                                    else labels.COLUMNS["expected"]),
                "rows": rows,
                "fails": sum(1 for f in findings if f.severity == Severity.FAIL and not f.unverified),
                "warns": sum(1 for f in findings if f.severity == Severity.WARN and not f.unverified),
                "unverified": sum(1 for f in findings if f.unverified),
            }
        )
    rendered.sort(key=lambda g: (-g["fails"], -g["warns"], g["check_id"]))
    return rendered


_STATUS_ORDER = {"wrong": 0, "check": 1, "not_checked": 2, "correct": 3}


def display_of(report: Report) -> str:
    try:
        return load_registry().get(report.regulation).display_name
    except KeyError:
        return report.regulation


def _statement_cards(report: Report) -> dict:
    """The report as a reader wants it: what is wrong, then what is fine."""
    rows = []
    for verdict in sorted(report.statements,
                          key=lambda v: (_STATUS_ORDER.get(v.status, 9), v.code)):
        left, right = word_diff(verdict.expected, verdict.found)
        rows.append({
            "v": verdict,
            "label": labels.STATUS.get(verdict.status, labels.NOT_CHECKED),
            "found_html": right,
            "expected_html": left,
            "action": labels.STATUS_ACTION.get(verdict.status, ""),
        })
    problems = [r for r in rows if r["v"].status != "correct"]
    correct = [r for r in rows if r["v"].status == "correct"]

    # Findings that are not about one statement's wording - a missing
    # language, a leftover placeholder, a code set that differs between two
    # documents. Without these the report would simply lose them.
    statement_checks = {"A-02", "A-03", "A-04", "C-15"}
    others = []
    for finding in report.findings:
        if finding.check_id in statement_checks or finding.unverified:
            continue
        if finding.severity is Severity.INFO and finding.code:
            continue  # fill-in notes ride on their own statement card
        others.append({
            "finding": finding,
            "label": labels.result_of(finding.check_id, finding.severity, False),
            "action": labels.action_for(finding, display_of(report)),
        })
    others.sort(key=lambda o: _SEVERITY_ORDER.get(o["finding"].severity, 9))

    return {"problems": problems, "correct": correct, "others": others,
            "counts": {
                "correct": len(correct),
                "wrong": sum(1 for r in rows if r["v"].status == "wrong"),
                "check": sum(1 for r in rows if r["v"].status == "check"),
                "not_checked": sum(1 for r in rows if r["v"].status == "not_checked"),
            }}


def render_html(report: Report) -> str:
    registry = load_registry()
    try:
        display = registry.get(report.regulation).display_name
    except KeyError:
        display = report.regulation
    template = _environment().get_template("report.html.j2")
    return template.render(
        report=report,
        groups=_grouped(report, display),
        regulation_display=display,
        coverage_percent=report.coverage.percent,
        verdict=labels.verdict_of(report, display),
        cards=_statement_cards(report),
        L=labels,
        SEV=Severity,
        set_by=labels.SET_BY.get(report.detected_by, report.detected_by),
    )


def save(report: Report, directory: Path | None = None) -> tuple[Path, Path]:
    """Write both report.json and report.html; returns (json_path, html_path)."""
    target = directory or reports_dir()
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / f"{report.id}.json"
    html_path = target / f"{report.id}.html"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    html_path.write_text(render_html(report), encoding="utf-8")
    return json_path, html_path


def load(report_id: str, directory: Path | None = None) -> Report | None:
    target = directory or reports_dir()
    path = target / f"{report_id}.json"
    if not path.exists():
        return None
    return Report.model_validate_json(path.read_text(encoding="utf-8"))
