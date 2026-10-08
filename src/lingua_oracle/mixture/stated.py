"""What Section 2 says the mixture is classified as.

Two renderings, and a sheet may use either. The application writes the code and
the category with no class name - "H225 Category 2" - so the class comes from
the code. Supplier sheets usually write the class out, in short form
("Aerosol 1; H222") or long ("Aspiration hazard, Category 1"). Both are read.
"""

from __future__ import annotations

import re

from lingua_oracle.detect.codes import CODE_RE
from lingua_oracle.detect.hazard_classes import is_listed_hazard_class
from lingua_oracle.mixture.classes import HazardClass, acute_classes, class_of, parse_class

#: "Skin Corr. 1B", "Aquatic Chronic 3" - a class token as Annex VI writes it.
#: Checked against the committed class list rather than against the shape:
#: "SECTION 2" is shaped like a class too.
_CLASS_TOKEN = re.compile(r"\b([A-Z][A-Za-z.]*(?:\s+[A-Za-z.]+){0,3})\s+(\d[A-Fa-f]?)\b")


def stated_classes(lines, spans) -> list[HazardClass]:
    """Every hazard class Section 2 states, however it writes it."""
    from lingua_oracle.detect.sections import section_of

    out: list[HazardClass] = []

    def remember(hazard_class: HazardClass | None) -> None:
        if hazard_class and hazard_class not in out:
            out.append(hazard_class)

    for index, line in enumerate(lines):
        if section_of(spans, index) != "2":
            continue
        text = line.text or ""
        for match in _CLASS_TOKEN.finditer(text):
            token = f"{match.group(1)} {match.group(2)}"
            if is_listed_hazard_class(token):
                remember(parse_class(token))
        for match in CODE_RE.finditer(text):
            code = match.group(0).upper().replace(" ", "")
            if code.startswith("H"):
                remember(class_of(match.group(0).strip()) or class_of(code))
                # Acute toxicity by route: the class name says the route, and
                # a code covering two categories states both.
                for hazard_class in acute_classes(code):
                    remember(hazard_class)
    return out


#: What a sheet says when its classification rests on something other than
#: the calculation: test data on the mixture, bridging, expert judgement.
_JUSTIFIED = re.compile(
    r"\b(bridging|test(?:ed)? data|tested|test results?|on the basis of (?:test|data)|"
    r"based on (?:test|data|testing)|expert judg(?:e)?ment|weight of evidence)\b",
    re.IGNORECASE)
_ABOUT_MIXTURE = re.compile(r"\b(mixture|product|preparation)\b", re.IGNORECASE)


def justifications(lines, spans) -> list[str]:
    """Lines of Section 2, or Section 11 about the mixture, citing test data,
    bridging or expert judgement - quoted, for a reader to weigh. Section 11's
    tests on single ingredients are not a reason for the mixture's
    classification and are left out."""
    from lingua_oracle.detect.sections import section_of
    from lingua_oracle.mixture.section_eleven import _lines as section_11_lines

    out: list[str] = []
    for index, line in enumerate(lines):
        text = " ".join((line.text or "").split())
        if section_of(spans, index) == "2" and _JUSTIFIED.search(text):
            out.append(text[:200])
    for text in section_11_lines(lines):
        text = " ".join(text.split())
        if _JUSTIFIED.search(text) and _ABOUT_MIXTURE.search(text):
            out.append(text[:200])
    return list(dict.fromkeys(out))
