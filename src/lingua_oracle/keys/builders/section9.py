"""What each regulation's text says Section 9 must give for the physical
state, in its own words: data/section9/<regulation>.json. Not an answer key.

* eu_clp - REACH Annex II 9.1(a), "shall generally be indicated";
* uk_clp - GB REACH Annex II 9.1(a) "Appearance: The physical state ...",
  under "shall be clearly identified";
* un_ghs - Rev.11 Table A4.3.9.1, "Physical state", in a text that
  recommends ("should be indicated");
* ca_whmis - HPR Schedule 1, item 9(a), "physical state";
* us_osha - Appendix D, Table D.1, 9(a) "Physical state", under "each
  section of the SDS must contain all of the specified information";
* au_whs - Schedule 7 lists no Section 9 items: no quote.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.common import BROWSER_UA, SourceUnavailable, fetch, strip_markers
from lingua_oracle.keys.builders.section14 import _flat, _pdf, _quote, _structure
from lingua_oracle.registry import data_dir

REGULATIONS = ("eu_clp", "uk_clp", "un_ghs", "au_whs", "ca_whmis", "us_osha")


def _eu(use_cache: bool) -> dict:
    from lxml import html as LH

    from lingua_oracle.keys.builders.section16 import REACH_URL

    raw = fetch(REACH_URL, headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"},
                use_cache=use_cache)
    text = strip_markers(_flat(" ".join(LH.fromstring(raw).itertext())))
    starts = [m.start() for m in re.finditer(
        "ANNEX II REQUIREMENTS FOR THE COMPILATION OF SAFETY DATA SHEETS", text)]
    body = text[starts[-1]:] if starts else ""
    return {"binding": True, "item": _quote(
        body, r"\(a\) Physical state The physical state \(gas, liquid or solid\) shall generally "
              r"be indicated at standard conditions of temperature and pressure\.",
        f"{_structure('eu_clp')['document']}, Annex II, 9.1(a)")}


def _gb() -> dict:
    text = _pdf(sources.require("uk-gb-reach/gb_reach_annex_ii.pdf"))
    start = text.find("9.1. Information on basic physical and chemical properties")
    body = text[start:start + 3000]
    lead = _quote(body, r"The following properties shall be clearly identified", "")
    item = _quote(body, r"\(a\) Appearance: The physical state \(solid .+?\), liquid, gas\) and "
                        r"the colour of the substance or mixture as supplied",
                  f"{_structure('uk_clp')['document']}, Annex II, 9.1(a)")
    return {"binding": True, "item": {"quote": f"{lead['quote']} … {item['quote']}",
                                      "citation": item["citation"]}}


def _ghs() -> dict:
    text = _pdf(sources.require("un-ghs/GHS_Rev11_en.pdf"))
    start = text.find("Table A4.3.9.1: Basic physical and chemical properties")
    body = text[start:start + 3000]
    lead = _quote(body, r"Relevant information as required should be indicated for every property "
                        r"listed in this table", "")
    item = _quote(body, r"Physical state − generally at standard conditions",
                  f"{_structure('un_ghs')['document']}, Annex 4, Table A4.3.9.1")
    return {"binding": False, "item": {"quote": f"{lead['quote']} … {item['quote']}",
                                       "citation": item["citation"]}}


def _hpr() -> dict:
    text = _pdf(sources.require("ca-whmis/hpr_bilingual.pdf"))
    return {"binding": True, "item": _quote(
        text, r"Physical and chemical properties \(a\) physical state;",
        f"{_structure('ca_whmis')['document']}, Schedule 1, item 9(a)")}


def _osha(use_cache: bool) -> dict:
    from lingua_oracle.keys.builders.section16 import APPENDIX_D_URL

    local = sources.BY_PATH["us-osha/appendix_d.html"].where
    raw = local.read_bytes() if local.exists() else fetch(
        APPENDIX_D_URL, headers={"User-Agent": BROWSER_UA}, use_cache=use_cache)
    text = _flat(re.sub(r"<[^>]+>|&nbsp;", " ", raw.decode("utf-8", "replace")))
    lead = _quote(text, r"While each section of the SDS must contain all of the specified "
                        r"information", "")
    item = _quote(text, r"9\. Physical and chemical properties †? ?\(a\) Physical state\.",
                  "29 CFR 1910.1200 Appendix D, Table D.1, 9(a)")
    return {"binding": True, "item": {"quote": f"{lead['quote']} … {item['quote']}",
                                      "citation": item["citation"]}}


def build(regulation: str, *, use_cache: bool = True) -> dict:
    match regulation:
        case "eu_clp":
            held = _eu(use_cache)
        case "uk_clp":
            held = _gb()
        case "un_ghs":
            held = _ghs()
        case "ca_whmis":
            held = _hpr()
        case "us_osha":
            held = _osha(use_cache)
        case "au_whs":
            held = {"binding": None, "item": None,
                    "why": "Schedule 7 names Section 9 but lists none of its items."}
        case _:
            raise SourceUnavailable(f"no Section 9 rules for {regulation}")
    return {"regulation": regulation, "status": "ok", **held}


def section9_dir() -> Path:
    return data_dir() / "section9"


def write(regulation: str, *, use_cache: bool = True) -> Path:
    held = build(regulation, use_cache=use_cache)
    section9_dir().mkdir(parents=True, exist_ok=True)
    path = section9_dir() / f"{regulation}.json"
    path.write_text(json.dumps(held, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load(regulation: str) -> dict | None:
    path = section9_dir() / f"{regulation}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
