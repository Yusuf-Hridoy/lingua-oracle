"""What each regulation requires Section 16 to say about hazard statements.

Not an answer key: one small file per regulation under data/section16/, read
out of the regulation's own text on safety data sheets and quoted, so the
check that applies it (B-08) can cite it.

Three outcomes, never a fourth:

* ``rule`` - the text says which statements Section 16 must write out, and
  that sentence is quoted;
* ``no_rule`` - the text on Section 16 was read and says nothing about
  statements; the passage read is quoted, so "no rule" is a finding, not a
  guess;
* ``pending_source`` - the text is not on file. Nothing is borrowed from
  another regulation, and the check stays silent.

Where each comes from:

* EU - REACH Annex II, Part A, Section 16, from the consolidated act on CELLAR
  (Annex II is REACH's, not CLP's: CLP sets the classification, REACH the
  safety data sheet).
* GB - GB REACH Annex II, as retained. legislation.gov.uk answers a plain
  request with an AWS WAF challenge, so it is read from a file put on file by
  hand, or is pending.
* US - 29 CFR 1910.1200 Appendix D, item 16.
* Canada - Hazardous Products Regulations, Schedule 1, item 16.
* UN GHS - Annex 4, A4.3.16, of the revision the key is built from.
* Australia - the WHS Regulations' own schedule on safety data sheets is not
  on file; the Purple Book is not Australian law on this point and stands in
  for nothing.
"""

from __future__ import annotations

import html as _html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.common import (
    BROWSER_UA,
    SourceUnavailable,
    fetch,
    strip_markers,
)
from lingua_oracle.registry import data_dir

REGULATIONS = ("eu_clp", "uk_clp", "us_osha", "ca_whmis", "un_ghs", "au_whs")

#: The consolidation of REACH read. Pinned like CLP's, so a rebuild is
#: deterministic; `lingua sources check-updates` is where a newer one shows.
REACH_CELEX = "02006R1907-20260622"
REACH_URL = f"http://publications.europa.eu/resource/celex/{REACH_CELEX}"
APPENDIX_D_URL = ("https://www.osha.gov/laws-regs/regulations/standardnumber/"
                  "1910/1910.1200AppD")

#: The sentence that is the rule, wherever a regulation has one.
_RULE = re.compile(
    r"\(e\)\s*a list of relevant hazard statements[^;]*?not written out in full "
    r"under sections 2 to 15", re.I)


