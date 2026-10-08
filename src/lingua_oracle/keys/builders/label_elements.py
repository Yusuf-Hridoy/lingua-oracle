"""Label elements per hazard class and category, from each regulation's text.

Not an answer key: data/label_elements/<reg>.json. For every class and
category its text assigns label elements to - signal word, hazard statement
codes, pictograms - with the precedence rules the text states, each quoted
and located. A class whose table cannot be read is listed under `unparsed`
and is not checked: nothing is filled in from another text.

* EU, GB - CLP Annex I label tables ("Label elements for ..."); pictogram
  codes from Annex V (the tables print them as images); the class and
  category codes a sheet writes ("Flam. Liq. 2") from Annex VI, Table 1.1;
  precedence from Article 26 and the Annex I paragraph applying Article 27.
* UN GHS (Rev.11), Australia and Canada (Rev.7) - Annex 1 for the category,
  signal word and hazard statement code; the chapter's label table for the
  symbol, named in words; precedence from 1.4.10.5.3. Canada's HPR, section
  3(1)(c), points at the GHS for these elements; Australia's exclusions are
  the Safe Work Australia guidance's.
* US - 29 CFR 1910.1200 Appendix C, class by class, the statements matched
  to codes through the OSHA answer key; precedence from C.2.1.

Pictograms are codes where the text has codes (CLP: 'GHS02') and names
where it names them (the GHS, OSHA: "Flame"). Neither is translated into
the other.
"""

from __future__ import annotations

import html as _html
import json
import re
from dataclasses import asdict, dataclass, field
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
_CODE = re.compile(r"\b(EUH\d{3}[A-Za-z]*|H\d{3}[A-Za-z]*)\b")


@dataclass
class Rule:
    binding: bool
    quote: str
    citation: str


@dataclass
class Entry:
    section: str              # the text's own section or table group: "2.6"
    hazard_class: str         # as the text names it: "flammable liquids"
    category: list[str]       # every name the category goes by: ["1", "1A"]
    subclass: str = ""        # "oral", "aquatic chronic", "skin sensitisation"
    codes: list[str] = field(default_factory=list)       # "Flam. Liq. 2", where the text has them
    h_codes: list[str] = field(default_factory=list)
    signal: str = ""          # "Danger" / "Warning" / "" (none)
    pictograms: list[str] = field(default_factory=list)
    source: str = ""


@dataclass
class Precedence:
    """One rule of precedence: if `when` applies, `drop` does not appear (or
    may be left out), optionally only where `drop` is there for `only_for`."""

    when: list[str]
    drop: str
    effect: str               # "not_appear" / "optional" / "may_omit"
    only_for: list[str]
    rule: Rule
    #: Where `when` counts only when it is there for these classes.
    when_for: list[str] = field(default_factory=list)


@dataclass
class LabelElements:
    regulation: str
    document: str
    status: str = "ok"
    why: str = ""
    pictogram_kind: str = "code"        # "code" or "name"
    pictogram_names: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    signal_rule: Rule | None = None
    pictogram_rules: list[Precedence] = field(default_factory=list)
    statement_rules: list[Precedence] = field(default_factory=list)
    #: What the regulation does not adopt, quoted: "aquatic acute 1-3".
    not_adopted: list[dict] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _verb(quote: str) -> bool:
    return bool(re.search(r"\b(shall|must)\b", quote.lower()))


# -- categories as the tables name them --------------------------------------------

_CATEGORY = re.compile(
    r"Sub-Categories (?:1A/1B/1C|1A, 1B, 1C) and Category 1"
    r"|Category \d[A-C]?(?:/\d[A-C])?(?: ?\(Category [^)]*\))?(?: and sub-?categories (?:1A and 1B|1A, 1B(?: and 1C)?))?"
    r"|Type [A-G](?: (?:&|and) [A-G])?"
    r"|Division \d\.\d"
    r"|Unstable [Ee]xplosives?"
    r"|Additional category for effects on or via lactation"
    r"|(?:Compressed|Liquefied|Refrigerated liquefied|Dissolved) gas"
    r"|Acute \d|Chronic \d"
    r"|\bP[BM]T\b|\bvP[vB][BM]\b")


def category_names(label: str) -> list[str]:
    """Every name a table's category column goes by, as a sheet might write
    its category: "Sub-Categories 1A/1B/1C and Category 1" -> 1, 1A, 1B, 1C."""
    label = label.strip()
    out: list[str] = []
    if label.lower().startswith("unstable"):
        return ["Unst."]
    if label.lower().startswith("additional category"):
        return ["Lact."]
    if re.match(r"(Compressed|Liquefied|Refrigerated|Dissolved)", label):
        return [label.lower()]
    if label in ("PBT", "vPvB", "PMT", "vPvM"):
        return [label]
    division = re.match(r"Division (\d\.\d)", label)
    if division:
        return [division.group(1)]
    types = re.match(r"Type ([A-G])(?: (?:&|and) ([A-G]))?", label)
    if types:
        letters = [x for x in types.groups() if x]
        return letters + (["".join(letters)] if len(letters) > 1 else [])
    for found in re.findall(r"\d[A-C]?", label):
        if found not in out:
            out.append(found)
    return out


