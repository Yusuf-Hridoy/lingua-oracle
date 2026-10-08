"""C-16: the label elements Section 2 prints, against its classification.

Each requirement is the regulation's own (data/label_elements/<reg>.json):
the signal word, hazard statement codes and pictograms its table assigns to
each class and category, and its precedence rules.

* signal word - the strictest the classifications call for ("Danger" over
  "Warning"); wrong or missing is a fault;
* hazard statements - a classification without its code is a fault; a code
  no classification calls for is one to check;
* pictograms - judged only where the sheet names them in text ("GHS02",
  "Flame"); otherwise "not checked (pictograms are images)". One the
  classification does not call for, or a precedence rule removes, is one to
  check, quoting the rule; one missing is one to check too, since the sheet
  may show it as an image;
* a rule that lets a statement "be omitted" is shown as a note: printing the
  statement anyway breaks nothing.
"""

from __future__ import annotations

import re

from lingua_oracle.consistency.classification import Classification, table
from lingua_oracle.models import ConsistencyRow

CHECK = "C-16"
_GHS_CODE = re.compile(r"\bGHS0[1-9]\b")


def _row(key, status, text, *, rule=None, found="", expected="", section="2") -> ConsistencyRow:
    return ConsistencyRow(section=section, check=CHECK, key=key, status=status, text=text,
                          quote=(rule or {}).get("quote", ""),
                          citation=(rule or {}).get("citation", ""),
                          found=found, expected=expected)


def _source(classification: Classification) -> dict:
    sources = sorted({e.get("source", "") for e in classification.entries})
    return {"quote": "", "citation": "; ".join(s for s in sources if s)}


def signal_word(classifications, stated: list[str], held: dict) -> list[ConsistencyRow]:
    needed = {e["signal"] for c in classifications for e in c.entries if e["signal"]}
    required = "Danger" if "Danger" in needed else "Warning" if "Warning" in needed else ""
    because = [c.text for c in classifications
               if any(e["signal"] == required for e in c.entries)]
    rule = held.get("signal_rule") or {}
    says = {w for w in ("Danger", "Warning") for s in stated if s.lower() == w.lower()}
    if not required:
        return []
    source = {"quote": f"{', '.join(because[:3])}: signal word “{required}”",
              "citation": "; ".join(sorted({e.get("source", "") for c in classifications
                                           for e in c.entries if e["signal"] == required}))}
    if not says:
        return [_row("Signal word", "fix", f"No signal word found; the classification calls for "
                     f"“{required}”.", rule=source, expected=required)]
    if required not in says:
        return [_row("Signal word", "fix", f"“{', '.join(sorted(says))}” is stated; "
                     f"{because[0]} calls for “{required}”.", rule=source,
                     found=", ".join(sorted(says)), expected=required)]
    if required == "Danger" and "Warning" in says:
        return [_row("Signal word", "fix" if rule.get("binding") else "check",
                     "Both “Danger” and “Warning” are stated.", rule=rule,
                     found="Danger, Warning", expected="Danger")]
    return [_row("Signal word", "ok", f"“{required}”, as {because[0]} calls for.", rule=source)]


def statements(classifications, codes: set[str], held: dict) -> list[ConsistencyRow]:
    rows: list[ConsistencyRow] = []
    called: set[str] = set()
    for c in classifications:
        wanted = c.h_codes
        called |= wanted
        if wanted & codes:
            rows.append(_row(c.text, "ok", f"{', '.join(sorted(wanted & codes))} printed, as "
                             f"{c.text} calls for.", rule=_source(c)))
            continue
        # A statement a precedence rule lets be omitted is not missing.
        omitted = [r for r in held.get("statement_rules", [])
                   if r["drop"] in wanted and set(r["when"]) & codes]
        if omitted:
            rows.append(_row(c.text, "info", f"{', '.join(sorted(wanted))} left out where "
                             f"{omitted[0]['when'][0]} is printed, as the text allows.",
                             rule=omitted[0]["rule"]))
            continue
        rows.append(_row(c.text, "fix", f"{c.text} calls for {' or '.join(sorted(wanted))}, "
                         "which Section 2 does not print.", rule=_source(c),
                         expected=" or ".join(sorted(wanted))))
    known = {code for e in held["entries"] for code in e["h_codes"]}
    for code in sorted(codes & known - called):
        rows.append(_row(code, "check", f"{code} is printed, but no classification in "
                         "Section 2 calls for it.", found=code))
    for rule in held.get("statement_rules", []):
        if rule["drop"] in codes and set(rule["when"]) & codes:
            rows.append(_row(rule["drop"], "info", f"{rule['drop']} is printed beside "
                             f"{rule['when'][0]}; the text lets it be omitted.",
                             rule=rule["rule"]))
    return rows


def _stated_pictograms(lines: list[str], held: dict) -> set[str]:
    text = "\n".join(lines)
    if held.get("pictogram_kind") == "code":
        return set(_GHS_CODE.findall(text))
    found = set()
    for name in sorted(held.get("pictogram_names", []), key=len, reverse=True):
        # "Flame" inside "Flame over circle" is not a second pictogram.
        inside = any(name.lower() in f and name.lower() != f for f in found)
        if not inside and re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
            found.add(name.lower())
    return found


