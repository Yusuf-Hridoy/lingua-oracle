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
_BAND = re.compile(r"\u2264\s*(ingredient|concentration)|but\s*<")


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
class Implication:
    """One class a regulation says carries another with it."""

    source_class: str
    implied: str
    place: Place
    raw: str

    def as_dict(self) -> dict:
        return {"class": self.source_class, "implies": self.implied,
                "raw": self.raw, "source": self.place.as_dict()}


@dataclass
class Table:
    """One regulation's rules, as they will be written out."""

    regulation: str
    document: str
    covers: list[str] = field(default_factory=list)
    rules: dict[str, dict[str, list[Value]]] = field(default_factory=dict)
    implications: list[Implication] = field(default_factory=list)
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
            "implications": [i.as_dict() for i in self.implications],
            "notes": self.notes,
        }


# -- the shape of a cut-off table ---------------------------------------------

#: Row label -> the class and category of the ingredient that row is about.
#: One pattern per class, written to match both the UN's spelling and OSHA's.
_INGREDIENT_ROWS = (
    # The acts spell it "sensitiser", the Purple Book "sensitizer". Each
    # pattern is anchored at the start of the row's own label: a footnote
    # saying "If a Category 2 specific target organ toxicant is present at
    # 1,0 %" names the class too, and that number is not a limit.
    (re.compile(r"^respiratory sensiti[sz]er.*sub[- ]?category 1a"), ("Resp. Sens.", "1A")),
    (re.compile(r"^respiratory sensiti[sz]er.*sub[- ]?category 1b"), ("Resp. Sens.", "1B")),
    (re.compile(r"^respiratory sensiti[sz]er.*category 1$"), ("Resp. Sens.", "1")),
    (re.compile(r"^skin sensiti[sz]er.*sub[- ]?category 1a"), ("Skin Sens.", "1A")),
    (re.compile(r"^skin sensiti[sz]er.*sub[- ]?category 1b"), ("Skin Sens.", "1B")),
    (re.compile(r"^skin sensiti[sz]er.*category 1$"), ("Skin Sens.", "1")),
    (re.compile(r"^category 1a/b mutagen"), ("Muta.", "1A/1B")),
    (re.compile(r"^category 1a.*mutagen"), ("Muta.", "1A")),
    (re.compile(r"^category 1b.*mutagen"), ("Muta.", "1B")),
    (re.compile(r"^category 2.*mutagen"), ("Muta.", "2")),
    (re.compile(r"^category 1a/b carcinogen"), ("Carc.", "1A/1B")),
    (re.compile(r"^category 1a.*carcinogen"), ("Carc.", "1A")),
    (re.compile(r"^category 1b.*carcinogen"), ("Carc.", "1B")),
    (re.compile(r"^category 1 carcinogen"), ("Carc.", "1")),
    (re.compile(r"^category 2.*carcinogen"), ("Carc.", "2")),
    (re.compile(r"^additional category for.*lactation"), ("Lact.", "")),
    (re.compile(r"^category 1a.*reproduct"), ("Repr.", "1A")),
    (re.compile(r"^category 1b.*reproduct"), ("Repr.", "1B")),
    (re.compile(r"^category 1 reproduct"), ("Repr.", "1")),
    (re.compile(r"^category 2.*reproduct"), ("Repr.", "2")),
    # The GB rendering drops an amendment marker between "Organ" and
    # "Toxicant", so the class is recognised by the words that survive it.
    (re.compile(r"^category 1\b.*target organ"), ("TARGET", "1")),
    (re.compile(r"^category 2\b.*target organ"), ("TARGET", "2")),
)

#: What a column heading says about the physical state of the ingredient,
#: where a table splits its limits on one. Nothing else about a column is
#: needed: the published tables are diagonal, and a row's limits are its own.
_STATES = (
    (re.compile(r"solid\s*/\s*liquid|liquid\s*/\s*solid"), "solid/liquid"),
    (re.compile(r"^gas$"), "gas"),
    (re.compile(r"all physical states"), "all physical states"),
)


#: A footnote printed as the last row of a table. Its text names classes and
#: carries numbers - CLP's note under Table 3.7.2 gives the 0,1 % at which a
#: safety data sheet must be available - and none of them are limits.
_FOOTNOTE = re.compile(r"^\(?\d*\)?\s*note\b")