# -- EU and GB: CLP's own tables -------------------------------------------------

_CLP_TABLE = re.compile(
    r"(?:TABLE|Table) (?P<number>\d\.\d{1,2}\.\d)\.?\s+"
    r"(?:Label elements (?:for|of) (?P<a>[^.]+?)|(?P<b>[A-Z][^.]+?) label elements)\s+"
    r"(?:\(\s*\)\s+)?(?:\(\d\)\s+)?(?P<body>(?:(?:Respiratory|Skin) sensitisation\s+)*"
    r"(?:Classification|SHORT-TERM|Category \d|P[BM]T vP[vB][BM]|Hazard Statement).+?)"
    r"(?=\s(?:TABLE|Table) \d|\s\d\.\d{1,2}\.\d\.?\s[A-Z]|$)")


def _segments(body: str) -> list[tuple[str, str]]:
    """A label table split into its blocks: aquatic short- and long-term."""
    parts = re.split(r"(SHORT-TERM \(ACUTE\) AQUATIC HAZARD|LONG-TERM \(CHRONIC\) AQUATIC HAZARD)",
                     body)
    if len(parts) == 1:
        return [("", body)]
    out = []
    for k in range(1, len(parts), 2):
        out.append(("aquatic acute" if "SHORT" in parts[k] else "aquatic chronic",
                    parts[k + 1]))
    return out


def _clp_entries(text: str, document: str, unparsed: list[str]) -> list[Entry]:
    entries: list[Entry] = []
    # A table broken over a page has its caption printed again: its parts,
    # joined, are the table.
    tables: dict[str, list] = {}
    for table in _CLP_TABLE.finditer(text):
        name = (table.group("a") or table.group("b") or "").strip().lower()
        tables.setdefault(table.group("number"), [name, ""])[1] += " " + table.group("body")
    for number, (name, whole) in tables.items():
        section = ".".join(number.split(".")[:2])
        for subclass, body in _segments(whole.strip()):
            body = body.split("Precautionary Statement")[0]
            head = re.split(r"GHS Pictograms?|Symbol/pictogram|Signal Word", body)[0]
            signals = re.findall(r"Danger|Warning|No signal word",
                                 body.split("Signal Word", 1)[-1].split("Hazard Statement")[0])
            statements = body.split("Hazard Statement", 1)[-1]
            labels = [m.group(0) for m in _CATEGORY.finditer(head)]
            # A footnote printed inside the header repeats a label: once each -
            # unless the columns really do share it (one per class).
            if len(labels) > len(signals) + 1:
                labels = list(dict.fromkeys(labels))
            if not labels and subclass:
                labels = re.findall(r"(?:Acute|Chronic) \d", head)
            # A table naming two classes over its columns (respiratory and
            # skin sensitisation) gives each column its class.
            column_classes = re.findall(r"(Respiratory sensitisation|Skin sensitisation)", head)
            codes = re.findall(r"(EUH\d{3}[A-Za-z]*|H\d{3}[A-Za-z]*)\s*(?::|(?=\s[A-Z]))",
                               statements)
            routes = re.findall(r"— (Oral|Dermal|Inhalation)", statements)
            n = len(labels)
            if not n or not codes or not (n - 1 <= len(signals) <= n + 1):
                unparsed.append(f"{document}, Table {number} ({name}): columns not read")
                continue
            # A column with no signal word printed - Type G, Division 1.6 - has
            # no statement either.
            signals = (signals + ["No signal word"] * n)[:n]
            columns = _columns(codes, n, signals)
            if columns is None:
                unparsed.append(f"{document}, Table {number} ({name}): "
                                f"{len(codes)} codes for {n} categories")
                continue
            for k, label in enumerate(labels):
                for r, group in enumerate(columns[k]):
                    route = routes[r].lower() if routes and r < len(routes) and \
                        len(columns[k]) == len(routes) else ""
                    sub = subclass or (column_classes[k].lower() if len(column_classes) == n
                                       else "") or route
                    entries.append(Entry(
                        section=section, hazard_class=name, category=category_names(label),
                        subclass=sub, h_codes=group,
                        signal="" if signals[k] == "No signal word" else signals[k],
                        source=f"{document}, Annex I, Table {number}"))
    return entries


def _columns(codes: list[str], n: int, signals: list[str]) -> list[list[list[str]]] | None:
    """Which statement codes go in which of a table's n columns, as rows:
    columns[k] is a list of rows (one per route where the table has routes),
    each the codes of that column in that row."""
    if len(codes) % n == 0:
        per = len(codes) // n
        return [[[codes[r * n + k]] for r in range(per)] for k in range(n)]
    printed = [k for k in range(n) if signals[k] != "No signal word"]
    if len(codes) == len(printed):
        out: list[list[list[str]]] = [[] for _ in range(n)]
        for k, code in zip(printed, codes, strict=True):
            out[k] = [[code]]
        return out
    # Several codes to a column: a new column starts where the numbers stop
    # rising (aerosols: H222 H229 | H223 H229 | H229) ...
    groups: list[list[str]] = []
    for code in codes:
        if groups and _number(code) > _number(groups[-1][-1]):
            groups[-1].append(code)
        else:
            groups.append([code])
    if len(groups) == n:
        return [[group] for group in groups]
    # ... or the last column carries the rest (STOT SE 3: H335, H336).
    if len(codes) > n:
        return [[[code]] for code in codes[:n - 1]] + [[codes[n - 1:]]]
    return None


