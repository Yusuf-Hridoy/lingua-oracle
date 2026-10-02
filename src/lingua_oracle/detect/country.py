"""Where a sheet appears to come from, for suggesting a regulation.

Used only when the document names no regulation at all. A supplier's address
and telephone number say where they are, not which law the sheet was written
to - so this never decides anything. It offers a starting point the reader
confirms, and the report says plainly that it was a guess from the address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Countries, and the regulation a sheet from there most likely follows.
#: EU member states all map to CLP, which is the regulation, not the country.
_EU = "eu_clp"
COUNTRY_REGULATION: dict[str, str] = {
    "Australia": "au_whs",
    "New Zealand": "au_whs",
    "Canada": "ca_whmis",
    "United Kingdom": "uk_clp",
    "England": "uk_clp", "Scotland": "uk_clp", "Wales": "uk_clp",
    "Great Britain": "uk_clp",
    "United States": "us_osha", "U.S.A.": "us_osha", "USA": "us_osha",
    "Germany": _EU, "France": _EU, "Spain": _EU, "Italy": _EU,
    "Netherlands": _EU, "Belgium": _EU, "Ireland": _EU, "Denmark": _EU,
    "Sweden": _EU, "Finland": _EU, "Austria": _EU, "Poland": _EU,
    "Portugal": _EU, "Czech": _EU, "Hungary": _EU, "Greece": _EU,
}

#: International dialling prefixes. "+1" is both the US and Canada, so it is
#: deliberately absent: a prefix that cannot tell two regulations apart is no
#: help in choosing between them.
PHONE_REGULATION: dict[str, str] = {
    "+61": "au_whs", "+64": "au_whs",
    "+44": "uk_clp",
    "+49": _EU, "+33": _EU, "+34": _EU, "+39": _EU, "+31": _EU,
    "+32": _EU, "+353": _EU, "+45": _EU, "+46": _EU, "+358": _EU,
    "+43": _EU, "+48": _EU, "+351": _EU, "+420": _EU, "+36": _EU, "+30": _EU,
}


@dataclass(frozen=True)
class CountryHint:
    regulation: str
    #: What was found, for the reader to judge: "address, +61 phone".
    reason: str


def country_hint(text: str) -> CountryHint | None:
    """A regulation suggested by where the sheet seems to come from."""
    found: dict[str, list[str]] = {}

    # Every country named, not just the first: a sheet that mentions two is a
    # sheet we cannot place, and stopping early would hide that.
    for name, regulation in COUNTRY_REGULATION.items():
        if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
            reasons = found.setdefault(regulation, [])
            if "address" not in reasons:
                reasons.append("address")

    # Longest prefix first, so +353 is not read as +35.
    for prefix in sorted(PHONE_REGULATION, key=len, reverse=True):
        if re.search(rf"\{prefix}[\s\d(]", text):
            regulation = PHONE_REGULATION[prefix]
            reasons = found.setdefault(regulation, [])
            reasons.append(f"{prefix} phone")
            break

    if not found:
        return None
    # Where the address and the phone disagree, we know less than we thought.
    if len(found) > 1:
        return None
    regulation, reasons = next(iter(found.items()))
    return CountryHint(regulation=regulation, reason=", ".join(reasons))
