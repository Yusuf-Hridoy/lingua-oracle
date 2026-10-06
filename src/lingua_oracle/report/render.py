"""Rendering reports to JSON and to a single self-contained HTML file."""

from __future__ import annotations

import base64
import difflib
import functools
import html
import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from lingua_oracle.checks import title_of
from lingua_oracle.detect.language import language_name
from lingua_oracle.models import Report, Severity
from lingua_oracle.registry import load_registry
from lingua_oracle.report import labels

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"


#: How large a saved report may get once the fonts are inside it. A report is
#: an attachment people mail to each other; past this the typeface is not worth
#: the weight, and the fallback stack is a perfectly good read.
_REPORT_BUDGET = 1_000_000

_FONT_URL_RE = re.compile(r'url\("fonts/([^"]+)"\)')


@functools.lru_cache(maxsize=1)
def app_css() -> str:
    """The design system, read once. Served at /static/app.css."""
    return (STATIC / "app.css").read_text(encoding="utf-8")


@functools.lru_cache(maxsize=1)
def _embedded_css() -> str:
    """app.css with the fonts inlined, for a report that travels alone."""

    def embed(match: re.Match[str]) -> str:
        path = STATIC / "fonts" / match.group(1)
        if not path.exists():
            return match.group(0)
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'url("data:font/woff2;base64,{data}")'

    return _FONT_URL_RE.sub(embed, app_css())


@functools.lru_cache(maxsize=1)
def _stripped_css() -> str:
    """app.css with the @font-face blocks removed, so nothing is requested."""
    return re.sub(r"@font-face\s*\{[^}]*\}\s*", "", app_css())


def report_css(body_size: int = 0) -> str:
    """The stylesheet a saved report carries.

    The fonts go in where the result still fits in an attachment. Where they do
    not, the @font-face rules are removed rather than left pointing at files
    that will not be there - a saved report never requests anything.
    """
    embedded = _embedded_css()
    if body_size + len(embedded) <= _REPORT_BUDGET:
        return embedded
    return _stripped_css()

_SEVERITY_ORDER = {Severity.FAIL: 0, Severity.WARN: 1, Severity.INFO: 2}


def reports_dir() -> Path:
    import os

    d = Path(os.environ.get("LINGUA_REPORTS_DIR", Path.cwd() / "reports"))
    d.mkdir(parents=True, exist_ok=True)
    return d


#: A token is a run of non-space, or an ellipsis, each carrying any space that
#: follows it so joining restores the original exactly. The ellipsis is split
#: out on its own because "Use…" and "Use …" are the same statement written two
#: ways: tokenising on whitespace alone made them differ, and the diff then
#: highlighted a space.
_TOKEN_RE = re.compile(r"…|[^\s…]+")


def _tokens(text: str) -> list[str]:
    out, pos = [], 0
    for match in _TOKEN_RE.finditer(text or ""):
        if match.start() > pos and out:
            out[-1] += (text or "")[pos : match.start()]
        elif match.start() > pos:
            out.append((text or "")[pos : match.start()])
        out.append(match.group(0))
        pos = match.end()
    if pos < len(text or "") and out:
        out[-1] += (text or "")[pos:]
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
    # ".j2" has to be in the list. Every template here is named "x.html.j2", and
    # select_autoescape looks at the final suffix - so "html" alone never fired,
    # and the report rendered text taken out of an uploaded PDF without escaping
    # it. The only value that must not be escaped is the stylesheet, which is
    # wrapped in Markup where it is passed in.
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "j2", "html.j2"],
                                     default_for_string=True, default=True),
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


def _highlight_blank(text: str) -> str:
    """The document's own text with only the placeholder marked."""
    out, pos = [], 0
    for match in re.finditer(r"…", text or ""):
        before = (text or "")[pos : match.start()]
        out.append(html.escape(before))
        # The act writes "to…" with nothing between; the highlight needs air
        # around it or it reads as part of the word before it.
        if before and not before[-1].isspace():
            out.append(" ")
        out.append('<mark class="diff">…</mark>')
        pos = match.end()
    out.append(html.escape((text or "")[pos:]))
    return "".join(out)


