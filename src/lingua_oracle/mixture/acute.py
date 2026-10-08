"""Acute toxicity of a mixture, by additivity, per route and per regulation.

    100 / ATEmix = sum over relevant ingredients of Ci / ATEi

with Ci the concentration and ATEi the ingredient's acute toxicity estimate
(CLP Annex I 3.1.3.6.1 and its equivalents; the regulation's own paragraph is
cited from `data/acute_toxicity/`). Each ingredient's ATEi is taken, in order:

1. from its list entry, where the entry prints an ATE for the route;
2. from Section 11, where the sheet prints an LD50/LC50/ATE for it;
3. from its category, converted with the regulation's own table (3.1.2) -
   the category from the list entry where it gives one, else from the H code.
   H300, H310 and H330 each cover two categories; both are converted, and a
   verdict that depends on which is reported as one to check.

An ingredient below the regulation's relevance threshold (1 %) is left out,
as is one whose ATEi lies beyond the categories the regulation counts - and
one with no acute data at all, since a sheet that gives an ingredient no acute
classification is not saying its toxicity is unknown. Where a sheet does say
so ("x % of the mixture consists of ingredient(s) of unknown acute toxicity",
which the regulations require it to), and x exceeds the regulation's
threshold, the sum is corrected for it: (100 - x) / ATEmix = sum(Ci / ATEi).

Both ends of every range are evaluated, and inhalation is calculated for the
form the mixture is in (gas, vapour, dust or mist) - both vapour and dust/mist
where Section 9 does not say whether it is a liquid or a solid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from lingua_oracle.mixture.acute_table import AcuteRules, _n
from lingua_oracle.mixture.classes import ACUTE_CODES, HazardClass

ROUTES = ("oral", "dermal", "inhalation")
FAMILY = {"oral": "Acute toxicity, oral", "dermal": "Acute toxicity, dermal",
          "inhalation": "Acute toxicity, inhalation"}
CLASS_NAME = {"oral": "Acute Tox. (oral)", "dermal": "Acute Tox. (dermal)",
              "inhalation": "Acute Tox. (inhalation)"}
UNIT = {"oral": "mg/kg", "dermal": "mg/kg", "gases": "ppmV", "vapours": "mg/l",
        "dusts_mists": "mg/l"}
FORM_WORD = {"gases": "gas", "vapours": "vapour", "dusts_mists": "dust/mist"}


def forms(route: str, state: str | None) -> tuple[str, ...]:
    """The table rows a route is read from, for the mixture's physical state."""
    if route != "inhalation":
        return (route,)
    return {"gas": ("gases",), "liquid": ("vapours",), "solid": ("dusts_mists",)
            }.get(state or "", ("vapours", "dusts_mists"))


@dataclass(frozen=True)
class Reading:
    """One ATE an ingredient was given for one route, and where it came from."""

    value: Decimal
    source: str          # words for the trace: "list entry", "Section 11", ...
    category: str = ""   # the category it was converted from, if it was


@dataclass
class Section11Ate:
    route: str           # oral / dermal / inhalation
    form: str | None     # gases / vapours / dusts_mists for inhalation
    value: Decimal
    raw: str


def _list_ate(ingredient, form: str) -> Reading | None:
    limits = ingredient.limits
    for ate in (limits.ates if limits else []):
        route = "inhalation" if ate.route == "inhalation" else ate.route
        if route != ("inhalation" if form in FORM_WORD else form):
            continue
        if form in FORM_WORD:
            stated = _form_of(ate.source, ate.unit)
            if stated not in (form, None):
                continue
        return Reading(ate.value, f"list entry: “{ate.source}”")
    return None


def _form_of(text: str, unit: str = "") -> str | None:
    lowered = text.lower()
    if "dust" in lowered or "mist" in lowered:
        return "dusts_mists"
    if "vapour" in lowered or "vapor" in lowered:
        return "vapours"
    if "gas" in lowered or unit.lower().startswith("ppm"):
        return "gases"
    return None


def categories(ingredient, route: str, entry=None) -> tuple[str, ...]:
    """The acute category (or categories) an ingredient is classified in."""
    codes = [c.upper() for c in ingredient.h_codes]
    acute_codes = [c for c in codes if c in ACUTE_CODES]
    if entry is not None:
        # The entry lists its classes and codes in the same order: pair them.
        classes = [c for c in entry.hazard_classes if c.startswith("Acute Tox")]
        entry_codes = [c.upper() for c in entry.h_codes if c.upper() in ACUTE_CODES]
        if len(classes) == len(entry_codes):
            for raw, code in zip(classes, entry_codes, strict=True):
                if ACUTE_CODES[code][0] == route:
                    digits = re.search(r"\d", raw)
                    if digits:
                        return (digits.group(0),)
    found: list[str] = []
    for code in acute_codes:
        code_route, cats = ACUTE_CODES[code]
        if code_route == route:
            found += [c for c in cats if c not in found]
    return tuple(found)


def readings(ingredient, route: str, form: str, rules: AcuteRules, *,
             entry=None, section_11: list[Section11Ate] | None = None
             ) -> list[Reading]:
    """Every ATE this ingredient could carry for one route: one, or two where
    an H code covers two categories. Empty where it has no acute data."""
    listed = _list_ate(ingredient, form)
    if listed:
        return [listed]
    for found in section_11 or []:
        if found.route == route and (route != "inhalation" or found.form in (form, None)):
            return [Reading(found.value, f"Section 11: “{found.raw[:90]}”")]
    out = []
    for category in categories(ingredient, route, entry):
        point = rules.conversion.get(form, {}).get(category)
        if point is not None:
            out.append(Reading(point, f"converted from Category {category} "
                                      f"({rules.citations['conversion']})", category))
    return out


