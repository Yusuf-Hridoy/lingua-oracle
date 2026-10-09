"""C-21: Section 14 against the official dangerous goods list.

US sheets are held against the DOT Hazardous Materials Table (49 CFR
172.101); others against the UN Model Regulations' Dangerous Goods List -
"not checked (list not on file)" where that list is not on file. For each
transport block the sheet prints (ADR, RID, IMDG, IATA, DOT ... or one block
for all), the UN number, proper shipping name, class and packing group are
read and held against the list entry: an unknown number, or a name, class
or packing group the entry does not give, is a fault.

A proper shipping name is, on the DOT table, the entry's Roman type, as 49
CFR 172.101(c) says: italic words "may be used in addition", singular or
plural, any case. On the UN list it is the upper-case portion (3.1.2.1),
its qualifying words in any order (3.1.2.3).
A name differing only in spelling is one to check - (c)(1) allows the ICAO
and IMDG spellings, which are not on file - except "inflammable" for
"flammable", which (c)(1) forbids. Section 14 printed as a table, one column
per mode, is read column by column.

A sheet saying "not regulated" for transport is correct unless Section 2
classifies it a flammable liquid: then it is one to check, quoting the
transport criterion where it is on file (DOT: 49 CFR 173.120), and saying
the list does not decide it where it is not.
"""

from __future__ import annotations

import re

from lingua_oracle.keys.builders import lists
from lingua_oracle.models import ConsistencyRow

CHECK = "C-21"
_MODE = re.compile(r"\b(ADR|RID|ADN|IMDG|IATA|ICAO|DOT|TDG|US DOT|49 CFR)\b")
_UN = re.compile(r"\b(?:(UN|NA|ID)\s?-?\s?(\d{4})|UN[- ]?(?:number|No\.?)\s*[:：]?\s*(?:UN)?\s*(\d{4}))\b",
                 re.IGNORECASE)
_NOT_REGULATED = re.compile(r"not regulated|not classified as (?:a )?dangerous|not (?:a )?dangerous "
                            r"goods?|not restricted|no dangerous goods?|not subject to",
                            re.IGNORECASE)
_NAME_LABEL = re.compile(r"(?:UN\s+)?proper\s+shipping\s+name|shipping\s+name|"
                         r"designation officielle|benennung", re.IGNORECASE)
_CLASS_LABEL = re.compile(r"(?:transport\s+)?hazard\s+class(?:\(es\))?|^\s*class(?:\s+or\s+division)?"
                          r"\b|klasse|classe", re.IGNORECASE)
_GROUP_LABEL = re.compile(r"pack(?:ing|aging)\s+group|verpackungsgruppe|groupe d['’]emballage",
                          re.IGNORECASE)
_NUMBER_LABEL = re.compile(r"\bUN\s*(?:ID\s*)?(?:number|no\.?)|identification\s+number|"
                           r"UN-Nummer|numéro ONU", re.IGNORECASE)
_NOTHING = re.compile(r"^\s*(?:not applicable|n/?a|none|[-–—]+|the field does not apply.*)\s*\.?$",
                      re.IGNORECASE)
_ROMAN = re.compile(r"\b(III|II|I)\b")
_PAGE = re.compile(r"(?:\bpage\s*)?\d+\s*(?:/|of)\s*\d+\s*$", re.IGNORECASE)


def _page_furniture(line: str) -> bool:
    """A page number ("SDS 1 / 2", "Page 3 of 9") a page break left between
    the values of a table."""
    return bool(_PAGE.search(line)) and len(line.split()) <= 5


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _values_after(lines: list[str], label: re.Pattern):
    """Each value printed after the label, on its line or the next; "" where
    it is "not applicable" or the like."""
    for k, line in enumerate(lines):
        found = label.search(line or "")
        if found:
            rest = line[found.end():].strip(" :：-–")
            if not rest and k + 1 < len(lines):
                rest = (lines[k + 1] or "").strip(" :：-–")
            yield "" if _NOTHING.match(rest) else rest


def _value_after(lines: list[str], label: re.Pattern) -> str:
    """The first value after the label that is not itself a label - a
    heading ("14.2 UN proper shipping name") may stand above "Shipping
    Name: ...". """
    labels = (_NAME_LABEL, _CLASS_LABEL, _GROUP_LABEL, _NUMBER_LABEL)
    for value in _values_after(lines, label):
        if not any(x.match(value) for x in labels):
            return value
    return ""