@dataclass
class Section16Rule:
    regulation: str
    status: str            # rule / no_rule / pending_source
    document: str
    section: str
    text: str = ""         # the passage, as printed
    why: str = ""          # for pending_source: what is missing

    @property
    def citation(self) -> str:
        return f"{self.document}, {self.section}"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _html_text(raw: bytes) -> str:
    return _flat(_html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace"))))


def _pdf_text(path: Path) -> list[tuple[int, str]]:
    import pymupdf

    with pymupdf.open(path) as doc:
        return [(n + 1, _flat(page.get_text())) for n, page in enumerate(doc)]


def _eu(use_cache: bool) -> Section16Rule:
    from lxml import html as LH

    document = f"Regulation (EC) No 1907/2006 (REACH), consolidated {REACH_CELEX}"
    try:
        raw = fetch(REACH_URL, headers={"Accept": "application/xhtml+xml",
                                        "Accept-Language": "eng"}, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001 - reported as pending, not swallowed
        return Section16Rule("eu_clp", "pending_source", document, "Annex II",
                             why=f"CELLAR fetch failed: {exc}")
    text = strip_markers(_flat(" ".join(LH.fromstring(raw).itertext())))
    start = text.find("ANNEX II REQUIREMENTS FOR THE COMPILATION OF SAFETY DATA SHEETS")
    section = text.find("SECTION 16: Other information", start)
    found = _RULE.search(text, section) if start >= 0 and section >= 0 else None
    if found is None:
        raise SourceUnavailable("REACH Annex II, Section 16(e) not found in "
                                f"{REACH_CELEX}; the act's layout has changed")
    return Section16Rule("eu_clp", "rule", document,
                         "Annex II, Part A, Section 16(e)", found.group(0))


def _gb() -> Section16Rule:
    source = sources.BY_PATH["uk-gb-reach/gb_reach_annex_ii.pdf"]
    document = ("GB REACH (Regulation (EC) No 1907/2006 as retained), "
                "legislation.gov.uk, document generated 2026-10-08")
    if not source.where.exists():
        return Section16Rule("uk_clp", "pending_source", document, "Annex II",
                             why="not on file: " + sources.describe(source.path))
    pages = _pdf_text(source.where)
    for number, text in pages:
        found = _RULE.search(text)
        if found:
            return Section16Rule("uk_clp", "rule", document,
                                 f"Annex II, Part A, Section 16(e), page {number}",
                                 found.group(0))
    for number, text in pages:
        at = text.find("SECTION 16: Other information")
        if at >= 0:
            return Section16Rule("uk_clp", "no_rule", document,
                                 f"Annex II, Section 16, page {number}",
                                 text[at:at + 600])
    raise SourceUnavailable("GB REACH Annex II on file has no Section 16")


def _osha(use_cache: bool) -> Section16Rule:
    document = "29 CFR 1910.1200 Appendix D"
    local = sources.BY_PATH["us-osha/appendix_d.html"].where
    try:
        raw = local.read_bytes() if local.exists() else fetch(
            APPENDIX_D_URL, headers={"User-Agent": BROWSER_UA}, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001
        return Section16Rule("us_osha", "pending_source", document, "item 16",
                             why=f"Appendix D fetch failed: {exc}")
    text = _html_text(raw)
    found = re.search(r"16\. Other information, including date of preparation or "
                      r"last revision .*?last change to it\.", text)
    if found is None:
        raise SourceUnavailable("Appendix D item 16 not found; the page has changed")
    return _no_rule_or_rule("us_osha", document, "Table D.1, item 16", found.group(0))


def _hpr() -> Section16Rule:
    document = "Hazardous Products Regulations (SOR/2015-17)"
    for number, text in _pdf_text(sources.require("ca-whmis/hpr_bilingual.pdf")):
        found = re.search(r"16 Other information Date of the latest revision of "
                          r"the safety data sheet", text)
        if found:
            return _no_rule_or_rule("ca_whmis", document,
                                    f"Schedule 1, item 16, page {number}", found.group(0))
    raise SourceUnavailable("HPR Schedule 1 item 16 not found")


def _ghs() -> Section16Rule:
    document = "UN GHS Rev.11 (2025)"
    for number, text in _pdf_text(sources.require("un-ghs/GHS_Rev11_en.pdf")):
        found = re.search(r"A4\.3\.16 SECTION 16: Other information .*?"
                          r"included in this section if desired\.", text)
        if found:
            return _no_rule_or_rule("un_ghs", document,
                                    f"Annex 4, A4.3.16, page {number}", found.group(0))
    raise SourceUnavailable("GHS Rev.11 A4.3.16 not found")


def _no_rule_or_rule(regulation: str, document: str, section: str,
                     passage: str) -> Section16Rule:
    """A passage on Section 16 that was read: a rule only if it says one."""
    found = _RULE.search(passage)
    if found:
        return Section16Rule(regulation, "rule", document, section, found.group(0))
    return Section16Rule(regulation, "no_rule", document, section, passage)


def build(regulation: str, *, use_cache: bool = True) -> Section16Rule:
    match regulation:
        case "eu_clp":
            return _eu(use_cache)
        case "uk_clp":
            return _gb()
        case "us_osha":
            return _osha(use_cache)
        case "ca_whmis":
            return _hpr()
        case "un_ghs":
            return _ghs()
        case "au_whs":
            return Section16Rule(
                "au_whs", "pending_source",
                "Work Health and Safety Regulations", "schedule on safety data sheets",
                why="not on file; the GHS edition the key is built from is not "
                    "Australia's rule on safety data sheets")
    raise ValueError(f"no Section 16 source for {regulation}")


def rules_dir() -> Path:
    return data_dir() / "section16"


def write(regulation: str, *, use_cache: bool = True) -> Path:
    rule = build(regulation, use_cache=use_cache)
    rules_dir().mkdir(parents=True, exist_ok=True)
    path = rules_dir() / f"{regulation}.json"
    path.write_text(json.dumps(asdict(rule), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def load(regulation: str) -> Section16Rule | None:
    path = rules_dir() / f"{regulation}.json"
    if not path.exists():
        return None
    return Section16Rule(**json.loads(path.read_text(encoding="utf-8")))
