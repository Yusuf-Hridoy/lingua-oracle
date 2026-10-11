"""Rules a sheet's data and composition are held against beyond the
mixture's cut-off tables, each quoted from the regulation's own text with
where it stands: data/special_rules/<regulation>.json. Not an answer key.

* aspiration - the mixture rule for Category 1: the share of Category 1
  ingredients and the kinematic viscosity at a temperature, read from the
  sentence (CLP 3.10.3.3.1.2; GHS 3.10.3.3.1.2; HPR 8.10; OSHA A.10);
* extreme_ph - "in the absence of any other information" a mixture at pH
  <= 2 or >= 11.5 is Skin Corrosion / Serious Eye Damage Category 1, unless
  its acid/alkaline reserve says otherwise;
* aerosol - into how many categories every aerosol falls;
* gas_method - the method the text points flammable and oxidising gas
  mixtures at (ISO 10156), which is not on file;
* euh - EUH208 (Table 3.4.6's elicitation limits), EUH210, EUH066, EUH071,
  EUH401 (Annex II), EU and GB;
* annex_vi_notes - Annex VI Part 1's notes, by letter, EU and GB.

A rule whose sentence is not found is "not_on_file" and nothing is judged
by it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.common import BROWSER_UA, fetch
from lingua_oracle.registry import data_dir

REGULATIONS = ("eu_clp", "uk_clp", "un_ghs", "au_whs", "ca_whmis", "us_osha")
APPENDIX_A_URL = "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppA"
APPENDIX_B_URL = "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppB"
_NUMBER = re.compile(r"(?<![\w.])(\.?)((?:[A-Z]\.)?\d{1,2}(?:\.\d{1,2}){1,5})\.?(?=\s|[A-Z(‘])")
#: Words before a number that make it a reference, not the paragraph's own.
_REFERENCE = re.compile(r"(?:Sections?|section|see|in|and|of|to|Table|Figure|point|under|"
                        r"paragraph|with|per|Annex)\s*\(?$")


def _flat(text: str) -> str:
    return " ".join((text or "").split())


def _decimal(text: str) -> float:
    return float(text.replace(",", "."))


def _find(text: str, pattern: str, document: str, *, where: str = "", nth: int = 0) -> dict:
    """The sentence, with the paragraph number just before it."""
    found = list(re.finditer(pattern, text))
    if len(found) <= nth:
        return {"status": "not_on_file", "quote": "", "citation": document}
    match = found[nth]
    place = where or _paragraph(text, match.start())
    return {"status": "ok", "quote": _flat(match.group(0)),
            "citation": f"{document}{', ' + place if place else ''}"}


def _paragraph(text: str, at: int) -> str:
    """The paragraph number just before a sentence: not a cross-reference
    ("see Section 3.2.1.2"), and whole - a source that drops a number's first
    part (".10.3.3.1.2.") has it restored from the last whole number before."""
    start = text.rfind(" ", 0, max(0, at - 900)) + 1
    window = text[start:at + 1]
    last_whole, found = "", ""
    for m in _NUMBER.finditer(window):
        if _REFERENCE.search(window[max(0, m.start() - 16):m.start()]):
            continue
        number = m.group(2)
        if m.group(1) and last_whole:
            number = last_whole.split(".")[0] + "." + number
        elif not m.group(1):
            last_whole = number
        found = number
    return found


_ASPIRATION = (r"A mixture is classified (?:as|in) Category 1 when the sum of the concentrations of "
               r"Category 1 ingredients is ≥ ?10 ?%,? and the mixture has a kinematic viscosity "
               r"(?:of )?≤ ?20[.,]5 ?mm ?2 ?/s, measured at 40 ?° ?C\.")
#: The HPR writes the same rule in its own words, as item (a) of 8.10.5.
_ASPIRATION_HPR = (r"A mixture that contains one or more ingredients that are classified as an "
                   r"aspiration toxicant is classified in the category “Aspiration Hazard — "
                   r"Category 1” if \(a\)[^;]{0,400}?kinematic viscosity less than or equal to "
                   r"20\.5 mm2/s, measured at 40 ?°C")
_PH_SKIN = (r"In the absence of any other information, a mixture is considered corrosive"
            r"[^.]{0,60}pH ≤ ?2 or (?:a )?pH ≥ ?11[.,]5\.|A mixture with an extreme pH \(pH ≤ ?2 or ≥ "
            r"?11[.,]5\) is considered corrosive \(Category 1\)[^.]*\.")
_PH_EYE = (r"In the absence of any other information, a mixture is considered to cause serious eye "
           r"damage[^.]{0,30}pH ≤ ?2 or (?:a pH )?≥ ?11[.,]5\.|A mixture with an extreme pH \(pH ≤ ?2 "
           r"or ≥ ?11[.,]5\) is considered to cause serious eye damage \(Category 1\)[^.]*\.")
_AEROSOL = r"Aerosols (?:shall be |are )classified in one of (?:the )?three categories[^.]*\."


def _aspiration(text: str, document: str, pattern: str = _ASPIRATION) -> dict:
    rule = _find(text, pattern, document)
    if rule["status"] == "ok":
        quote = rule["quote"]
        rule["share"] = _decimal(re.findall(r"(\d+(?:\.\d)?) ?%", quote.split("kinematic")[0])[-1])
        rule["viscosity"] = _decimal(re.search(r"(20[.,]5)", quote).group(1))
        rule["temperature"] = _decimal(re.search(r"at (\d+) ?° ?C", quote).group(1))
    return rule


def _ph(text: str, document: str, skin: str = _PH_SKIN, eye: str = _PH_EYE) -> dict:
    out = {"skin": _find(text, skin, document), "eye": _find(text, eye, document)}
    quote = out["skin"]["quote"] or out["eye"]["quote"]
    if quote:
        low, high = re.search(r"(?:≤ ?|equal to )(\w+)[^≥]*?(?:≥ ?|greater than )(11[.,]5)",
                              quote).groups()
        out["low"] = 2.0 if low in ("2", "two") else _decimal(low)
        out["high"] = _decimal(high)
    out["status"] = "ok" if quote else "not_on_file"
    return out


_SCL_SKIN = (r"If there are data showing that \(an\) ingredient\(s\) (?:is/are|may be) corrosive or "
             r"irritant to (?:the )?skin at a concentration of[^.]*?accordingly[^.]*\.")
_SCL_EYE = (r"If there are data showing that \(an\) ingredient\(s\) may be corrosive to the skin or "
            r"seriously damaging to the eye[^.]*?accordingly[^.]*\.")


def _scl(text: str, document: str, *, listed: bool) -> dict:
    """How the skin and eye summations take an ingredient with a specific
    limit: classified accordingly; and, for a list, that its limits must be
    used and the generic ones where it gives none for a category."""
    out = {"skin": _find(text, _SCL_SKIN, document), "eye": _find(text, _SCL_EYE, document)}
    if listed:
        # Both under Annex VI Part 1's heading "1.1.2.3. Specific concentration
        # limits, M-factors and Acute Toxicity Estimates (ATE)" - which the GB
        # PDF prints as ".1.2.3.", so the place is named from the heading.
        where = ("Annex VI, Part 1, 1.1.2.3" if re.search(
            r"\.?1?\.1\.2\.3\.\s?Specific concentration limits, M-factors and Acute Toxicity "
            r"Estimates", text) else "Annex VI, Part 1")
        out["list_use"] = _find(text, r"The SCLs and harmonised ATEs must be used by the "
                                      r"manufacturer, importer or downstream user for the "
                                      r"classification of a mixture containing this substance\.",
                                document, where=where)
        out["list_generic"] = _find(text, r"Where no specific concentration limits are given in "
                                          r"(?:this Annex|the list) for a certain category, the "
                                          r"generic concentration limits given in Annex I must be "
                                          r"applied[^.]*\.", document, where=where)
    out["status"] = "ok" if out["skin"]["status"] == "ok" or out["eye"]["status"] == "ok" \
        else "not_on_file"
    return out


def _gas_method(text: str, document: str) -> dict:
    flammable = _find(text, r"[^.]*(?:calculation|tests?)[^.]*ISO 10156[^.]*\.", document)
    return {**flammable, "method": "ISO 10156"} if flammable["status"] == "ok" else flammable


def _euh(text: str, document: str) -> dict:
    annex = f"{document}, Annex II"
    q = r"[‘'\"“] ?"
    euh208 = _find(text, r"The label on the packaging of mixtures not classified as sensitising but "
                         r"containing at least one substance classified as sensitising and present "
                         r"in a concentration equal to or greater than that specified in Table "
                         rf"3\.4\.6 of Annex I shall bear the statement: EUH208 — {q}Contains "
                         r"\(name of sensitising substance\)\. May produce an allergic reaction ?.",
                   annex, where="2.8")
    table = re.search(r"Table 3\.4\.6 Concentration limits for elicitation.{0,1600}", text)
    limits = {}
    if table:
        for kind, sub, value in re.findall(r"(Respiratory|Skin) sensitiser (?:Category 1|Sub-category "
                                           r"(1A|1B)) ≥ ([\d,]+) ?%", table.group(0)):
            limits.setdefault(f"{kind.lower()} {sub or '1'}", _decimal(value))
        tenth = re.search(r"For sensitising substances with[^.]*one tenth[^.]*\.", table.group(0))
        euh208["scl_rule"] = _flat(tenth.group(0)) if tenth else ""
    euh208["limits"] = limits
    euh208["limits_citation"] = f"{document}, Annex I, Table 3.4.6"
    euh210 = _find(text, r"2\.10\. Mixtures not intended for the general public For mixtures not "
                         rf"classified as hazardous but which contain:.+?EUH210 — {q}Safety data "
                         r"sheet available on request.", annex, where="2.10")
    # Each "— ≥ ..." of 2.10, whole, as the text sets it out.
    body = euh210["quote"].split("which contain:", 1)[-1].split("the label on the packaging")[0]
    euh210["conditions"] = [_flat(item).rstrip(" ;,") for item in re.split(r"\s—\s", body)
                            if item.strip().startswith(("≥", "at least"))]
    euh066 = _find(text, rf"EUH066 — {q}Repeated exposure may cause skin dryness or cracking.{{1,2}} "
                         r"For substances and mixtures which may cause concern.+?relevant evidence "
                         r"concerning their predicted effects on the skin\.", annex)
    euh071 = _find(text, rf"EUH071 — {q}Corrosive to the respiratory tract.{{1,2}} For substances and "
                         r"mixtures in addition to classification for inhalation toxicity.+?which "
                         r"may be inhaled\.", annex)
    euh401 = _find(text, r"PART 4: SPECIAL RULE FOR LABELLING OF PLANT PROTECTION PRODUCTS.+?EUH401 "
                         rf"— {q}To avoid risks to human health and the environment, comply with the "
                         r"instructions for use.", annex, where="Part 4")
    return {"EUH208": euh208, "EUH210": euh210, "EUH066": euh066, "EUH071": euh071,
            "EUH401": euh401}


def _notes(text: str, document: str) -> dict:
    """Annex VI Part 1, 1.1.3: what each note means. Not in the GB text on
    file (the GB MCL took Annex VI's place), so nothing there."""
    anchor = text.find("Notes relating to the identification, classification and labelling of "
                       "substances Note A:")
    start = text.find("Note A:", anchor) if anchor >= 0 else -1
    block = text[start:start + 40000] if start >= 0 else ""
    out = {}
    for letter, table, body in re.findall(r"Note ([A-Z]{1,2})( \(Table 3\))?: (.+?)(?= Note [A-Z]{1,2}"
                                          r"(?: \(Table 3\))?:| 1\.1\.3\.2| 1\.1\.4| 1\.2\.| PART 2"
                                          r"| Part 2|$)", block):
        out.setdefault(letter, {"quote": _flat(f"Note {letter}{table}: {body}")[:1500],
                                "citation": f"{document}, Annex VI, Part 1, 1.1.3"})
    return out


def _whs_adoption() -> list[dict]:
    """That the WHS Regulations themselves take in the GHS's hazard classes -
    aerosols among them, not only under the transport rules: "GHS" is Rev.7,
    "hazardous chemical" is any GHS class but the ones it lists, and Schedule
    11 counts aerosols by category."""
    import pymupdf

    source = sources.BY_PATH["australia/model_whs_regulations_2025-12-05.pdf"]
    with pymupdf.open(sources.require(source.path)) as pdf:
        text = _flat(" ".join(page.get_text() for page in pdf))
    act = source.version or "Model Work Health and Safety Regulations"
    out = []
    for pattern, place in (
        (r"GHS means the Globally Harmonised System of Classification and Labelling of Chemicals, "
         r"Seventh revised edition, published by the United Nations as modified under Schedule 6\.",
         "regulation 5(1), “GHS”"),
        (r"hazardous chemical means a substance, mixture or article that satisfies the criteria for "
         r"any one or more hazard classes in the GHS.+?hazardous to the ozone layer\.",
         "regulation 5(1), “hazardous chemical”"),
        (r"43 Aerosols Category 1, category 2, category 3 or any combination of categories 1, 2 "
         r"and 3", "Schedule 11, table 11.1, item 43"),
    ):
        found = _find(text, pattern, act, where=place)
        if found["status"] == "ok":
            out.append({"quote": found["quote"], "citation": found["citation"]})
    return out


def _text(regulation: str, use_cache: bool) -> tuple[str, dict[str, tuple[str, str]]]:
    """(document, {part: (name, text)}) - the parts each rule is read from."""
    from lingua_oracle.keys.builders.hazard_criteria import _clp_text, _ghs_text

    if regulation in ("eu_clp", "uk_clp"):
        document, text = _clp_text(regulation)
        return document, {"all": (document, text)}
    if regulation in ("un_ghs", "au_whs"):
        document, text = _ghs_text(regulation == "un_ghs")
        if regulation == "au_whs":
            document = f"{document}, as adopted by the WHS Regulations"
        return document, {"all": (document, text)}
    if regulation == "ca_whmis":
        import pymupdf

        document = "Hazardous Products Regulations (SOR/2015-17)"
        with pymupdf.open(sources.require("ca-whmis/hpr_bilingual.pdf")) as pdf:
            text = _flat(" ".join(page.get_text() for page in pdf))
        return document, {"all": (document, text)}
    import html as _html

    def appendix(url: str) -> str:
        raw = fetch(url, headers={"User-Agent": BROWSER_UA}, use_cache=use_cache)
        return _flat(_html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace"))))

    return "29 CFR 1910.1200", {"A": ("29 CFR 1910.1200 Appendix A", appendix(APPENDIX_A_URL)),
                                "B": ("29 CFR 1910.1200 Appendix B", appendix(APPENDIX_B_URL))}


def build(regulation: str, *, use_cache: bool = True) -> dict:
    document, parts = _text(regulation, use_cache)
    health = parts.get("A") or parts["all"]
    physical = parts.get("B") or parts["all"]
    out = {"regulation": regulation, "document": document}
    out["aspiration"] = (_aspiration(health[1], health[0], _ASPIRATION_HPR)
                         if regulation == "ca_whmis" else _aspiration(health[1], health[0]))
    if regulation == "ca_whmis":
        out["extreme_ph"] = _ph(
            health[1], health[0],
            skin=r"A (?:mixture|substance) for which the pH is less than or equal to two or equal "
                 r"to or greater than 11\.5 is classified in the category “Skin Corrosion — "
                 r"Category 1”[^.]*\.",
            eye=r"A (?:mixture|substance) for which the pH is less than or equal to two or equal to "
                r"or greater than 11\.5 is classified in the category “Serious Eye Damage — "
                r"Category 1”[^.]*\.")
    else:
        out["extreme_ph"] = _ph(health[1], health[0])
    out["aerosol"] = _find(physical[1], _AEROSOL if regulation != "ca_whmis" else
                           r"An aerosol is classified in a category of this hazard class in "
                           r"accordance with the following table", physical[0])
    if out["aerosol"]["status"] == "ok":
        counted = set(re.findall(r"Aerosols — Category (\d)", physical[1]))
        out["aerosol"]["categories"] = len(counted) if counted else 3
    if regulation == "au_whs" and out["aerosol"]["status"] == "ok":
        out["aerosol"]["adoption"] = _whs_adoption()
    out["gas_method"] = _gas_method(physical[1], physical[0])
    out["scl"] = _scl(health[1], health[0], listed=regulation in ("eu_clp", "uk_clp"))
    if regulation in ("eu_clp", "uk_clp"):
        out["euh"] = _euh(parts["all"][1], document)
        out["annex_vi_notes"] = _notes(parts["all"][1], document)
    return out


def rules_dir() -> Path:
    return data_dir() / "special_rules"


def write(regulation: str, *, use_cache: bool = True) -> Path:
    held = build(regulation, use_cache=use_cache)
    rules_dir().mkdir(parents=True, exist_ok=True)
    path = rules_dir() / f"{regulation}.json"
    path.write_text(json.dumps(held, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load(regulation: str) -> dict | None:
    path = rules_dir() / f"{regulation}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
