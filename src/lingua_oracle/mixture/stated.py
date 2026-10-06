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
from lingua_oracle.mixture.classes import HazardClass, class_of, parse_class

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
    return out
