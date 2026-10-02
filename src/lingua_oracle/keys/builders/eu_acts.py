"""Which amending act last touched each part of CLP Annex IV.

CLP states every precautionary statement twice - Annex IV Part 1 beside the
hazard class it is selected for, Part 2 in all 24 languages - and the two have
drifted, because several amending acts rewrote one Part and not the other.
Deciding which rendering is the law therefore means knowing, per code and per
language, which act produced each one.

Two sources are used, and they must agree:

* **The acts themselves.** Each amending regulation's own ANNEX IV says what it
  does, entry by entry: "The entry concerning code P261 is replaced as follows".
  Parsed here into {marker: {Part: {code: operation}}}.
* **The consolidation's markers.** The Publications Office interleaves ``▼M12``,
  ``▼B`` and so on through the consolidated text, marking which act produced the
  block that follows. Read per row for Part 1 and per table for Part 2.

Where they agree, the later act wins and that Part holds the text in force.
Where they disagree, or where the two Parts come from the same act, nothing is
inferred: Part 2 stands and the disagreement is written into the audit. The rule
this replaces was a vote - if 80% of languages showed the same difference, call
it an amendment - which had no way to tell a 2019 rewrite from a typing error
repeated across translations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import html as LH

from lingua_oracle.keys.builders.common import fetch, normalise_code, strip_markers

#: ``▼M12``, ``►B``, ``▼C3`` - an arrow and the act's tag in the consolidation.
MARKER = re.compile(r"[▼►]\s*(M\d+|B|C\d+|A\d+)")
_CODE = re.compile(r"\b([PH]\s?\d{3}(?:\s*\+\s*[PH]\s?\d{3})*)\b")
_BARE_CODE = re.compile(
    r"^[‘'\"\u201c]?\s*([PH][\s\d+\[\]]*\d)\s*[’'\"\u201d]?$")
_ANNEX_IV = re.compile(r"ANNEX\s+IV")
_NEXT_ANNEX = re.compile(r"ANNEX\s+V[I]*")


def act_rank(marker: str | None) -> int | None:
    """Order of an act in the consolidation. Base act 0, M<n> is n.

    Corrigenda (``C<n>``) get no rank: a corrigendum corrects a specific act,
    so its position in this sequence is not defined by its own number.
    """
    if marker == "B":
        return 0
    if marker and (m := re.fullmatch(r"M(\d+)", marker)):
        return int(m.group(1))
    return None


def celex_for(title: str) -> str | None:
    """CELEX id from an act's title, e.g. '(EU) 2016/918' -> '32016R0918'.

    Two numbering styles, and they read in opposite orders: up to 2014 an act is
    "No 487/2013" (number first), afterwards "2016/918" (year first). A
    corrigendum has no CELEX of its own here - its line names the act it
    corrects, which is a different document - so it gets none.
    """
    if title.strip().lower().startswith("corrigendum"):
        return None
    if m := re.search(r"No\s+(\d+)/(\d{4})", title):
        number, year = m.group(1), m.group(2)
    elif m := re.search(r"\((?:EU|EC|EEC)\)\s*(\d{4})/(\d+)", title):
        year, number = m.group(1), m.group(2)
    else:
        return None
    return f"3{year}R{int(number):04d}"


def amending_acts(doc) -> dict[str, dict[str, str]]:
    """{marker: {title, celex, oj, date}} from the consolidation's front matter."""
    out: dict[str, dict[str, str]] = {}
    tag = re.compile(r"[▼►]?\s*(M\d+|C\d+|B)\s*$")
    for table in doc.xpath("//table")[:3]:
        for row in table.xpath(".//tr"):
            cells = [" ".join(" ".join(c.itertext()).split())
                     for c in row.xpath(".//td|.//th")]
            if len(cells) < 2 or not cells[1]:
                continue
            m = tag.match(cells[0].strip())
            if not m:
                continue
            rest = cells[2:]
            out.setdefault(m.group(1), {
                "title": cells[1],
                "celex": celex_for(cells[1]) or "",
                "oj": " ".join(rest[:2]).strip(),
                "date": rest[2] if len(rest) > 2 else "",
            })
    return out