def blocks(section_14: list[str]) -> list[tuple[str, list[str]]]:
    """The transport blocks: (mode, lines) - one block where no mode is named."""
    out: list[tuple[str, list[str]]] = []
    mode, current = "", []
    for line in section_14:
        found = _MODE.search(line or "")
        if found and len((line or "").split()) <= 8 and not _UN.search(line or ""):
            if current:
                out.append((mode, current))
            mode, current = found.group(1).upper(), [line]
            continue
        current.append(line)
    if current:
        out.append((mode, current))
    return out


def read_block(lines: list[str]) -> dict:
    """UN number, name, class and packing group a block states."""
    text = "\n".join(lines)
    number = None
    # A heading ("14.1 UN number") may stand above the label and its number.
    for value in _values_after(lines, _NUMBER_LABEL):
        labelled = re.match(r"(?:UN)?\s*(\d{4})\b", value)
        if labelled:
            number = f"UN{labelled.group(1)}"
            break
    for found in ([] if number else _UN.finditer(text)):
        prefix = (found.group(1) or "UN").upper()
        digits = found.group(2) or found.group(3)
        number = f"{'UN' if prefix == 'ID' else prefix}{digits}"
        break
    inline = re.search(r"\b(?:UN|NA)\s?(\d{4})\s*,\s*([^,\n]+(?:\([^)]*\))?)\s*,\s*"
                       r"(\d(?:\.\d)?)\s*(?:\([^)]*\))?\s*,\s*(?:PG\s*)?(III|II|I)\b", text)
    name = _value_after(lines, _NAME_LABEL)
    hazard_class = _value_after(lines, _CLASS_LABEL)
    group = _value_after(lines, _GROUP_LABEL)
    if inline:
        name = name or inline.group(2)
        hazard_class = hazard_class or inline.group(3)
        group = group or inline.group(4)
    cls = re.search(r"\b(\d(?:\.\d)?)\b", hazard_class or "")
    pg = _ROMAN.search(group or "")
    return {"number": number, "name": (name or "").strip(), "class": cls.group(1) if cls else "",
            "group": pg.group(1) if pg else "", "not_regulated": bool(_NOT_REGULATED.search(text))}


def _row(status, key, text, rule=None, *, found="", expected="") -> ConsistencyRow:
    return ConsistencyRow(section="14", check=CHECK, key=key, status=status, text=text,
                          quote=(rule or {}).get("quote", ""),
                          citation=(rule or {}).get("citation", ""), found=found,
                          expected=expected)


def _fold(text: str) -> list[str]:
    """Words, case and punctuation set aside, singular or plural alike."""
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _norm(text).split()]


def _name_agrees(stated: str, name: str, *, ordered: bool = True) -> bool:
    """The list's name in the sheet's words; others - a description, a
    technical name - may be used in addition. DOT: the Roman-type words in
    order, from the sheet's first word on. UN: in any order, as 3.1.2.3
    lets qualifying words be ("AQUEOUS SOLUTION OF DIMETHYLAMINE")."""
    said, listed = _fold(stated), _fold(name)
    if not said or not listed:
        return False
    if not ordered:
        return all(said.count(word) >= listed.count(word) for word in set(listed))
    if said[0] != listed[0]:
        return False
    rest = iter(said)
    return all(word in rest for word in listed)


def _class_agrees(stated: str, listed: str) -> bool:
    """Class or division as the entry gives it; an entry giving a class
    without a division (AEROSOLS, "2") takes any division of it. Class 1's
    compatibility group is not compared."""
    number = re.match(r"\d(?:\.\d)?", listed or "")
    if not number:
        return True
    number = number.group(0)
    return stated == number or ("." not in number and stated.split(".")[0] == number)


def _distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def _spelling_only(stated: str, name: str) -> bool:
    said, listed = _fold(stated), _fold(name)
    return len(said) >= len(listed) > 0 and all(
        a == b or (a[:1] == b[:1] and _distance(a, b) <= 2)    # aluminum, aluminium
        for a, b in zip(said, listed, strict=False))


