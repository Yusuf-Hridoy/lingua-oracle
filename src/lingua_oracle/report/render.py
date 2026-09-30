"""Rendering reports to JSON and to a single self-contained HTML file."""

from __future__ import annotations

import difflib
import html
import json
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


def char_diff(expected: str | None, found: str | None) -> tuple[str, str]:
    """Character-level diff of expected vs found, as two HTML fragments."""
    if expected is None and found is None:
        return "", ""
    a, b = expected or "", found or ""
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    # Character diffs between two unrelated sentences align on stray letters and
    # read as confetti. Below this similarity the texts are simply different, so
    # show each one whole.
    if a and b and matcher.ratio() < 0.65:
        return (
            f'<mark class="del">{html.escape(a)}</mark>',
            f'<mark class="ins">{html.escape(b)}</mark>',
        )
    left: list[str] = []
    right: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        piece_a = html.escape(a[i1:i2])
        piece_b = html.escape(b[j1:j2])
        if tag == "equal":
            left.append(piece_a)
            right.append(piece_b)
        elif tag == "delete":
            left.append(f'<mark class="del">{piece_a}</mark>')
        elif tag == "insert":
            right.append(f'<mark class="ins">{piece_b}</mark>')
        else:
            left.append(f'<mark class="del">{piece_a}</mark>')
            right.append(f'<mark class="ins">{piece_b}</mark>')
    return "".join(left), "".join(right)


def _environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["char_diff"] = lambda pair: char_diff(pair[0], pair[1])
    return env


def _grouped(report: Report) -> list[dict]:
    """Findings grouped by check, failures first."""
    groups: dict[str, list] = {}
    for finding in report.findings:
        groups.setdefault(finding.check_id, []).append(finding)

    rendered = []
    for check_id, findings in groups.items():
        findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 3), f.code or ""))
        rows = []
        for f in findings:
            left, right = char_diff(f.expected, f.found)
            rows.append({
                "finding": f,
                "expected_html": left,
                "found_html": right,
                "result": (labels.NOT_CHECKED if f.unverified
                           else labels.SEVERITY[f.severity]),
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


def render_html(report: Report) -> str:
    registry = load_registry()
    try:
        display = registry.get(report.regulation).display_name
    except KeyError:
        display = report.regulation
    template = _environment().get_template("report.html.j2")
    return template.render(
        report=report,
        groups=_grouped(report),
        regulation_display=display,
        coverage_percent=report.coverage.percent,
        verdict=labels.verdict_of(report),
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