def _issue_status(verdict) -> str:
    """The word shown on the card.

    A statement whose wording is right but whose blank was never filled is not
    "check this" - there is nothing to weigh up, the sheet is unfinished. It
    reads as "Fix this", alongside the placeholders and missing sections.
    """
    if verdict.status == "check" and (
            verdict.blank_unfilled or "never filled in" in (verdict.why or "")):
        return "fix"
    return verdict.status


def _statement_cards(report: Report) -> dict:
    """The report as a reader wants it: what to fix, then what is fine."""
    display = display_of(report)
    rows = []
    for verdict in sorted(report.statements,
                          key=lambda v: (_STATUS_ORDER.get(v.status, 9), v.code)):
        status = _issue_status(verdict)
        # A blank nobody filled in needs one column, not two. The official text
        # and the document's are the same statement; showing them side by side
        # invites a reader to hunt for a difference that is not there, and the
        # only thing that matters is the placeholder still sitting in it.
        blank = status == "fix" and verdict.blank_unfilled
        if blank:
            left, right = "", _highlight_blank(verdict.found)
        else:
            left, right = word_diff(verdict.expected, verdict.found)
        rows.append({
            "v": verdict,
            "status": status,
            "minor": bool(getattr(verdict, "minor_difference", False))
                     and status not in ("correct", "not_checked"),
            "label": labels.STATUS.get(status, labels.NOT_CHECKED),
            "found_html": right,
            "expected_html": left,
            "action": labels.STATUS_ACTION.get(status, ""),
            "single": blank or not verdict.expected,
            "instruction": (labels.blank_instruction(verdict.code, verdict.expected)
                            if blank else ""),
            # On a placeholder card the official wording is a reference, not
            # something to compare against - the document already says it. One
            # line, no diff, so nobody goes looking for a difference.
            "reference": verdict.expected if blank else "",
            "official_heading": (
                f"Closest {display} statement · {verdict.nearest_code}"
                if getattr(verdict, "nearest_code", "") else "Official wording"
            ),
            "match_note": verdict.match_note,
        })
    problems = [r for r in rows if r["status"] not in ("correct", "not_checked")
                and not r["minor"]]
    # Same words, different punctuation or capital letters. Each one is worth
    # saying and none is worth a card of its own: a dozen of them pushed the
    # statements that genuinely differ off the first screen.
    minor = [r for r in rows if r["minor"]]
    correct = [r for r in rows if r["status"] == "correct"]
    unchecked = [r for r in rows if r["status"] == "not_checked"]

    # Findings that are not about one statement's wording - a missing language,
    # a leftover placeholder, a code set that differs between two documents.
    # Without these the report would simply lose them.
    statement_checks = {"A-02", "A-03", "A-04", "C-15"}
    for finding in report.findings:
        if finding.check_id in statement_checks or finding.unverified:
            continue
        if finding.severity is Severity.INFO and finding.code:
            continue  # fill-in notes ride on their own statement card
        # A-01 compares the signal word against the official text, so its
        # failure is wrong wording like any other; the rest are things to fix.
        if finding.severity is not Severity.FAIL:
            status = "check"
        elif finding.check_id in labels.WORDING_CHECKS:
            status = "wrong"
        else:
            status = "fix"
        problems.append({
            "v": None,
            "finding": finding,
            "status": status,
            "minor": False,
            "label": labels.STATUS[status],
            "single": True,
            "action": labels.action_for(finding, display),
        })

    order = {"wrong": 0, "fix": 1, "check": 2}
    problems.sort(key=lambda r: order.get(r["status"], 9))
    # The counts cover everything the reader can see, collapsed card included,
    # because the banner sentence is written from these numbers and the stat
    # cells show them. Two sets of numbers for one report is how a banner comes
    # to disagree with the figures beside it.
    counts = {
        "wrong": sum(1 for r in problems if r["status"] == "wrong"),
        "fix": sum(1 for r in problems if r["status"] == "fix"),
        "check": (sum(1 for r in problems if r["status"] == "check") + len(minor)),
        "correct": len(correct),
        "not_checked": len(unchecked),
        "minor": len(minor),
        "blanks": sum(1 for r in problems
                      if r["status"] == "fix" and r.get("v")
                      and r["v"].blank_unfilled),
    }
    # Where each wording came from, in full. Off the cards, which carry the
    # regulation and the instrument only.
    provenance = sorted(
        {(v.code, v.source_detail) for v in report.statements if v.source_detail}
    )
    return {"problems": problems, "correct": correct, "unchecked": unchecked,
            "minor": minor, "counts": counts, "provenance": provenance}


