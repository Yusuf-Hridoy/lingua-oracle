"""Contradictions inside a published list's own entry.

A list is a reference, and a reference with two answers in it is still the
reference - the tool's job is to say so, not to pick one. HCIS's entry for
toluene carries H360 and H361d together: "may damage the unborn child" and
"suspected of damaging the unborn child", which are category 1 and category 2
of the same class. Its own class column says Repr. 1A. Both codes are in the
export; this is not a reading error, and the report says where it came from.

Only classes a substance can hold once are checked. Acute toxicity and target
organ toxicity carry a category per route and per organ, so two categories
there are ordinary and are not reported.
"""

from __future__ import annotations

from lingua_oracle.mixture.classes import class_of

#: Classes where one substance has one category. A second is a contradiction
#: rather than a second route.
SINGLE_CATEGORY = (
    "Skin Corr.", "Skin Irrit.", "Eye Dam.", "Eye Irrit.",
    "Resp. Sens.", "Skin Sens.", "Muta.", "Carc.", "Repr.", "Lact.",
    "Aquatic Acute", "Aquatic Chronic",
)


def contradictions(entry) -> list[str]:
    """Where one entry's codes put the same class in two categories."""
    by_class: dict[str, dict[str, list[str]]] = {}
    for code in entry.h_codes:
        hazard = class_of(code)
        if hazard is None or hazard.name not in SINGLE_CATEGORY:
            continue
        by_class.setdefault(hazard.name, {}).setdefault(str(hazard), []).append(code)
    out = []
    for name, categories in sorted(by_class.items()):
        if len(categories) < 2:
            continue
        said = "; ".join(
            f"{category} ({', '.join(sorted(codes))})"
            for category, codes in sorted(categories.items()))
        out.append(f"{name} appears twice: {said}")
    return out


def describe(entry) -> list[str]:
    """Every anomaly worth printing for one entry, with where it came from."""
    found = contradictions(entry)
    if not found:
        return []
    where = entry.source_ref or "the list"
    return [f"{line} - as published in {where}" for line in found]