def markers_by_code(doc) -> tuple[dict[str, str], dict[str, str]]:
    """({code: marker} for Part 1 rows, {code: marker} for Part 2 tables).

    Markers are not attached to the rows they govern; they are interleaved in
    document order and hold until the next one. So the document is walked once,
    in order, carrying the marker currently in force.
    """
    from lingua_oracle.keys.builders.eu_clp import _CODE_CELL, _row_cells

    in_force: str | None = None
    table_marker: list[str | None] = []
    row_marker: dict[tuple[int, int], str | None] = {}
    index = -1
    for el in doc.iter():
        for text in (el.text, el.tail):
            if text:
                found = MARKER.findall(text)
                if found:
                    in_force = found[-1]
        if el.tag != "table":
            continue
        index += 1
        table_marker.append(in_force)
        current = in_force
        for r_i, row in enumerate(el.xpath(".//tr")):
            for sub in row.iter():
                for text in (sub.text, sub.tail):
                    if text:
                        found = MARKER.findall(text)
                        if found:
                            current = found[-1]
            row_marker[(index, r_i)] = current

    part_one: dict[str, str] = {}
    part_two: dict[str, str] = {}
    for t_i, table in enumerate(doc.xpath("//table")):
        rows = table.xpath(".//tr")
        if len(rows) < 2:
            continue
        head = _row_cells(rows[0])
        is_part_one = not (len(head) < 3
                           or _CODE_CELL.match(head[0].strip().replace(" ", "")))
        if is_part_one:
            for r_i, row in enumerate(rows[1:], start=1):
                cells = _row_cells(row)
                if len(cells) < 2:
                    continue
                code = normalise_code(cells[0])
                if _CODE_CELL.match(code) and row_marker.get((t_i, r_i)):
                    part_one.setdefault(code, row_marker[(t_i, r_i)])
        else:
            code = normalise_code(head[0])
            if _CODE_CELL.match(code) and table_marker[t_i]:
                part_two.setdefault(code, table_marker[t_i])
    return part_one, part_two


def _annex_iv_paragraphs(doc) -> list[str]:
    """The act's own ANNEX IV, as a list of paragraph texts in document order."""
    out: list[str] = []
    inside = False
    for el in doc.iter("p", "h1", "h2", "h3"):
        text = " ".join(" ".join(el.itertext()).split())
        if not inside:
            if _ANNEX_IV.fullmatch(text):
                inside = True
            continue
        if _NEXT_ANNEX.fullmatch(text):
            break
        out.append(text)
    return out


def _operation(text: str) -> str | None:
    if re.search(r"\b(is|are) deleted", text):
        return "deleted"
    if re.search(r"\b(is|are) inserted", text):
        return "inserted"
    if re.search(r"replaced (by|as) (the )?follow", text):
        return "replaced"
    return None


def annex_iv_scope(celex: str, *, use_cache: bool = True
                   ) -> dict[str, dict[str, str]]:
    """{'Part 1': {code: operation}, 'Part 2': {...}} for one amending act.

    Read from the act's English version. An act amends every language at once -
    its Annex IV gives the replacement in each language, and for Part 2 in all of
    them in one block - so which entries it touches is a fact about the act, not
    about a language.
    """
    raw = fetch(f"http://publications.europa.eu/resource/celex/{celex}",
                headers={"Accept": "application/xhtml+xml", "Accept-Language": "eng"},
                use_cache=use_cache)
    paragraphs = _annex_iv_paragraphs(LH.fromstring(raw))
    scope: dict[str, dict[str, str]] = {"Part 1": {}, "Part 2": {}}
    part: str | None = None
    for i, text in enumerate(paragraphs):
        if m := re.match(r"Part (\d) is amended", text):
            part = f"Part {m.group(1)}"
            continue
        if m := re.match(r"Tables? (\d)\.(\d)", text):
            # Part 1's tables are numbered 6.x, Part 2's 1.x.
            part = "Part 1" if m.group(1) == "6" else "Part 2"
            continue
        operation = _operation(text)
        if not operation or part is None:
            continue
        if operation == "deleted":
            # Nothing follows a deletion, so the sentence is the only source.
            codes = [normalise_code(c) for c in _CODE.findall(text)]
        else:
            # The sentence names the entries loosely - "codes P370 + P380 +
            # P375 [+ P378]" splits into five separate codes under any regex
            # that does not know the combination. The entries themselves follow,
            # each opening with its own code, and those are unambiguous.
            codes = []
            for ahead in paragraphs[i + 1:]:
                stripped = ahead.strip()
                if _operation(stripped) or re.match(
                        r"(Tables? \d\.\d|Part \d is amended)", stripped):
                    break
                if m := _BARE_CODE.match(stripped):
                    codes.append(normalise_code(m.group(1)))
        for code in codes:
            scope[part].setdefault(code, operation)
    return scope


