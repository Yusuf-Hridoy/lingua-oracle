"""The mixture rule table each regulation is calculated with.

One file per regulation under `data/mixture_rules/`, holding the cut-off
values and summation limits that regulation adopts and, beside every single
number, the document, section and page it was read from. Nothing here is typed
from memory: a value this builder cannot find in the text is left out, and the
calculation then reports that rule as not on file rather than guessing it.

Where the values come from, and why:

* `un_ghs`    - UN GHS Rev.11, the edition on file.
* `au_whs`    - UN GHS Rev.7, the edition Australia's WHS Regulations adopt.
* `ca_whmis`  - UN GHS Rev.7 as the Hazardous Products Regulations incorporate
                it. Which classes WHMIS covers is read from the HPR itself,
                not assumed: a class the regulations never name is recorded as
                not covered, which is how the aquatic classes drop out.
* `us_osha`   - 29 CFR 1910.1200 Appendix A. The appendix is HTML and not on
                file, so this builder fetches it, exactly as the Appendix C
                builder does, and only ever at build time.
* `eu_clp`, `uk_clp` - CLP Annex I, carried over from the rules this tool
                already implemented and already cites paragraph by paragraph.
                Annex I is not among the documents on file as a parsable text,
                so these two tables record the paragraph and table each number
                comes from and leave the page empty rather than invent one.
* `jp_jis`    - nothing. JIS Z 7252/7253 is not on file in any readable form
                (see builders/pending.py), so Japan has no table and the
                report says the check is not available there.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.common import BROWSER_UA, SourceUnavailable, fetch
from lingua_oracle.registry import data_dir

APPENDIX_A_URL = (
    "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppA")

#: Every class this tool can calculate, in the spelling the rest of the code
#: uses. A regulation's table says which of these it covers.
CALCULABLE = (
    "Skin Corr.", "Skin Irrit.", "Eye Dam.", "Eye Irrit.",
    "Resp. Sens.", "Skin Sens.", "Muta.", "Carc.", "Repr.", "Lact.",
    "STOT SE", "STOT RE", "Aquatic Acute", "Aquatic Chronic",
)


class NotInTheText(RuntimeError):
    """A table or row the builder expected is not in the document.

    Raised rather than skipped: a rule quietly missing from a published table
    would show up in the report as "not on file", which would be a lie about
    the document.
    """


# -- reading numbers out of cells ---------------------------------------------

_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_ANY_NUMBER = re.compile(r"(\d+(?:[.,]\d+)?)")
#: "1.0 \u2264 ingredient < 10 %" and "\u2265 1 % but < 5 %" are bands. The number
#: that matters is the bottom of the band, and the published tables do not
#: always print a per cent sign on it.
_BAND = re.compile(r"\u2264\s*ingredient|but\s*<")


def _amount(cell: str) -> Decimal | None:
    """The limit a cell states: the bottom of a band, or the percentage."""
    text = (cell or "").replace("\u00a0", " ")
    match = (_ANY_NUMBER if _BAND.search(text) else _NUMBER).search(text)
    if match is None:
        return None
    try:
        return Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:  # pragma: no cover - the regex rules this out
        return None


#: Rev.7 sets its comparison signs in a symbol font, which extracts as private
#: use characters. They are the same signs; they are put back so one parser
#: reads both editions.
_SYMBOLS = {"\uf0b3": "\u2265", "\uf0a3": "\u2264", "\uf0b4": "\u00d7",
            "\uf03c": "<", "\uf03e": ">", "\uf02d": "-"}


def _tidy(cell: str | None) -> str:
    text = (cell or "")
    for odd, sign in _SYMBOLS.items():
        text = text.replace(odd, sign)
    return " ".join(text.split())


def _label(cell: str | None) -> str:
    """A row or column label reduced to what two editions would share."""
    text = _tidy(cell).casefold()
    text = text.replace("\u00d7", "×")
    text = text.replace("‐", "-").replace("–", "-")
    return " ".join(re.sub(r"[^a-z0-9<>≥≤+×/ .-]", " ", text).split())


@dataclass
class Place:
    """Where one number was read from."""

    document: str
    section: str
    page: int | None = None

    def as_dict(self) -> dict:
        return {"document": self.document, "section": self.section,
                "page": self.page}


@dataclass
class Value:
    amount: Decimal
    raw: str
    place: Place
    qualifier: str = ""

    def as_dict(self) -> dict:
        out = {"amount": str(self.amount), "raw": self.raw,
               "source": self.place.as_dict()}
        if self.qualifier:
            out["qualifier"] = self.qualifier
        return out


@dataclass
class Table:
    """One regulation's rules, as they will be written out."""

    regulation: str
    document: str
    covers: list[str] = field(default_factory=list)
    rules: dict[str, dict[str, list[Value]]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def put(self, rule: str, key: str, value: Value) -> None:
        values = self.rules.setdefault(rule, {}).setdefault(key, [])
        # A published row and its continuation can carry the same limit twice.
        # One value stated twice is still one value.
        if any(v.amount == value.amount and v.qualifier == value.qualifier
               for v in values):
            return
        values.append(value)

    def as_dict(self) -> dict:
        return {
            "regulation": self.regulation,
            "document": self.document,
            "covers": sorted(self.covers),
            "rules": {rule: {key: [v.as_dict() for v in values]
                             for key, values in sorted(keys.items())}
                      for rule, keys in sorted(self.rules.items())},
            "notes": self.notes,
        }


# -- the shape of a cut-off table ---------------------------------------------

#: Row label -> the class and category of the ingredient that row is about.
#: One pattern per class, written to match both the UN's spelling and OSHA's.
_INGREDIENT_ROWS = (
    (re.compile(r"respiratory sensitizer.*sub[- ]?category 1a"), ("Resp. Sens.", "1A")),
    (re.compile(r"respiratory sensitizer.*sub[- ]?category 1b"), ("Resp. Sens.", "1B")),
    (re.compile(r"respiratory sensitizer.*category 1$"), ("Resp. Sens.", "1")),
    (re.compile(r"skin sensitizer.*sub[- ]?category 1a"), ("Skin Sens.", "1A")),
    (re.compile(r"skin sensitizer.*sub[- ]?category 1b"), ("Skin Sens.", "1B")),
    (re.compile(r"skin sensitizer.*category 1$"), ("Skin Sens.", "1")),
    (re.compile(r"category 1a/b mutagen"), ("Muta.", "1A/1B")),
    (re.compile(r"category 1a mutagen"), ("Muta.", "1A")),
    (re.compile(r"category 1b mutagen"), ("Muta.", "1B")),
    (re.compile(r"category 2 mutagen"), ("Muta.", "2")),
    (re.compile(r"category 1a/b carcinogen"), ("Carc.", "1A/1B")),
    (re.compile(r"category 1a carcinogen"), ("Carc.", "1A")),
    (re.compile(r"category 1b carcinogen"), ("Carc.", "1B")),
    (re.compile(r"category 1 carcinogen"), ("Carc.", "1")),
    (re.compile(r"category 2 carcinogen"), ("Carc.", "2")),
    (re.compile(r"additional category for effects on or via lactation"), ("Lact.", "")),
    (re.compile(r"category 1a reproductive"), ("Repr.", "1A")),
    (re.compile(r"category 1b reproductive"), ("Repr.", "1B")),
    (re.compile(r"category 1 reproductive"), ("Repr.", "1")),
    (re.compile(r"category 2 reproductive"), ("Repr.", "2")),
    (re.compile(r"category 1 target organ toxicant"), ("TARGET", "1")),
    (re.compile(r"category 2 target organ toxicant"), ("TARGET", "2")),
)

#: Column header -> the category of the mixture that column classifies into.
_COLUMN_CATEGORIES = (
    (re.compile(r"sub[- ]?category 1a|category 1a"), "1A"),
    (re.compile(r"sub[- ]?category 1b|category 1b"), "1B"),
    (re.compile(r"lactation"), ""),
    (re.compile(r"category 1"), "1"),
    (re.compile(r"category 2"), "2"),
    (re.compile(r"category 3"), "3"),
)


def _row_class(label: str) -> tuple[str, str] | None:
    for pattern, found in _INGREDIENT_ROWS:
        if pattern.search(label):
            return found
    return None


def _column_category(header: str) -> str | None:
    for pattern, category in _COLUMN_CATEGORIES:
        if pattern.search(header):
            return category
    return None


def _cut_offs(rows: list[list[str]], hazard: str, place: Place, table: Table,
              rule: str) -> None:
    """A cut-off table: one ingredient class per row, one mixture category per
    column, and the limit where they meet.

    Only the cells where the row's class and the column's category are the same
    are limits this tool uses - the rest of the grid is "--". The one exception
    is the band a category 1 target organ toxicant falls into, which classifies
    the mixture in category 2 and is recorded as a step down.
    """
    own: list[list[str]] = []
    above: list[list[str]] = []
    last: tuple[str, str] | None = None
    for raw_row in rows:
        cells = [_tidy(c) for c in raw_row]
        label = _label(cells[0] if cells else "")
        found = _row_class(label)
        if found is None and not (label == "" and last is not None):
            # Still in the header. A heading that spans several columns is
            # published once with the cells beside it empty, so each column
            # keeps what stood above it as well as its own words - and its own
            # words win, or the "Category 2" column would answer to the
            # "Category 1B" heading printed to its left.
            while len(own) < len(cells):
                own.append([])
                above.append([])
            spanning = ""
            for index, cell in enumerate(cells):
                if _tidy(cell):
                    own[index].append(_label(cell))
                    spanning = _label(cell)
                elif spanning:
                    above[index].append(spanning)
            continue
        if found is not None:
            last = found
        assert last is not None
        name, category = (hazard, last[1]) if last[0] == "TARGET" else last
        for index, cell in enumerate(cells[1:], start=1):
            if index >= len(own):
                continue
            amount = _amount(_tidy(cell))
            if amount is None:
                continue
            column = _column_category(" ".join(own[index]))
            if column is None:
                column = _column_category(" ".join(above[index]))
            if column is None:
                continue
            for part in category.split("/"):
                # A column headed "Category 1" covers its sub-categories: the
                # 1A row beneath it gives the limit for 1A.
                if (part == column or (not part and not column)
                        or (column and part and part.startswith(column))):
                    table.put(rule, f"{name} {part}".strip(), Value(
                        amount, _tidy(cell), place,
                        qualifier=_qualifier(own[index] + above[index], cell)))
                elif (name.startswith("STOT") and part == "1" and column == "2"
                      and "<" in cell):
                    # "1.0 <= ingredient < 10 %": a category 1 ingredient below
                    # the category 1 limit classifies the mixture category 2.
                    table.put(rule, f"{name} 1 step down", Value(
                        amount, _tidy(cell), place))


def _parent_categories(table: Table) -> None:
    """Give a bare category 1 the limit its own column heads.

    The published tables list a row per sub-category - 1A, 1B - under a column
    headed "Category 1 carcinogen". A sheet that says only "Carc. 1" is
    claiming that column, and where every sub-category under it carries the
    same limit, that limit is the column's. Where the sub-categories differ -
    the sensitizers - nothing is derived: those tables print their own
    category 1 row.
    """
    limits = table.rules.get("generic_limits", {})
    for name in ("Muta.", "Carc.", "Repr."):
        parent = f"{name} 1"
        if parent in limits:
            continue
        subs = [limits.get(f"{name} 1A"), limits.get(f"{name} 1B")]
        if not all(subs):
            continue
        shape = [[(v.amount, v.qualifier) for v in values] for values in subs]
        if shape[0] != shape[1]:
            continue
        for value in subs[0]:
            table.put("generic_limits", parent, Value(
                value.amount, value.raw, value.place,
                qualifier=value.qualifier))


def _qualifier(headers: list[str], cell: str) -> str:
    """What distinguishes one value in a cell from another in the same cell.

    The published tables give more than one limit for the same class where the
    answer depends on something this tool cannot see - the physical state of
    the ingredient, or which of two options an authority took. The distinction
    is kept so the report can show it rather than pick one silently.
    """
    state = next((h for h in headers
                  if "solid" in h or h == "gas" or "physical state" in h), "")
    note = re.search(r"\((?:see )?(note[^)]*)\)", cell)
    return " ".join(x for x in (state, note.group(1) if note else "") if x)


# -- UN GHS -------------------------------------------------------------------

#: Caption -> the rule it sets, for the tables this tool calculates. The
#: numbering is the UN's and is shared by Rev.7 and Rev.11.
_GHS_TABLES = {
    "3.2.3": "skin",
    "3.3.3": "eye",
    "3.4.5": "sensitisation",
    "3.5.1": "mutagenicity",
    "3.6.1": "carcinogenicity",
    "3.7.1": "reproductive",
    "3.8.2": "stot_se",
    "3.9.3": "stot_re",
    "4.1.3": "aquatic_acute",
    "4.1.4": "aquatic_chronic",
}


#: What the first cell of a cut-off table says, in both editions and in
#: Appendix A: it names what the rows are.
_FIRST_CELL = re.compile(r"(sum of (the concentrations|ingredients)|"
                         r"ingredients? classified as)")


def _is_cut_off_table(rows: list[list[str]]) -> bool:
    # The phrase heads the first column, but not always in the first row: a
    # heading spanning the value columns can be printed above it.
    return any(_FIRST_CELL.search(_label(row[0] if row else ""))
               for row in rows[:3])


def _ghs_pages(pdf) -> dict[str, tuple[int, list[list[str]]]]:
    """Find each cut-off table in a Purple Book, by its caption.

    A caption is printed above its table and repeated in the running text, and
    the page may carry several tables - a decision tree beside the cut-offs.
    The one wanted is the one whose first column lists the ingredients, so it
    is chosen by that rather than by being first on the page.
    """
    found: dict[str, tuple[int, list[list[str]]]] = {}
    caption = re.compile(
        r"Table (" + "|".join(re.escape(n) for n in _GHS_TABLES) + r")\s*[::]")
    for page in pdf.pages:
        text = page.extract_text() or ""
        numbers = {m.group(1) for m in caption.finditer(text)}
        if not numbers:
            continue
        tables = [t for t in page.extract_tables()
                  if len(t) > 2 and _is_cut_off_table(t)]
        if not tables:
            continue
        for number in sorted(numbers):
            if number in found:
                continue
            found[number] = (page.page_number, tables[0])
    return found


def _ghs(path: Path, regulation: str, document: str,
         covers: list[str] | None = None) -> Table:
    import pdfplumber

    table = Table(regulation=regulation, document=document)
    with pdfplumber.open(path) as pdf:
        pages = _ghs_pages(pdf)
        text_by_page = {i: " ".join((p.extract_text() or "").split())
                        for i, p in enumerate(pdf.pages)}
    missing = sorted(set(_GHS_TABLES) - set(pages))
    if missing:
        raise NotInTheText(
            f"{document}: no table found for {', '.join(missing)}")

    for number, rule in _GHS_TABLES.items():
        page_number, rows = pages[number]
        place = Place(document, f"Table {number}", page_number)
        if rule == "skin":
            _skin(rows, place, table)
        elif rule == "eye":
            _eye(rows, place, table)
        elif rule in ("aquatic_acute", "aquatic_chronic"):
            _aquatic(rows, place, table, rule)
        else:
            _cut_offs(rows, _HAZARD_OF[rule], place, table, "generic_limits")
    _stot_se_3(text_by_page, document, table)
    _parent_categories(table)
    table.covers = list(covers if covers is not None else _covered(table))
    return table


#: Which hazard the target-organ tables are about: the same rows, two classes.
_HAZARD_OF = {"sensitisation": "", "mutagenicity": "", "carcinogenicity": "",
              "reproductive": "", "stot_se": "STOT SE", "stot_re": "STOT RE"}


def _skin(rows: list[list[str]], place: Place, table: Table) -> None:
    """Table 3.2.3 / A.2.3: skin corrosion and irritation by summation."""
    wanted = {
        r"^skin category 1$": ("Skin Corr. 1", "Skin Corr. 1 to Skin Irrit. 2"),
        r"^skin category 2$": ("Skin Irrit. 2", None),
    }
    seen: set[str] = set()
    for row in rows:
        label = _label(row[0] if row else "")
        for pattern, keys in wanted.items():
            if not re.search(pattern, label):
                continue
            amounts = [(_amount(_tidy(c)), _tidy(c)) for c in row[1:]
                       if _amount(_tidy(c))]
            for key, (amount, raw) in zip(keys, amounts, strict=False):
                if key:
                    table.put("skin", key, Value(amount, raw, place))
                    seen.add(key)
        if label.startswith(("10 ×", "(10 ×")) and "category 3" not in label:
            amounts = [(_amount(_tidy(c)), _tidy(c)) for c in row[1:]
                       if _amount(_tidy(c))]
            if amounts:
                table.put("skin", "weighted Skin Irrit. 2",
                          Value(amounts[0][0], amounts[0][1], place))
                table.put("skin", "Skin Corr. 1 multiplier",
                          Value(Decimal(10), _tidy(row[0]), place))
                seen.add("weighted Skin Irrit. 2")
    for key in ("Skin Corr. 1", "Skin Irrit. 2", "weighted Skin Irrit. 2"):
        if key not in seen:
            raise NotInTheText(f"{place.document}: {place.section} has no {key}")


def _eye(rows: list[list[str]], place: Place, table: Table) -> None:
    """Table 3.3.3 / A.3.3: eye damage and irritation by summation."""
    seen: set[str] = set()
    for row in rows:
        label = _label(row[0] if row else "")
        amounts = [(_amount(_tidy(c)), _tidy(c)) for c in row[1:]
                   if _amount(_tidy(c))]
        if not amounts:
            continue
        if label.startswith(("10 ×", "(10 ×")):
            table.put("eye", "weighted Eye Irrit. 2",
                      Value(amounts[0][0], amounts[0][1], place))
            table.put("eye", "Eye Dam. 1 multiplier",
                      Value(Decimal(10), _tidy(row[0]), place))
            seen.add("weighted Eye Irrit. 2")
        elif "+" in label and "category 1" in label:
            table.put("eye", "Eye Dam. 1",
                      Value(amounts[0][0], amounts[0][1], place))
            seen.add("Eye Dam. 1")
            if len(amounts) > 1:
                table.put("eye", "Eye Dam. 1 to Eye Irrit. 2",
                          Value(amounts[1][0], amounts[1][1], place))
        elif re.search(r"^eye (irritation )?.?category 2", label):
            table.put("eye", "Eye Irrit. 2",
                      Value(amounts[0][0], amounts[0][1], place))
            seen.add("Eye Irrit. 2")
    for key in ("Eye Dam. 1", "Eye Irrit. 2", "weighted Eye Irrit. 2"):
        if key not in seen:
            raise NotInTheText(f"{place.document}: {place.section} has no {key}")


def _aquatic(rows: list[list[str]], place: Place, table: Table,
             rule: str) -> None:
    """Table 4.1.3 / 4.1.4: the aquatic classes by summation.

    Each row is an expression - "(M × 10 × Acute 1) + Acute 2 >= 25 %" - so the
    trigger and the weight each category carries into the next are both in the
    row, and both are read from it.
    """
    family = "Aquatic Acute" if rule == "aquatic_acute" else "Aquatic Chronic"
    for row in rows:
        text = _tidy(row[0] if row else "")
        amount = _amount(text)
        outcome = _label(row[1] if len(row) > 1 else "")
        category = re.search(r"(acute|chronic) ([1-4])", outcome)
        if amount is None or category is None:
            continue
        table.put(rule, f"{family} {category.group(2)}",
                  Value(amount, text, place))
        for weight in re.finditer(r"(\d+) ×\s*(?:M ×\s*)?(?:acute|chronic) ([1-4])",
                                  _label(text)):
            table.put(rule,
                      f"{family} {weight.group(2)} into {category.group(2)}",
                      Value(Decimal(weight.group(1)), text, place))
    if not table.rules.get(rule):
        raise NotInTheText(f"{place.document}: {place.section} gave no rows")


_SUGGESTED = re.compile(
    r"cut-?off value\s*/?\s*concentration limit of (\d+(?:\.\d+)?)\s*%", re.I)
#: The paragraph that carries this rule, in either document's numbering. The
#: Purple Book's pages are two columns and extract interleaved, so the nearest
#: preceding paragraph number is not reliably this rule's - only a number from
#: the mixture subsection itself is taken.
_PARAGRAPH = re.compile(r"\b((?:A\.)?\d\.8\.3\.4\.\d)\b")


def _stot_se_3(text_by_page: dict[int, str], document: str,
               table: Table) -> None:
    """The additive cut-off for category 3 target organ toxicity.

    Both the Purple Book and Appendix A give this one in a sentence rather than
    a table, and both hedge it - "has been suggested", "is appropriate". The
    number is recorded with the sentence it came from, so a reader can see what
    the source actually commits to.
    """
    for index, text in sorted(text_by_page.items()):
        match = _SUGGESTED.search(text)
        if match is None:
            continue
        before = _PARAGRAPH.findall(text[:match.start()])
        section = before[-1] if before else "3.8.3.4 (paragraph not identified)"
        sentence = text[match.start():match.start() + 200].split(". ")[0]
        table.put("stot_se_3", "STOT SE 3", Value(
            Decimal(match.group(1)), sentence, Place(document, section, index + 1),
            qualifier="given as a suggested limit"))
        return
    # Not an error: a regulation need not have this rule at all.
    table.notes.append(
        "no additive cut-off for category 3 target organ toxicity found in "
        f"{document}; that rule is reported as not on file")


def _covered(table: Table) -> list[str]:
    """The classes a table actually has rules for."""
    found = set()
    for rule, keys in table.rules.items():
        for key in keys:
            for name in CALCULABLE:
                if key.startswith(name) or rule.startswith(
                        name.casefold().replace(" ", "_")):
                    found.add(name)
        if rule == "skin":
            found |= {"Skin Corr.", "Skin Irrit."}
        if rule == "eye":
            found |= {"Eye Dam.", "Eye Irrit."}
    return sorted(found)


# -- OSHA ---------------------------------------------------------------------

#: Appendix A's own numbering for the same tables.
_OSHA_TABLES = {
    "A.2.3": ("skin", None),
    "A.3.3": ("eye", None),
    "A.4.5": ("generic_limits", ""),
    "A.5.1": ("generic_limits", ""),
    "A.6.1": ("generic_limits", ""),
    "A.7.1": ("generic_limits", ""),
    "A.8.2": ("generic_limits", "STOT SE"),
    "A.9.3": ("generic_limits", "STOT RE"),
}

OSHA_DOCUMENT = "29 CFR 1910.1200 Appendix A"


def _osha(body: bytes) -> Table:
    """Appendix A, which OSHA publishes as HTML.

    The appendix states one value per cell where the Purple Book offers an
    authority a choice, because OSHA has already made that choice. Classes it
    has no table for - the aquatic ones - are not covered by the standard, and
    the report says so rather than leaving a gap.
    """
    from lxml import html

    doc = html.fromstring(body)
    table = Table(regulation="us_osha", document=OSHA_DOCUMENT)
    found: set[str] = set()
    for element in doc.iter("table"):
        head = " ".join(element.text_content().split())[:120]
        match = re.search(r"Table (A\.\d+\.\d+)\s*[-–]", head)
        if match is None or match.group(1) not in _OSHA_TABLES:
            continue
        number = match.group(1)
        if number in found:
            continue
        found.add(number)
        rule, hazard = _OSHA_TABLES[number]
        rows = _html_rows(element)
        place = Place(OSHA_DOCUMENT, f"Table {number}", None)
        if rule == "skin":
            _skin(rows, place, table)
        elif rule == "eye":
            _eye(rows, place, table)
        else:
            _cut_offs(rows, hazard or "", place, table, rule)
    missing = sorted(set(_OSHA_TABLES) - found)
    if missing:
        raise NotInTheText(
            f"{OSHA_DOCUMENT}: no table found for {', '.join(missing)}")
    text = " ".join(doc.text_content().split())
    _stot_se_3({0: text}, OSHA_DOCUMENT, table)
    _parent_categories(table)
    table.notes.append(
        "Appendix A has no cut-off table for the aquatic classes: the standard "
        "does not cover them, so they are reported as not covered rather than "
        "as not calculated.")
    table.covers = _covered(table)
    return table


def _html_rows(element) -> list[list[str]]:
    """An HTML table as a rectangle.

    A cell that spans columns or rows is written once in the markup, so the
    rows beneath it come out short and every column after it is read against
    the wrong heading. Each spanned cell is repeated into the places it covers,
    which is what the table looks like on the page.
    """
    grid: list[list[str | None]] = []
    for index, row in enumerate(element.iter("tr")):
        while len(grid) <= index:
            grid.append([])
        column = 0
        for cell in row.iter("td", "th"):
            while column < len(grid[index]) and grid[index][column] is not None:
                column += 1
            text = " ".join(cell.text_content().split())
            across = max(1, int(cell.get("colspan") or 1))
            down = max(1, int(cell.get("rowspan") or 1))
            for d in range(down):
                while len(grid) <= index + d:
                    grid.append([])
                line = grid[index + d]
                for a in range(across):
                    while len(line) <= column + a:
                        line.append(None)
                    line[column + a] = text
            column += across
    width = max((len(line) for line in grid), default=0)
    return [[(cell or "") for cell in line] + [""] * (width - len(line))
            for line in grid]


def _osha_body(*, use_cache: bool = True) -> bytes:
    local = sources.BY_PATH["us-osha/appendix_a.html"].where
    if local.exists():
        return local.read_bytes()
    try:
        return fetch(APPENDIX_A_URL, headers={"User-Agent": BROWSER_UA},
                     use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        raise SourceUnavailable(
            f"OSHA Appendix A fetch failed: {exc}. "
            f"{sources.describe('us-osha/appendix_a.html')}") from exc


# -- Canada -------------------------------------------------------------------

#: What the Hazardous Products Regulations have to say about a class for it to
#: be one WHMIS covers. The regulations name their hazard classes in full, so
#: a class they never name is one they do not have.
_HPR_NAMES = {
    "Skin Corr.": "skin corrosion",
    "Skin Irrit.": "skin irritation",
    "Eye Dam.": "serious eye damage",
    "Eye Irrit.": "eye irritation",
    "Resp. Sens.": "respiratory sensitiz",
    "Skin Sens.": "skin sensitiz",
    "Muta.": "germ cell mutagenicity",
    "Carc.": "carcinogenicity",
    "Repr.": "reproductive toxicity",
    "Lact.": "via lactation",
    "STOT SE": "single exposure",
    "STOT RE": "repeated exposure",
    # The class as the regulations would have to name it. A passing mention of
    # aquatic ecotoxicity in what a safety data sheet must say is not the
    # regulations adopting an aquatic hazard class.
    "Aquatic Acute": "hazardous to the aquatic environment",
    "Aquatic Chronic": "hazardous to the aquatic environment",
}


def _hpr_covers(path: Path) -> tuple[list[str], str]:
    """Which classes the HPR names, read from the regulations themselves."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        text = " ".join(" ".join((p.extract_text() or "").split())
                        for p in pdf.pages).casefold()
    # Once is a mention; a class the regulations run on is named many times
    # over - in the class list, the classification rules and the label rules.
    covered = [name for name, phrase in _HPR_NAMES.items()
               if text.count(phrase) > 1]
    absent = sorted(set(_HPR_NAMES) - set(covered))
    note = ("classes the Hazardous Products Regulations never name, and so do "
            f"not cover: {', '.join(absent)}" if absent else
            "the Hazardous Products Regulations name every class this tool "
            "calculates")
    return covered, note


# -- EU and GB CLP ------------------------------------------------------------

#: Annex I, paragraph by paragraph, as this tool already implemented it. Every
#: entry names the paragraph and table the number comes from; Annex I is not on
#: file as a text this builder can parse, so there is no page, and saying so is
#: better than printing one that was never checked.
_ANNEX_I: tuple[tuple[str, str, str, str], ...] = (
    ("skin", "Skin Corr. 1", "5", "3.2.3.3.4, Table 3.2.3"),
    ("skin", "Skin Corr. 1 to Skin Irrit. 2", "1", "3.2.3.3.4, Table 3.2.3"),
    ("skin", "Skin Irrit. 2", "10", "3.2.3.3.4, Table 3.2.3"),
    ("skin", "weighted Skin Irrit. 2", "10", "3.2.3.3.4, Table 3.2.3"),
    ("skin", "Skin Corr. 1 multiplier", "10", "3.2.3.3.4, Table 3.2.3"),
    ("eye", "Eye Dam. 1", "3", "3.3.3.3.4, Table 3.3.3"),
    ("eye", "Eye Dam. 1 to Eye Irrit. 2", "1", "3.3.3.3.4, Table 3.3.3"),
    ("eye", "Eye Irrit. 2", "10", "3.3.3.3.4, Table 3.3.3"),
    ("eye", "weighted Eye Irrit. 2", "10", "3.3.3.3.4, Table 3.3.3"),
    ("eye", "Eye Dam. 1 multiplier", "10", "3.3.3.3.4, Table 3.3.3"),
    ("aquatic_acute", "Aquatic Acute 1", "25", "4.1.3.5.5, Table 4.1.1"),
    ("aquatic_chronic", "Aquatic Chronic 1", "25", "4.1.3.5.5, Table 4.1.2"),
    ("aquatic_chronic", "Aquatic Chronic 2", "25", "4.1.3.5.5, Table 4.1.2"),
    ("aquatic_chronic", "Aquatic Chronic 3", "25", "4.1.3.5.5, Table 4.1.2"),
    ("aquatic_chronic", "Aquatic Chronic 4", "25", "4.1.3.5.5, Table 4.1.2"),
    ("aquatic_chronic", "Aquatic Chronic 1 into 2", "10", "4.1.3.5.5, Table 4.1.2"),
    ("aquatic_chronic", "Aquatic Chronic 1 into 3", "100", "4.1.3.5.5, Table 4.1.2"),
    ("aquatic_chronic", "Aquatic Chronic 2 into 3", "10", "4.1.3.5.5, Table 4.1.2"),
    ("generic_limits", "Skin Sens. 1", "1.0", "3.4.3.3, Table 3.4.6"),
    ("generic_limits", "Skin Sens. 1A", "0.1", "3.4.3.3, Table 3.4.6"),
    ("generic_limits", "Skin Sens. 1B", "1.0", "3.4.3.3, Table 3.4.6"),
    ("generic_limits", "Resp. Sens. 1", "0.2", "3.4.3.3, Table 3.4.6"),
    ("generic_limits", "Resp. Sens. 1A", "0.1", "3.4.3.3, Table 3.4.6"),
    ("generic_limits", "Resp. Sens. 1B", "0.2", "3.4.3.3, Table 3.4.6"),
    ("generic_limits", "Muta. 1", "0.1", "3.5.3.1, Table 3.5.2"),
    ("generic_limits", "Muta. 1A", "0.1", "3.5.3.1, Table 3.5.2"),
    ("generic_limits", "Muta. 1B", "0.1", "3.5.3.1, Table 3.5.2"),
    ("generic_limits", "Muta. 2", "1.0", "3.5.3.1, Table 3.5.2"),
    ("generic_limits", "Carc. 1", "0.1", "3.6.3.1, Table 3.6.2"),
    ("generic_limits", "Carc. 1A", "0.1", "3.6.3.1, Table 3.6.2"),
    ("generic_limits", "Carc. 1B", "0.1", "3.6.3.1, Table 3.6.2"),
    ("generic_limits", "Carc. 2", "1.0", "3.6.3.1, Table 3.6.2"),
    ("generic_limits", "Repr. 1", "0.3", "3.7.3.1, Table 3.7.2"),
    ("generic_limits", "Repr. 1A", "0.3", "3.7.3.1, Table 3.7.2"),
    ("generic_limits", "Repr. 1B", "0.3", "3.7.3.1, Table 3.7.2"),
    ("generic_limits", "Repr. 2", "3.0", "3.7.3.1, Table 3.7.2"),
    ("generic_limits", "Lact.", "0.3", "3.7.3.1, Table 3.7.2"),
    ("generic_limits", "STOT SE 1", "10.0", "3.8.3.4, Table 3.8.3"),
    ("generic_limits", "STOT SE 2", "10.0", "3.8.3.4, Table 3.8.3"),
    ("generic_limits", "STOT SE 1 step down", "1.0", "3.8.3.4, Table 3.8.3"),
    ("generic_limits", "STOT RE 1", "10.0", "3.9.3.4, Table 3.9.4"),
    ("generic_limits", "STOT RE 2", "10.0", "3.9.3.4, Table 3.9.4"),
    ("generic_limits", "STOT RE 1 step down", "1.0", "3.9.3.4, Table 3.9.4"),
    ("stot_se_3", "STOT SE 3", "20", "3.8.3.4.5, Table 3.8.3"),
)


def _clp(regulation: str, document: str) -> Table:
    table = Table(regulation=regulation, document=document)
    for rule, key, amount, section in _ANNEX_I:
        table.put(rule, key, Value(
            Decimal(amount), f"{amount} %", Place(document, section, None)))
    table.covers = _covered(table)
    table.notes.append(
        "carried over from the Annex I rules this tool already implemented; "
        "every value names the paragraph and table it comes from, and no page "
        "because Annex I is not on file as a text this builder reads")
    return table


# -- building -----------------------------------------------------------------

def rules_dir() -> Path:
    return data_dir() / "mixture_rules"


def build(regulation: str, *, use_cache: bool = True) -> Table:
    """One regulation's rule table, read from the documents on file."""
    if regulation == "eu_clp":
        return _clp("eu_clp", "Regulation (EC) No 1272/2008, Annex I")
    if regulation == "uk_clp":
        return _clp("uk_clp",
                    "Regulation (EC) No 1272/2008 as retained in GB law, Annex I")
    if regulation == "un_ghs":
        return _ghs(sources.require("un-ghs/GHS_Rev11_en.pdf"), "un_ghs",
                    "UN GHS Rev.11 (2025)")
    if regulation == "au_whs":
        return _ghs(sources.require("ghs-rev7/GHS_Rev7_en.pdf"), "au_whs",
                    "UN GHS Rev.7 (2017), as adopted by the WHS Regulations")
    if regulation == "ca_whmis":
        covers, note = _hpr_covers(sources.require("ca-whmis/hpr_bilingual.pdf"))
        table = _ghs(sources.require("ghs-rev7/GHS_Rev7_en.pdf"), "ca_whmis",
                     "UN GHS Rev.7 (2017), as incorporated by the Hazardous "
                     "Products Regulations (SOR/2015-17)", covers=covers)
        table.notes.append(note)
        return table
    if regulation == "us_osha":
        return _osha(_osha_body(use_cache=use_cache))
    raise SourceUnavailable(
        f"no mixture rules for {regulation}: no document on file sets them")


def write(regulation: str, *, use_cache: bool = True) -> Path:
    table = build(regulation, use_cache=use_cache)
    rules_dir().mkdir(parents=True, exist_ok=True)
    path = rules_dir() / f"{regulation}.json"
    path.write_text(json.dumps(table.as_dict(), indent=2, ensure_ascii=False)
                    + "\n", encoding="utf-8")
    return path
