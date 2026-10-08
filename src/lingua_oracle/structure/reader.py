"""Reading a sheet's structure, and judging it by the regulation's own text.

The requirements come from data/sds_structure/<reg>.json - nothing here
adds one. What this module does is find, on the sheet:

* the section headings: a line opening with the section label the text uses
  in that language ("SECTION 1:", "ABSCHNITT 1:", "1. JAGU.") or with a bare
  number whose words read as that section's heading;
* the sub-section headings ("1.3", "1.3."), within their section;
* the objective items: a telephone number, an e-mail address, a date, page
  numbering - each in the place the text puts it.

and then holds each against the table. A rule binds or not as the table
says (its own verb); a rule the table does not hold is not applied, and an
item the sheet cannot be read for (its section is missing) is not judged
twice.

Headings are compared exactly once case, punctuation, spacing and the label
are set aside: "Hazard identification" is not "Hazards identification".
"Hazard(s)" accepts both. Where the text has no wording in the sheet's
language, the wording is not judged; the numbers and order still are.
"""

from __future__ import annotations

import functools
import json
import re
import unicodedata
from dataclasses import dataclass, field

from lingua_oracle.extract.base import Document
from lingua_oracle.models import StructureReport, StructureRow, StructureSectionResult
from lingua_oracle.registry import data_dir

SECTIONS = "B-12"
SUBSECTIONS = "B-13"
ITEMS = "B-14"


@functools.lru_cache(maxsize=16)
def load(regulation: str) -> dict | None:
    path = data_dir() / "sds_structure" / f"{regulation}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# -- comparing words -------------------------------------------------------------

def _fold(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold()
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"(?<=\w)-\s*(?=\w)", "", text)        # fire-fighting = firefighting
    return text


def tokens(text: str) -> list[str]:
    """The words of a heading, case and punctuation set aside. A sheet that
    prints the text's own "use(s)" has printed "uses"."""
    return re.findall(r"[^\W_]+", re.sub(r"(?<=[^\W\d_])\(s\)", "s", _fold(text)))


def _pattern(required: str) -> re.Pattern[str]:
    """The required heading as a pattern over tokens: "hazard(s)" takes both."""
    words = []
    for word in re.findall(r"[^\W_]+(?:\(s\))?", _fold(required)):
        if word.endswith("(s)"):
            words.append(re.escape(word[:-3]) + "s?")
        else:
            words.append(re.escape(word))
    return re.compile(r"^" + r" ".join(words) + r"$")


def same_heading(found: str, required: str) -> bool:
    return bool(_pattern(required).match(" ".join(tokens(found))))


def _starts_with(found_tokens: list[str], required: str) -> int:
    """How many of the found tokens make up the required heading at their
    start, or 0 where they do not."""
    pattern = _pattern(required)
    for end in range(len(found_tokens), 0, -1):
        if pattern.match(" ".join(found_tokens[:end])):
            return end
    return 0


def _score(found: str, required: str) -> float:
    a = {w.rstrip("s") for w in tokens(found)}
    b = {w.rstrip("s") for w in tokens(required.replace("(s)", ""))}
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# -- items -------------------------------------------------------------------------

_PHONE = re.compile(r"(?<![\w@/])(?:\+|00)?\(?\d[\d\s().\-/]{5,}\d(?![\w/])")
_CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DATE = re.compile(
    r"\b\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2})\b"
    r"|\b\d{4}[./-]\d{1,2}[./-]\d{1,2}\b"
    r"|\b\d{1,2}\.?\s+[^\W\d_]{3,}\.?,?\s+\d{4}\b"
    r"|\b[^\W\d_]{3,}\.?\s+\d{1,2},?\s+\d{4}\b")
_EMERGENCY = re.compile(r"emergenc|urgence|urgencia|notruf|notfall|nød|nöd|hätä",
                        re.IGNORECASE)
_CONTINUED = re.compile(r"continued on (the )?next page|end of (the )?(safety data sheet|sds)",
                        re.IGNORECASE)


def phones(text: str) -> list[str]:
    out = []
    for found in _PHONE.finditer(text):
        raw = found.group(0).strip()
        digits = re.sub(r"\D", "", raw)
        if not 7 <= len(digits) <= 15 or _CAS.match(raw) or _DATE.fullmatch(raw):
            continue
        out.append(raw)
    return out


# -- the sheet -------------------------------------------------------------------------

@dataclass
class _Heading:
    line: int
    page: int
    printed: str | None          # the number the sheet prints, if any
    number: str                  # the section it is taken to be
    text: str                    # the heading words, label and number off
    raw: str
    misnumbered: bool = False


@dataclass
class _Sub:
    number: str
    line: int
    text: str                    # what follows the number on its line
    content: list[str] = field(default_factory=list)


