"""PubChem's GHS classifications for an ingredient, by CAS number.

Reference data, not law: PubChem gathers what its sources say - the CLP
harmonised entry, ECHA's C&L notifications (with how many notifiers say
each code), national lists - and none of it binds a sheet. It is read so a
mixture can be calculated from the same kind of input the app uses, and
from the most commonly notified classification where no binding list has
the substance.

Fetched here, at build time, never at check time: `lingua keys build pubchem
--cas ...` (or `--from` documents) writes data/reference_classifications/
<cas>.json, which the check only reads. That folder is local: the CAS
numbers in it are the ingredients of the documents checked.

* the CAS number is looked up as a name (PUG-REST), the first compound
  number (CID) is taken;
* PUG-View's "GHS Classification" heading for that compound is read - every
  entry, in PubChem's order, with its source, its codes and the share of
  notifications each code has where ECHA's aggregate gives one.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from lingua_oracle.registry import data_dir

CID_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{cas}/cids/JSON"
VIEW_URL = ("https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
            "?heading=GHS+Classification")
LABEL = "PubChem (ECHA C&L notifications) — reference, not legally binding"

_CODE = re.compile(r"\b((?:EUH|AUH|H)\d{3}[A-Za-z]{0,2})\b(?:\s*\(\s*(>|<)?\s*([\d.]+)\s*%\s*\))?")
_REPORTS = re.compile(r"per (\d+) reports? by companies from (\d+) notifications?")
_NOT_MEETING = re.compile(r"(?:not meeting|does not meet) GHS hazard criteria.*?\(?(\d+)\s+of\s+"
                          r"(\d+)")


def folder() -> Path:
    """data/reference_classifications, or LINGUA_REFERENCE_DIR where set."""
    import os

    override = os.environ.get("LINGUA_REFERENCE_DIR")
    return Path(override) if override else data_dir() / "reference_classifications"


def parse(view: dict, *, cas: str, cid: int | None, url: str) -> dict:
    """Every classification PubChem's GHS heading lists, in its order."""
    record = view.get("Record", {})
    sources = {r.get("ReferenceNumber"): r for r in record.get("Reference", [])}
    blocks: dict[int, dict] = {}
    order: list[int] = []

    def walk(sections):
        for section in sections:
            for info in section.get("Information", []):
                ref = info.get("ReferenceNumber")
                if ref not in blocks:
                    source = sources.get(ref, {})
                    blocks[ref] = {"reference": ref, "source": source.get("SourceName", ""),
                                   "name": source.get("Name", ""), "statements": [],
                                   "codes": [], "summary": ""}
                    order.append(ref)
                strings = [s.get("String", "") for s in
                           info.get("Value", {}).get("StringWithMarkup", [])]
                if info.get("Name") == "GHS Hazard Statements":
                    blocks[ref]["statements"] += strings
                elif info.get("Name") in ("ECHA C&L Notifications Summary", "Note"):
                    blocks[ref]["summary"] = " ".join([blocks[ref]["summary"], *strings]).strip()
            walk(section.get("Section", []))

    walk(record.get("Section", []))
    entries = []
    for ref in order:
        block = blocks[ref]
        if not block["statements"]:
            continue
        seen: dict[str, dict] = {}
        for text in block["statements"]:
            for found in _CODE.finditer(text):
                code = found.group(1)
                share = float(found.group(3)) if found.group(3) else None
                seen.setdefault(code, {"code": code, "percent": share,
                                       "bound": found.group(2) or ""})
        block["codes"] = list(seen.values())
        reports = _REPORTS.search(block["summary"])
        not_meeting = _NOT_MEETING.search(block["summary"])
        block["reports"] = int(reports.group(1)) if reports else None
        block["notifications"] = int(reports.group(2)) if reports else None
        block["not_meeting"] = ([int(not_meeting.group(1)), int(not_meeting.group(2))]
                                if not_meeting else None)
        entries.append(block)
    return {"cas": cas, "cid": cid, "source_url": url, "label": LABEL,
            "status": "ok" if entries else "no_ghs", "entries": entries}


def fetch(cas: str, *, use_cache: bool = True) -> dict:
    """The record for one CAS number, from PubChem."""
    import httpx

    from lingua_oracle.keys.builders.common import fetch as get

    lookup = CID_URL.format(cas=cas)
    try:
        cids = json.loads(get(lookup, use_cache=use_cache)).get("IdentifierList", {}).get("CID")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"cas": cas, "cid": None, "source_url": lookup, "label": LABEL,
                    "status": "not_found", "entries": []}
        raise
    if not cids:
        return {"cas": cas, "cid": None, "source_url": lookup, "label": LABEL,
                "status": "not_found", "entries": []}
    url = VIEW_URL.format(cid=cids[0])
    try:
        view = json.loads(get(url, use_cache=use_cache))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:          # the compound has no GHS heading
            return {"cas": cas, "cid": cids[0], "source_url": url, "label": LABEL,
                    "status": "no_ghs", "entries": []}
        raise
    return parse(view, cas=cas, cid=cids[0], url=url)


def write(cas: str, *, use_cache: bool = True, today: str | None = None) -> Path:
    """Fetch and keep one record; the date it was read stays the same while
    what PubChem says does not change, so a rebuild leaves the file alone."""
    cas = cas.strip()
    held = fetch(cas, use_cache=use_cache)
    path = folder() / f"{cas}.json"
    old = load(cas)
    stamp = today or date.today().isoformat()
    if old is not None and {k: v for k, v in old.items() if k != "retrieved"} == held:
        stamp = old.get("retrieved", stamp)
    folder().mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**held, "retrieved": stamp}, indent=1, ensure_ascii=False)
                    + "\n", encoding="utf-8")
    return path


def load(cas: str) -> dict | None:
    """The record on file for a CAS number, or None. Never fetches."""
    path = folder() / f"{(cas or '').strip()}.json"
    if not cas or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
