"""C-22: substances of very high concern - Sections 3, 2 and 15 (EU).

An ingredient on the ECHA Candidate List (data/lists/svhc_candidate.json)
at 0,1 % or more is held against what REACH Annex II requires of it, each
requirement quoted from the consolidated act (data from the CELLAR text):

* Section 3 must name it: 3.2.1(c) for a classified mixture and 3.2.2(b)
  for one that is not, for substances listed "for reasons other than the
  hazards referred to in point (a)"; a substance listed for a hazard of
  point (a) (carcinogenic, mutagenic, toxic for reproduction) is named under
  3.2.1(a), whose cut-off for those categories is the same 0,1 %. "shall be
  indicated" - a fault where it is not.
* Section 2 must say so where it is listed for endocrine disrupting
  properties: 2.3, "shall be provided" - a fault where it does not.
* Section 15 - 15.1 asks for "relevant Union safety, health and
  environmental provisions" and names no list; one to check where Section
  15 does not mention it.

GB: no GB Candidate List is on file - "not checked". Other regulations: the
Candidate List is REACH's, and is not theirs.
"""

from __future__ import annotations

import re

from lingua_oracle.keys.builders import lists
from lingua_oracle.models import ConsistencyRow

CHECK = "C-22"


def _hazard_reason(reason: str) -> bool:
    """Listed for a hazard of 3.2.1(a): carcinogenic, mutagenic, toxic for
    reproduction (Article 57(a)-(c))."""
    return bool(re.search(r"Article 57\s*\(?[abc]\)?|carcinogenic|mutagenic|toxic for "
                          r"reproduction", reason, re.IGNORECASE)) and "57(f)" not in reason


def run(regulation: str, section_3: list[str], section_2: list[str], section_15: list[str],
        ingredients: list[tuple[str, str, object]]) -> list[ConsistencyRow]:
    """`ingredients` are (CAS, name, highest share in %) from Section 3."""
    if regulation == "uk_clp":
        return [ConsistencyRow(section="15", check=CHECK, key="Candidate List",
                               status="na", text="Not checked (list not on file): no GB "
                                                 "Candidate List is on file.")]
    if regulation != "eu_clp":
        return []
    held = lists.load("svhc_candidate")
    if held is None or held.get("status") != "ok":
        return [ConsistencyRow(section="15", check=CHECK, key="Candidate List", status="na",
                               text="Not checked (list not on file).")]
    by_cas = {c: e for e in held["entries"] for c in e["cas"]}
    rules = held.get("annex_ii", {})
    listed = f"ECHA Candidate List, {held.get('version', '')}"
    rows: list[ConsistencyRow] = []
    two, three, fifteen = (" ".join(x).lower() for x in (section_2, section_3, section_15))
    for cas, _name, share in ingredients:
        entry = by_cas.get(cas)
        if entry is None or share is None or share < 0.1:
            continue
        who = f"{entry['name']} ({cas})"
        rule3 = rules.get("3.2.1(a)" if _hazard_reason(entry["reason"]) else "3.2.1(c)", {})
        if cas in three or (entry["name"].lower() in three):
            rows.append(ConsistencyRow(section="3", check=CHECK, key=who, status="ok",
                                       text=f"On the Candidate List ({entry['reason']}; "
                                            f"{entry['date']}); named in Section 3.",
                                       citation=listed))
        else:
            rows.append(ConsistencyRow(section="3", check=CHECK, key=who, status="fix",
                                       text=f"On the Candidate List at {share} %, but Section 3 "
                                            "does not name it.", quote=rule3.get("quote", ""),
                                       citation=rule3.get("citation", listed)))
        if "endocrine" in entry["reason"].lower():
            said = ("endocrine" in two) and (cas in two or "candidate list" in two
                                             or "article 59" in two or entry["name"].lower() in two)
            rule = rules.get("2.3", {})
            rows.append(ConsistencyRow(section="2", check=CHECK, key=f"{who} - 2.3",
                                       status="ok" if said else "fix",
                                       text=("Section 2 says it is on the Candidate List for "
                                             "endocrine disrupting properties." if said else
                                             "Listed for endocrine disrupting properties; "
                                             "Section 2.3 does not say so."),
                                       quote="" if said else rule.get("quote", ""),
                                       citation=rule.get("citation", listed)))
        mentioned = cas in fifteen or entry["name"].lower() in fifteen or bool(
            re.search(r"candidate list|svhc|very high concern|article 59", fifteen))
        rule = rules.get("15.1", {})
        rows.append(ConsistencyRow(section="15", check=CHECK, key=who,
                                   status="ok" if mentioned else "check",
                                   text=("Section 15 mentions it." if mentioned else
                                         "On the Candidate List; Section 15 does not mention it."),
                                   quote="" if mentioned else rule.get("quote", ""),
                                   citation=rule.get("citation", listed)))
    return rows