def _labels(table: dict, language: str) -> list[str]:
    words = {"section", "sección", "seccion", "abschnitt", "rubrique", "punkt", "punt"}
    for section in table["sections"][:1]:
        for lang, label in section["label"].items():
            if lang == language or language.startswith(lang):
                words.update(w for w in re.findall(r"[^\W\d_]+", label))
    return sorted((w for w in words if len(w) > 1), key=len, reverse=True)


def _required(table: dict, number: str, language: str) -> list[str]:
    """The heading(s) the sheet may print for a section, in its language.
    Canada mandates both languages: either, or both, may be printed."""
    section = table["sections"][int(number) - 1]
    heading = section["heading"]
    if table["regulation"] == "ca_whmis":
        options = [heading["en"], heading["fr"], f"{heading['en']} {heading['fr']}",
                   f"{heading['fr']} {heading['en']}"]
        return options
    tag = language.split("-")[0]
    return [heading[tag]] if tag in heading else []


def _all_required(table: dict, number: str) -> list[str]:
    return list(table["sections"][int(number) - 1]["heading"].values())


def _find_headings(document: Document, table: dict, language: str) -> list[_Heading]:
    lines = document.raw_lines
    labels = "|".join(re.escape(w) for w in _labels(table, language))
    before = re.compile(rf"^\s*(?:{labels})\s*(\d{{1,2}})(?![.,]?\d)\s*[.:)\-—–]*\s*(?P<rest>.*)$",
                        re.IGNORECASE)
    after = re.compile(rf"^\s*(\d{{1,2}})\s*\.?\s*(?:{labels})\b\s*[.:)\-—–]*\s*(?P<rest>.*)$",
                       re.IGNORECASE)
    bare = re.compile(r"^\s*(\d{1,2})(?![.,]?\d)\s*[.:)]?\s+(?P<rest>[^\W\d_].*)$")
    found: list[_Heading] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        text = " ".join((line.text or "").split())
        if not text or len(text) > 200:
            continue
        labelled = before.match(text) or after.match(text)
        match = labelled or bare.match(text)
        if match is None:
            continue
        printed = match.group(1)
        if not 1 <= int(printed) <= 16:
            continue
        rest = match.group("rest").strip()
        # A heading wrapped onto the next line: take it in while it helps.
        if index + 1 < len(lines):
            joined = f"{rest} {' '.join((lines[index + 1].text or '').split())}"
            options = _all_required(table, printed)
            if (any(_starts_with(tokens(joined), r) > len(tokens(rest)) for r in options)
                    and not any(same_heading(rest, r) for r in options)):
                rest = joined
        own = max((_score(rest, r) for r in _all_required(table, printed)), default=0)
        best_number, best = printed, own
        for k in range(1, 17):
            score = max((_score(rest, r) for r in _all_required(table, str(k))), default=0)
            if score > best:
                best_number, best = str(k), score
        if labelled is None and best < 0.5:
            continue                     # a numbered line of content, not a heading
        misnumbered = best_number != printed and best >= 0.75 and own < 0.5
        number = best_number if misnumbered else printed
        if number in seen:
            continue                     # a running head repeating the heading
        seen.add(number)
        found.append(_Heading(index, line.page, printed, number, rest, text, misnumbered))
    return found


def _spans(headings: list[_Heading], total: int) -> dict[str, tuple[int, int]]:
    ordered = sorted(headings, key=lambda h: h.line)
    out = {}
    for k, heading in enumerate(ordered):
        end = ordered[k + 1].line if k + 1 < len(ordered) else total
        out[heading.number] = (heading.line, end)
    return out


def _subsections(lines, start: int, end: int, number: str) -> list[_Sub]:
    pattern = re.compile(rf"^\s*{number}\.(\d{{1,2}})(?![\d,])\.?\s*(?P<rest>.*)$")
    subs: list[_Sub] = []
    for index in range(start + 1, end):
        text = " ".join((lines[index].text or "").split())
        found = pattern.match(text)
        if found and not re.match(r"^\d", found.group("rest") or "x"):
            subs.append(_Sub(f"{number}.{found.group(1)}", index, found.group("rest")))
        elif subs:
            subs[-1].content.append(text)
    return subs


def _row(check, key, binding, text, rule=None, *, ok=False, na=False, found="",
         expected="") -> StructureRow:
    status = "na" if na else "ok" if ok else ("fix" if binding else "check")
    return StructureRow(check=check, key=key, status=status, text=text,
                        quote=(rule or {}).get("quote", ""),
                        citation=(rule or {}).get("citation", ""),
                        found=found, expected=expected)