@dataclass(frozen=True)
class Decision:
    """Which Part holds the text in force for one code in one language."""

    code: str
    language: str
    part: str                 # "Part 1" or "Part 2"
    act: str                  # the marker of the deciding act, or "B"
    note: str
    corroborated: bool

    @property
    def from_part_one(self) -> bool:
        return self.part == "Part 1"


def decide(code: str, language: str, part_one_marker: str | None,
           part_two_marker: str | None,
           scope: dict[str, dict[str, dict[str, str]]]) -> Decision:
    """Choose the Part whose text is in force for one code in one language.

    `scope` is {marker: {Part: {code: operation}}} for the acts that have been
    read. The acts decide; the markers corroborate. Anything short of agreement
    keeps Part 2, which is what the key has always held, and says why.
    """
    def latest_from_acts(part: str) -> str:
        touched = [m for m, s in scope.items() if code in s.get(part, {})]
        ranked = [(act_rank(m), m) for m in touched if act_rank(m) is not None]
        return max(ranked)[1] if ranked else "B"

    acts_one, acts_two = latest_from_acts("Part 1"), latest_from_acts("Part 2")
    agree_one = part_one_marker == acts_one
    agree_two = part_two_marker == acts_two
    rank_one, rank_two = act_rank(acts_one), act_rank(acts_two)

    if not (agree_one and agree_two):
        return Decision(
            code, language, "Part 2", part_two_marker or "B",
            f"acts and markers disagree (Part 1: act {acts_one} vs marker "
            f"{part_one_marker or 'none'}; Part 2: act {acts_two} vs marker "
            f"{part_two_marker or 'none'}) - Part 2 kept",
            corroborated=False,
        )
    if rank_one is None or rank_two is None:
        return Decision(code, language, "Part 2", part_two_marker or "B",
                        "an act with no place in the sequence (a corrigendum) "
                        "produced one of the Parts - Part 2 kept",
                        corroborated=False)
    if rank_one > rank_two:
        return Decision(code, language, "Part 1", acts_one,
                        f"Part 1 was last amended by {acts_one}, Part 2 by "
                        f"{acts_two}", corroborated=True)
    if rank_two > rank_one:
        return Decision(code, language, "Part 2", acts_two,
                        f"Part 2 was last amended by {acts_two}, Part 1 by "
                        f"{acts_one}", corroborated=True)
    return Decision(code, language, "Part 2", acts_two,
                    f"both Parts come from the same act ({acts_two})",
                    corroborated=True)


def markers_used(part_one: dict[str, str], part_two: dict[str, str],
                 codes: set[str] | None = None) -> set[str]:
    """Markers that govern an Annex IV precautionary statement in this document."""
    used = set()
    for mapping in (part_one, part_two):
        for code, marker in mapping.items():
            if code.startswith("P") and (codes is None or code in codes):
                used.add(marker)
    return {m for m in used if m}


__all__ = [
    "Decision",
    "act_rendering",
    "act_rank",
    "amending_acts",
    "annex_iv_scope",
    "celex_for",
    "decide",
    "markers_by_code",
    "markers_used",
    "strip_markers",
]


_QUOTES = "‘’“”'\"„«»"


def act_rendering(celex: str, lang_iso3: str, language: str, code: str, part: str,
                  *, use_cache: bool = True) -> str | None:
    """How the amending act itself prints one statement, in one language.

    The consolidation is a rendering of the acts, and renderings can lose a
    character. When the text in force looks defective, the act that produced it
    is the place to check: if the act prints the same thing, the defect is the
    law's own and no correction can be made from it.
    """
    from lingua_oracle.keys.builders.eu_clp import _row_cells

    raw = fetch(f"http://publications.europa.eu/resource/celex/{celex}",
                headers={"Accept": "application/xhtml+xml",
                         "Accept-Language": lang_iso3},
                use_cache=use_cache)
    doc = LH.fromstring(raw)
    for table in doc.xpath("//table"):
        rows = table.xpath(".//tr")
        for r_i, row in enumerate(rows):
            cells = _row_cells(row)
            if not cells:
                continue
            if normalise_code(cells[0].strip(_QUOTES).strip()) != code:
                continue
            if part == "Part 1":
                if len(cells) >= 2 and cells[1].strip():
                    return strip_markers(cells[1]).strip(_QUOTES).strip()
            else:
                # A Part 2 entry is a block: the code, then one row per language.
                for later in rows[r_i + 1:]:
                    later_cells = _row_cells(later)
                    if (len(later_cells) >= 2
                            and later_cells[0].strip().upper() == language.upper()):
                        return strip_markers(
                            later_cells[1]).strip(_QUOTES).strip()
    return None