def _number(code: str) -> int:
    return int(re.search(r"\d{3}", code).group(0))


_ANNEX_V_ITEM = re.compile(r"Section (\d\.\d{1,2}):? (.+?)(?=Section \d\.\d{1,2}|\d\.\d\. |$)")


def _annex_v(text: str) -> list[tuple[str, str, str]]:
    """(pictogram code, section, words) for each line of Annex V Parts 1 and 2."""
    start = text.find("ANNEX V HAZARD PICTOGRAMS INTRODUCTION")
    if start < 0:
        start = text.find("HAZARD PICTOGRAMS INTRODUCTION")
    end = text.find("PART 5", start)
    block = text[start:end if end > start else start + 8000]
    out = []
    for found in re.finditer(r"(GHS0\d)(.+?)(?=\d\.\d{1,2}\. (?:Symbol|A pictogram)|PART \d|$)",
                             block):
        code, rest = found.group(1), found.group(2).split("A pictogram is not required")[0]
        for item in _ANNEX_V_ITEM.finditer(rest):
            out.append((code, item.group(1), _flat(item.group(2)).rstrip(".; ")))
    return out


def _stem(word: str) -> str:
    for suffix in ("es", "s"):
        if word.endswith(suffix) and len(word) > 4:
            word = word[:-len(suffix)]
            break
    return word[:6].replace("z", "s")


def _stems(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "which", "after", "substance", "substances",
            "mixture", "mixtures", "hazard", "hazardous", "categories", "category"}
    return {_stem(w) for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2 and w not in stop}


def _attach_pictograms(entries: list[Entry], annex_v) -> None:
    for code, section, words in annex_v:
        lowered = words.lower()
        names = set(re.findall(r"\b(\d\.\d|\d[A-C]?|[A-G])\b", words))
        if "unstable explosive" in lowered:
            names.add("Unst.")
        if "lactation" in lowered:
            names.add("Lact.")
        for entry in entries:
            if entry.section != section:
                continue
            sub = entry.subclass
            if sub.startswith("aquatic"):
                # "— Acute hazard category: Acute 1 — Long-term hazard
                # categories: Chronic 1, Chronic 2"
                word = "acute" if sub.endswith("acute") else "chronic"
                listed = re.findall(rf"{word} (\d)", lowered)
                if not set(listed) & set(entry.category):
                    continue
            else:
                if names and not (set(entry.category) & names):
                    continue
                if sub and sub not in ("oral", "dermal", "inhalation") and \
                        sub.split()[0] not in lowered:
                    continue
            # Skin corrosion and skin irritation share a section; so do eye
            # damage and eye irritation: the words say which.
            if section in ("3.2", "3.3"):
                corrosive = any(c in entry.h_codes for c in ("H314", "H318"))
                if ("irritation" in lowered and "corrosion" not in lowered
                        and "damage" not in lowered) == corrosive:
                    continue
            if code not in entry.pictograms:
                entry.pictograms.append(code)


def _table_1_1(text: str) -> list[tuple[str, str]]:
    """Annex VI Table 1.1: (hazard class, its class and category codes)."""
    start = text.find("Hazard Class Hazard Class and Category Code")
    if start < 0:
        return []
    end = text.find("Table 1.2", start)
    block = text[start + len("Hazard Class Hazard Class and Category Code"):end]
    from lingua_oracle.mixture.classes import parse_class  # noqa: F401 - shape only

    vocabulary = _class_code_vocabulary()
    pattern = "|".join(re.escape(c) for c in sorted(vocabulary, key=len, reverse=True))
    out: list[tuple[str, str]] = []
    position, name = 0, ""
    for found in re.finditer(rf"(?<![\w.])(?:{pattern})(?![\w])", block):
        between = _flat(block[position:found.start()]).strip(" ()*0123456789,")
        if len(between) > 80:
            break                       # past the table: running text again
        if between and not re.fullmatch(r"[\W\d]*", between):
            name = between
        code = found.group(0)
        out.append((name, code))
        position = found.end()
        # "Resp. Sens. 1, 1A, 1B": the further categories share the prefix.
        more = re.match(r"((?:,\s*\d[A-C]?)+)", block[position:])
        if more:
            prefix = code.rsplit(" ", 1)[0]
            out += [(name, f"{prefix} {c}") for c in re.findall(r"\d[A-C]?", more.group(1))]
            position += more.end()
    return out