@dataclass
class RouteRun:
    end: str
    form: str
    variant: int
    ate_mix: Decimal | None
    category: str | None
    trace: list[str] = field(default_factory=list)


def _fmt(value: Decimal) -> str:
    if value >= 100:
        return _n(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return _n(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _run(inputs, route, form, end, choice, rules, unknown) -> RouteRun:
    terms, used = [], []
    for item in inputs:
        options = item["readings"].get(form) or []
        if not options:
            continue
        reading = options[min(choice, len(options) - 1)]
        share = item["ingredient"].low if end == "low" else item["ingredient"].high
        if share < rules.relevance:
            continue
        if reading.value > rules.ingredient_limit.get(form, reading.value):
            continue
        terms.append(share / reading.value)
        used.append(f"{_n(share)} / {_n(reading.value)} ({item['ingredient'].label}, "
                    f"{reading.source})")
    total = sum(terms, Decimal(0))
    unit = UNIT[form]
    where = f"{end} end" + (f", {FORM_WORD[form]}" if form in FORM_WORD else "")
    if not terms:
        return RouteRun(end, form, choice, None, None,
                        [f"{where}: no relevant ingredient has an acute toxicity "
                         f"estimate for this route"])
    numerator = Decimal(100)
    correction = ""
    if unknown is not None and unknown > rules.unknown_threshold:
        numerator -= unknown
        correction = (f" corrected for {_n(unknown)} % of unknown acute toxicity "
                      f"({rules.citations['unknown']})")
    ate_mix = numerator / total
    category = rules.category(form, ate_mix)
    verdict = (f"Category {category} ({rules.band_text(form, category)}, "
               f"{rules.citations['bands']})" if category
               else "beyond every category: not classified")
    trace = [f"{where}: {_n(numerator)} / ATEmix = " + " + ".join(used)
             + f" = {_fmt(total)}{correction}",
             f"{where}: ATEmix = {_fmt(ate_mix)} {unit} → {verdict}"]
    return RouteRun(end, form, choice, ate_mix, category, trace)


def calculate(ingredients, rules: AcuteRules, state: str | None, *,
              entries: dict | None = None,
              section_11: dict[str, list[Section11Ate]] | None = None,
              unknown: dict[str, Decimal] | None = None) -> dict[str, dict]:
    """Per route: every run, the categories they gave, and what entered them.

    `entries` maps a CAS number to its list entry, `section_11` to the ATEs
    Section 11 prints for it, and `unknown` a route (or "" for all routes) to
    the share of unknown acute toxicity the sheet states.
    """
    entries, section_11, unknown = entries or {}, section_11 or {}, unknown or {}
    out: dict[str, dict] = {}
    for route in ROUTES:
        route_forms = forms(route, state)
        inputs = []
        for ingredient in ingredients:
            cas = (ingredient.cas or "").strip()
            found = {form: readings(ingredient, route, form, rules,
                                    entry=entries.get(cas),
                                    section_11=section_11.get(cas))
                     for form in route_forms}
            if any(found.values()):
                inputs.append({"ingredient": ingredient, "readings": found})
        if not inputs:
            continue
        variants = max(len(r) for i in inputs for r in i["readings"].values())
        share = unknown.get(route, unknown.get(""))
        runs = [_run(inputs, route, form, end, choice, rules, share)
                for form in route_forms for end in ("low", "high")
                for choice in range(variants)]
        contributions = []
        for item in inputs:
            for form, options in item["readings"].items():
                for reading in options:
                    contributions.append({
                        "name": item["ingredient"].name, "cas": item["ingredient"].cas,
                        "percentage": (f"{_n(item['ingredient'].low)} - "
                                       f"{_n(item['ingredient'].high)}"
                                       if item["ingredient"].is_range
                                       else _n(item["ingredient"].high)),
                        "hazard_class": f"ATE {_n(reading.value)} {UNIT[form]}"
                                        + (f" ({FORM_WORD[form]})" if form in FORM_WORD else ""),
                        "contributed": reading.source, "unit": ""})
        out[route] = {"runs": runs, "contributions": contributions,
                      "forms": route_forms, "variants": variants}
    return out


def stated_categories(stated: list[HazardClass]) -> dict[str, set[str]]:
    """What Section 2 states for each route, from the classes read off it."""
    out: dict[str, set[str]] = {}
    for route, name in CLASS_NAME.items():
        cats = {c.category for c in stated if c.name == name and c.category}
        if cats:
            out[route] = cats
    return out


_UNKNOWN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*%\s*of the mixture consists of (?:ingredient|component)s?"
    r"(?:\(s\))?\s+(?:of|with)\s+unknown acute\s*(?:\(?(oral|dermal|inhalation)[^)]*\)?\s*)?"
    r"toxicity", re.I)


def unknown_share(lines) -> dict[str, Decimal]:
    """The share of unknown acute toxicity the sheet itself states, by route."""
    out: dict[str, Decimal] = {}
    for line in lines:
        for found in _UNKNOWN.finditer(line.text or ""):
            out[(found.group(2) or "").lower()] = Decimal(found.group(1).replace(",", "."))
    return out
