"""Hazard statement codes and the classes they stand for.

An ingredient's classification reaches us two ways. Where Annex VI has
harmonised the substance, the entry names the class and category outright and
that is what is used. Where it has not, all we have is the H codes the app or
the sheet carries, and the class has to come from the code.

A code does not always determine the category. H314 is Skin Corr. 1, and
whether it is 1A, 1B or 1C is not in the code; H317 is Skin Sens. 1 and may be
1A or 1B. Where the code is silent this table says so by giving the category
without its sub-division, and the rules fall back to the category level - which
is what CLP itself does when sub-categories are unknown.

The table is written out rather than derived, because a derivation from Annex
VI's own rows is only as good as the row alignment and some rows do not align.
`test_mixture_classes.py` cross-checks every entry here against the mapping
Annex VI's own entries show, so it is verified against the law rather than
asserted.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HazardClass:
    """A CLP hazard class and category, as Annex VI writes them."""

    name: str
    category: str | None = None

    def __str__(self) -> str:
        return f"{self.name} {self.category}".strip()

    @property
    def generic(self) -> HazardClass:
        """The category without its sub-division: Skin Corr. 1B -> Skin Corr. 1."""
        if not self.category:
            return self
        digits = "".join(c for c in self.category if c.isdigit())
        return HazardClass(self.name, digits or None)

    @property
    def sub_category(self) -> str | None:
        """The letter, where there is one: 1B -> "B"."""
        if not self.category:
            return None
        letters = "".join(c for c in self.category if c.isalpha())
        return letters or None


#: What each hazard statement code says about the class. Only the codes the
#: implemented rules need; anything else is left out rather than guessed, and
#: an ingredient carrying it contributes to no rule.
CODE_TO_CLASS: dict[str, HazardClass] = {
    # Skin corrosion / irritation - Annex I 3.2
    "H314": HazardClass("Skin Corr.", "1"),
    "H315": HazardClass("Skin Irrit.", "2"),
    # Serious eye damage / eye irritation - Annex I 3.3
    "H318": HazardClass("Eye Dam.", "1"),
    "H319": HazardClass("Eye Irrit.", "2"),
    # Sensitisation - Annex I 3.4
    "H317": HazardClass("Skin Sens.", "1"),
    "H334": HazardClass("Resp. Sens.", "1"),
    # Germ cell mutagenicity - Annex I 3.5
    "H340": HazardClass("Muta.", "1"),
    "H341": HazardClass("Muta.", "2"),
    # Carcinogenicity - Annex I 3.6
    "H350": HazardClass("Carc.", "1"),
    "H350i": HazardClass("Carc.", "1"),
    "H351": HazardClass("Carc.", "2"),
    # Reproductive toxicity - Annex I 3.7
    "H360": HazardClass("Repr.", "1"),
    "H360F": HazardClass("Repr.", "1"),
    "H360D": HazardClass("Repr.", "1"),
    "H360FD": HazardClass("Repr.", "1"),
    "H360Fd": HazardClass("Repr.", "1"),
    "H360Df": HazardClass("Repr.", "1"),
    "H361": HazardClass("Repr.", "2"),
    "H361f": HazardClass("Repr.", "2"),
    "H361d": HazardClass("Repr.", "2"),
    "H361fd": HazardClass("Repr.", "2"),
    "H362": HazardClass("Lact.", None),
    # Specific target organ toxicity - Annex I 3.8 and 3.9
    "H370": HazardClass("STOT SE", "1"),
    "H371": HazardClass("STOT SE", "2"),
    "H335": HazardClass("STOT SE", "3"),
    "H336": HazardClass("STOT SE", "3"),
    "H372": HazardClass("STOT RE", "1"),
    "H373": HazardClass("STOT RE", "2"),
    # Hazardous to the aquatic environment - Annex I 4.1
    "H400": HazardClass("Aquatic Acute", "1"),
    "H410": HazardClass("Aquatic Chronic", "1"),
    "H411": HazardClass("Aquatic Chronic", "2"),
    "H412": HazardClass("Aquatic Chronic", "3"),
    "H413": HazardClass("Aquatic Chronic", "4"),
}

#: The two STOT SE 3 effects, which are summed separately (Annex I 3.8.3.4.5).
#: The code says which effect it is; the class does not.
STOT_SE_3_EFFECT = {
    "H335": "respiratory irritation",
    "H336": "narcotic effects",
}


#: The acute toxicity statements: the route each is for, and the categories it
#: is assigned to (Annex I Table 3.1.3). H300, H310 and H330 cover two
#: categories each, so a code alone does not say which.
ACUTE_CODES: dict[str, tuple[str, tuple[str, ...]]] = {
    "H300": ("oral", ("1", "2")), "H301": ("oral", ("3",)),
    "H302": ("oral", ("4",)), "H303": ("oral", ("5",)),
    "H310": ("dermal", ("1", "2")), "H311": ("dermal", ("3",)),
    "H312": ("dermal", ("4",)), "H313": ("dermal", ("5",)),
    "H330": ("inhalation", ("1", "2")), "H331": ("inhalation", ("3",)),
    "H332": ("inhalation", ("4",)), "H333": ("inhalation", ("5",)),
}
ACUTE_CLASS = {"oral": "Acute Tox. (oral)", "dermal": "Acute Tox. (dermal)",
               "inhalation": "Acute Tox. (inhalation)"}


def acute_classes(code: str) -> list[HazardClass]:
    """The route-specific acute classes a code states - two where it covers two."""
    found = ACUTE_CODES.get((code or "").strip().upper())
    if found is None:
        return []
    route, cats = found
    return [HazardClass(ACUTE_CLASS[route], c) for c in cats]


def class_of(code: str) -> HazardClass | None:
    """The hazard class a statement code stands for, or None if not mapped."""
    return CODE_TO_CLASS.get((code or "").strip())


def parse_class(raw: str) -> HazardClass | None:
    """"Skin Corr. 1B" -> HazardClass("Skin Corr.", "1B").

    The "*" of a minimum classification is dropped: it qualifies how the entry
    was arrived at, not which class it is.
    """
    import re

    text = " ".join((raw or "").replace("*", " ").split())
    if not text:
        return None
    match = re.match(r"^(?P<name>.*?)\s*(?P<category>\d[A-Fa-f]?)$", text)
    if not match or not match.group("name"):
        return HazardClass(text, None)
    return HazardClass(match.group("name").strip(), match.group("category"))