def code_key(code: str) -> str:
    """A class and category code with its dots and spaces set aside: the
    act writes "Skin. Sens. 1" in Table 1.1, sheets "Skin Sens. 1"."""
    return re.sub(r"[\s.]", "", code).lower()


def _class_code_vocabulary() -> list[str]:
    """The class and category codes CLP's Annex VI uses, as already read from
    the act for the substance list (data/hazard_classes/eu_clp.json)."""
    path = data_dir() / "hazard_classes" / "eu_clp.json"
    return json.loads(path.read_text(encoding="utf-8"))["codes"]


def _attach_codes(entries: list[Entry], table_1_1: list[tuple[str, str]]) -> None:
    for name, code in table_1_1:
        suffix = re.search(r"(\d\.\d|\d[A-C]?|[A-G]{1,2}|Lact\.|Expl\.|Gas)$", code)
        words = _stems(name)
        for entry in entries:
            # Every word of Table 1.1's class name is in the label table's.
            theirs = _stems(f"{entry.hazard_class} {entry.subclass}")
            if not words or not words <= theirs or len(words) / len(theirs) < 0.5:
                continue
            special = ((code == "Unst. Expl." and "Unst." in entry.category)
                       or (code == "Lact." and "Lact." in entry.category)
                       or (code == "Press. Gas" and entry.section == "2.5"))
            if not special and (not suffix or suffix.group(1) not in entry.category):
                continue
            # Aquatic acute and chronic, skin corrosion and irritation, eye
            # damage and irritation, respiratory and skin sensitisation:
            # the code's own words pick the column.
            if entry.subclass in ("aquatic acute", "aquatic chronic") and \
                    entry.subclass.split()[1][:5] not in code.lower():
                continue
            if "sensitisation" in entry.subclass and entry.subclass[:4] not in code.lower():
                continue
            if entry.section in ("3.2", "3.3"):
                corrosive = any(c in entry.h_codes for c in ("H314", "H318"))
                if (("Corr." in code or "Dam." in code) != corrosive):
                    continue
            if code not in entry.codes:
                entry.codes.append(code)


_CLP_PRECEDENCE = re.compile(
    r"\(?(?P<letter>[a-e])\)? if the hazard pictogram ‘(?P<when>GHS0\d)’(?: or ‘(?P<when2>GHS0\d)’)?"
    r" applies(?: for (?P<for_when>[^,]+))?, (?:the hazard pictogram ‘(?P<drop>GHS0\d)’ "
    r"shall not appear(?: for (?P<only>[^;]+))?|the use of the hazard pictograms? ‘(?P<opt1>GHS0\d)’"
    r"(?: and ‘(?P<opt2>GHS0\d)’)? shall be optional[^;]*)")


def _only_for(words: str | None) -> list[str]:
    """ "skin sensitisation or for skin and eye irritation" -> the classes."""
    if not words:
        return []
    out = []
    for part in re.split(r",? or for |,? and for ", words.strip(" .;")):
        part = part.strip()
        pair = re.match(r"(\w+) and (\w+) (\w+)$", part)
        if pair:
            out += [f"{pair.group(1)} {pair.group(3)}", f"{pair.group(2)} {pair.group(3)}"]
            continue
        either = re.match(r"(\w+) or (\w+) (\w+)$", part)
        if either:
            out += [f"{either.group(1)} {either.group(3)}", f"{either.group(2)} {either.group(3)}"]
            continue
        out += [p.strip() for p in part.split(" or ")]
    return out


def _clp_rules(structure: LabelElements, text: str, document: str) -> None:
    art26 = re.search(r"Article 26 Principles of precedence for hazard pictograms 1\.? .+?"
                      r"(?=2\.? Where the classification)", text)
    if art26:
        for found in _CLP_PRECEDENCE.finditer(art26.group(0)):
            quote = _flat(found.group(0))
            citation = f"{document}, Article 26(1)({found.group('letter')})"
            when = [w for w in (found.group("when"), found.group("when2")) if w]
            if found.group("drop"):
                structure.pictogram_rules.append(Precedence(
                    when, found.group("drop"), "not_appear", _only_for(found.group("only")),
                    Rule(True, quote, citation), _only_for(found.group("for_when"))))
            for optional in (found.group("opt1"), found.group("opt2")):
                if optional:
                    structure.pictogram_rules.append(Precedence(
                        when, optional, "optional", [], Rule(True, quote, citation)))
    else:
        structure.unparsed.append(f"{document}, Article 26: not found")
    statements = re.search(r"In accordance with Article 27 the following principles of "
                           r"precedence for hazard statements may apply to labelling: .+?"
                           r"(?=\s\d\.\d\.\d|\s1\.3\.)", text)
    if statements:
        for found in re.finditer(r"\(([a-h])\) if the (?:hazard )?statement "
                                 r"(?P<when>(?:EU)?H\d{3}) ‘[^’]+’ is assigned, the statement "
                                 r"(?P<drop>(?:EU)?H\d{3}) ‘[^’]+’ may be omitted",
                                 statements.group(0)):
            structure.statement_rules.append(Precedence(
                [found.group("when")], found.group("drop"), "may_omit", [],
                Rule(False, _flat(found.group(0)),
                     f"{document}, Annex I, the paragraph applying Article 27, "
                     f"({found.group(1)})")))
    signal = re.search(r"Article 21\b[^.]*\.[^.]*Danger[^.]*Warning[^.]*\.", text)
    if signal:
        structure.signal_rule = Rule(_verb(signal.group(0)), _flat(signal.group(0)),
                                     f"{document}, Article 20/21")


