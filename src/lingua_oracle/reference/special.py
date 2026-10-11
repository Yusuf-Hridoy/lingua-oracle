"""The special rules, applied to one input's codes: each decision quotes its
rule from data/special_rules/<regulation>.json, and where the rule needs
data the sheet does not give the verdict is "can't confirm", with what is
missing - never a guess.

* aspiration (H304) - the share of Category 1 ingredients against the
  rule's limit, and Section 9's kinematic viscosity at the rule's
  temperature;
* extreme pH (H314, H318) - Section 9's pH at or past the rule's limits:
  corrosive "in the absence of any other information", so a sheet without
  the code is one to check (its acid/alkaline reserve may say otherwise);
* aerosols (H222, H223, H229) - every aerosol falls in one of the
  categories; which one needs test data the sheet does not carry;
* gas mixtures (H220, H221, H270) - the text points at ISO 10156, which is
  not on file;
* EUH208, EUH210 - from the composition, by Annex II and Table 3.4.6;
  EUH066, EUH071, EUH401 - what the sheet can and cannot show for them;
* Annex VI notes - a note that lets the harmonised classification fall
  ("applies unless ...") turns a Wrong from that entry into can't confirm.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CONFIRMED, WRONG, CANT, CHECK = "confirmed", "wrong", "cant", "check"
_SENS = {"H317": "skin", "H334": "respiratory"}
_AEROSOL = ("H222", "H223", "H229")
_GAS = ("H220", "H221", "H270")
_CONDITIONAL = re.compile(r"applies unless|need not apply|does not need to|need not be classified|"
                          r"not be classified as a carcinogen if|unless it can be shown",
                          re.IGNORECASE)


@dataclass
class Ingredient:
    key: str
    name: str
    low: float | None
    high: float | None
    codes: list[str] | None
    entry: object | None = None          # the list entry input B took, if any


def _cite(rule: dict) -> str:
    return f" ({rule['citation']}: “{rule['quote']}”)" if rule.get("quote") else ""


def _share(ingredients, test) -> tuple[float, float, bool]:
    """(low, high) total of the ingredients `test` picks, and whether every
    ingredient could be read."""
    low = high = 0.0
    complete = True
    for item in ingredients:
        if item.codes is None:
            complete = False
            continue
        if test(item):
            low += item.low or 0.0
            high += item.high or 0.0
    return low, high, complete


def aspiration(rules, ingredients, viscosity: dict, printed) -> dict:
    rule = rules.get("aspiration") or {}
    if rule.get("status") != "ok":
        return {"H304": (CANT, "the regulation's aspiration rule for mixtures is not on file.",
                         "")} if "H304" in printed else {}
    low, high, complete = _share(ingredients, lambda i: "H304" in (i.codes or []))
    limit, target, temp = rule["share"], rule["viscosity"], rule["temperature"]
    shown = f"Category 1 ingredients total {low:g}-{high:g} %" if low != high else \
        f"Category 1 ingredients total {high:g} %"
    if high < limit and complete:
        if "H304" in printed:
            return {"H304": (CANT, f"{shown}, below the {limit:g} % the rule sets{_cite(rule)}.",
                             "")}
        return {}
    if high < limit:
        return {"H304": (CANT, f"{shown} with data; an ingredient without data may add to it"
                               f"{_cite(rule)}.", "")} if "H304" in printed else {}
    if low < limit:
        return {"H304": (CANT, f"{shown}: the range spans the {limit:g} % limit{_cite(rule)}.",
                         "")}
    value, kind, at = viscosity.get("value"), viscosity.get("kind"), viscosity.get("temperature")
    if value is None or kind != "kinematic" or at != temp:
        why = ("Section 9 gives no viscosity" if not viscosity else
               "Section 9 gives no value for the viscosity" if value is None else
               f"Section 9 gives a {kind or 'unspecified'} viscosity ({viscosity.get('text')})"
               if kind != "kinematic" else
               f"Section 9's kinematic viscosity is not at {temp:g} °C ({viscosity.get('text')})")
        return {"H304": (CANT, f"{shown}, but {why}; the rule needs the kinematic viscosity at "
                               f"{temp:g} °C{_cite(rule)}.", "")}
    if value <= target:
        given = (f"{shown} and the kinematic viscosity is {value:g} mm²/s at {temp:g} °C: "
                 f"Category 1{_cite(rule)}.")
        return {"H304": (CONFIRMED, given, "") if "H304" in printed else
                (WRONG, f"{given} Section 2 lacks it.", "H304")}
    if "H304" in printed:
        return {"H304": (CANT, f"{shown}, but the kinematic viscosity is {value:g} mm²/s, above "
                               f"{target:g}{_cite(rule)}.", "")}
    return {}


def extreme_ph(rules, ph: dict, printed) -> dict:
    rule = rules.get("extreme_ph") or {}
    value = ph.get("value")
    if rule.get("status") != "ok" or value is None:
        return {}
    if not (value <= rule["low"] or value >= rule["high"]):
        return {}
    skin, eye = rule.get("skin", {}), rule.get("eye", {})
    said = f"Section 9 gives pH {value:g}"
    out = {}
    if "H314" in printed:
        out["H314"] = (CONFIRMED, f"{said}: corrosive in the absence of any other information"
                                  f"{_cite(skin)}.", "")
    elif skin.get("status") == "ok":
        out["H314"] = (CHECK, f"{said}, and Section 2 does not say corrosive: unless the "
                              f"acid/alkaline reserve shows otherwise{_cite(skin)}.", "H314")
    if "H314" not in printed and "H318" not in printed and eye.get("status") == "ok":
        out["H318"] = (CHECK, f"{said}, and Section 2 does not say serious eye damage: unless the "
                              f"acid/alkaline reserve shows otherwise{_cite(eye)}.", "H318")
    return out


def aerosol(rules, printed, is_aerosol: bool) -> dict:
    rule = rules.get("aerosol") or {}
    if not is_aerosol:
        return {}
    given = [c for c in _AEROSOL if c in printed]
    if rule.get("status") != "ok":
        return dict.fromkeys(given, (CANT, "the regulation's aerosol rule is not on file.", ""))
    if not given:
        key = " / ".join(_AEROSOL)
        return {key: (WRONG, f"the sheet is an aerosol, and every aerosol falls in one of the "
                             f"categories; Section 2 gives none{_cite(rule)}.", key)}
    return {c: (CANT, "the category depends on the flammable components, the heat of "
                      f"combustion and test results the sheet does not give{_cite(rule)}.", "")
            for c in given}


def gas_mixture(rules, printed, is_gas: bool, several: bool) -> dict:
    if not (is_gas and several):
        return {}
    rule = rules.get("gas_method") or {}
    return {c: (CANT, "method not on file: the text points gas mixtures at "
                      f"{rule.get('method', 'a standard')}, which is not on file{_cite(rule)}.", "")
            for c in _GAS if c in printed}


def _elicitation(item, limits: dict) -> tuple[float | None, str]:
    """Table 3.4.6's limit for a sensitiser, by its sub-category where the
    list entry gives one."""
    kinds = [k for c, k in _SENS.items() if c in (item.codes or [])]
    if not kinds:
        return None, ""
    classes = " ".join(getattr(item.entry, "hazard_classes", []) or [])
    best = None
    for kind in kinds:
        name = "Skin Sens\\." if kind == "skin" else "Resp\\. Sens\\."
        sub = ("1A" if re.search(rf"{name} 1A", classes) else
               "1B" if re.search(rf"{name} 1B", classes) else "1")
        value = limits.get(f"{kind} {sub}")
        if value is not None and (best is None or value < best[0]):
            best = (value, f"{kind} sensitiser {'Category 1' if sub == '1' else 'Sub-category ' + sub}")
    return best if best else (None, "")


def euh(rules, ingredients, printed, section_two: str, hazardous: bool) -> dict:
    held = rules.get("euh") or {}
    if not held:
        return {}
    out = {}
    text = section_two.lower()
    # EUH208 - not classified as sensitising, a sensitiser at or above Table 3.4.6's limit.
    rule = held.get("EUH208", {})
    sensitising = any(c in printed for c in _SENS)
    if rule.get("status") == "ok" and not sensitising:
        limits = rule.get("limits") or {}
        reaching = []
        for item in ingredients:
            limit, what = _elicitation(item, limits)
            if limit is not None and (item.low or 0) >= limit:
                reaching.append(f"{item.name or item.key} ({what}, {item.low:g} % ≥ {limit:g} %)")
        said = "EUH208" in printed or "may produce an allergic reaction" in text
        if reaching:
            given = f"{'; '.join(reaching)}{_cite(rule)}"
            out["EUH208"] = ((CONFIRMED, f"Table 3.4.6's limit is reached: {given}.", "")
                             if said else (WRONG, f"Table 3.4.6's limit is reached: {given}; "
                                                  "Section 2 lacks EUH208.", "EUH208"))
        elif said:
            complete = all(i.codes is not None for i in ingredients)
            out["EUH208"] = (CANT, "no ingredient " + ("" if complete else "with data ")
                                   + f"reaches Table 3.4.6's limit{_cite(rule)}.", "")
    # EUH210 - a mixture not classified as hazardous, with an ingredient Annex II 2.10 names.
    rule = held.get("EUH210", {})
    if rule.get("status") == "ok" and not hazardous:
        met = _euh210(rule, ingredients)
        if met:
            given = f"{met}{_cite(rule)}"
            out["EUH210"] = ((CONFIRMED, f"Annex II 2.10 applies: {given}.", "")
                             if "EUH210" in printed else
                             (WRONG, f"Annex II 2.10 applies: {given}; Section 2 lacks EUH210.",
                              "EUH210"))
        elif "EUH210" in printed:
            out["EUH210"] = (CANT, "no ingredient meets a condition the sheet can show (a "
                                   f"workplace exposure limit is not on the sheet){_cite(rule)}.",
                             "")
    elif rule.get("status") == "ok" and "EUH210" in printed:
        out["EUH210"] = (CANT, "Annex II 2.10 sets EUH210 for mixtures not classified as "
                               f"hazardous, and Section 2 classifies this one{_cite(rule)}.", "")
    for code, why in (("EUH066", "assigned on practical observations or evidence of skin "
                                 "dryness the sheet does not give"),
                      ("EUH401", "for plant protection products; whether this is one is not "
                                 "decided here")):
        if code in printed and held.get(code, {}).get("status") == "ok":
            out[code] = (CANT, f"{why}{_cite(held[code])}.", "")
    if "EUH071" in printed and held.get("EUH071", {}).get("status") == "ok":
        basis = [c for c in ("H330", "H331", "H332", "H314") if c in printed]
        out["EUH071"] = ((CANT, f"goes with {', '.join(basis)}, as printed; whether the data "
                                "show corrosivity is not on the sheet"
                                f"{_cite(held['EUH071'])}.", "") if basis else
                         (CHECK, "EUH071 goes with an inhalation toxicity or skin corrosion "
                                 f"classification; Section 2 gives neither{_cite(held['EUH071'])}.",
                          ""))
    return out


def _euh210(rule, ingredients) -> str:
    """The first of 2.10's conditions an ingredient meets, said."""
    for item in ingredients:
        codes = item.codes or []
        classes = " ".join(getattr(item.entry, "hazard_classes", []) or [])
        share = item.low or 0
        for condition in rule.get("conditions", []):
            limit = re.search(r"≥ ([\d,]+) ?%", condition)
            value = float(limit.group(1).replace(",", ".")) if limit else None
            if value is None or share < value:
                continue
            words = condition.lower()
            hit = (("sensitiser category 1a" in words and re.search(r"Sens\. 1A", classes)) or
                   ("sensitiser category 1, 1b" in words and any(c in codes for c in _SENS)) or
                   ("carcinogenic category 2" in words and "H351" in codes) or
                   ("toxic to reproduction" in words and any(c.startswith(("H360", "H361", "H362"))
                                                             for c in codes)) or
                   ("other health or environmental hazards" in words and any(
                       re.fullmatch(r"H3\d\d\w*|H4\d\d", c) for c in codes)))
            if hit:
                return f"{item.name or item.key} at {share:g} %: “{condition}”"
    return ""


def notes(rules, ingredients, rows: dict, families_of) -> dict:
    """A conditional Annex VI note on the entry input B took: a Wrong in a
    family the note lets fall becomes can't confirm, quoting the note."""
    held = rules.get("annex_vi_notes") or {}
    out = {}
    for item in ingredients:
        letters = list(getattr(item.entry, "notes", []) or [])
        for letter in letters:
            note = held.get(letter.strip())
            if not note or not _CONDITIONAL.search(note["quote"]):
                continue
            words = note["quote"].lower()
            touched = {f for word, f in (("carcinogen", "Carcinogenicity"),
                                         ("mutagen", "Germ cell mutagenicity"),
                                         ("reproduction", "Reproductive toxicity"))
                       if word in words}
            for code, (status, _, expected) in rows.items():
                family = families_of(code.split(" / ")[0])
                if status == WRONG and (not touched or family in touched):
                    out[code] = (CANT, f"{item.name or item.key}'s Annex VI entry carries "
                                       f"{note['citation']}: “{note['quote'][:400]}”", expected)
    return out
