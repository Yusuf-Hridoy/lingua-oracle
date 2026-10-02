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
    countries: dict[str, None] = {}
    # Every country named, not just the first: a sheet that mentions two is a
    # sheet we may not be able to place, and stopping early would hide that.
    for name, regulation in COUNTRY_REGULATION.items():
        if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
            countries[regulation] = None

    phone: str | None = None
    # Longest prefix first, so +353 is not read as +35.
    for prefix in sorted(PHONE_REGULATION, key=len, reverse=True):
        if re.search(rf"\{prefix}[\s\d(]", text):
            phone = prefix
            break

    by_phone = PHONE_REGULATION[phone] if phone else None

    # A corporate footer names countries the supplier merely trades in -
    # "MilliporeSigma in the US and Canada" sits on a sheet whose own address
    # is in Australia. The telephone number belongs to the contact details, so
    # where it agrees with one of the countries named, that is the one.
    if by_phone and by_phone in countries:
        return CountryHint(by_phone, f"address, {phone} phone")
    if len(countries) == 1 and not by_phone:
        return CountryHint(next(iter(countries)), "address")
    if by_phone and not countries:
        return CountryHint(by_phone, f"{phone} phone")
    # Nothing agrees, or nothing was found: we know less than we thought.
    return None