def _eu(use_cache: bool) -> LabelElements:
    from lxml import html as LH

    from lingua_oracle.keys.builders.eu_clp import BASE_URL, CELEX

    document = f"Regulation (EC) No 1272/2008, consolidated {CELEX}"
    raw = fetch(BASE_URL, headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"},
                use_cache=use_cache)
    text = strip_markers(_flat(" ".join(LH.fromstring(raw).itertext())))
    return _clp_like("eu_clp", document, text)


def _gb() -> LabelElements:
    import pymupdf

    path = sources.require("uk-gb-clp/gb_clp_full.pdf")
    document = "Regulation (EC) No 1272/2008 as retained in GB law"
    with pymupdf.open(path) as pdf:
        text = _flat(" ".join(page.get_text() for page in pdf))
    # legislation.gov.uk's running heads and amendment markers break tables and
    # sentences across pages; they are not the act's words.
    text = re.sub(r"Regulation \(EC\) No 1272/2008 of the European Parliament and of the "
                  r"Council of\.\.\..{0,80}?Document Generated: \d{4}-\d{2}-\d{2}"
                  r"(?: \d+(?![.\d]))? Changes to legislation:.*?\(See end of Document for "
                  r"details\)(?: \d{1,3}(?![.\d]))?", " ", text)
    text = re.sub(r"\[F\d+|\[X\d+|\]|F\d+\s*(?:\.\s*){3}", "", text)
    return _clp_like("uk_clp", document, _flat(text))


def _clp_like(regulation: str, document: str, text: str) -> LabelElements:
    structure = LabelElements(regulation, document, pictogram_kind="code",
                              pictogram_names=[f"GHS0{n}" for n in range(1, 10)])
    annex_i = text[text.find("ANNEX I"):]
    structure.entries = _clp_entries(annex_i, document, structure.unparsed)
    _attach_pictograms(structure.entries, _annex_v(text))
    _attach_codes(structure.entries, _table_1_1(text))
    _clp_rules(structure, text, document)
    # Danger over Warning: CLP Article 20(3).
    found = re.search(r"Where the signal word ‘Danger’ is used on the label, the signal word "
                      r"‘Warning’ shall not appear on the label\.", text)
    if found:
        structure.signal_rule = Rule(True, found.group(0), f"{document}, Article 20(3)")
    return structure


def rules_dir() -> Path:
    return data_dir() / "label_elements"


def build(regulation: str, *, use_cache: bool = True) -> LabelElements:
    match regulation:
        case "eu_clp":
            return _eu(use_cache)
        case "uk_clp":
            return _gb()
        case "us_osha":
            return _osha(use_cache)
        case "ca_whmis" | "un_ghs" | "au_whs":
            return _ghs(regulation)
    raise ValueError(f"no label elements source for {regulation}")


