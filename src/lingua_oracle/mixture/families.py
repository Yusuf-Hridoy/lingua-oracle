"""Hazard families, and which of two classifications in one is the stricter.

Section 2 and a calculation rarely produce the same words for the same
hazard. A sheet says Skin Corr. 1; the declared ingredients give Skin Irrit. 2.
Comparing those as strings makes the sheet wrong twice over - once for stating
a class the ingredients do not give, once for not stating the class they do -
when what has actually happened is that the sheet is stricter about the skin
than the part of the mixture it declares.

So the comparison is per family. A family is one endpoint - the skin, the eye,
carcinogenicity - and the classes in it are ordered: Skin Corr. 1 is stricter
than Skin Irrit. 2, 1A is stricter than 1B. The verdict is then about the
family, and says which side is stricter rather than listing both as faults.

Which categories exist is the regulation's business, not this file's: a
category another regulation adopts and this one does not simply never turns
up. The order within a family is the order the categories are numbered in,
which every one of these regulations shares.
"""

from __future__ import annotations

from dataclasses import dataclass

from lingua_oracle.mixture.classes import HazardClass

#: One endpoint each, in the order a report shows them. The classes in a
#: family are listed most severe first.
FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Skin", ("Skin Corr.", "Skin Irrit.")),
    ("Eye", ("Eye Dam.", "Eye Irrit.")),
    ("Respiratory sensitisation", ("Resp. Sens.",)),
    ("Skin sensitisation", ("Skin Sens.",)),
    ("Germ cell mutagenicity", ("Muta.",)),
    ("Carcinogenicity", ("Carc.",)),
    ("Reproductive toxicity", ("Repr.",)),
    ("Effects on or via lactation", ("Lact.",)),
    ("Target organ toxicity, single exposure", ("STOT SE",)),
    ("Target organ toxicity, repeated exposure", ("STOT RE",)),
    ("Hazardous to the aquatic environment, short-term", ("Aquatic Acute",)),
    ("Hazardous to the aquatic environment, long-term", ("Aquatic Chronic",)),
)

#: Acute toxicity, one family per route. Calculated by additivity in
#: `mixture/acute.py` rather than by the cut-off rules, so kept out of
#: FAMILIES - whose loop compares cut-off results - but known here, so the
#: comparison and the report treat them like every other family.
ACUTE_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Acute toxicity, oral", ("Acute Tox. (oral)",)),
    ("Acute toxicity, dermal", ("Acute Tox. (dermal)",)),
    ("Acute toxicity, inhalation", ("Acute Tox. (inhalation)",)),
)
_FAMILY_OF = {name: family for family, names in (*FAMILIES, *ACUTE_FAMILIES)
              for name in names}


def family_of(hazard_class: HazardClass | str | None) -> str | None:
    """The endpoint a class belongs to, or nothing for a class not compared."""
    if hazard_class is None:
        return None
    name = (hazard_class.name if isinstance(hazard_class, HazardClass)
            else str(hazard_class).rsplit(" ", 1)[0])
    return _FAMILY_OF.get(name)


def classes_in(family: str) -> tuple[str, ...]:
    return next(names for name, names in (*FAMILIES, *ACUTE_FAMILIES)
                if name == family)


@dataclass(frozen=True, eq=False)
class Severity:
    """How strict a classification is, inside its own family.

    Lower is stricter, which is the order the categories are numbered in: Skin
    Corr. before Skin Irrit., 1 before 2, 1A before 1B. A category written
    without its sub-division - "Skin Corr. 1" where the sheet did not say 1A,
    1B or 1C - is not weaker than any of them, and is compared as equal to
    them; a sheet is not wrong for declining to guess a sub-category.
    """

    rank: int
    digits: int
    letter: int | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        if (self.rank, self.digits) != (other.rank, other.digits):
            return False
        if self.letter is None or other.letter is None:
            return True
        return self.letter == other.letter

    def __lt__(self, other: Severity) -> bool:
        if (self.rank, self.digits) != (other.rank, other.digits):
            return (self.rank, self.digits) < (other.rank, other.digits)
        if self.letter is None or other.letter is None:
            return False
        return self.letter < other.letter

    def __hash__(self) -> int:
        return hash((self.rank, self.digits))


def severity(hazard_class: HazardClass) -> Severity | None:
    """Where one classification sits in its family's order."""
    family = family_of(hazard_class)
    if family is None:
        return None
    names = classes_in(family)
    if hazard_class.name not in names:
        return None
    category = hazard_class.category or ""
    digits = "".join(c for c in category if c.isdigit())
    letters = "".join(c for c in category if c.isalpha()).upper()
    return Severity(
        rank=names.index(hazard_class.name),
        digits=int(digits) if digits else 0,
        letter=(ord(letters[0]) - ord("A")) if letters else None)


def stricter(left: HazardClass, right: HazardClass) -> bool:
    """True where `left` is a stricter classification than `right`.

    Only within one family: the eye and the skin are different injuries, and
    the severity of one says nothing about the severity of the other.
    """
    if family_of(left) != family_of(right) or family_of(left) is None:
        return False
    a, b = severity(left), severity(right)
    if a is None or b is None:
        return False
    return a < b


def strictest(classes) -> HazardClass | None:
    """The strictest of several classifications in one family."""
    ranked = [(severity(c), c) for c in classes if severity(c) is not None]
    if not ranked:
        return None
    best = ranked[0]
    for found in ranked[1:]:
        if found[0] < best[0]:
            best = found
    return best[1]


def by_family(classes) -> dict[str, list[HazardClass]]:
    """Group classifications by the endpoint each is about."""
    out: dict[str, list[HazardClass]] = {}
    for hazard_class in classes:
        family = family_of(hazard_class)
        if family is not None:
            out.setdefault(family, []).append(hazard_class)
    return out
