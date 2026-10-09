"""Whether the mixture is a gas, read from Section 9.

Two of the limits in the sensitisation tables depend on it: a respiratory
sensitiser classifies a solid or liquid mixture at 1,0 % and a gas at 0,2 %,
and nothing in a composition says which the mixture is. Section 9 does, under
"Physical state" or "Appearance", so that is where this looks.

Only the distinction the tables draw is read - gas, or solid or liquid - and
only where the sheet says so plainly. A sheet that does not say is reported as
not saying: the calculation then runs both ways and the report says the answer
depends on it, which is the truth and is more use than a guess.
"""

from __future__ import annotations

import re

#: The labels Section 9 puts in front of the answer, in the languages the
#: application issues sheets in.
_LABELS = (
    r"physical state", r"state", r"form", r"appearance", r"physical form",
    r"aggregatzustand", r"form", r"état physique", r"forme",
    r"estado físico", r"stato fisico", r"fysisk tilstand",
    r"fysische toestand", r"estado físico",
)
#: The label, then its value on the same line after a separator - or nothing,
#: the value on the line below ("Physical state" / "Liquid", or / ": liquid").
_LABEL_RE = re.compile(
    r"^\s*(?:9\.1\.?\s*)?(?:" + "|".join(_LABELS) + r")\s*(?:[:–-]\s*(?P<value>.*))?$",
    re.IGNORECASE)

#: Where Section 9 starts and where it stops. The section detector tracks only
#: the sections the wording check needs, so this finds its own.
#: The label before the number is any one word ("Section", "PUNKT", "ABSCHNITT").
_SECTION_9 = re.compile(
    r"^\s*(?:[^\W\d]+\s*)?9[.):]?\s*(physical and chemical|"
    r"physikalische und chemische|propriétés physiques|"
    r"propiedades físicas|proprietà fisiche|fysiske og kemiske|"
    r"fysische en chemische)", re.IGNORECASE)
_SECTION_10 = re.compile(
    r"^\s*(?:[^\W\d]+\s*)?10[.):]?\s*(stability|stabilität|stabilité|"
    r"estabilidad|stabilità|stabilitet|stabiliteit)", re.IGNORECASE)

#: What the value has to say for each answer. "Gas" and "gaseous" only: an
#: aerosol is a liquid or a solid dispersed in a propellant, and the tables do
#: not call it a gas.
_GAS = re.compile(r"\b(gas|gases|gaseous|gasförmig|gaz|gaseoso|gassoso)\b",
                  re.IGNORECASE)
_LIQUID = re.compile(
    r"\b(liquid|liquide|líquido|liquido|væske|vloeistof|flüssig|fluid)\b",
    re.IGNORECASE)
_SOLID = re.compile(
    r"\b(solid|solide|sólido|solido|fast|vast|feststoff|"
    r"powder|poudre|polvo|polvere|pulver|poeder|"
    r"granule|granules|granulat|pellet|pellets|flake|flakes|"
    r"crystals?|crystalline|wax|wachs)\b",
    re.IGNORECASE)
#: Forms that are a solid or a liquid without saying which: dispersed in a
#: propellant, or between the two.
_EITHER = re.compile(r"\b(paste|pâte|pasta|gel|aerosol|aérosol)\b", re.IGNORECASE)

#: What the rule tables call each answer.
GAS = "gas"
SOLID_OR_LIQUID = "solid/liquid"
LIQUID = "liquid"
SOLID = "solid"


def bucket(state: str | None) -> str | None:
    """The two states the rule tables distinguish: gas, or solid or liquid."""
    if state in (LIQUID, SOLID, SOLID_OR_LIQUID):
        return SOLID_OR_LIQUID
    return state


def physical_state(lines, spans=None) -> str | None:
    """"gas", "liquid", "solid" - "solid/liquid" for an aerosol, paste or gel,
    which the sheet does not put in either - or nothing where it does not say.

    The answer as the sheet gives it: the limits that turn on it only
    distinguish a gas from everything else (`bucket`), but inhalation toxicity
    is a vapour for a liquid and a dust for a solid.

    Section 9 is found here rather than taken from the section detector, which
    tracks only the sections the wording check needs. The value may follow its
    label or sit on the line below it: a two-column layout flattens to
    "State :" and then "liquid", and both are the same sentence.
    """
    return _read(lines)[0]


def printed_state(lines, spans=None) -> str:
    """What Section 9 prints for the physical state ("aerosol", "Liquid"),
    where it says one; "" where it does not."""
    return _read(lines)[1]


#: The languages whose Section 9 labels `_LABELS` holds: elsewhere a state
#: not found is a state not read, not one not stated.
LANGUAGES = frozenset({"en", "de", "fr", "es", "pt", "it", "da", "nl"})


def read_section(lines: list[str]) -> tuple[str | None, str]:
    """(state, printed) from Section 9's own lines, found by the caller."""
    return _scan([line or "" for line in lines])


def _read(lines) -> tuple[str | None, str]:
    inside, section = False, []
    for line in lines:
        text = (line.text or "").strip()
        if _SECTION_9.match(text):
            inside = True
            continue
        if inside and _SECTION_10.match(text):
            break
        if inside:
            section.append(text)
    return _scan(section)


def _scan(lines: list[str]) -> tuple[str | None, str]:
    for index, line in enumerate(lines):
        match = _LABEL_RE.match(line.strip())
        if match is None:
            continue
        value = (match.group("value") or "").strip()
        below = index + 1
        while not value and below < len(lines) and below <= index + 2:
            # The value below; a lone ":" a layout put between them is not it.
            value = lines[below].strip().lstrip(":：").strip()
            below += 1
        if _GAS.search(value):
            return GAS, value
        liquid, solid = _LIQUID.search(value), _SOLID.search(value)
        if liquid and not solid:
            return LIQUID, value
        if solid and not liquid:
            return SOLID, value
        if liquid or solid or _EITHER.search(value):
            return SOLID_OR_LIQUID, value
    return None, ""


def state_of(qualifier: str) -> str | None:
    """The physical state a limit is given for, if it is given for one."""
    text = (qualifier or "").casefold()
    if "all physical states" in text:
        return "all physical states"
    if "solid" in text or "liquid" in text:
        return SOLID_OR_LIQUID
    if "gas" in text:
        return GAS
    return None


def applicable(values, state: str | None):
    """The limits that apply to a mixture in this state.

    A limit given for all physical states applies whatever the mixture is; one
    given for a state applies only to that state. Where the sheet does not say
    what state the mixture is in, every limit stays in play and the calculation
    is run against each of them.
    """
    if state is None:
        return tuple(values)
    state = bucket(state)
    kept = tuple(v for v in values
                 if state_of(v.qualifier) in (None, "all physical states", state))
    return kept or tuple(values)