def write(regulation: str, *, use_cache: bool = True) -> Path:
    structure = build(regulation, use_cache=use_cache)
    rules_dir().mkdir(parents=True, exist_ok=True)
    path = rules_dir() / f"{regulation}.json"
    path.write_text(json.dumps(asdict(structure), indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


# -- the GHS: Annex 3 for codes, the chapters for symbols and signal words ----------

_A3_ROW = re.compile(
    r"(?P<code>H\d{3}[A-Za-z]?(?:\+H\d{3})*) (?P<statement>[A-Z][^()]+?) "
    r"(?P<hclass>[A-Z][A-Za-z ,/()\-]+?) \(chapter (?P<chapter>\d\.\d{1,2})\) "
    r"(?P<cats>(?:(?:\d[A-C]?|[A-G]|Type [A-G]|Division \d\.\d|\d\.\d|(?:Compressed|Liquefied|"
    r"Refrigerated liquefied|Dissolved) gas)(?:,\s*|\s+and\s+|\s+or\s+)?)+)")


def _ghs_symbols(text: str) -> list[str]:
    """The standard symbols, from the caption list in 1.4.10.3: each name
    starts with a capital ("Flame over circle", "Skull and crossbones")."""
    found = [m.start() for m in re.finditer(r"1\.4\.10\.3 Reproduction of the symbol", text)]
    if not found:
        raise SourceUnavailable("GHS 1.4.10.3 not found")
    block = text[found[-1]:found[-1] + 1200]
    caption = re.search(r"((?:Flame|Exploding|Corrosion|Gas|Skull|Exclamation|Environment|Health)"
                        r"[A-Za-z ]+?)\s+1\.4\.10\.4", block)
    if caption is None:
        raise SourceUnavailable("GHS 1.4.10.3 symbol list not read")
    return re.findall(r"[A-Z][a-z]+(?: [a-z]+)*", caption.group(1))


def _split_names(text: str, names: list[str]) -> list[str]:
    """A table row of symbol names, one per column."""
    vocabulary = sorted(names + ["No symbol", "No pictogram"], key=len, reverse=True)
    pattern = "|".join(re.escape(n) for n in vocabulary)
    return re.findall(pattern, text, re.IGNORECASE)


def _ghs_chapter_tables(text: str, names: list[str]) -> dict[str, list[dict]]:
    """Each chapter's label table: per column, its category names, symbol and
    signal word - and the column's class where one table holds two."""
    out: dict[str, list[dict]] = {}
    for table in re.finditer(r"Table (?P<number>\d\.\d{1,2}\.\d{1,2}): Label elements for "
                             r"(?P<title>.+?)(?=Hazard statement)(?P<rest>.{0,1200})", text):
        chapter = ".".join(table.group("number").split(".")[:2])
        if chapter in out:
            continue
        whole = table.group("title")
        blocks = re.split(r"(SHORT-TERM \(ACUTE\) AQUATIC HAZARD|LONG-TERM \(CHRONIC\) AQUATIC "
                          r"HAZARD)", whole + " " + table.group("rest").split("Decision logic")[0])
        pieces = [("", blocks[0])] if len(blocks) == 1 else [
            ("short-term (acute)" if "SHORT" in blocks[k] else "long-term (chronic)", blocks[k + 1])
            for k in range(1, len(blocks), 2)]
        columns: list[dict] = []
        for subclass, piece in pieces:
            head = piece.split("Symbol")[0]
            symbols = _split_names(piece.split("Symbol", 1)[-1].split("Signal word")[0], names)
            signals = re.findall(r"Danger|Warning|No signal word",
                                 piece.split("Signal word", 1)[-1].split("Hazard statement")[0])
            labels = [m.group(0) for m in _CATEGORY.finditer(head)]
            if len(labels) > len(symbols):
                labels = list(dict.fromkeys(labels))
            # "Category 1 ... 1 A 1 B 1 C": Category 1 printed over three columns.
            if re.search(r"1 ?A 1 ?B 1 ?C", head) and len(symbols) == len(labels) + 2:
                at = next(k for k, label in enumerate(labels) if category_names(label)[0] == "1")
                labels[at:at + 1] = ["Category 1A", "Category 1B", "Category 1C"]
            classes = re.findall(r"(Respiratory sensiti[sz]ation|Skin sensiti[sz]ation)", head)
            if len(symbols) != len(labels) or len(signals) != len(labels):
                continue
            for k, label in enumerate(labels):
                columns.append({
                    "category": category_names(label),
                    "subclass": subclass or (classes[k].lower() if len(classes) == len(labels)
                                             else ""),
                    "symbol": "" if symbols[k].lower().startswith("no ") else symbols[k],
                    "signal": "" if signals[k] == "No signal word" else signals[k],
                    "table": table.group("number")})
        if columns:
            out[chapter] = columns
    return out


def _ghs(regulation: str) -> LabelElements:
    import pymupdf

    rev11 = regulation == "un_ghs"
    path = sources.require("un-ghs/GHS_Rev11_en.pdf" if rev11 else "ghs-rev7/GHS_Rev7_en.pdf")
    edition = "UN GHS Rev.11 (2025)" if rev11 else "UN GHS Rev.7 (2017)"
    document = {"un_ghs": edition,
                "au_whs": f"{edition}, as adopted by the WHS Regulations",
                "ca_whmis": f"{edition}, as incorporated by the Hazardous Products Regulations, "
                            "section 3(1)(c)"}[regulation]
    with pymupdf.open(path) as pdf:
        text = _flat(" ".join(page.get_text() for page in pdf))
    structure = LabelElements(regulation, document, pictogram_kind="name")
    names = _ghs_symbols(text)
    structure.pictogram_names = names
    chapters = _ghs_chapter_tables(text, names)
    a3 = [m.start() for m in re.finditer(r"Table A3\.1\.1", text)]
    rows = text[a3[-2] if len(a3) > 1 else a3[-1]:][:60000] if a3 else ""
    seen: set[tuple] = set()
    for row in _A3_ROW.finditer(rows):
        code, chapter = row.group("code"), row.group("chapter")
        if "+" in code or (code, chapter) in seen:
            continue
        seen.add((code, chapter))
        hclass = row.group("hclass").strip()
        lowered = hclass.lower()
        cats = {"Lact."} if "lactation" in lowered else \
            set(re.findall(r"\d\.\d|\d[A-C]?|\b[A-G]\b", row.group("cats"))) | {
            g.lower() for g in re.findall(r"(?:Compressed|Liquefied|Refrigerated liquefied|"
                                          r"Dissolved) gas", row.group("cats"))}
        columns = chapters.get(chapter, [])
        matched = False
        for column in columns:
            if not set(column["category"]) & cats:
                continue
            sub = column["subclass"]
            words = set(re.findall(r"[a-z]+", lowered))
            if sub.startswith(("short", "long")):
                if not {w for w in re.findall(r"[a-z]+", sub) if w != "term"} & words:
                    continue
            elif sub and sub.split()[0][:6] not in lowered:
                continue
            route = next((r for r in ("oral", "dermal", "inhalation") if r in lowered), "")
            structure.entries.append(Entry(
                section=chapter, hazard_class=lowered.split(",")[0].split(" (")[0],
                category=column["category"], subclass=sub or route, h_codes=[code],
                signal=column["signal"],
                pictograms=[column["symbol"]] if column["symbol"] else [],
                source=f"{document}, Table A3.1.1 and Table {column['table']}"))
            matched = True
        if not matched:
            structure.unparsed.append(f"{document}: {code} ({hclass}, chapter {chapter}) - "
                                      "no label table column for its category")
    _ghs_rules(structure, text, document)
    if regulation == "au_whs":
        _australian_exclusions(structure)
    return structure


_GHS_SYMBOL_WORDS = {"skull and crossbones": "Skull and crossbones",
                     "exclamation mark": "Exclamation mark", "corrosive": "Corrosion",
                     "corrosion": "Corrosion", "health hazard symbol": "Health hazard",
                     "health hazard": "Health hazard"}


def _symbol(words: str) -> str:
    lowered = words.lower().strip()
    for key, name in _GHS_SYMBOL_WORDS.items():
        if key in lowered:
            return name
    return words


def _ghs_rules(structure: LabelElements, text: str, document: str) -> None:
    found = [m.start() for m in re.finditer(r"1\.4\.10\.5\.3\.1 Precedence for the allocation", text)]
    if not found:
        structure.unparsed.append(f"{document}: 1.4.10.5.3.1 not found")
        return
    block = text[found[-1]:found[-1] + 4000]
    for clause in re.finditer(
            r"\((?P<letter>[a-c])\) if the (?P<when>[a-z ]+?)(?: symbol)? (?:applies|appears)"
            r"(?: for (?P<when_for>[a-z ]+?))?, the (?P<drop>[a-z ]+?) should not appear"
            r"(?: where it is used for (?P<only>[a-z ,]+?))?[;.]", block):
        structure.pictogram_rules.append(Precedence(
            [_symbol(clause.group("when"))], _symbol(clause.group("drop")), "not_appear",
            _only_for(clause.group("only")),
            Rule(False, _flat(clause.group(0)), f"{document}, 1.4.10.5.3.1({clause.group('letter')})"),
            _only_for(clause.group("when_for"))))
    signal = re.search(r"If the signal word “Danger” applies, the signal word “Warning” should "
                       r"not appear\.", block)
    if signal:
        structure.signal_rule = Rule(False, signal.group(0), f"{document}, 1.4.10.5.3.2")
    for clause in re.finditer(r"\(([a-d])\) If the statement (H\d{3}) “[^”]+” is assigned, the "
                              r"statement (H\d{3}) “[^”]+” may be omitted", block):
        structure.statement_rules.append(Precedence(
            [clause.group(2)], clause.group(3), "may_omit", [],
            Rule(False, _flat(clause.group(0)), f"{document}, 1.4.10.5.3.3({clause.group(1)})")))


def _australian_exclusions(structure: LabelElements) -> None:
    """What the WHS Regulations leave out of "hazardous chemical", as Safe
    Work Australia's guidance lists it: those classifications are notes."""
    import pymupdf

    path = sources.require("australia/swa_classification_guidance.pdf")
    with pymupdf.open(path) as pdf:
        pages = [(n + 1, _flat(p.get_text())) for n, p in enumerate(pdf)]
    for number, page in pages:
        found = re.search(r"Hazardous chemical means a substance, mixture or article that "
                          r"satisfies the criteria for a hazard class in the GHS.+?following hazard "
                          r"classes: a\. acute toxicity\s*\W\s*oral, dermal and inhalation\s*\W\s*"
                          r"category 5;.+?h\. hazardous to the ozone layer\.", page)
        if not found:
            continue
        citation = ("Safe Work Australia, Guidance on the classification of hazardous "
                    f"chemicals under the WHS Regulations, page {number}")
        listing = found.group(0)[found.group(0).index("a. acute"):]
        for item in re.finditer(r"(?:^|; )[a-h]\. ([^;]+?)(?=;|\.$)", listing):
            words = item.group(1)
            cats = re.findall(r"\d[A-C]?", re.split(r"\s\W\s", words)[-1]) \
                if "categor" in words else []
            structure.not_adopted.append({"what": words.strip(), "categories": cats,
                                          "rule": asdict(Rule(True, _flat(found.group(0)),
                                                              citation))})
        return
    structure.unparsed.append("Safe Work Australia exclusions not found")


# -- US: Appendix C, class by class ------------------------------------------------

_OSHA_BLOCK = re.compile(
    r"(?P<hclass>[A-Z][A-Z0-9 ,/()\-]+?) \(Classified in Accordance with Appendix (?P<app>[AB]\.\d+)"
    r"[^)]*\) Pictogram (?P<pic>.+?) Hazard category Signal word Hazard statement (?P<rows>.+?)"
    r"(?= Precautionary statements)")
_OSHA_ROW = re.compile(
    r"(?P<cat>\d[A-C]?(?: to \d[A-C])?|Types? [A-G](?: (?:and|&|to) [A-G])?|Division \d\.\d"
    r"|Unstable explosives?|(?:Compressed|Liquefied|Refrigerated liquefied|Dissolved) gas"
    r"|Effects on or via lactation) (?P<signal>Danger|Warning|No signal word) "
    r"(?P<statement>.+?)(?= (?:\d[A-C]?(?: to \d[A-C])?|Types? [A-G]|Division \d\.\d|"
    r"(?:Compressed|Liquefied|Refrigerated liquefied|Dissolved) gas) (?:Danger|Warning|No signal "
    r"word) |$)")


def _osha(use_cache: bool) -> LabelElements:
    from lingua_oracle.keys.builders.us_osha import SOURCE_URL as APPENDIX_C_URL
    from lingua_oracle.keys.store import load_key

    document = "29 CFR 1910.1200 Appendix C"
    local = sources.BY_PATH["us-osha/appendix_c.html"].where
    raw = (local.read_bytes() if local.exists() else
           fetch(APPENDIX_C_URL, headers={"User-Agent": BROWSER_UA}, use_cache=use_cache)
           ).decode("utf-8", "replace")
    names = sorted({_flat(re.sub(r"(?i)\s*pictogram\s*$", "", _html.unescape(a))).strip()
                    for a in re.findall(r'alt="([^"]*[Pp]ictogram[^"]*)"', raw)} - {""})
    text = _flat(_html.unescape(re.sub(r"<[^>]+>", " ", raw)))
    structure = LabelElements("us_osha", document, pictogram_kind="name",
                              pictogram_names=names)
    key = load_key("us_osha", "en")
    by_text: dict[str, str] = {}
    for entry in (key.entries if key else []):
        if entry.code.startswith("H") and entry.text:
            by_text.setdefault(_norm(entry.text), entry.code)
    for block in _OSHA_BLOCK.finditer(text):
        hclass = block.group("hclass").strip().lower()
        pictogram = block.group("pic").strip()
        pictogram = "" if pictogram.lower().startswith("no ") else pictogram
        for row in _OSHA_ROW.finditer(block.group("rows")):
            statement = row.group("statement").strip()
            code = by_text.get(_norm(statement)) or next(
                (c for t, c in by_text.items() if _norm(statement).startswith(t)), None)
            if code is None:
                structure.unparsed.append(f"{document}: {hclass} {row.group('cat')}: "
                                          f"“{statement[:60]}” matched to no code")
                continue
            route = next((r for r in ("oral", "dermal", "inhalation") if r in hclass), "")
            structure.entries.append(Entry(
                section=block.group("app"), hazard_class=hclass.split(" - ")[0].strip(),
                category=_osha_categories(row.group("cat")), subclass=route, h_codes=[code],
                signal="" if row.group("signal") == "No signal word" else row.group("signal"),
                pictograms=[pictogram] if pictogram else [],
                source=f"{document}, {block.group('hclass').strip()}"))
    _osha_rules(structure, text, document)
    return structure


def _norm(text: str) -> str:
    """A statement's words: fill-ins - "<…>", "<<state route>>" - set aside."""
    text = re.sub(r"<<[^>]*>>|<[^>]*>|…", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _osha_categories(label: str) -> list[str]:
    span = re.match(r"(\d)([A-C]) to \d([A-C])", label)
    if span:
        return [span.group(1)] + [f"{span.group(1)}{c}" for c in "ABC"
                                  if span.group(2) <= c <= span.group(3)]
    return category_names(label.replace("Types", "Type"))


def _osha_rules(structure: LabelElements, text: str, document: str) -> None:
    block = re.search(r"C\.2\.1 Precedence of Hazard Information (.+?) C\.2\.2", text)
    if not block:
        structure.unparsed.append(f"{document}: C.2.1 not found")
        return
    signal = re.search(r"C\.2\.1\.1 If the signal word “Danger” is included, the signal word "
                       r"“Warning” shall not appear;", block.group(0))
    if signal:
        structure.signal_rule = Rule(True, signal.group(0).rstrip(";"), f"{document}, C.2.1.1")
    for clause in re.finditer(
            r"(C\.2\.1\.\d) If the (?P<when>[a-z &]+?) pictogram is included(?: for "
            r"(?P<when_for>[a-z ]+?))?, the (?P<drop>[a-z ]+?) pictogram shall not appear where "
            r"it is used for (?P<only>[a-z ,]+?)[;.]", block.group(0)):
        structure.pictogram_rules.append(Precedence(
            [_symbol(clause.group("when"))], _symbol(clause.group("drop")), "not_appear",
            _only_for(clause.group("only")),
            Rule(True, _flat(clause.group(0)).rstrip(";"), f"{document}, {clause.group(1)}"),
            _only_for(clause.group("when_for"))))
