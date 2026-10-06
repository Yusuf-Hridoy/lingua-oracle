"""What the calculation works on: ingredients with ranges and classifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from lingua_oracle.mixture.classes import (
    STOT_SE_3_EFFECT,
    HazardClass,
    class_of,
    parse_class,
)
from lingua_oracle.mixture.limits import MFactor, ParsedLimits, SpecificLimit


@dataclass
class MixtureIngredient:
    """One ingredient at one concentration, with what it is classified as.

    The concentration is a range because sheets give ranges; a single value is
    a range whose ends are equal. `percentage` is whichever end the calculation
    is currently standing on, so a rule never has to know about ranges.
    """

    cas: str | None
    name: str | None
    low: Decimal
    high: Decimal
    classes: list[HazardClass] = field(default_factory=list)
    h_codes: list[str] = field(default_factory=list)
    limits: ParsedLimits | None = None
    #: Where the classification came from: "annex_vi" or "codes".
    classification_source: str = "codes"
    percentage: Decimal = Decimal(0)

    @property
    def label(self) -> str:
        return self.name or self.cas or "an ingredient"

    @property
    def is_range(self) -> bool:
        return self.low != self.high

    def at(self, end: str) -> MixtureIngredient:
        """The same ingredient standing at one end of its range."""
        from dataclasses import replace

        return replace(self, percentage=self.low if end == "low" else self.high)

    def specific_limit_for(self, hazard_class: HazardClass) -> SpecificLimit | None:
        return self.limits.limit_for(hazard_class) if self.limits else None

    def m_factor_for(self, hazard_class: HazardClass) -> Decimal | None:
        """The M-factor for an aquatic class, where Annex VI gives one.

        The act prints M-factors without saying which of acute and chronic each
        belongs to. Where one is given it is used for whichever aquatic class
        the ingredient has; where two are given they are taken in the order
        printed, acute then chronic, which is the order Annex VI lists them in.
        Either way the assumption is recorded by the rule that used it.
        """
        if not self.limits or not self.limits.m_factors:
            return None
        factors: list[MFactor] = self.limits.m_factors
        if len(factors) == 1:
            return factors[0].value
        wanted = 0 if hazard_class.name.casefold().endswith("acute") else 1
        return factors[min(wanted, len(factors) - 1)].value

    def stot_se_3_share(self, effect: str) -> str | None:
        """The effect this ingredient's STOT SE 3 is for, if it is that one."""
        for code in self.h_codes:
            if STOT_SE_3_EFFECT.get(code) == effect:
                return effect
        return None


def from_annex_vi(cas, name, low, high, entry, limits) -> MixtureIngredient:
    """An ingredient classified by its harmonised entry."""
    classes = [c for c in (parse_class(raw) for raw in entry.hazard_classes) if c]
    return MixtureIngredient(
        cas=cas, name=name, low=low, high=high, classes=classes,
        h_codes=[*entry.h_codes, *entry.euh_codes], limits=limits,
        classification_source="annex_vi")


def from_codes(cas, name, low, high, codes) -> MixtureIngredient:
    """An ingredient classified by the H codes the app or the sheet carries."""
    classes = []
    for code in codes:
        hazard_class = class_of(code)
        if hazard_class is not None and hazard_class not in classes:
            classes.append(hazard_class)
    return MixtureIngredient(cas=cas, name=name, low=low, high=high,
                             classes=classes, h_codes=list(codes),
                             classification_source="codes")