def _field(line: str) -> str | None:
    """Which field a label line of a column table names, if it is one."""
    text = (line or "").strip()
    if _NUMBER_LABEL.search(text) and not re.search(r"\d{4}", text):
        return "number"
    if re.match(r"(?:UN\s+)?proper\b|shipping\s+name", text, re.IGNORECASE):
        return "name"
    if re.fullmatch(r"(?:transport(?:\s+hazard\s+class(?:\(es\))?)?|hazard\s+class(?:\(es\))?|"
                    r"class(?:\s+or\s+division)?)\s*:?", text, re.IGNORECASE):
        return "class"
    if _GROUP_LABEL.search(text):
        return "group"
    if re.match(r"environmental|marine\s+pollutant|special\s+precautions|ems\b|limited\s+quantit|"
                r"transport\s+in\s+bulk|emergency", text, re.IGNORECASE):
        return "other"
    return None


_MODE_ONLY = re.compile(r"(ADR|RID|ADN|IMDG|IATA|ICAO|DOT|TDG|US DOT|49 CFR)(?:\s*/\s*\w+)?"
                        r"(?:\s+(?:classification|regulations?|code|DGR))?\s*:?", re.IGNORECASE)


def columns(section_14: list[str]) -> list[tuple[str, dict]] | None:
    """A table with a column per mode - the modes on lines of their own, one
    after another, then each label followed by a value per mode."""
    lines = [(line or "").strip() for line in section_14]
    for start in range(len(lines)):
        k = 0
        while start + k < len(lines) and _MODE_ONLY.fullmatch(lines[start + k]):
            k += 1
        if k >= 2:
            break
    else:
        return None
    modes = [_MODE_ONLY.fullmatch(x).group(1).upper() for x in lines[start:start + k]]
    values: dict[str, list[str]] = {}
    current = None
    for line in lines[start + k:]:
        if not line or _page_furniture(line):
            continue
        if _MODE_ONLY.fullmatch(line):
            break                                  # a second table
        field = _field(line)
        if field:
            if len(values.get(field, [])) < k:
                current = field
                values.setdefault(field, [])
            continue
        if current and len(values[current]) < k:
            values[current].append("" if _NOTHING.match(line) else line)
            if len(values[current]) == k:
                current = None
    if len(values.get("number", [])) != k:
        return None
    out = []
    for i, mode in enumerate(modes):
        raw_number = values["number"][i]
        found = re.search(r"\b(UN|NA)?\s?-?\s?(\d{4})\b", raw_number)
        cls = re.search(r"\b(\d(?:\.\d)?)\b", (values.get("class") or [""] * k)[i])
        pg = _ROMAN.search((values.get("group") or [""] * k)[i])
        out.append((mode, {"number": f"{(found.group(1) or 'UN').upper()}{found.group(2)}"
                           if found else None,
                           "name": (values.get("name") or [""] * k)[i],
                           "class": cls.group(1) if cls else "", "group": pg.group(1) if pg else "",
                           "not_regulated": bool(_NOT_REGULATED.search(raw_number))}))
    return out