def read(document: Document, regulation: str, language: str) -> StructureReport:
    table = load(regulation)
    if table is None or table.get("status") != "ok":
        return StructureReport(regulation=regulation, state="not_available",
                               message="What this regulation requires of an SDS's "
                                       "structure is not on file.")
    lines = document.raw_lines
    headings = _find_headings(document, table, language)
    by_number = {h.number: h for h in headings}
    spans = _spans(headings, len(lines))
    rules = {k: table.get(k) for k in ("headings", "subheadings", "order", "empty", "optional")}
    heading_binding = bool(rules["headings"] and rules["headings"]["binding"])
    tag = language.split("-")[0]
    wording_on_file = (regulation == "ca_whmis" and tag in ("en", "fr")) or \
        tag in table.get("languages", [])
    report = StructureReport(regulation=regulation, document=table["document"])

    # Order, where the text states one: the sections as they come on the sheet.
    late: dict[str, str] = {}
    if rules["order"]:
        highest = None
        for heading in sorted(headings, key=lambda h: h.line):
            if highest is not None and int(heading.number) < int(highest):
                late[heading.number] = highest
            highest = heading.number if highest is None or int(heading.number) > int(highest) \
                else highest

    for section in table["sections"]:
        number = section["number"]
        required = _required(table, number, language)
        result = StructureSectionResult(number=number,
                                        required_heading=required[0] if required else "")
        heading = by_number.get(number)
        if heading is None:
            if not section.get("required", True):
                result.rows.append(_row(SECTIONS, "Section", False,
                                        f"Section {number} is not on the sheet; the text "
                                        "makes it optional.", rules["optional"], na=True))
            else:
                result.rows.append(_row(SECTIONS, "Section", heading_binding,
                                        f"Section {number} is missing.", rules["headings"],
                                        expected=required[0] if required else ""))
            report.sections.append(result)
            continue
        result.found, result.heading, result.page = True, heading.raw, heading.page
        if heading.misnumbered:
            result.rows.append(_row(SECTIONS, "Number", heading_binding,
                                    f"The heading of Section {number} is numbered "
                                    f"{heading.printed}.", rules["headings"],
                                    found=heading.raw))
        else:
            result.rows.append(_row(SECTIONS, "Number", heading_binding,
                                    f"Numbered {number}.", rules["headings"], ok=True))
        if number in late:
            result.rows.append(_row(SECTIONS, "Order", rules["order"]["binding"],
                                    f"Section {number} comes after Section {late[number]}.",
                                    rules["order"]))
        elif rules["order"]:
            result.rows.append(_row(SECTIONS, "Order", True, "In order.", rules["order"],
                                    ok=True))
        if not wording_on_file:
            result.rows.append(_row(SECTIONS, "Heading", False,
                                    "Heading wording not checked: the text is not on file "
                                    "in this language.", na=True, found=heading.text))
        elif any(same_heading(heading.text, r) for r in required):
            result.rows.append(_row(SECTIONS, "Heading", heading_binding, "As the text "
                                    "prints it.", rules["headings"], ok=True))
        else:
            result.rows.append(_row(SECTIONS, "Heading", heading_binding,
                                    "The heading differs from the text's.", rules["headings"],
                                    found=heading.text, expected=" / ".join(required[:2])))
        start, end = spans[number]
        _section_body(result, table, section, lines, start, end, rules, language,
                      wording_on_file)
        report.sections.append(result)

    _items(report, table, document, spans, headings)
    return report


def _section_body(result, table, section, lines, start, end, rules, language,
                  wording_on_file) -> None:
    number = section["number"]
    content = [" ".join((lines[i].text or "").split()) for i in range(start + 1, end)]
    content = [c for c in content if c]
    required_subs = section.get("subsections") or []
    if required_subs:
        subs = {s.number: s for s in _subsections(lines, start, end, number)}
        one_of = next((g for g in table.get("one_of", []) if required_subs[0]["number"] in g
                       or any(s["number"] in g for s in required_subs)), [])
        binding = bool(rules["subheadings"] and rules["subheadings"]["binding"])
        tag = language.split("-")[0]
        for sub in required_subs:
            sub_number = sub["number"]
            wording = sub["heading"].get(tag, "")
            key = f"{sub_number} {wording}".strip()
            found = subs.get(sub_number)
            if found is None:
                if sub_number in one_of and any(o in subs for o in one_of):
                    continue
                if sub_number in one_of:
                    others = " or ".join(one_of)
                    result.rows.append(_row(SUBSECTIONS, key, binding,
                                            f"None of {others} is on the sheet; the text "
                                            "requires one.", rules["subheadings"]))
                    continue
                result.rows.append(_row(SUBSECTIONS, key, binding,
                                        f"Sub-section {sub_number} is missing.",
                                        rules["subheadings"], expected=wording))
                continue
            rest_tokens = tokens(found.text)
            used = _starts_with(rest_tokens, wording) if wording_on_file and wording else 0
            if wording_on_file and wording and not used:
                result.rows.append(_row(SUBSECTIONS, key, binding,
                                        "The sub-heading differs from the text's.",
                                        rules["subheadings"], found=found.text,
                                        expected=wording))
            elif wording_on_file and wording:
                result.rows.append(_row(SUBSECTIONS, key, binding, "Present, as the text "
                                        "words it.", rules["subheadings"], ok=True))
            else:
                result.rows.append(_row(SUBSECTIONS, key, binding, "Present.",
                                        rules["subheadings"], ok=True))
            leftover = rest_tokens[used:] if used else rest_tokens
            has_content = bool(leftover) if used else False
            blank = not has_content and not any(c for c in found.content)
            if blank and rules["empty"] and table.get("empty_scope") == "subsection":
                    result.rows.append(_row(SUBSECTIONS, f"{sub_number} content",
                                            rules["empty"]["binding"],
                                            f"Sub-section {sub_number} is blank.",
                                            rules["empty"]))
    elif rules["empty"] and table.get("empty_scope") == "section":
        if not content and not section.get("content_optional"):
            result.rows.append(_row(SUBSECTIONS, "Content", rules["empty"]["binding"],
                                    f"Section {number} is empty.", rules["empty"]))


