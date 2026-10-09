"""The two inputs an ingredient's classification can be calculated from.

A - "same input as ExactSDS": the codes the app stores for a product it
    holds; for a product it does not, what the app's PubChem lookup would
    give - the first compound number, the first "GHS Hazard Statements"
    entry PubChem lists, plain H codes only (no letter suffix, no EUH or
    AUH), de-duplicated. The app shortens a list of more than five codes
    with an AI step; that cannot be reproduced, so such an input is "not
    reproducible", and the first five - the app's own fallback - are kept
    as a labelled extra.
B - "best available": the binding list (Annex VI for the EU, the GB MCL for
    Great Britain; HCIS for Australia, which is a reference) where it has
    the substance; otherwise the classification most commonly notified to
    ECHA, as PubChem aggregates it - the notification block with the most
    reports, the codes more than half of its reports give.

Nothing here decides anything about the mixture: it only says, per
ingredient, which codes each input holds and where they came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lingua_oracle.keys.builders import pubchem

_PLAIN = re.compile(r"\bH\d{3,4}\b")          # what the app's PubChem reading keeps
_CODE = re.compile(r"\b(?:EUH|AUH|H)\d{3}[A-Za-z]{0,2}\b")
APP_LABEL = "ExactSDS stored codes (the app's own record)"
FIRST_LABEL = ("PubChem, first listed classification - as the app selects it - reference, "
               "not legally binding")
FALLBACK_LABEL = "first 5 codes (the app's own fallback)"


@dataclass
class Input:
    """One ingredient's codes under one input."""

    codes: list[str] | None          # None: no data to say
    source: str
    binding: bool = False
    reproducible: bool = True
    why: str = ""
    #: The app's own fallback where A is not reproducible: its first five codes.
    fallback: list[str] | None = None
    #: What PubChem says, kept for the likely-cause notes.
    detail: dict = field(default_factory=dict)


def _first_entry(record: dict) -> dict | None:
    return next((e for e in record.get("entries", []) if e.get("statements")), None)


def input_a(cas: str, app_codes: list[str] | None) -> Input:
    if app_codes is not None:
        return Input(list(app_codes), APP_LABEL, detail={"from": "app"})
    record = pubchem.load(cas)
    if record is None:
        return Input(None, FIRST_LABEL, why=f"no PubChem record on file for {cas}")
    if record["status"] == "not_found":
        return Input([], FIRST_LABEL, why="PubChem does not know this CAS number",
                     detail={"from": "pubchem", "status": "not_found"})
    first = _first_entry(record)
    if first is None:
        return Input([], FIRST_LABEL, why="PubChem has no GHS classification for it",
                     detail={"from": "pubchem", "status": "no_ghs"})
    codes = list(dict.fromkeys(c for text in first["statements"] for c in _PLAIN.findall(text)))
    detail = {"from": "pubchem", "status": "ok", "first_source": first["source"],
              "first_count": len(codes)}
    if len(codes) > 5:
        return Input(None, FIRST_LABEL, reproducible=False,
                     why="not reproducible: the app uses an AI selection", fallback=codes[:5],
                     detail=detail)
    return Input(codes, FIRST_LABEL, detail=detail)


def majority(record: dict | None) -> tuple[list[str] | None, dict]:
    """The most commonly notified classification: ECHA's notification block
    with the most reports, and the codes more than half of them give."""
    if record is None or record.get("status") != "ok":
        return None, {}
    blocks = [e for e in record["entries"] if e.get("reports")]
    if not blocks:
        return None, {}
    block = max(blocks, key=lambda e: e["reports"])
    codes = [c["code"] for c in block["codes"]
             if c["percent"] is None or c["percent"] > 50 or c.get("bound") == ">"]
    return codes, {"reports": block["reports"], "notifications": block.get("notifications"),
                   "source": block["source"]}


def input_b(cas: str, regulation: str) -> Input:
    from lingua_oracle.substances.load import for_check

    use, table = for_check(regulation)
    usable = use is not None and table is not None and (use.binding or use.name == "au_hcis")
    if usable:
        entries = table.by_cas().get((cas or "").strip(), [])
        if len(entries) == 1 and not entries[0].covers_several_substances:
            entry = entries[0]
            label = f"{use.title} ({'binding' if use.binding else 'reference only'})"
            return Input([*entry.h_codes, *getattr(entry, "euh_codes", [])], label,
                         binding=use.binding, detail={"from": "list", "list": use.name})
    record = pubchem.load(cas)
    codes, about = majority(record)
    if codes is None:
        why = (f"no PubChem record on file for {cas}" if record is None else
               "PubChem does not know this CAS number" if record["status"] == "not_found" else
               "PubChem has no notification data for it")
        return Input(None, pubchem.LABEL, why=why)
    return Input(codes, f"{pubchem.LABEL}; most commonly notified ({about['reports']} reports)",
                 detail={"from": "pubchem", **about})


def likely_causes(cas: str, a: Input, b: Input) -> list[str]:
    """Why the app's data may lack a code input B has - for the technical
    details only, never part of a verdict."""
    if a.codes is None or b.codes is None:
        return []
    missing = [c for c in b.codes if c.casefold() not in {x.casefold() for x in a.codes}]
    if not missing and set(map(str.casefold, a.codes)) == set(map(str.casefold, b.codes)):
        return []
    out: list[str] = []
    record = pubchem.load(cas) or {}
    first = _first_entry(record) if record else None
    if not a.codes and record.get("status") == "no_ghs":
        return [f"{cas}: the app stores an empty list when PubChem has no GHS section."]
    suffixed = [c for c in missing if re.fullmatch(r"H\d{3}[A-Za-z]{1,2}", c)]
    if suffixed:
        out.append(f"{cas}: {', '.join(suffixed)} missing - the app's extraction does not "
                   "capture codes with a letter suffix.")
    supplemental = [c for c in missing if c.startswith(("EUH", "AUH"))]
    if supplemental:
        out.append(f"{cas}: {', '.join(supplemental)} missing - the app does not capture "
                   "supplemental codes.")
    first_count = len(_PLAIN.findall(" ".join(first["statements"]))) if first else 0
    aquatic = [c for c in missing if re.fullmatch(r"H4\d\d", c)]
    if aquatic and first_count > 5:
        out.append(f"{cas}: {', '.join(aquatic)} missing - may have been dropped by the app's "
                   "AI shortening (PubChem lists more than 5 codes).")
    rest = [c for c in missing if c not in suffixed + supplemental + aquatic]
    extra = [c for c in a.codes if c.casefold() not in {x.casefold() for x in b.codes}]
    if not (rest or extra):
        return out
    kind = "harmonised" if b.binding or b.detail.get("from") == "list" else "majority"
    today = list(dict.fromkeys(c for text in (first or {}).get("statements", [])
                               for c in _PLAIN.findall(text)))
    if a.detail.get("from") == "app" and first is not None and (
            {c.casefold() for c in today} != {c.casefold() for c in a.codes}):
        out.append(f"{cas}: the app's stored codes ({', '.join(a.codes)}) differ from the {kind} "
                   f"classification and from PubChem's first entry today ({', '.join(today)}) - "
                   "a stored list is not fetched again once written.")
    else:
        out.append(f"{cas}: the app's codes differ from the {kind} classification - the app "
                   "uses only the first PubChem entry.")
    return out


def codes_in(text: str) -> list[str]:
    """Hazard statement codes printed in a text, combined ones split."""
    return list(dict.fromkeys(_CODE.findall(text or "")))