def _row_class(label: str) -> tuple[str, str] | None:
    if _FOOTNOTE.match(label):
        return None
    for pattern, found in _INGREDIENT_ROWS:
        if pattern.search(label):
            return found
    return None


def _state(heading: str) -> str:
    for pattern, state in _STATES:
        if pattern.search(heading):
            return state
    return ""


def _cut_offs(rows: list[list[str]], hazard: str, place: Place, table: Table,
              rule: str) -> None:
    """A cut-off table: one ingredient class per row, its limits along the row.

    These tables are diagonal - the cell where a row's class meets its own
    category holds the limit, and the rest of the grid is dashes - so a limit
    on a row belongs to that row's class and nothing has to be inferred from
    which column it sits in. What the column does say is what the limit is
    qualified by: the sensitiser tables split solid or liquid from gas, and
    both halves are kept, because a mixture is one or the other and the report
    is not entitled to pick.

    The one cell that is not its row's own category is the band a category 1
    target organ toxicant falls into - "1,0 % <= concentration < 10 %" - which
    classifies the mixture category 2 and is recorded as a step down.
    """
    states: dict[int, str] = {}
    last: tuple[str, str] | None = None
    for raw_row in rows:
        cells = [_tidy(c) for c in raw_row]
        label = _label(cells[0] if cells else "")
        found = _row_class(label)
        values = [(index, cell) for index, cell in enumerate(cells[1:], start=1)
                  if _amount(cell) is not None]
        if _FOOTNOTE.match(label):
            last = None
            continue
        if found is None and (last is None or not values):
            # A heading. The only thing worth remembering from one is which
            # physical state each column is for.
            for index, cell in enumerate(cells[1:], start=1):
                state = _state(_label(cell))
                if state:
                    states[index] = state
            continue
        if found is not None:
            last = found
        name, category = (hazard, last[1]) if last[0] == "TARGET" else last
        for index, cell in values:
            amount = _amount(cell)
            if (name.startswith("STOT") and category == "1"
                    and _BAND.search(cell)):
                table.put(rule, f"{name} 1 step down",
                          Value(amount, cell, place))
                continue
            for part in category.split("/"):
                table.put(rule, f"{name} {part}".strip(), Value(
                    amount, cell, place,
                    qualifier=_qualifier(states.get(index, ""), cell)))


