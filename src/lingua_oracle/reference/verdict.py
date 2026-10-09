"""A verdict for every hazard statement code: Section 2 against the mixture,
calculated by Lingua's own rules from two inputs.

The calculation is `mixture.section` - the regulation's own rules on file -
run twice: once on input A (the app's input) and once on input B (the best
available data); see `reference.inputs`. Each code Section 2 prints, and
each code the calculation gives that Section 2 lacks, gets one row:

* Confirmed - the calculation gives it;
* Wrong - the calculation gives something else, or Section 2 lacks it;
* Can't confirm - and why: a physical hazard, a supplemental statement, no
  data for an ingredient, Section 2 stricter than the ingredients, ...

Where A and B disagree both are said. Section 2 differing from A points at
the calculation; A differing from B points at the data.

Without concentrations: one ingredient is taken as the substance at 100 %,
and that is said; several are checked only in part. A sheet that says its
classification rests on bridging cannot be confirmed without the mixture it
was bridged from.
"""

from __future__ import annotations

import re
from dataclasses import asdict

from lingua_oracle.mixture import families
from lingua_oracle.mixture.classes import ACUTE_CODES, CODE_TO_CLASS, acute_classes
from lingua_oracle.models import HCodeSection
from lingua_oracle.reference import inputs as ref

_BY_CODE = {code.casefold(): hazard_class for code, hazard_class in CODE_TO_CLASS.items()}
_ROUTE = {"oral": "oral", "dermal": "dermal", "inhalation": "inhalation"}
CONFIRMED, WRONG, CANT, CHECK = "confirmed", "wrong", "cant", "check"
_BRIDGING = re.compile(r"\bbridging\b", re.IGNORECASE)


def family_of_code(code: str) -> str | None:
    acute = acute_classes(code)
    if acute:
        return families.family_of(acute[0])
    hazard_class = _BY_CODE.get(code.casefold()) or _BY_CODE.get(code[:4].casefold())
    return families.family_of(hazard_class) if hazard_class else None


def codes_of(class_text: str) -> list[str]:
    """The codes a calculated class is printed with: "Skin Irrit. 2" -> H315."""
    text = (class_text or "").strip()
    route = re.search(r"\((oral|dermal|inhalation)\)", text)
    category = re.search(r"(\d)[A-C]?\s*$", text)
    if route and category:
        return [c for c, (r, cats) in ACUTE_CODES.items()
                if r == route.group(1) and category.group(1) in cats]
    if not category:
        return []
    name = text[:category.start()].strip()
    return [code for code, hc in CODE_TO_CLASS.items()
            if hc.name == name and (hc.category or "")[:1] == category.group(1)]


def _why_not_calculated(code: str) -> str:
    if code.startswith(("EUH", "AUH")):
        return "a supplemental statement, assigned by its own criterion - not calculated from the ingredients"
    if re.match(r"H2\d\d", code):
        return ("a physical hazard, decided by the product's own properties (Section 9) - not "
                "calculated from the ingredients")
    return "a hazard this tool does not calculate from the ingredients"


def _rows_for(section, printed: list[str], complete: bool, missing: list[str],
              carried: set[str] | None = None) -> dict:
    """{code: (status, reason, expected)} for one calculation. `carried`:
    the codes the input's ingredients carry - which of a class's codes the
    calculation's class is (STOT SE 3 is H335 or H336)."""
    carried = carried or set()

    def own(codes: list[str]) -> list[str]:
        return [c for c in codes if c.casefold() in carried] or codes

    out: dict[str, tuple[str, str, str]] = {}
    results = section.results if section is not None else []
    by_family = {(r.get("family") or str(r.get("hazard_class"))): r for r in results}
    gap = f" No data for {', '.join(missing)}." if missing else ""
    undisclosed = section.undisclosed if section is not None else "0"
    if undisclosed not in ("0", "", None) and float(undisclosed) > 0:
        gap += f" The undisclosed {undisclosed} % may carry it."
    for code in printed:
        family = family_of_code(code)
        if family is None:
            out[code] = (CANT, _why_not_calculated(code), "")
            continue
        result = by_family.get(family)
        if result is None:
            out[code] = (CANT, "none of the ingredients, at these concentrations, gives this "
                               "hazard." + gap, "")
            continue
        calculated = result.get("calculated_class") or ""
        expected = " / ".join(own(codes_of(calculated)))
        verdict = result["verdict"]
        if calculated and code.casefold() in {c.casefold() for c in own(codes_of(calculated))}:
            # The code is the calculated class's own ("H361D" for Repr. 2),
            # whatever the class reader made of Section 2.
            out[code] = (CONFIRMED, f"the ingredients give {calculated}.", "")
        elif verdict == "consistent":
            if not calculated:
                out[code] = (CONFIRMED, "the ingredients give it.", "")
            else:
                # The family agrees, the effect does not: STOT SE 3 from H336
                # (narcotic effects) does not support H335 (respiratory).
                out[code] = (CANT, f"the ingredients give {calculated} as {expected}, not as "
                                   f"{code}." + gap, expected)
        elif verdict == "inconsistent":
            out[code] = (WRONG, f"the ingredients give {calculated or 'no classification'}"
                                + (f" ({expected})" if expected else "") + ".", expected)
        else:
            out[code] = (CANT, (result.get("message") or "the calculation cannot decide it.")
                         + (gap if verdict == "cannot_tell" else ""), expected)
    # What the calculation gives that Section 2 does not print at all.
    for result in results:
        if result.get("stated") or result["verdict"] != "inconsistent":
            continue
        codes = own(codes_of(result.get("calculated_class") or ""))
        if codes and not {c.casefold() for c in codes_of(result.get("calculated_class") or "")
                          } & {p.casefold() for p in printed}:
            key = " / ".join(codes)
            out.setdefault(key, (WRONG, f"the ingredients give {result['calculated_class']}; "
                                        "Section 2 lacks it.", key))
    return out