def _body_estimate(report: Report) -> int:
    """Rough size of the report's own markup, before the stylesheet."""
    return sum(
        len(v.found) + len(v.expected) + len(v.why) + len(v.source) + 400
        for v in report.statements
    ) + sum(len(f.message or "") + 400 for f in report.findings) + 4000


#: What the Ingredients section was able to look at, in one line.
_INGREDIENT_SOURCE = {
    "app": "checked against this product's record in ExactSDS",
    "pdf": "read from Section 3 of this sheet",
    "nothing": "nothing on this sheet to check",
    "skipped": "not checked",
}


def ingredient_reasons() -> dict[str, str]:
    from lingua_oracle.ingredients.report import REASONS

    return REASONS


def _ingredient_source(section) -> str:
    if section is None:
        return ""
    return _INGREDIENT_SOURCE.get(section.source, "")


#: What the Mixture section was able to do, in one line.
_MIXTURE_SOURCE = {
    "nothing": "nothing to calculate from",
    "out_of_scope": "not calculated",
    "skipped": "not calculated",
}


def _mixture_source(section) -> str:
    """Where the rules behind this section came from, in the document's name.

    Every regulation is calculated by its own text now, so naming CLP here -
    as this line used to, whatever the sheet was written to - would be wrong
    on five regulations out of six.
    """
    state = getattr(section, "state", "")
    if state == "calculated":
        document = getattr(section, "source_document", "")
        return (f"calculated from the ingredients, by {document}" if document
                else "calculated from the ingredients")
    return _MIXTURE_SOURCE.get(state, "")


def display_name_of(regulation: str | None) -> str:
    """A regulation's display name. Its id is a database key, not a word.

    Nothing in the interface shows "ca_whmis" or "us_osha" at a reader: those
    are how this tool refers to a regulation among itself.
    """
    if not regulation:
        return ""
    try:
        return load_registry().get(regulation).display_name
    except KeyError:
        return regulation


def _mixture_tone(section) -> str:
    if section is None or not section.counts:
        return "check"
    if section.counts.get("inconsistent"):
        return "fix"
    if section.counts.get("cannot_tell"):
        return "check"
    return "ok" if section.counts.get("consistent") else "check"


def _ingredient_tone(section) -> str:
    if section is None or not section.counts:
        return "check"
    if section.counts.get("fix"):
        return "fix"
    if section.counts.get("inconsistent_substances"):
        return "check"
    return "ok" if section.counts.get("with_entry") else "check"


def render_html(report: Report) -> str:
    registry = load_registry()
    try:
        display = registry.get(report.regulation).display_name
    except KeyError:
        display = report.regulation
    template = _environment().get_template("report.html.j2")
    cards = _statement_cards(report)
    ing = report.ingredients
    substances = (ing.substances if ing else []) or []
    return template.render(
        ing=ing,
        ing_source=_ingredient_source(ing),
        ing_said_by=("This sheet says" if ing and ing.source == "pdf"
                     else "The app says"),
        ing_tone=_ingredient_tone(ing),
        ing_under=[s for s in substances if s["uses_under_classified"]],
        ing_inconsistent=[s for s in substances
                          if s["inconsistent"] and not s["uses_under_classified"]],
        ing_matches=[s for s in substances if s["status"] == "ok"
                     and not s["uses_under_classified"]],
        ing_extra=[s for s in substances if s["status"] == "info"
                   and not s["uses_under_classified"]],
        ing_unchecked=[s for s in substances if s["status"] == "not_checked"],
        ing_reasons=ingredient_reasons(),
        regulation_name=display_name_of,
        mixture=report.mixture,
        mixture_source=_mixture_source(report.mixture),
        mixture_tone=_mixture_tone(report.mixture),
        report=report,
        groups=_grouped(report, display),
        regulation_display=display,
        coverage_percent=report.coverage.percent,
        verdict=labels.verdict_of(report, display, counts=cards["counts"]),
        app_css=Markup(report_css(_body_estimate(report))),
        language_name=language_name(report.language),
        cards=cards,
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
