"""Official lists Sections 14 and 15 are held against, from their own sources.

Not answer keys: data/lists/<name>.json.

* svhc_candidate - the ECHA Candidate List of substances of very high
  concern (REACH Article 59(1)), from ECHA's own export: substance name,
  EC and CAS numbers, reason for inclusion and date. A CAS number whose
  check digit is wrong is kept as printed and flagged.
* us_dot_hmt - the US DOT Hazardous Materials Table, 49 CFR 172.101, from
  eCFR (pinned version): identification number, proper shipping name,
  hazard class, label codes, packing groups, special provisions - with the
  Class 3 definition of 49 CFR 173.120 quoted beside it.
* un_dangerous_goods - the Dangerous Goods List of the UN Model
  Regulations, Vol. I, chapter 3.2: read from the PDF where it is on file,
  "pending_source" where it is not.

Builds are deterministic: the same source gives byte-identical files.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.common import fetch
from lingua_oracle.registry import data_dir

LISTS = ("svhc_candidate", "us_dot_hmt", "un_dangerous_goods")
ECFR_DATE = "2026-09-08"
HMT_URL = (f"https://www.ecfr.gov/api/versioner/v1/full/{ECFR_DATE}/title-49.xml"
           "?part=172&section=172.101")
CLASS_3_URL = (f"https://www.ecfr.gov/api/versioner/v1/full/{ECFR_DATE}/title-49.xml"
               "?part=173&section=173.120")


def _flat(text: str) -> str:
    return " ".join((text or "").split())


def cas_valid(cas: str) -> bool:
    """The CAS check digit: the last digit is the sum of the others, each
    weighted by its place from the right, modulo 10."""
    found = re.fullmatch(r"(\d{2,7})-(\d{2})-(\d)", cas or "")
    if not found:
        return False
    digits = (found.group(1) + found.group(2))[::-1]
    return sum((k + 1) * int(d) for k, d in enumerate(digits)) % 10 == int(found.group(3))


# -- the Candidate List --------------------------------------------------------------

def _svhc() -> dict:
    from lingua_oracle.keys.builders import xlsx

    source = sources.BY_PATH["eu-echa/candidate_list_export_2026-10-09.xlsx"]
    path = sources.require(source.path)
    rows = xlsx.rows(path)
    exported = next((r.get("A", "") for r in xlsx.rows(path, "criteria")
                     if (r.get("A") or "").startswith("Export date")), "")
    header = next(k for k, r in enumerate(rows) if r.get("A") == "Substance name")
    entries, invalid = [], []
    last: dict = {}
    for row in rows[header + 1:]:
        name = _flat(row.get("A", ""))
        if not name and not row.get("D") and not row.get("C"):
            continue
        # "Group entries are split in different rows": a row without a name
        # belongs to the entry above it.
        base = {"name": name, "description": _flat(row.get("B", "")),
                "reason": _flat(row.get("E", "")), "date": _iso(row.get("F", ""))}
        if not name:
            base = {k: v or last.get(k, "") for k, v in base.items()}
        last = base
        ec = re.findall(r"\d{3}-\d{3}-\d", row.get("C", "") or "")
        cas = re.findall(r"\d{2,7}-\d{2}-\d", row.get("D", "") or "")
        for c in cas:
            if not cas_valid(c):
                invalid.append(c)
        entries.append(dict(base, ec=ec, cas=cas))
    return {"list": "svhc_candidate", "status": "ok",
            "document": "ECHA Candidate List of substances of very high concern for "
                        "authorisation (REACH Article 59(1))",
            "version": f"{exported.replace('Export date: ', 'export of ')}",
            "source": source.path, "entries": entries, "invalid_cas": sorted(set(invalid)),
            # What REACH Annex II requires of a Candidate List substance in a
            # mixture, quoted from the consolidated act.
            "annex_ii": _annex_ii()}


def _iso(date: str) -> str:
    date = (date or "").strip()
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date, fmt).date().isoformat()
        except ValueError:
            continue
    return date


def _annex_ii() -> dict[str, dict]:
    """The Annex II sentences, read from the REACH text on file."""
    from lxml import html as LH

    from lingua_oracle.keys.builders.common import strip_markers
    from lingua_oracle.keys.builders.section16 import REACH_CELEX, REACH_URL

    raw = fetch(REACH_URL, headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"})
    text = strip_markers(" ".join(" ".join(LH.fromstring(raw).itertext()).split()))
    starts = [m.start() for m in re.finditer(
        "ANNEX II REQUIREMENTS FOR THE COMPILATION OF SAFETY DATA SHEETS", text)]
    body = text[starts[-1]:starts[-1] + 120000] if starts else ""
    act = f"Regulation (EC) No 1907/2006 (REACH), consolidated {REACH_CELEX}, Annex II"
    out = {}
    patterns = {
        "3.2.1(c)": r"\(c\) provided that the concentration of an individual substance is equal "
                    r"to or greater than 0,1 %, substances that meet any of the following "
                    r"criteria:.+?for reasons other than the hazards referred to in point \(a\) "
                    r"of this subsection such as endocrine disrupting properties,",
        "3.2.1(a)": r"3\.2\.1\. For a mixture meeting the criteria for classification in accordance "
                    r"with Regulation \(EC\) No 1272/2008, the following substances \(see also "
                    r"Table 1\.1\) shall be indicated, together with their concentration or "
                    r"concentration range in the mixture:",
        "2.3": r"Information shall be provided on whether the substance meets the criteria for "
               r"persistent, bioaccumulative and toxic.+?For a mixture, information shall be "
               r"provided for each such substance that is present in the mixture at a "
               r"concentration equal to or greater than 0,1 % by weight\.",
        "15.1": r"15\.1\. Safety, health and environmental regulations/legislation specific for "
                r"the substance or mixture Information shall be provided regarding relevant Union "
                r"safety, health and environmental provisions[^.]*\.",
    }
    for key, pattern in patterns.items():
        found = re.search(pattern, body)
        if found:
            out[key] = {"quote": " ".join(found.group(0).split()),
                        "citation": f"{act}, {key}"}
    return out


# -- the DOT Hazardous Materials Table ----------------------------------------------

def _hmt(use_cache: bool) -> dict:
    from lxml import etree

    raw = fetch(HMT_URL, use_cache=use_cache)
    root = etree.fromstring(raw)
    entries: list[dict] = []
    for row in root.iter("TR"):
        tds = row.findall("TD")
        cells = [_flat("".join(td.itertext())) for td in tds]
        if len(cells) < 7:
            continue
        symbols, name, hazard_class, number, group, labels, provisions = cells[:7]
        if not name and entries and not number:
            # A further packing group of the entry above.
            if group and group not in entries[-1]["packing_groups"]:
                entries[-1]["packing_groups"].append(group)
            continue
        if not re.fullmatch(r"(?:UN|NA)\d{4}", number or ""):
            continue                       # "see ..." and forbidden rows have no number
        readings, unsure = _roman(tds[1])
        entries.append({"id": number, "name": name, "proper_shipping_names": readings,
                        "names_unsure": unsure,
                        "class": hazard_class,
                        "symbols": symbols, "labels": [x.strip() for x in labels.split(",")
                                                       if x.strip()],
                        "packing_groups": [group] if group else [],
                        "special_provisions": [x.strip() for x in provisions.split(",")
                                               if x.strip()]})
    class_3 = _flat(re.sub(r"<[^>]+>", " ", fetch(CLASS_3_URL, use_cache=use_cache)
                           .decode("utf-8", "replace")))
    definition = re.search(r"\(a\) Flammable liquid\. For the purpose of this subchapter, a "
                           r"flammable liquid \(Class 3\) means a liquid having a flash point of "
                           r"not more than 60 °C \(140 °F\).*?\.(?= |$)", class_3)
    text = _flat(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace")))
    names = {}
    for key, pattern in {
        "c": r"Proper shipping names are limited to those shown in Roman type \(not italics\)\.",
        "c1": r"\(1\) Proper shipping names may be used in the singular or plural.+?may not be "
              r"used in place of the word “flammable”\.",
        "c2": r"\(2\) Punctuation marks and words in italics are not part of the proper shipping "
              r"name.+?as appropriate\.",
    }.items():
        found = re.search(pattern, text)
        names[key] = {"quote": found.group(0) if found else "",
                      "citation": f"49 CFR 172.101({key[0]}){'(' + key[1:] + ')' if key[1:] else ''}"
                                  f", eCFR as of {ECFR_DATE}"}
    return {"list": "us_dot_hmt", "status": "ok",
            "document": "49 CFR 172.101, Hazardous Materials Table",
            "version": f"eCFR as of {ECFR_DATE}", "source": HMT_URL, "entries": entries,
            # What a proper shipping name is, in 172.101(c)'s own words.
            "name_rules": names,
            "class_3": {"quote": _flat(definition.group(0)) if definition else "",
                        "citation": f"49 CFR 173.120(a), eCFR as of {ECFR_DATE}"}}


def _roman(cell) -> tuple[list[str], bool]:
    """The proper shipping names a column 2 cell allows: its Roman type
    (172.101(c)), each italic "or" a choice "in the sequence" - which words
    it binds is not marked, so every plausible reading is kept, the way the
    template matcher keeps every split of a slash. Unsure where a choice
    binds words before it: which words, the cell does not mark."""
    parts: list[tuple[bool, str]] = [(False, cell.text or "")]
    for child in cell:
        parts.append((child.tag == "E", "".join(child.itertext())))
        parts.append((False, child.tail or ""))
    groups: list[str] = [""]
    choice = False
    for italic, text in parts:
        text = _flat(text)
        if not text:
            continue
        if italic:
            choice = choice or text.strip(" ,") == "or"
            continue
        if choice:
            groups.append(text)
            choice = False
        else:
            groups[-1] = f"{groups[-1]} {text}".strip()
    # 172.101(c)(2)'s own examples: a choice beginning with a capital stands
    # alone ("Carbon dioxide, solid or Dry ice"); one in lower case binds the
    # last words before it ("Articles, pressurized pneumatic or hydraulic").
    readings = groups[:1]
    unsure = False
    for before, after in zip(groups, groups[1:], strict=False):
        if after[:1].isupper() or after[:1] in "(0123456789":
            readings.append(after)
            continue
        unsure = True
        words = before.split()
        readings += [" ".join(words[:k] + [after]) for k in range(1, len(words))]
    out = []
    for r in readings:
        r = _flat(r).strip(" ,;")
        if r and r not in out:
            out.append(r)
    return out, unsure


# -- the UN Dangerous Goods List ----------------------------------------------------

def _un() -> dict:
    source = sources.BY_PATH["un-model-regulations/model_regulations_vol1.pdf"]
    if not source.where.exists():
        return {"list": "un_dangerous_goods", "status": "pending_source",
                "document": "UN Model Regulations, Vol. I, chapter 3.2 (Dangerous Goods List)",
                "why": "not on file: " + sources.describe(source.path), "entries": []}
    raise NotImplementedError("the UN Dangerous Goods List reader is written once the "
                              "PDF is on file and its layout can be read")


def build(name: str, *, use_cache: bool = True) -> dict:
    match name:
        case "svhc_candidate":
            return _svhc()
        case "us_dot_hmt":
            return _hmt(use_cache)
        case "un_dangerous_goods":
            return _un()
    raise ValueError(f"no list called {name}")


def lists_dir() -> Path:
    return data_dir() / "lists"


def write(name: str, *, use_cache: bool = True) -> Path:
    held = build(name, use_cache=use_cache)
    lists_dir().mkdir(parents=True, exist_ok=True)
    path = lists_dir() / f"{name}.json"
    path.write_text(json.dumps(held, indent=1, ensure_ascii=False, sort_keys=False) + "\n",
                    encoding="utf-8")
    return path


def load(name: str) -> dict | None:
    path = lists_dir() / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
