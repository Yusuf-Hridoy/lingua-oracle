"""A substance's Section 2, against the list entry for its CAS number.

A substance is classified as its harmonised entry says, so there is nothing to
calculate: each class and each hazard statement code Section 2 states is held
against the entry for the CAS number Section 3 (or Section 1) gives. The codes
are judged by exactly the rules an ingredient is - `check_ingredient_on`, the
23rd ATP's dates included - and the classes class by class:

* a class the entry gives, stated in the same category - correct;
* stated in a weaker category than a minimum classification ("*") allows, or
  in a different category of a class with no "*" - a fault;
* not stated at all, where Section 2 writes its classes out - a fault;
* a class the entry does not cover - ordinary, and said as information.

Which list, and whether a difference is a fault or only worth knowing, is the
regulation's own answer (`substances.lists`), as for ingredients.
"""

from __future__ import annotations

import re

from lingua_oracle.detect.codes import CODE_RE
from lingua_oracle.detect.hazard_classes import is_listed_hazard_class
from lingua_oracle.ingredients.compare import (
    Reason,
    Status,
    check_ingredient_on,
    compare_categories,
    entries_for,
    parse_class,
)
from lingua_oracle.keys.builders.annex_vi import base_code
from lingua_oracle.models import SubstanceSection

_CLASS_TOKEN = re.compile(r"\b([A-Z][A-Za-z.]*(?:\s+[A-Za-z.]+){0,3})\s+(\d[A-Fa-f]?)\b")
CAS_RE = re.compile(r"(?<![\d-])(\d{2,7}-\d{2}-\d)(?![\d-])")


def explicit_classes(lines, spans) -> list[str]:
    """The classes Section 2 writes out by name - "Flam. Liq. 2" - in order.

    Only the written-out ones: a class inferred from a code says nothing about
    whether the sheet stated the class.
    """
    from lingua_oracle.detect.sections import section_of

    out: list[str] = []
    for index, line in enumerate(lines):
        if section_of(spans, index) != "2":
            continue
        for match in _CLASS_TOKEN.finditer(line.text or ""):
            token = f"{match.group(1)} {match.group(2)}"
            if is_listed_hazard_class(token) and token not in out:
                out.append(token)
    return out


def section_two_codes(lines, spans) -> list[str]:
    """Every H and EUH code Section 2 prints, in order, once each."""
    from lingua_oracle.detect.sections import section_of

    out: list[str] = []
    for index, line in enumerate(lines):
        if section_of(spans, index) != "2":
            continue
        for match in CODE_RE.finditer(line.text or ""):
            code = match.group(0).replace(" ", "")
            if code.upper().startswith(("H", "EUH")) and "+" not in code \
                    and code not in out:
                out.append(code)
    return out


def cas_before_section_two(lines, spans) -> str:
    """A CAS number Section 1 prints beside the word CAS, or ""."""
    first = min((s.start for s in spans if s.name == "2"), default=len(lines))
    for line in lines[:first]:
        text = line.text or ""
        if "cas" in text.lower():
            found = CAS_RE.search(text)
            if found:
                return found.group(1)
    return ""


def _class_rows(stated: list[str], official: list[str]) -> list[dict]:
    rows: list[dict] = []
    stated_parsed = [parse_class(s) for s in stated]
    used: set[int] = set()
    for raw in official:
        want = parse_class(raw)
        same = [i for i, s in enumerate(stated_parsed)
                if s.name.casefold() == want.name.casefold()]
        if not same:
            rows.append({"stated": "", "official": raw.strip(),
                         "result": "fix" if stated else "na",
                         "note": (f"Section 2 does not state {raw.strip()}."
                                  if stated else
                                  "Section 2 writes no classes out; judged by "
                                  "its codes below.")})
            continue
        best = min(same, key=lambda i: stated_parsed[i].rank)
        used.add(best)
        verdict = compare_categories(stated[best], raw)
        if verdict == "equal":
            rows.append({"stated": stated[best], "official": raw.strip(),
                         "result": "ok", "note": "Matches the entry."})
        elif verdict == "stricter" and want.minimum:
            rows.append({"stated": stated[best], "official": raw.strip(),
                         "result": "ok",
                         "note": "Stricter than the minimum classification, "
                                 "which is allowed."})
        else:
            rows.append({"stated": stated[best], "official": raw.strip(),
                         "result": "fix",
                         "note": f"The entry gives {raw.strip()}."})
    for i, raw in enumerate(stated):
        if i not in used and not any(
                parse_class(o).name.casefold() == stated_parsed[i].name.casefold()
                for o in official):
            rows.append({"stated": raw, "official": "", "result": "info",
                         "note": "The entry does not cover this class, which is "
                                 "ordinary: a supplier classifies for the hazards "
                                 "it leaves to them."})
    return rows


def check(cas: str, *, regulation: str, sheet_codes: list[str],
          stated_classes: list[str], name: str = "", concentration: str = "",
          on=None) -> SubstanceSection:
    """The substance section for one sheet."""
    from lingua_oracle.substances.load import for_check
    from lingua_oracle.substances.upcoming import for_list

    section = SubstanceSection(cas=cas, name=name, concentration=concentration,
                               sheet_codes=list(sheet_codes))
    use, table = for_check(regulation)
    if use is None or table is None:
        section.state, section.message = "no_list", (
            "No list of classified substances is on file for this regulation, "
            "so the substance was not checked against one.")
        return section
    section.list_name, section.list_title = use.name, use.title
    section.list_binding, section.list_authority = use.binding, use.authority
    if not cas:
        section.state, section.message = "no_cas", (
            "No CAS number in Section 3 or Section 1, so no entry can be "
            "looked up.")
        return section

    verdict = check_ingredient_on(cas, list(sheet_codes), table,
                                  upcoming=for_list(use.name), on=on)
    if verdict.status is Status.NOT_CHECKED:
        section.state = {Reason.NO_ENTRY: "no_entry",
                         Reason.SEVERAL_ENTRIES: "several_entries",
                         Reason.GROUP_ENTRY: "group_entry"}.get(
                             verdict.reason, "no_entry")
        section.message = verdict.findings[0].message if verdict.findings else ""
        section.upcoming = list(verdict.upcoming)
        return section

    # The entry the verdict was reached on: the table in force, or the
    # amended one where the amendment decided it.
    upcoming = for_list(use.name)
    tables = [table] + ([upcoming.table] if upcoming else [])
    entry = next(e for t in reversed(tables) for e in entries_for(cas, t)
                 if e.index_no == verdict.entry_index_no
                 and e.source_ref == verdict.source_ref)
    section.official_name = entry.name
    section.entry_index_no = entry.index_no
    section.source_ref = verdict.source_ref
    section.official_codes = list(verdict.required_codes)
    section.upcoming = list(verdict.upcoming)
    section.classes = _class_rows(stated_classes, entry.hazard_classes)

    missing = set(verdict.missing_codes)
    for code in verdict.required_codes:
        section.codes.append(
            {"code": code, "result": "fix" if code in missing else "ok",
             "note": (f"The entry requires {code}; Section 2 does not carry it."
                      if code in missing else "Required by the entry, and stated.")})
    required = {base_code(c.upper()) for c in verdict.required_codes}
    for code in sheet_codes:
        if base_code(code.upper()) not in required:
            section.codes.append(
                {"code": code, "result": "info",
                 "note": "Not in the entry - the supplier's own classification."})

    faults = any(r["result"] == "fix" for r in (*section.classes, *section.codes))
    section.status = (("fix" if use.binding else "check") if faults else "ok")
    return section
