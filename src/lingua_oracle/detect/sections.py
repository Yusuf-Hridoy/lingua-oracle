"""Locating SDS sections 2, 3 and 16, or treating a document as a label."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

import yaml

from lingua_oracle.extract.base import Document, Line
from lingua_oracle.registry import data_dir

LABEL = "label"
INTERESTING = ("2", "3", "16")
_SUBSECTION_RE = re.compile(r"^\s*\d{1,2}\.\d{1,2}(?!\d)")


@dataclass
class HeadingRules:
    language: str
    section_word: str
    sections: dict[str, list[str]]
    label_markers: list[str]


@functools.lru_cache(maxsize=32)
def load_headings(language: str) -> HeadingRules:
    tag = language.lower().split("-")[0]
    path = data_dir() / "headings" / f"{tag}.yaml"
    if not path.exists():
        path = data_dir() / "headings" / "en.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return HeadingRules(
        language=raw.get("language", tag),
        section_word=raw.get("section_word") or "SECTION",
        sections={str(k): list(v) for k, v in (raw.get("sections") or {}).items()},
        label_markers=list(raw.get("label_markers") or []),
    )


def _numbered_re(section_word: str) -> re.Pattern[str]:
    # "SECTION 2.", "2.", "PUNKT 16:", "第2項"
    return re.compile(
        rf"^\s*(?:(?:{section_word})\s*)?(\d{{1,2}})\s*[.):：]?\s*(?=\S|$)",
        re.IGNORECASE,
    )


@dataclass
class SectionSpan:
    name: str
    start: int
    end: int


def detect_sections(doc: Document, language: str) -> list[SectionSpan]:
    """Split the document's lines into named section spans.

    A document with no recognisable numbered headings is treated as a single
    "label" section, which is how label artwork is handled.
    """
    rules = load_headings(language)
    lines = doc.lines
    numbered = _numbered_re(rules.section_word)
    marks: list[tuple[int, str]] = []

    for idx, line in enumerate(lines):
        text = line.text.strip()
        if not text or len(text) > 120:
            continue
        matched: str | None = None
        # A sub-section heading is not a section heading, whatever its words:
        # "9.2. Other information" is REACH's sub-heading in Section 9, and
        # would otherwise read as Section 16.
        if _SUBSECTION_RE.match(text):
            continue
        # A short standalone line naming the label starts a label block. Label
        # artwork carries no numbered SDS headings, so without this it would be
        # swallowed by whichever section preceded it. The line has to read as a
        # heading rather than prose: real sheets contain sentences such as
        # "Labelling of Chemicals (GHS) and relevant regulations." which must
        # not be mistaken for the start of label artwork.
        if (
            len(text) <= 60
            and len(text.split()) <= 6
            and not text.rstrip().endswith((".", ",", ";", ":"))
            and not numbered.match(text)
            and any(
                re.search(rf"\b{m}\b", text, re.IGNORECASE) for m in rules.label_markers
            )
        ):
            matched = LABEL
        for name, patterns in rules.sections.items():
            if matched:
                break
            if any(re.search(p, text, re.IGNORECASE) for p in patterns):
                matched = name
                break
        if matched is None:
            m = numbered.match(text)
            if m and m.group(1) in INTERESTING:
                rest = text[m.end():].strip()
                # A bare number with no title is more likely body text than a heading.
                if rest and not rest[0].isdigit():
                    matched = m.group(1)
        if matched and (not marks or marks[-1][1] != matched):
            marks.append((idx, matched))

    if not marks:
        return [SectionSpan(name=LABEL, start=0, end=len(lines))]

    spans: list[SectionSpan] = []
    for i, (start, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(lines)
        spans.append(SectionSpan(name=name, start=start, end=end))
    return spans


def section_of(spans: list[SectionSpan], line_index: int) -> str | None:
    for span in spans:
        if span.start <= line_index < span.end:
            return span.name
    return None


def lines_in(doc: Document, spans: list[SectionSpan], name: str) -> list[Line]:
    out: list[Line] = []
    for span in spans:
        if span.name == name:
            out.extend(doc.lines[span.start : span.end])
    return out