def _parent_categories(table: Table) -> None:
    """Give a bare category 1 the limit its own column heads.

    The published tables list a row per sub-category - 1A, 1B - under a column
    headed "Category 1 carcinogen". A sheet that says only "Carc. 1" is
    claiming that column, and where every sub-category under it carries the
    same limits, those are the column's. Where the sub-categories differ - the
    sensitisers, whose 1A is ten times stricter - nothing is derived: those
    tables print their own category 1 row.
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


def _qualifier(state: str, cell: str) -> str:
    """What one limit is conditional on, where the same class has more than one.

    Two things do that in the published tables: the physical state of the
    ingredient, and a note leaving the choice to the adopting authority. Both
    are kept with the number, so the report can say which limit it used rather
    than picking one silently.
    """
    note = re.search(r"[\[(](?:see )?(note[^\])]*)[\])]", cell, re.I)
    return " ".join(x for x in (state, note.group(1).lower() if note else "")
                    if x)


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
    _implications(text_by_page, document, table)
    _parent_categories(table)
    table.covers = list(covers if covers is not None else _covered(table))
    return table


#: Which hazard the target-organ tables are about: the same rows, two classes.
_HAZARD_OF = {"sensitisation": "", "mutagenicity": "", "carcinogenicity": "",
              "reproductive": "", "stot_se": "STOT SE", "stot_re": "STOT RE"}


def _weighted(label: str) -> bool:
    """A row that weights the severe class into the milder one."""
    return bool(re.match(r"^\(?\s*10\s*×", label))


def _skin(rows: list[list[str]], place: Place, table: Table) -> None:
    """Table 3.2.3 / A.2.3: skin corrosion and irritation by summation.

    Three rows matter, and each document names them its own way - "Skin
    Category 1" in the Purple Book, "Skin corrosion Sub-Category 1A, 1B, 1C or
    Category 1" in CLP - so they are told apart by which category they are
    about, and by the one that opens with the multiplier.
    """
    seen: set[str] = set()
    for row in rows:
        label = _label(row[0] if row else "")
        amounts = [(_amount(_tidy(c)), _tidy(c)) for c in row[1:]
                   if _amount(_tidy(c))]
        if not amounts:
            continue
        if _weighted(label):
            if "category 3" in label:
                continue
            table.put("skin", "weighted Skin Irrit. 2",
                      Value(amounts[0][0], amounts[0][1], place))
            table.put("skin", "Skin Corr. 1 multiplier",
                      Value(Decimal(10), _tidy(row[0]), place))
            seen.add("weighted Skin Irrit. 2")
        elif "category 1" in label:
            table.put("skin", "Skin Corr. 1",
                      Value(amounts[0][0], amounts[0][1], place))
            seen.add("Skin Corr. 1")
            if len(amounts) > 1:
                table.put("skin", "Skin Corr. 1 to Skin Irrit. 2",
                          Value(amounts[1][0], amounts[1][1], place))
        elif "category 2" in label:
            table.put("skin", "Skin Irrit. 2",
                      Value(amounts[0][0], amounts[0][1], place))
            seen.add("Skin Irrit. 2")
    for key in ("Skin Corr. 1", "Skin Irrit. 2", "weighted Skin Irrit. 2"):
        if key not in seen:
            raise NotInTheText(f"{place.document}: {place.section} has no {key}")


def _eye(rows: list[list[str]], place: Place, table: Table) -> None:
    """Table 3.3.3 / A.3.3: eye damage and irritation by summation.

    The damaging row is the one that adds skin corrosion to serious eye damage,
    whichever words a document uses for either.
    """
    seen: set[str] = set()
    for row in rows:
        label = _label(row[0] if row else "")
        amounts = [(_amount(_tidy(c)), _tidy(c)) for c in row[1:]
                   if _amount(_tidy(c))]
        if not amounts:
            continue
        if _weighted(label):
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
        # Whole row: one document prints the expression and the classification
        # it gives in two columns, another runs them together on a line.
        text = _tidy(" ".join(row))
        amount = _amount(text)
        outcome = _label(text)
        # The last one named: where a row and its outcome share a line, the
        # expression comes first and the classification it gives comes last.
        named = re.findall(r"(acute|chronic) ([1-4])", outcome)
        if amount is None or not named:
            continue
        category = named[-1]
        table.put(rule, f"{family} {category[1]}", Value(amount, text, place))
        for weight in re.finditer(
                r"(\d+) ×\s*(?:M ×\s*)?(?:acute|chronic) ([1-4])",
                _label(text)):
            table.put(rule, f"{family} {weight.group(2)} into {category[1]}",
                      Value(Decimal(weight.group(1)), text, place))
    if not table.rules.get(rule):
        raise NotInTheText(f"{place.document}: {place.section} gave no rows")


_SUGGESTED = re.compile(
    r"(?:cut-?off value\s*/?\s*)?(?:generic\s+)?concentration limit of "
    r"(\d+(?:[.,]\d+)?)\s*%", re.I)
#: The paragraph that carries this rule, in either document's numbering. The
#: Purple Book's pages are two columns and extract interleaved, so the nearest
#: preceding paragraph number is not reliably this rule's - only a number from
#: the mixture subsection itself is taken.
_PARAGRAPH = re.compile(r"\b((?:A\.)?\d\.8\.3\.4\.\d)\b")


def _stot_se_3(text_by_page: dict[int, str], document: str, table: Table,
               *, paragraph_prefix: str = "", paged: bool = True) -> None:
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
        section = paragraph_prefix + (
            before[-1] if before else "3.8.3.4 (paragraph not identified)")
        sentence = text[match.start():match.start() + 200].split(". ")[0]
        # What the document commits to. The Purple Book suggests this number,
        # CLP and Appendix A call it appropriate; neither is a flat rule, and
        # the report says which was said rather than flattening both.
        hedge = ("given as a suggested limit" if "suggest" in sentence.lower()
                 else "given as an appropriate limit"
                 if "appropriate" in sentence.lower() else "")
        table.put("stot_se_3", "STOT SE 3", Value(
            Decimal(match.group(1).replace(",", ".")), sentence,
            Place(document, section, index + 1 if paged else None),
            qualifier=hedge))
        return
    # Not an error: a regulation need not have this rule at all.
    table.notes.append(
        "no additive cut-off for category 3 target organ toxicity found in "
        f"{document}; that rule is reported as not on file")


#: A regulation saying that a skin corrosive damages the eye as well. It
#: decides whether a sheet stating Skin Corr. 1 and nothing about the eye has
#: left the eye unstated or has stated Eye Dam. 1 without writing it, and the
#: two readings give opposite verdicts. Only a regulation that says so in its
#: own text gets the benefit of it.
_IMPLIES_EYE = re.compile(
    r"skin corrosi\w+[^.]{0,90}(?:shall|should|are|is|will)\s+(?:be\s+)?"
    r"considered[^.]{0,120}serious (?:eye damage|damage to the eye)"
    r"[^.]{0,220}\.", re.I)


#: The same rule as the Purple Book states it: not in a sentence of its own
#: but as the note under the label-elements table, which says the eye
#: statement may be left off a skin corrosive because the skin statement
#: already carries it. The note is printed inside a decision figure whose
#: columns interleave when the page is read as text, so only the half that
#: survives intact is matched.
_IMPLIES_EYE_NOTE = re.compile(
    r"Where a chemical is classified as skin Category 1, labelling for "
    r"serious eye damage\s*/\s*eye irritation may be", re.I)
_LABEL_TABLE = re.compile(r"Table (3\.3\.\d+)\s*[::]\s*Label elements", re.I)


def _implications(text_by_page: dict[int, str], document: str, table: Table,
                  *, paragraph_prefix: str = "", paged: bool = True) -> None:
    """Record what a regulation says one classification carries with it.

    Two documents say it two ways. CLP and the retained GB act say it outright
    in 3.3.2.2: a skin corrosive is to be considered as seriously damaging to
    the eye. The Purple Book says it as the note under its label-elements
    table - the eye statement may be omitted from a skin corrosive because the
    skin statement already covers it - which is the same rule seen from the
    label. Either will do; neither is assumed.
    """
    for index, text in sorted(text_by_page.items()):
        match = _IMPLIES_EYE.search(text)
        page = index + 1 if paged else None
        if match is not None:
            before = re.findall(r"\b(\d\.\d\.\d(?:\.\d){0,3})\.?\s",
                                text[:match.start()])
            section = paragraph_prefix + (before[-1] if before
                                          else "paragraph not identified")
            table.implications.append(Implication(
                source_class="Skin Corr. 1", implied="Eye Dam. 1",
                place=Place(document, section, page),
                raw=" ".join(match.group(0).split())))
            return
        note = _IMPLIES_EYE_NOTE.search(text)
        if note is None:
            continue
        caption = _LABEL_TABLE.search(text)
        where = (f"{caption.group(1)}, note a" if caption
                 else "label elements table, note a")
        table.implications.append(Implication(
            source_class="Skin Corr. 1", implied="Eye Dam. 1",
            place=Place(document, f"Table {where}", page),
            raw=" ".join(note.group(0).split())
                + " omitted as this information is already included in the "
                  "hazard statement for skin Category 1"))
        return
    table.notes.append(
        f"{document} was searched and does not say that a skin corrosive is "
        "also seriously damaging to the eye, so that is not read into a sheet "
        "that states only skin corrosion")


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
    # Appendix A is a web page: it has no pages to cite, and the paragraph
    # number it prints is what a reader looks the sentence up by.
    _stot_se_3({0: text}, OSHA_DOCUMENT, table, paged=False)
    _implications({0: text}, OSHA_DOCUMENT, table, paged=False)
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

#: Annex I's own numbering for the tables this tool calculates. CLP numbers
#: them differently from the Purple Book - the sensitiser limits are 3.4.5
#: here and 3.4.5 there, but the mutagen limits are 3.5.2 against 3.5.1 - so
#: the mapping is written out rather than assumed to be shared.
_CLP_TABLES = {
    "3.2.3": ("skin", None),
    "3.3.3": ("eye", None),
    "3.4.5": ("generic_limits", ""),
    "3.5.2": ("generic_limits", ""),
    "3.6.2": ("generic_limits", ""),
    "3.7.2": ("generic_limits", ""),
    "3.8.3": ("generic_limits", "STOT SE"),
    "3.9.4": ("generic_limits", "STOT RE"),
    "4.1.1": ("aquatic_acute", None),
    "4.1.2": ("aquatic_chronic", None),
}

#: What the first cell of an Annex I cut-off table says. The act writes
#: "ingredient" in some tables and "component" in others.
_CLP_FIRST_CELL = ("sum of ingredients", "sum of components",
                   "ingredient classified as", "component classified as")


def _clp_tables(doc) -> dict[str, list[list[str]]]:
    """Annex I's cut-off tables, each under the number the act prints above it.

    The act is one long XHTML document whose paragraphs are themselves tables,
    so a table is found by what its first column says and then given its number
    by the nearest caption before it. Two of the tables - single and repeated
    exposure - are word for word identical, which is why the caption is read by
    position in the text rather than by matching on content.
    """
    flat = " ".join(doc.text_content().split())
    captions = [(m.start(), m.group(1))
                for m in re.finditer(r"Table (\d+\.\d+\.\d+)", flat)]
    found: dict[str, list[list[str]]] = {}
    cursor = 0
    for element in doc.xpath("//table"):
        rows = _html_rows(element)
        first = _label(rows[0][0] if rows and rows[0] else "")
        if not first.startswith(_CLP_FIRST_CELL):
            continue
        signature = " ".join(" ".join(row) for row in rows)[:60]
        at = flat.find(signature, cursor)
        if at < 0:
            continue
        cursor = at + len(signature)
        before = [number for position, number in captions if position < at]
        if before and before[-1] in _CLP_TABLES and before[-1] not in found:
            found[before[-1]] = rows
    return found


def _eu(doc, regulation: str, document: str) -> Table:
    table = Table(regulation=regulation, document=document)
    tables = _clp_tables(doc)
    missing = sorted(set(_CLP_TABLES) - set(tables))
    if missing:
        raise NotInTheText(
            f"{document}: no table found for {', '.join(missing)}")
    for number, (rule, hazard) in _CLP_TABLES.items():
        # Annex I has no pages: it is a text, and saying "page 1" of it would
        # be an invention. The table number is what a reader looks it up by.
        place = Place(document, f"Annex I, Table {number}", None)
        _read(tables[number], rule, hazard, place, table)
    flat = {0: " ".join(doc.text_content().split())}
    _stot_se_3(flat, document, table, paragraph_prefix="Annex I, ", paged=False)
    _implications(flat, document, table, paragraph_prefix="Annex I, ",
                  paged=False)
    _parent_categories(table)
    table.covers = _covered(table)
    return table


def _read(rows, rule: str, hazard: str | None, place: Place,
          table: Table) -> None:
    """One table, through whichever parser its rule needs."""
    if rule == "skin":
        _skin(rows, place, table)
    elif rule == "eye":
        _eye(rows, place, table)
    elif rule in ("aquatic_acute", "aquatic_chronic"):
        _aquatic(rows, place, table, rule)
    else:
        _cut_offs(rows, hazard or "", place, table, rule)


# -- GB CLP, which is a PDF ---------------------------------------------------

#: A token that opens a value cell in the GB rendering: "at least", or the
#: bottom of a band written as "1,0 % <= concentration < 10 %". Nothing else
#: does - a bare whole number ends "Category 1", and the <= and < inside a band
#: are interior - and taking any of those for a column start would cut the
#: labels, or the bands, in half.
_CELL_START = re.compile(r"^\u2265|^\d+,\d+$")

#: Where a table stops and the act goes back to prose.
_GB_AFTER_TABLE = re.compile(
    r"^(Note\b|\[?F?\d*TABLE\b|\d+\.\d+\.\d+\.|[a-z] For\b)", re.I)


def _gb_lines(page, top: float, bottom: float) -> list[list[str]]:
    """One table on one page of the GB PDF, rebuilt from where the words are.

    legislation.gov.uk's PDF draws no ruling lines a table extractor can use,
    and its own column guesses split words in half. The words themselves are
    placed accurately, so the grid is rebuilt from them: the columns are where
    the value cells begin, everything to the left of the first of them is the
    row's label, and a line carrying no value is the rest of the label above
    it, which is how the act prints a label too long for one line.
    """
    words = page.crop((0, top, page.width, bottom)).extract_words()
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= 2.5:
            lines[-1].append(word)
        else:
            lines.append([word])
    # Sorting by top alone puts a superscript ahead of the words beside it;
    # within a line the order is left to right.
    lines = [sorted(line, key=lambda w: w["x0"]) for line in lines]
    lines = [line for line in lines
             if not _GB_FURNITURE.search(" ".join(w["text"] for w in line))]

    starts = sorted({round(word["x0"]) for line in lines for word in line
                     if _CELL_START.match(word["text"])})
    if not starts:
        return []
    columns: list[float] = []
    for x in starts:
        if not columns or x - columns[-1] > 30:
            columns.append(x)
    edge = columns[0] - 5

    rows: list[list[str]] = []
    for line in lines:
        label = " ".join(w["text"] for w in line if w["x0"] < edge)
        cells = [""] * len(columns)
        for word in line:
            if word["x0"] < edge:
                continue
            index = max(i for i, x in enumerate(columns) if word["x0"] >= x - 12)
            cells[index] = (cells[index] + " " + word["text"]).strip()
        # Only on a row that states a limit: a heading row's columns are what
        # say which physical state each limit is for, and must stay apart.
        if any(_amount(c) for c in cells):
            cells = _rejoin(cells)
        rows.append([label, *cells])
    return rows


def _merge_wrapped(rows: list[list[str]]) -> list[list[str]]:
    """Put a label the act wrapped over two lines back together.

    A line carrying no limit, under one that does, is the rest of the row
    above - and the act wraps a label across columns as readily as across
    lines, so whatever is on it joins the label. Run over the whole table at
    once, because a table can wrap over the foot of its page too.
    """
    out: list[list[str]] = []
    for row in rows:
        label, cells = row[0], row[1:]
        if (out and not any(_amount(c) for c in cells)
                and any(_amount(c) for c in out[-1][1:])):
            rest = " ".join(x for x in (label, *cells) if x)
            out[-1][0] = f"{out[-1][0]} {rest}".strip()
            continue
        out.append(list(row))
    return out


def _caption(number: str) -> re.Pattern:
    """The act's caption line for one table, as the PDF prints it.

    legislation.gov.uk stamps amendment markers onto the caption - "[F61Table
    3.4.5" - and switches between "TABLE" and "Table" from one to the next.
    Matching the whole line keeps the references in the running text, which say
    things like "Table 3.2.3 provides the generic concentration limits", from
    being taken for the table itself.
    """
    return re.compile(rf"^\[?F?\d*TABLE\s*{re.escape(number)}\]?$", re.I)


def _gb_lines_of(page) -> list[tuple[float, float, str]]:
    """(top, bottom, text) for each line of a page, in order."""
    lines: list[list[dict]] = []
    for word in sorted(page.extract_words(), key=lambda w: (round(w["top"], 1),
                                                            w["x0"])):
        if lines and abs(word["top"] - lines[-1][0]["top"]) <= 2.5:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [(line[0]["top"], max(w["bottom"] for w in line),
             " ".join(w["text"] for w in line)) for line in lines]


def _gb_bounds(page, number: str) -> tuple[float, float] | None:
    """The strip of the page one table occupies: its caption to the next one."""
    caption = _caption(number)
    any_caption = re.compile(r"^\[?F?\d*TABLE\s*\d+\.\d+\.\d+\]?$", re.I)
    top: float | None = None
    for line_top, line_bottom, text in _gb_lines_of(page):
        if top is None:
            if caption.match(text.strip()):
                top = line_bottom
            continue
        if any_caption.match(text.strip()) or _GB_AFTER_TABLE.match(text.strip()):
            return top, line_top - 2
    return (top, page.height) if top is not None else None


#: The running header legislation.gov.uk stamps on every page. It is not part
#: of any table, and a table that runs over a page break would otherwise take
#: it into the label of whatever row the break fell on.
_GB_FURNITURE = re.compile(
    r"Regulation \(EC\) No 1272/2008 of the European|ANNEX I|"
    r"Document Generated|Changes to legislation|See end of Document")


def _gb_text_rows(page, top: float, bottom: float) -> list[list[str]]:
    """The lines of a table whose rows are expressions, not cells.

    The aquatic tables put a formula in one column and the classification it
    gives in the other, and the formula is long enough to wrap. Columns are no
    help here - the row is the sentence - so the lines are taken whole, and a
    line that states no percentage is the start of one that does.
    """
    rows: list[list[str]] = []
    carried = ""
    for line_top, _, text in _gb_lines_of(page):
        if not (top <= line_top <= bottom):
            continue
        if _GB_FURNITURE.search(text):
            continue
        joined = f"{carried} {text}".strip()
        if _amount(joined) is None:
            carried = joined
            continue
        rows.append([joined])
        carried = ""
    return rows


def _gb_rows(pdf, index: int, number: str, *, as_text: bool = False
             ) -> list[list[str]]:
    """One table, which may run over the foot of its page.

    The caption is on the page that starts the table; where the rows continue
    overleaf, the continuation is everything above that page's first caption,
    less the running header.
    """
    page = pdf.pages[index]
    bounds = _gb_bounds(page, number)
    if bounds is None:
        return []
    if as_text:
        return _gb_text_rows(page, *bounds)
    rows = _gb_lines(page, *bounds)
    if bounds[1] < page.height - 2 or index + 1 >= len(pdf.pages):
        return _merge_wrapped(rows)
    following = pdf.pages[index + 1]
    stop = following.height
    for line_top, _, text in _gb_lines_of(following):
        if (re.match(r"^\[?F?\d*TABLE\s*\d+\.\d+\.\d+\]?$", text.strip(),
                     re.I)
                or _GB_AFTER_TABLE.match(text.strip())):
            stop = line_top - 2
            break
    return _merge_wrapped(rows + _gb_lines(following, 0, stop))


def _rejoin(cells: list[str]) -> list[str]:
    """Put back a cell the column guess cut in half.

    Columns are taken from where cells begin, and one row can begin its cells
    further right than another - the category 2 column of Table 3.8.3 does -
    which leaves a boundary running through the middle of a band on the row
    above. A piece that does not open a cell belongs to the one before it.
    """
    out = list(cells)
    for index in range(1, len(out)):
        if not out[index] or _CELL_START.match(out[index].split()[0]):
            continue
        for previous in range(index - 1, -1, -1):
            if out[previous]:
                out[previous] = f"{out[previous]} {out[index]}".strip()
                out[index] = ""
                break
        else:
            out[index - 1] = out[index]
            out[index] = ""
    return out


def _gb(path: Path, regulation: str, document: str) -> Table:
    import pdfplumber

    table = Table(regulation=regulation, document=document)
    found: set[str] = set()
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for number, (rule, hazard) in _CLP_TABLES.items():
                if number in found:
                    continue
                if not any(_caption(number).match(line.strip())
                           for line in text.splitlines()):
                    continue
                rows = _gb_rows(pdf, page.page_number - 1, number,
                                as_text=rule.startswith("aquatic"))
                if not rows:
                    continue
                place = Place(document, f"Annex I, Table {number}",
                              page.page_number)
                # Into a table of its own first: a page that turned out not to
                # carry the table must leave nothing behind.
                scratch = Table(regulation=regulation, document=document)
                try:
                    _read(rows, rule, hazard, place, scratch)
                except NotInTheText:
                    continue
                if not scratch.rules:
                    continue
                for scratch_rule, keys in scratch.rules.items():
                    for key, values in keys.items():
                        for value in values:
                            table.put(scratch_rule, key, value)
                found.add(number)
            if len(found) == len(_CLP_TABLES):
                break
        text_by_page = {i: " ".join((p.extract_text() or "").split())
                        for i, p in enumerate(pdf.pages)}
    missing = sorted(set(_CLP_TABLES) - found)
    if missing:
        raise NotInTheText(
            f"{document}: no table found for {', '.join(missing)}")
    _stot_se_3(text_by_page, document, table, paragraph_prefix="Annex I, ")
    _implications(text_by_page, document, table, paragraph_prefix="Annex I, ")
    _parent_categories(table)
    table.covers = _covered(table)
    return table


# -- building -----------------------------------------------------------------

def rules_dir() -> Path:
    return data_dir() / "mixture_rules"


def build(regulation: str, *, use_cache: bool = True) -> Table:
    """One regulation's rule table, read from the documents on file."""
    if regulation == "eu_clp":
        from lingua_oracle.keys.builders.eu_clp import CELEX, _doc

        return _eu(_doc("eng", use_cache=use_cache), "eu_clp",
                   f"Regulation (EC) No 1272/2008, consolidated {CELEX}")
    if regulation == "uk_clp":
        return _gb(sources.require("uk-gb-clp/gb_clp_full.pdf"), "uk_clp",
                   "Regulation (EC) No 1272/2008 as retained in GB law")
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
