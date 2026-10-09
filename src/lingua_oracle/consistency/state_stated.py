"""C-25: Section 9 states the physical state.

Every calculation that turns on gas, liquid or solid - the sensitisation
limits, inhalation toxicity as a vapour or a dust - reads it there, and each
regulation's own text lists it among Section 9's items, quoted from
data/section9/<regulation>.json (Australia's Schedule 7 lists none). A
Section 9 that does not state it is one to check; one that does is shown as
it is printed.
"""

from __future__ import annotations

from lingua_oracle.keys.builders import section9
from lingua_oracle.models import ConsistencyRow

CHECK = "C-25"
_READ_AS = {"gas": "a gas", "liquid": "a liquid", "solid": "a solid",
            "solid/liquid": "a solid or a liquid, not saying which"}


def run(regulation: str, language: str, section_9: list[str]) -> list[ConsistencyRow]:
    from lingua_oracle.mixture.state import LANGUAGES, read_section

    if not section_9:
        return []
    held = section9.load(regulation) or {}
    item = held.get("item") or {}
    state, printed = read_section(section_9)
    tags = set(language.replace("+", "-").split("-"))
    if not state and not tags & LANGUAGES:
        return [ConsistencyRow(section="9", check=CHECK, key="Physical state", status="na",
                               text="Not checked: the physical state is read in "
                                    f"{', '.join(sorted(LANGUAGES))} only.")]
    if state:
        return [ConsistencyRow(section="9", check=CHECK, key="Physical state", status="ok",
                               text=f"“{printed}” — read as {_READ_AS[state]}.",
                               citation=item.get("citation", ""))]
    why = "" if item else f" {held['why']}" if held.get("why") else ""
    return [ConsistencyRow(section="9", check=CHECK, key="Physical state", status="check",
                           text=f"Physical state not stated in Section 9.{why}",
                           quote=item.get("quote", ""), citation=item.get("citation", ""))]
