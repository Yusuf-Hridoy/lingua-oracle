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

from lingua_oracle.detect.language import language_name
from lingua_oracle.models import Report
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


def _body_estimate(report: Report) -> int:
    """Rough size of the report's own markup, before the stylesheet."""
    return sum(
        len(v.found) + len(v.expected) + len(v.why) + len(v.source) + 400
        for v in report.statements
    ) + sum(len(f.message or "") + 400 for f in report.findings) + 4000


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


def render_html(report: Report) -> str:
    """The report, section by section as an SDS is read (`report.sections`)."""
    from lingua_oracle.report import sections

    display = display_of(report)
    set_by = labels.SET_BY.get(report.detected_by, report.detected_by)
    template = _environment().get_template("report.html.j2")
    ing = report.ingredients
    substances = (ing.substances if ing else []) or []
    return template.render(
        report=report,
        page=sections.build(report, display, set_by),
        PILL=sections.PILL,
        ing=ing,
        mixture=report.mixture,
        ing_anomalies=sorted({line for s in substances
                              for line in s.get("list_anomalies") or []}),
        provenance=sorted({(v.code, v.source_detail) for v in report.statements
                           if v.source_detail}),
        caveats=labels._caveats(report),
        regulation_name=display_name_of,
        regulation_display=display,
        language_name=language_name(report.language),
        set_by=set_by,
        L=labels,
        app_css=Markup(report_css(_body_estimate(report))),
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