def _partial(printed: list[str], per_ingredient: list[list[str] | None]) -> dict:
    """No concentrations: what can be said from which codes the ingredients carry."""
    carried = [c for codes in per_ingredient if codes for c in codes]
    known = {family_of_code(c) or c.casefold() for c in carried}
    out: dict[str, tuple[str, str, str]] = {}
    for code in printed:
        family = family_of_code(code)
        if family is None and (code.startswith(("EUH", "AUH")) or re.match(r"H2\d\d", code)):
            out[code] = (CANT, _why_not_calculated(code), "")
        elif (family or code.casefold()) not in known:
            out[code] = (CHECK, "no listed ingredient carries this hazard.", "")
        else:
            out[code] = (CANT, "an ingredient carries it, but Section 3 gives no "
                               "concentrations, so it can't be fully confirmed.", "")
    printed_families = {family_of_code(c) or c.casefold() for c in printed}
    for code in dict.fromkeys(carried):
        family = family_of_code(code)
        if family is not None and family not in printed_families:
            out.setdefault(code, (CHECK, f"an ingredient carries {code}; Section 2 has nothing "
                                         "for this hazard.", code))
    return out


def _calculate(rows, codes_by_cas, document, spans, regulation, table, *, use_list,
               stated: list[str] | None = None):
    from lingua_oracle.mixture import section as mixture_section

    data = [{**row, "h_codes": codes_by_cas.get(row["cas"]) or []} for row in rows]
    return mixture_section.build(data, document.lines, spans, regulation, table,
                                 stated_override=stated or None, use_list=use_list)


def _stated(document, spans, codes: list[str]) -> list[str]:
    """Section 2's classes: as the mixture's own reader reads them, and as
    each code printed - or each class stated in words - stands for."""
    from lingua_oracle.mixture.classes import class_of
    from lingua_oracle.mixture.stated import stated_classes

    out = [str(c) for c in stated_classes(document.lines, spans)]
    for code in codes:
        for hazard_class in acute_classes(code) or [class_of(code) or class_of(code[:4])]:
            if hazard_class is not None and str(hazard_class) not in out:
                out.append(str(hazard_class))
    return out


