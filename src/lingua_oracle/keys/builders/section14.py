"""What Section 14 must give when a UN number is given, per regulation, in
its own words: data/section14/<regulation>.json. Not an answer key.

* eu_clp - REACH Annex II 14.1-14.4, consolidated text from the
  Publications Office ("shall be provided"), with 14.2's exceptions: the
  name need not be given where it is the product identifier in 1.1, nor
  repeated where it is the same in every mode;
* uk_clp - GB REACH Annex II 14.1-14.4, the legislation.gov.uk PDF on file;
* un_ghs - GHS Rev.11 Annex 4, A4.3.14.1-A4.3.14.4 ("Provide ...", in a
  text that recommends - one to check, not a fault);
* au_whs - Schedule 7 names Section 14 but none of its fields: a note;
* ca_whmis - HPR section 4(2): items 12 to 15's content may be omitted;
* us_osha - Appendix D: Sections 12-15 are not mandatory.

The last two notes are the ones the structure key already quotes from the
same texts (data/sds_structure), so the two cannot disagree.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.common import SourceUnavailable, fetch, strip_markers
from lingua_oracle.registry import data_dir

REGULATIONS = ("eu_clp", "uk_clp", "un_ghs", "au_whs", "ca_whmis", "us_osha")


def _flat(text: str) -> str:
    return " ".join((text or "").split())


def _structure(regulation: str) -> dict:
    path = data_dir() / "sds_structure" / f"{regulation}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _pdf(path: Path) -> str:
    import pymupdf

    with pymupdf.open(path) as doc:
        return _flat(" ".join(page.get_text() for page in doc))


def _quote(text: str, pattern: str, citation: str) -> dict:
    found = re.search(pattern, text)
    if found is None:
        raise SourceUnavailable(f"{citation} not found; the text's layout has changed")
    return {"quote": found.group(0), "citation": citation}


def _eu(use_cache: bool) -> dict:
    from lxml import html as LH

    from lingua_oracle.keys.builders.section16 import REACH_URL

    raw = fetch(REACH_URL, headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"},
                use_cache=use_cache)
    text = strip_markers(_flat(" ".join(LH.fromstring(raw).itertext())))
    starts = [m.start() for m in re.finditer(
        "ANNEX II REQUIREMENTS FOR THE COMPILATION OF SAFETY DATA SHEETS", text)]
    body = text[starts[-1]:] if starts else ""
    body = body[body.find("14.1. UN number or ID number"):body.find("14.5. Environmental hazards")]
    act = f"{_structure('eu_clp')['document']}, Annex II"
    return {"binding": True, "fields": {
        "number": _quote(body, r"The UN number or the ID number \(.+?\) from the UN Model "
                               r"Regulations, IMDG, ADR, RID, ADN or ICAO TI shall be provided\.",
                         f"{act}, 14.1"),
        "name": _quote(body, r"The proper shipping name as provided in column 2.+?shall be "
                             r"provided, unless it was used as the product identifier in "
                             r"subsection 1\.1\.", f"{act}, 14.2"),
        "class": _quote(body, r"The transport hazard class \(and subsidiary risks\) assigned.+?"
                              r"according to the UN Model Regulations shall be provided\.",
                        f"{act}, 14.3"),
        "group": _quote(body, r"The packing group number from the UN Model Regulations shall be "
                              r"provided, if applicable, as required by the UN Model "
                              r"Regulations, ADR, RID and ADN\.", f"{act}, 14.4")},
        "name_once": _quote(body, r"If the UN number and the proper shipping name remain "
                                  r"unchanged in different transport modes, it is not necessary "
                                  r"to repeat this information\.", f"{act}, 14.2")}


def _gb() -> dict:
    source = sources.BY_PATH["uk-gb-reach/gb_reach_annex_ii.pdf"]
    text = _pdf(sources.require(source.path))
    start = text.find("SECTION 14: Transport information This section")
    body = text[start:text.find("14.5. Environmental hazards", start)]
    act = f"{_structure('uk_clp')['document']}, Annex II"
    return {"binding": True, "fields": {
        "number": _quote(body, r"The UN number \(i\.e\. .+?\) from the UN Model Regulations "
                               r"shall be provided\.", f"{act}, 14.1"),
        "name": _quote(body, r"The UN proper shipping name from the UN Model Regulations shall "
                             r"be provided, unless it was used as the product identifier in "
                             r"subsection 1\.1\.", f"{act}, 14.2"),
        "class": _quote(body, r"The transport hazard class \(and subsidiary risks\) assigned.+?"
                              r"according to the UN Model Regulations shall be provided\.",
                        f"{act}, 14.3"),
        "group": _quote(body, r"The packing group number from the UN Model Regulations shall be "
                              r"provided, if applicable\.", f"{act}, 14.4")}}


def _ghs() -> dict:
    text = _pdf(sources.require("un-ghs/GHS_Rev11_en.pdf"))
    start = text.find("A4.3.14.1 UN Number")
    body = text[start:text.find("A4.3.14.5", start)]
    act = f"{_structure('un_ghs')['document']}, Annex 4"
    return {"binding": False, "fields": {
        "number": _quote(body, r"Provide the UN Number \(i\.e\. four-figure identification number "
                               r"of the substance or article\) from the UN Model Regulations",
                         f"{act}, A4.3.14.1"),
        "name": _quote(body, r"Provide the UN proper shipping name from the UN Model Regulations\. "
                             r"For substances or mixtures the UN proper shipping name should be "
                             r"provided in this subsection if it has not appeared as the GHS "
                             r"product identifier or national or regional identifiers\.",
                       f"{act}, A4.3.14.2"),
        "class": _quote(body, r"Provide the transport class \(and subsidiary risks\) assigned.+?"
                              r"in accordance with the UN Model Regulations\.",
                        f"{act}, A4.3.14.3"),
        "group": _quote(body, r"Provide the packing group number from the UN Model Regulations, "
                              r"if applicable\.", f"{act}, A4.3.14.4")}}


def _au() -> dict:
    source = sources.BY_PATH["australia/model_whs_regulations_2025-12-05.pdf"]
    text = _pdf(sources.require(source.path))
    act = f"{_structure('au_whs')['document']}, Schedule 7, clause 1(2)(n)"
    lead = _quote(text, r"\(2\) A safety data sheet for a hazardous chemical must state the "
                        r"following information about the chemical:", act)
    item = _quote(text, r"\(n\) Section 14: Transport information;", act)
    return {"binding": None, "note": {"quote": f"{lead['quote']} … {item['quote']}",
                                      "citation": act,
                                      "text": "Schedule 7 names Section 14, but none of its "
                                              "fields."}}


def _from_structure(regulation: str, text: str) -> dict:
    optional = _structure(regulation).get("optional") or {}
    if not optional.get("quote"):
        raise SourceUnavailable(f"{regulation}: the structure key quotes no optional content")
    return {"binding": None, "note": {"quote": optional["quote"],
                                      "citation": optional["citation"], "text": text}}


def build(regulation: str, *, use_cache: bool = True) -> dict:
    match regulation:
        case "eu_clp":
            held = _eu(use_cache)
        case "uk_clp":
            held = _gb()
        case "un_ghs":
            held = _ghs()
        case "au_whs":
            held = _au()
        case "ca_whmis":
            held = _from_structure("ca_whmis", "The HPR lets Section 14's content be omitted.")
        case "us_osha":
            held = _from_structure("us_osha", "Appendix D makes Section 14's content "
                                              "non-mandatory.")
        case _:
            raise ValueError(f"no Section 14 rules for {regulation}")
    return {"regulation": regulation, "status": "ok", **held}


def section14_dir() -> Path:
    return data_dir() / "section14"


def write(regulation: str, *, use_cache: bool = True) -> Path:
    held = build(regulation, use_cache=use_cache)
    section14_dir().mkdir(parents=True, exist_ok=True)
    path = section14_dir() / f"{regulation}.json"
    path.write_text(json.dumps(held, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load(regulation: str) -> dict | None:
    path = section14_dir() / f"{regulation}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