def _for(classifications, words: list[str]) -> list[Classification]:
    """The classifications a precedence rule's "where it is used for ..."
    names: "skin irritation" names the skin irritation class."""
    out = []
    for c in classifications:
        names = " ".join(f"{e['hazard_class']} {e['subclass']} {' '.join(e.get('codes', []))}"
                         for e in c.entries).lower()
        for word in words:
            parts = [w[:5] for w in re.findall(r"[a-z]+", word.lower())]
            if parts and all(p in names for p in parts):
                out.append(c)
                break
    return out


def pictograms(classifications, lines: list[str], held: dict) -> list[ConsistencyRow]:
    stated = {p.lower() for p in _stated_pictograms(lines, held)}
    if not stated:
        return [_row("Pictograms", "na", "Not checked: the sheet names no pictogram in its "
                     "text (pictograms are images).")]
    sources: dict[str, list[Classification]] = {}
    for c in classifications:
        for entry in c.entries[:1] if len({tuple(e["pictograms"]) for e in c.entries}) == 1 \
                else c.entries:
            for p in entry["pictograms"]:
                sources.setdefault(p.lower(), [])
                if c not in sources[p.lower()]:
                    sources[p.lower()].append(c)
    required = set(sources)
    optional: dict[str, dict] = {}
    removed: dict[str, dict] = {}
    for rule in held.get("pictogram_rules", []):
        when = {w.lower() for w in rule["when"]}
        drop = rule["drop"].lower()
        if not when & required or drop not in required:
            continue
        if rule.get("when_for"):
            backing = [c for w in when for c in sources.get(w, [])]
            if not _for(backing, rule["when_for"]):
                continue
        if rule["effect"] == "optional":
            optional[drop] = rule
            continue
        users = sources.get(drop, [])
        if rule["only_for"] and len(_for(users, rule["only_for"])) < len(users):
            continue                     # still needed for another class
        removed[drop] = rule
    required -= set(removed)
    rows: list[ConsistencyRow] = []
    for p in sorted(stated):
        if p in removed:
            rule = removed[p]
            rows.append(_row(f"Pictogram {p}", "check", f"{p} is shown, but "
                             f"{rule['when'][0]} applies and the text says {p} does not "
                             "appear then.", rule=rule["rule"], found=p))
        elif p in required or p in optional:
            rows.append(_row(f"Pictogram {p}", "ok", f"{p}, as "
                             f"{sources[p][0].text} calls for." if p in sources else p))
        else:
            rows.append(_row(f"Pictogram {p}", "check", f"{p} is shown, but no classification "
                             "in Section 2 calls for it.", found=p))
    for p in sorted(required - stated):
        rows.append(_row(f"Pictogram {p}", "check", f"{sources[p][0].text} calls for {p}, which "
                         "the text does not name (it may be shown as an image).",
                         rule=_source(sources[p][0]), expected=p))
    return rows


def not_adopted(lines: list[str], codes: set[str], held: dict, criteria: dict | None,
                display: str) -> list[ConsistencyRow]:
    """Classes the regulation leaves out, stated anyway: a note each."""
    rows = []
    text = " ".join(lines).lower()
    for item in held.get("not_adopted", []):
        words = [w for w in re.findall(r"[a-z]+", item["what"].lower().split("–")[0]) if len(w) > 3]
        if words and all(w[:5] in text for w in words[:2]):
            cats = item.get("categories") or []
            if cats and not any(re.search(rf"(?:category|cat\.?)\s*{c}\b|\b(?:acute|chronic)\s*{c}\b",
                                          text) for c in cats):
                continue
            rows.append(_row(item["what"], "info", f"{item['what'].capitalize()} is not part of "
                             f"{display}; this classification is outside it.", rule=item["rule"]))
    aquatic = (criteria or {}).get("aquatic", {})
    if aquatic.get("status") == "not_adopted" and held["regulation"] != "au_whs":
        stated = sorted(c for c in codes if re.match(r"H4[01]\d$", c))
        if stated:
            rows.append(_row("Aquatic hazard", "info", f"{', '.join(stated)}: hazards to the "
                             f"aquatic environment are not part of {display}; this "
                             "classification is outside it.",
                             rule={"quote": aquatic.get("why", ""),
                                   "citation": aquatic.get("citation", "")}))
    return rows


def run(lines: list[str], classifications, codes: set[str], stated_signal: list[str],
        regulation: str, display: str, criteria: dict | None) -> list[ConsistencyRow]:
    held = table(regulation)
    if held is None:
        return [_row("Label elements", "na", "Not checked (criterion not on file).")]
    rows = not_adopted(lines, codes, held, criteria, display)
    if not classifications:
        rows.append(_row("Label elements", "na", "Not checked: no classification read in "
                         "Section 2."))
        return rows
    rows += signal_word(classifications, stated_signal, held)
    rows += statements(classifications, codes, held)
    rows += pictograms(classifications, lines, held)
    return rows