def build(document, spans, regulation: str, rows: list[dict], section_two: list[str],
          *, app_codes: dict[str, list[str]] | None = None, sheet_text: str = "",
          stated_as: dict[str, str] | None = None) -> HCodeSection:
    """`rows`: the composition (cas, name, concentration); `app_codes`: the
    app's stored codes by CAS where the product is one the app holds;
    `stated_as`: codes for the classes Section 2 states in words, with the
    words ("Reproductive Toxicity: Category 2" - an OSHA sheet prints no
    codes)."""
    from lingua_oracle.substances.load import for_check

    printed = ref.codes_in(" ".join(section_two))
    worded = {c: t for c, t in (stated_as or {}).items()
              if c.casefold() not in {p.casefold() for p in printed}}
    printed = printed + list(worded)
    rows = [r for r in rows if r.get("cas")]
    if not rows:
        return HCodeSection(state="nothing", printed=printed,
                            message="No ingredient with a CAS number to calculate from.")
    assumptions: list[str] = []
    with_share = [r for r in rows if r.get("concentration")]
    if not with_share and len(rows) == 1:
        rows = [{**rows[0], "concentration": "100"}]
        assumptions.append("One ingredient and no concentration: taken as the substance, at "
                           "100 %.")
    use, table = for_check(regulation)
    a = {r["cas"]: ref.input_a(r["cas"], (app_codes or {}).get(r["cas"]) if app_codes else None)
         for r in rows}
    b = {r["cas"]: ref.input_b(r["cas"], regulation) for r in rows}
    ingredients = [{"cas": r["cas"], "name": r.get("name") or "",
                    "concentration": r.get("concentration") or "",
                    "a": asdict(a[r["cas"]]), "b": asdict(b[r["cas"]])} for r in rows]
    notes = [n for r in rows for n in ref.likely_causes(r["cas"], a[r["cas"]], b[r["cas"]])]

    a_open = [cas for cas, x in a.items() if x.codes is None and x.reproducible]
    a_blocked = [cas for cas, x in a.items() if not x.reproducible]
    b_open = [cas for cas, x in b.items() if x.codes is None]
    runs: dict[str, dict] = {}
    bridged = bool(_BRIDGING.search(sheet_text))
    partial = not any(r.get("concentration") for r in rows)

    stated = _stated(document, spans, printed)

    def judged(chosen, open_cas, use_list):
        codes = {cas: x.codes for cas, x in chosen.items()}
        if partial:
            return _partial(printed, list(codes.values()))
        section = _calculate(rows, codes, document, spans, regulation, table, use_list=use_list,
                             stated=stated)
        carried = {c.casefold() for x in codes.values() for c in (x or [])}
        if use_list:
            carried |= {c.casefold() for x in chosen.values() for c in (x.codes or [])}
        return _rows_for(section, printed, not open_cas, open_cas, carried)

    if a_blocked:
        runs["A"] = {"available": False,
                     "why": "not reproducible: the app uses an AI selection for "
                            + ", ".join(a_blocked)}
        fallback = {cas: (x if x.reproducible else ref.Input(x.fallback, ref.FALLBACK_LABEL))
                    for cas, x in a.items()}
        runs["A5"] = {"available": True, "label": ref.FALLBACK_LABEL,
                      "rows": judged(fallback, a_open, False)}
    else:
        runs["A"] = {"available": True, "rows": judged(a, a_open, False)}
    binding_b = all(x.binding for x in b.values())
    runs["B"] = {"available": True, "rows": judged(b, b_open, True), "binding": binding_b}

    primary = runs["B"]["rows"]
    keys = list(dict.fromkeys([*primary, *(runs["A"].get("rows") or {})]))
    out_rows = []
    for key in keys:
        b_row = primary.get(key) or (CONFIRMED, "this input does not give it; Section 2 "
                                                 "rightly omits it.", "")
        a_row = (runs["A"].get("rows") or {}).get(key) if runs["A"]["available"] else None
        status, reason, expected = b_row
        if bridged and status in (CONFIRMED, WRONG, CHECK):
            status, reason = CANT, "needs the reference mixture: the sheet says its " \
                                   "classification rests on bridging."
        row = {"code": key, "printed": key in printed, "stated_as": worded.get(key, ""),
               "status": status, "reason": reason,
               "expected": expected, "binding": binding_b,
               "b": {"status": b_row[0], "reason": b_row[1]},
               "a": ({"status": a_row[0], "reason": a_row[1]} if a_row else
                     {"status": "", "reason": runs["A"].get("why", "")})}
        if "A5" in runs:
            a5 = runs["A5"]["rows"].get(key)
            if a5:
                row["a5"] = {"status": a5[0], "reason": a5[1]}
        if a_row and a_row[0] != b_row[0]:
            row["differs"] = (f"With ExactSDS's own input: {_word(a_row[0])} - {a_row[1]} "
                              f"With the binding/most common data: {_word(b_row[0])} - "
                              f"{b_row[1]}")
            causes = []
            if a_row[0] == WRONG:
                causes.append("Section 2 differs from what the app's own input gives: likely a "
                              "calculation issue.")
            causes.append("The app's input differs from the binding/most common data: likely a "
                          "data issue.")
            row["likely"] = causes
        elif a_row and a_row[0] == b_row[0] == WRONG:
            row["likely"] = ["Section 2 differs from what the app's own input gives: likely a "
                             "calculation issue."]
        out_rows.append(row)
    order = {WRONG: 0, CHECK: 1, CANT: 2, CONFIRMED: 3}
    out_rows.sort(key=lambda r: (order.get(r["status"], 9), r["code"]))
    if partial:
        assumptions.append("Section 3 gives no concentrations: only a partial check - the codes "
                           "can't be fully confirmed.")
    if bridged:
        assumptions.append("The sheet says its classification rests on bridging.")
    counts = {s: sum(1 for r in out_rows if r["status"] == s)
              for s in (CONFIRMED, WRONG, CHECK, CANT)}
    message = ("" if out_rows else "Section 2 prints no hazard statement, and the ingredients "
               "give none.")
    return HCodeSection(state="judged", message=message, printed=printed, rows=out_rows,
                        ingredients=ingredients, notes=list(dict.fromkeys(notes)),
                        assumptions=assumptions, counts=counts,
                        runs={k: {kk: vv for kk, vv in v.items() if kk != "rows"}
                              for k, v in runs.items()})


def _word(status: str) -> str:
    return {CONFIRMED: "Confirmed", WRONG: "Wrong", CANT: "Can't confirm",
            CHECK: "Check this"}.get(status, status)