def _scope_text(scope: str, document: Document, spans, lines) -> str | None:
    if scope == "document":
        return "\n".join(line.text or "" for line in lines)
    if scope == "first_page":
        first = document.pages[0].number if document.pages else 1
        return "\n".join(line.text or "" for line in lines if line.page == first)
    if "." in scope:
        section, _ = scope.split(".", 1)
        if section not in spans:
            return None
        start, end = spans[section]
        subs = _subsections(lines, start, end, section)
        found = next((s for s in subs if s.number == scope), None)
        if found is None:
            return None
        return "\n".join([found.text, *found.content])
    if scope not in spans:
        return None
    start, end = spans[scope]
    return "\n".join(lines[i].text or "" for i in range(start, end))


def _page_numbering(document: Document) -> tuple[bool, list[int]]:
    total = len(document.pages)
    missing = []
    for k, page in enumerate(document.pages, start=1):
        text = "\n".join(line.text or "" for line in (page.raw_lines or page.lines))
        numbered = re.search(rf"(?<!\d){k}\s*(?:/|[^\W\d_]{{1,6}}\.?)\s*{total}(?!\d)", text)
        if not numbered and not _CONTINUED.search(text):
            missing.append(page.number)
    return not missing, missing


_ITEM_WORDS = {"telephone": "a telephone number", "emergency_telephone":
               "an emergency telephone number", "email": "an e-mail address",
               "date": "a date", "page_numbering": "page numbering"}


_NOUN = {"telephone": "telephone number", "emergency_telephone": "emergency telephone "
         "number", "email": "e-mail address", "date": "date"}


def _items(report: StructureReport, table: dict, document: Document, spans,
           headings) -> None:
    lines = document.raw_lines
    sections = {s.number: s for s in report.sections}
    for item in table.get("items", []):
        rule, scope, kind = item["rule"], item["scope"], item["kind"]
        binding = rule["binding"]
        where = {"document": "on the sheet", "first_page": "on the first page"}.get(
            scope, f"in {'sub-section' if '.' in scope else 'Section'} {scope}")
        key = _ITEM_WORDS[kind].capitalize()
        target = (report.document_rows if scope in ("document", "first_page")
                  else sections[scope.split(".")[0]].rows)
        if kind == "page_numbering":
            ok, missing = _page_numbering(document)
            if ok:
                target.append(_row(ITEMS, key, binding, "Every page is numbered.", rule,
                                   ok=True))
            else:
                # Only "page x of y" (or the English alternatives) can be read
                # in every language: not finding it is a question, not a fault.
                target.append(_row(ITEMS, key, False,
                                   "Page numbering such as \"1 / 3\" was not found on "
                                   f"page(s) {', '.join(map(str, missing[:8]))}.", rule))
            continue
        text = _scope_text(scope, document, spans, lines)
        if text is None:
            target.append(_row(ITEMS, key, binding, f"Not judged: {where.replace('in ', '')} "
                               "is not on the sheet.", rule, na=True))
            continue
        present = {
            "telephone": lambda t: bool(phones(t)),
            "email": lambda t: bool(_EMAIL.search(t)),
            "date": lambda t: bool(_DATE.search(t)),
            "emergency_telephone": _emergency,
        }[kind](text)
        if present:
            target.append(_row(ITEMS, key, binding, f"Found {where}.", rule, ok=True))
        else:
            target.append(_row(ITEMS, key, binding, f"No {_NOUN[kind]} found {where}.", rule))


def _emergency(text: str) -> bool:
    rows = text.split("\n")
    for k, row in enumerate(rows):
        if _EMERGENCY.search(row):
            window = " ".join(rows[k:k + 3])
            if phones(window):
                return True
    return False