def run(section_14: list[str], regulation: str, flammable: list[str]) -> list[ConsistencyRow]:
    """`flammable` are the flammable-liquid categories Section 2 states."""
    if not section_14:
        return []
    us = regulation == "us_osha"
    dot = lists.load("us_dot_hmt")
    un = lists.load("un_dangerous_goods")
    rows: list[ConsistencyRow] = []
    read = columns(section_14) or [(mode, read_block(lines)) for mode, lines in blocks(section_14)]
    stated = [(mode, b) for mode, b in read if b["number"]]
    if not stated and not any(b["not_regulated"] for _, b in read):
        return [_row("na", "Transport", "Not checked: Section 14 gives no UN number and does "
                     "not say the product is not regulated for transport.")]
    if not stated:
        if any(b["not_regulated"] for _, b in read):
            if flammable:
                criterion = (dot or {}).get("class_3") if us else None
                if criterion and criterion.get("quote"):
                    rows.append(_row("check", "Not regulated", "Section 14 says not regulated for "
                                     f"transport, but Section 2 classifies it Flam. Liq. "
                                     f"{flammable[0]}; the DOT criterion for Class 3 is quoted.",
                                     criterion))
                else:
                    rows.append(_row("check", "Not regulated", "Section 14 says not regulated for "
                                     f"transport, but Section 2 classifies it Flam. Liq. "
                                     f"{flammable[0]}. The transport criterion is not on file, so "
                                     "the list does not decide it."))
            else:
                rows.append(_row("ok", "Not regulated", "Section 14 says not regulated for "
                                 "transport, and nothing on the sheet contradicts it."))
        return rows
    for mode, block in stated:
        use_dot = us and mode in ("", "DOT", "US DOT", "49 CFR")
        held = dot if use_dot else un
        title = mode or "Transport"
        if held is None or held.get("status") != "ok":
            rows.append(_row("na", f"{title} {block['number']}", "Not checked (list not on file): "
                             + ("the UN Model Regulations' Dangerous Goods List." if not use_dot
                                else "the DOT Hazardous Materials Table.")))
            continue
        rule = {"quote": "", "citation": f"{held['document']}, {held.get('version', '')}"}
        entries = [e for e in held["entries"] if e["id"] == block["number"]]
        if not entries:
            rows.append(_row("fix", f"{title} {block['number']}", f"{block['number']} is not in "
                             f"the {held['document']}.", rule, found=block["number"]))
            continue
        rules = held.get("name_rules", {})
        ordered = held.get("list") != "un_dangerous_goods"
        if block["name"]:
            fits = [e for e in entries if any(_name_agrees(block["name"], n, ordered=ordered)
                                              for n in e.get("proper_shipping_names", [e["name"]]))]
            names = [n for e in entries for n in e.get("proper_shipping_names", [e["name"]])]
            shown = " / ".join(dict.fromkeys(names[:4]))
            key = f"{title} {block['number']} name"
            spelling = rules.get("spelling") or {}
            if fits:
                entries = fits
            elif "inflammable" in spelling.get("quote", "") and "inflammable" in _fold(
                    block["name"]) and any("flammable" in _fold(n) for n in names):
                rows.append(_row("fix", key, f"Proper shipping name “{block['name']}” uses "
                                 "“inflammable”; the list's name says “flammable”.",
                                 spelling, found=block["name"], expected=shown))
            elif any(_spelling_only(block["name"], n) for n in names):
                other = ("the ICAO and IMDG spellings it may follow are not on file" if ordered
                         else "the mode's own rules (ADR, IMDG, IATA), which may spell it "
                              "otherwise, are not on file")
                rows.append(_row("check", key, f"Proper shipping name “{block['name']}” differs "
                                 f"from the list's for {block['number']} only in spelling; "
                                 f"{other}.", spelling, found=block["name"], expected=shown))
            else:
                unsure = all(e.get("names_unsure") for e in entries)
                rows.append(_row("check" if unsure else "fix", key, f"Proper shipping name "
                                 f"“{block['name']}” is not the list's for {block['number']}"
                                 + (" (the list's choices of words can be read more than one "
                                    "way)." if unsure else "."),
                                 rules.get("choices" if unsure else "what") or rule,
                                 found=block["name"], expected=shown))
        classes = sorted({e["class"] for e in entries if e["class"]})
        if block["class"] and classes and not any(_class_agrees(block["class"], c)
                                                  for c in classes):
            rows.append(_row("fix", f"{title} {block['number']} class", f"Class {block['class']} is "
                             f"not the list's for {block['number']} ({', '.join(classes)}).",
                             rule, found=block["class"], expected=", ".join(classes)))
        groups = {g for e in entries for g in e["packing_groups"]}
        if block["group"] and groups and block["group"] not in groups:
            rows.append(_row("fix", f"{title} {block['number']} packing group", f"Packing group "
                             f"{block['group']} is not one the list gives {block['number']} "
                             f"({', '.join(sorted(groups))}).", rule, found=block["group"],
                             expected=", ".join(sorted(groups))))
        if not [r for r in rows if r.key.startswith(f"{title} {block['number']}")] and not (
                block["name"] or block["class"] or block["group"]):
            rows.append(_row("ok", f"{title} {block['number']}", f"{block['number']} is on the "
                             "list; the sheet gives no shipping name, class or packing group "
                             "to compare with it.", rule))
        elif not [r for r in rows if r.key.startswith(f"{title} {block['number']}")]:
            rows.append(_row("ok", f"{title} {block['number']}", f"{block['number']}"
                             f"{', ' + block['name'] if block['name'] else ''}"
                             f"{', class ' + block['class'] if block['class'] else ''}"
                             f"{', PG ' + block['group'] if block['group'] else ''} - as the list "
                             "gives it.", rule))
    return rows
