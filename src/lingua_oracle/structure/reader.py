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
    """The required heading as a pattern over its words, spaces and hyphens
    set aside ("First Aid" is "First-aid"); "hazard(s)" takes both."""
    words = []
    for word in re.findall(r"[^\W_]+(?:\(s\))?", _fold(required)):
        if word.endswith("(s)"):
            words.append(re.escape(word[:-3]) + "s?")
        else:
            words.append(re.escape(word))
    return re.compile(r"^" + "".join(words) + r"$")


def same_heading(found: str, required: str) -> bool:
    return bool(_pattern(required).match("".join(tokens(found))))


def _starts_with(found_tokens: list[str], required: str) -> int:
    """How many of the found tokens make up the required heading at their
    start, or 0 where they do not."""
    pattern = _pattern(required)
    for end in range(len(found_tokens), 0, -1):
        if pattern.match("".join(found_tokens[:end])):
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
    r"|\b\d{1,2}-[^\W\d_]{3,9}\.?-\d{4}\b"
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


@functools.lru_cache(maxsize=1)
def _every_heading() -> dict[str, tuple[str, ...]]:
    """Each section's heading in every regulation and language on file: what
    a heading line may read like, whichever text the sheet followed."""
    out: dict[str, list[str]] = {str(n): [] for n in range(1, 17)}
    for path in sorted((data_dir() / "sds_structure").glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        for section in table.get("sections", []):
            out[section["number"]] += list(section["heading"].values())
    return {k: tuple(v) for k, v in out.items()}


def _overlap(found: str, number: str) -> float:
    return max((_score(found, h) for h in _every_heading()[number]), default=0.0)


def _title_like(text: str) -> bool:
    """A heading's words, not a sentence: short, opening with a letter, no
    sentence break inside."""
    words = text.split()
    return (0 < len(words) <= 10 and bool(re.match(r"[^\W\d_]", text))
            and not re.search(r"[.;]\s+\S", text))


def _below(lines, index: int, end: int | None = None) -> tuple[int, str]:
    """The line directly below this one, in the same column: on a two-column
    sheet the next line read may be the other column's, while the heading's
    own continuation sits under it at the same left edge."""
    here = lines[index]
    height = max(here.bbox[3] - here.bbox[1], 6.0)
    for k in range(index + 1, min(end or len(lines), index + 12)):
        line = lines[k]
        if line.page != here.page:
            break
        if line.bbox == (0.0, 0.0, 0.0, 0.0) or here.bbox == (0.0, 0.0, 0.0, 0.0):
            return k, " ".join((line.text or "").split())   # no geometry: next line
        if line.bbox[1] - here.bbox[1] > 2.5 * height:
            break
        if abs(line.bbox[0] - here.bbox[0]) <= 3 and line.bbox[1] > here.bbox[1] + 1:
            return k, " ".join((line.text or "").split())
    return -1, ""


def _beside(lines, index: int) -> tuple[int, str]:
    """The text on the same row to the right: a number printed in a column of
    its own, its words in the next."""
    here = lines[index]
    for k in range(index + 1, min(len(lines), index + 4)):
        line = lines[k]
        if line.page != here.page:
            break
        if here.bbox == (0.0, 0.0, 0.0, 0.0):
            return k, " ".join((line.text or "").split())
        if abs(line.bbox[1] - here.bbox[1]) <= 2 and line.bbox[0] > here.bbox[2]:
            return k, " ".join((line.text or "").split())
    return -1, ""


def _continues(text: str) -> bool:
    """A line that carries on the one above: opens in lower case, is short,
    and is not itself numbered."""
    return bool(re.match(r"^[^\W\d_A-ZÀ-ÞΑ-ΩА-Я]", text)) and len(text.split()) <= 8


def _find_headings(document: Document, table: dict, language: str) -> list[_Heading]:
    lines = document.raw_lines
    labels = "|".join(re.escape(w) for w in _labels(table, language))
    before = re.compile(rf"^\s*(?:{labels})\s*(\d{{1,2}})(?![.,]?\d)\s*[.,:)\-—–]*\s*(?P<rest>.*)$",
                        re.IGNORECASE)
    after = re.compile(rf"^\s*(\d{{1,2}})\s*\.?\s*(?:{labels})\b\s*[.,:)\-—–]*\s*(?P<rest>.*)$",
                       re.IGNORECASE)
    bare = re.compile(r"^\s*(\d{1,2})(?![.,]?\d)\s*[.:)]?\s*(?P<rest>[^\W\d_].*)$")
    best: dict[str, tuple[float, _Heading]] = {}
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
        _, following = _below(lines, index)
        if not rest:
            _, beside = _beside(lines, index)
            words = beside or (following if labelled else "")
            if words and not re.match(r"^\d", words):
                rest = words                     # its words beside it, or below
                following = ""
        elif rest and following and _continues(following) and not re.search(r"[.:]$", rest):
            rest = f"{rest} {following}"         # a heading wrapped onto the next line
        own = _overlap(rest, printed)
        # A numbered line is a heading when it reads as one: a title that
        # shares words with this section's heading in some text on file. A
        # numbered step in Section 4, or a sentence opening "Section 8 on
        # suitable materials", is not.
        # A line opening with the section label is a heading when it reads as
        # a title, whatever its words; a bare number needs its words too.
        if labelled is not None:
            if not (own >= 0.5 or _title_like(rest)):
                continue
        elif not (own >= 0.5 or (_title_like(rest) and own > 0)):
            continue
        best_number, best_score = printed, own
        for k in range(1, 17):
            score = _overlap(rest, str(k))
            if score > best_score:
                best_number, best_score = str(k), score
        misnumbered = best_number != printed and best_score >= 0.75 and own < 0.34
        number = best_number if misnumbered else printed
        heading = _Heading(index, line.page, printed, number, rest, text, misnumbered)
        held = best.get(number)
        # The same number twice - a running head, a mention - is the line
        # that reads most like the heading; the first where they tie.
        if held is None or own > held[0]:
            best[number] = (own, heading)
    return sorted((h for _, h in best.values()), key=lambda h: h.line)


def _spans(headings: list[_Heading], total: int) -> dict[str, tuple[int, int]]:
    ordered = sorted(headings, key=lambda h: h.line)
    out = {}
    for k, heading in enumerate(ordered):
        end = ordered[k + 1].line if k + 1 < len(ordered) else total
        out[heading.number] = (heading.line, end)
    return out


def _subsections(lines, start: int, end: int, number: str,
                 wording: dict[str, str] | None = None) -> list[_Sub]:
    """The numbered sub-sections between a section's heading and the next.
    A sub-heading whose number stands alone on its line takes its words from
    the line below; one wrapped onto the next line is joined where that
    brings it closer to the text's words."""
    pattern = re.compile(rf"^\s*{number}\.(\d{{1,2}})(?![\d,])\.?\s*(?P<rest>.*)$")
    wording = wording or {}
    subs: list[_Sub] = []
    taken: set[int] = set()
    for index in range(start + 1, end):
        if index in taken:
            continue
        text = " ".join((lines[index].text or "").split())
        found = pattern.match(text)
        if found and not re.match(r"^\d", found.group("rest") or "x"):
            sub_number, rest = f"{number}.{found.group(1)}", found.group("rest")
            at, following = _below(lines, index, end)
            if not rest:
                at, following = _beside(lines, index)
                if at < 0:
                    at, following = _below(lines, index, end)
            if following and not pattern.match(following):
                required = wording.get(sub_number, "")
                if not rest:
                    rest = following
                    taken.add(at)
                elif required and _starts_with(tokens(f"{rest} {following}"), required) > \
                        _starts_with(tokens(rest), required):
                    rest = f"{rest} {following}"
                    taken.add(at)
            subs.append(_Sub(sub_number, index, rest))
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
                rule = section.get("required_by") or rules["headings"]
                result.rows.append(_row(SECTIONS, "Section", bool(rule and rule["binding"]),
                                        f"Section {number} is missing.", rule,
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
            result.rows.append(_heading_differs(regulation, table, number, heading.text,
                                                required, heading_binding, rules["headings"]))
        start, end = spans[number]
        _section_body(result, table, section, lines, start, end, rules, language,
                      wording_on_file)
        report.sections.append(result)

    _items(report, table, document, spans, headings)
    return report


#: Where the text prints the headings a sheet "shall include" - REACH Annex
#: II, Part B, EU and GB - any other wording is a fault. Elsewhere a heading
#: that names the same section in other words ("Hazards identification",
#: "Product and company identification") is one to check; only a missing
#: heading, a wrong number or words naming another section are faults.
_WORDING_EXACT = {"eu_clp", "uk_clp"}


def _heading_differs(regulation, table, number, found, required, binding, rule):
    """A heading in other words than the text's: which section do they name?"""
    own = _overlap(found, number)
    other, score = number, own
    for k in range(1, 17):
        if str(k) != number and _overlap(found, str(k)) > score:
            other, score = str(k), _overlap(found, str(k))
    expected = " / ".join(required[:2])
    if other != number and score >= 0.5:
        title = table["sections"][int(other) - 1]["heading"].get("en", "")
        return _row(SECTIONS, "Heading", binding,
                    f"The heading names Section {other} ({title}), not Section {number}.",
                    rule, found=found, expected=expected)
    if regulation in _WORDING_EXACT:
        return _row(SECTIONS, "Heading", binding, "The heading differs from the text's.",
                    rule, found=found, expected=expected)
    return _row(SECTIONS, "Heading", False,
                f"Names Section {number} in other words than the text's.", rule,
                found=found, expected=expected)


def _section_body(result, table, section, lines, start, end, rules, language,
                  wording_on_file) -> None:
    number = section["number"]
    content = [" ".join((lines[i].text or "").split()) for i in range(start + 1, end)]
    content = [c for c in content if c]
    required_subs = section.get("subsections") or []
    if required_subs:
        tag = language.split("-")[0]
        wording = {s["number"]: s["heading"].get(tag, "") for s in required_subs}
        subs = {s.number: s for s in _subsections(lines, start, end, number, wording)}
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
    elif not content and section.get("content_optional"):
        # The heading is required; what goes under it may be left out.
        result.rows.append(_row(SUBSECTIONS, "Content", True,
                                f"No content under the heading; the text lets Section "
                                f"{number}'s content be left out.", rules["optional"], ok=True))
    elif rules["empty"] and table.get("empty_scope") == "section":
        if not content:
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


def section_spans(document: Document, regulation: str, language: str) -> dict[str, tuple[int, int]]:
    """Each section's (first, last) raw line, as the structure reader finds
    the headings: {"9": (120, 160)}. Empty where no table is on file."""
    table = load(regulation)
    if table is None or table.get("status") != "ok":
        return {}
    headings = _find_headings(document, table, language)
    return _spans(headings, len(document.raw_lines))
