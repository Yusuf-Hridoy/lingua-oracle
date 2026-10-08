"""Acute toxicity of mixtures: each regulation's own bands, conversions and rules.

`data/acute_toxicity/<regulation>.json`, read out of the regulation's text:

* the category bands for each route (CLP Table 3.1.1 and its equivalents),
* the converted point estimate for each category (Table 3.1.2),
* the concentration from which an ingredient is relevant (3.1.3.3(a)),
* the share of ingredients of unknown acute toxicity above which the
  additivity formula is corrected for them (3.1.3.6.2.3),
* whether ingredients beyond Category 4 still enter the sum,

each with the document, paragraph and page it came from. Nothing is typed in:
a table this builder cannot read is an error, not a default.

The formula itself - 100 / ATEmix = sum(Ci / ATEi), and its correction for
the unknown share - is printed as an image in some sources and as scrambled
typeset maths in others. What each source does give in text is the variables
it is written in and the paragraph it is in; both are recorded as the
evidence, and `mixture/acute.py` computes the additivity those define.

Thousands are written with a space ("2 000", "1 100"), which makes "300 300"
and "5 100" ambiguous in plain text. The tables' own structure settles it: a
band's upper bound is the next band's lower bound, so the text between them
is the same number written twice; and converted point estimates rise with the
category, which picks the one reading of a run of numbers that can be right.
"""

from __future__ import annotations

import itertools
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path

from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.common import SourceUnavailable, strip_markers
from lingua_oracle.registry import data_dir

ROUTES = ("oral", "dermal", "gases", "vapours", "dusts_mists")
#: How each route's row is labelled in every source on file.
_ROUTE_LABEL = {
    "oral": r"Oral\s*\(?\s*mg\s*/\s*kg",
    "dermal": r"Dermal\s*\(?\s*mg\s*/\s*kg",
    "gases": r"Gases\s*\(?\s*ppm|Inhalation\s*\(gases\)",
    "vapours": r"Vapou?rs\s*\(?\s*mg\s*/\s*l|Inhalation\s*\(vapou?rs\)",
    "dusts_mists": (r"Dusts?\s*(?:and|/)\s*mists?\s*\(?\s*mg\s*/\s*l"
                    r"|Inhalation\s*\(dusts?\s*(?:and|/)\s*mists?\)"),
}
_ROUTE_ANY = re.compile("|".join(f"(?:{v})" for v in _ROUTE_LABEL.values()), re.I)


class NotInTheText(RuntimeError):
    """A table or rule this builder expected is not in the document."""


@dataclass
class Cited:
    value: object
    document: str
    section: str
    page: int | None = None
    raw: str = ""

    @property
    def citation(self) -> str:
        where = f", page {self.page}" if self.page else ""
        return f"{self.document}, {self.section}{where}"


@dataclass
class AcuteTable:
    regulation: str
    document: str
    #: route -> [{"category": "1", "low": "0", "high": "5"}, ...] (low exclusive)
    bands: dict[str, list[dict]] = field(default_factory=dict)
    bands_from: Cited | None = None
    #: route -> {"1": "0.5", ...}
    conversion: dict[str, dict[str, str]] = field(default_factory=dict)
    conversion_from: Cited | None = None
    relevance: Cited | None = None
    unknown_threshold: Cited | None = None
    formula: Cited | None = None
    #: The highest ATE an ingredient may have and still enter the sum, by route.
    ingredient_limit: dict[str, str] = field(default_factory=dict)
    ingredient_limit_from: Cited | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), default=str))


# -- numbers as the sources print them --------------------------------------------

_ATOM = re.compile(r"\d+(?:[.,]\d+)?")


def _value(atoms: list[str]) -> Decimal:
    """Atoms of one number, thousands separated by spaces: ["2", "000"] -> 2000."""
    head, *rest = atoms
    return Decimal(head.replace(",", ".") + "".join(rest))


def _mergeable(atoms: list[str]) -> bool:
    return all(re.fullmatch(r"\d{3}", a) for a in atoms[1:]) and \
        re.fullmatch(r"\d{1,3}", atoms[0]) is not None if len(atoms) > 1 else True


def _take(atoms: list[str], want: Decimal) -> list[str] | None:
    """The atoms after the number `want` at their start, or None."""
    for size in range(1, min(3, len(atoms)) + 1):
        head = atoms[:size]
        if _mergeable(head) and _value(head) == want:
            return atoms[size:]
    return None


def _twice(chunk: str) -> Decimal:
    """The number a band boundary repeats: "300 300" -> 300, "1 000 1 000" -> 1000."""
    atoms = _ATOM.findall(chunk)
    half = len(atoms) // 2
    if len(atoms) % 2 or atoms[:half] != atoms[half:] or not _mergeable(atoms[:half]):
        raise NotInTheText(f"not a repeated boundary: {chunk!r}")
    return _value(atoms[:half])


def _leading(chunk: str) -> Decimal:
    """The number a chunk starts with, thousands spaces included."""
    match = re.match(r"\s*(\d{1,3}(?:\s\d{3})+(?![\d.,])|\d+(?:[.,]\d+)?)", chunk)
    if match is None:
        raise NotInTheText(f"no number at {chunk[:40]!r}")
    return _value(match.group(1).split())


def _rising(atoms: list[str], count: int) -> list[Decimal]:
    """The one reading of `atoms` as `count` numbers that rises, or an error."""
    readings = []
    for cuts in itertools.combinations(range(1, len(atoms)), count - 1):
        parts = [atoms[a:b] for a, b in zip((0, *cuts), (*cuts, len(atoms)), strict=True)]
        if not all(_mergeable(p) for p in parts):
            continue
        values = [_value(p) for p in parts]
        if all(x < y for x, y in itertools.pairwise(values)):
            readings.append(values)
    if len(readings) != 1:
        raise NotInTheText(f"{len(readings)} readings of {' '.join(atoms)} as {count} values")
    return readings[0]


# -- the tables ---------------------------------------------------------------------

def _route_segments(text: str) -> dict[str, str]:
    """Each route's row: from its label to the next route's label."""
    out: dict[str, str] = {}
    marks = sorted((m.start(), route) for route, pattern in _ROUTE_LABEL.items()
                   for m in [re.search(pattern, text, re.I)] if m)
    if not marks:
        return out
    ends = [start for start, _ in marks[1:]] + [len(text)]
    for (start, route), end in zip(marks, ends, strict=True):
        out[route] = text[start:end]
    return out


def bands_in(text: str) -> dict[str, list[dict]]:
    """Table 3.1.1's bands: "ATE <= 5   5 < ATE <= 50   ...   300 < ATE <= 2 000"."""
    out: dict[str, list[dict]] = {}
    for route, segment in _route_segments(text).items():
        marks = list(re.finditer(r"(<\s*)?ATE\s*≤", segment))
        if not marks:
            continue
        uppers: list[Decimal] = []
        for here, nxt in itertools.pairwise(marks):
            uppers.append(_twice(segment[here.end():nxt.start()]))
        uppers.append(_leading(segment[marks[-1].end():]))
        lows = [Decimal(0), *uppers[:-1]]
        out[route] = [{"category": str(n), "low": str(lo), "high": str(hi)}
                      for n, (lo, hi) in enumerate(zip(lows, uppers, strict=True), 1)]
    return out


def conversion_in(text: str, bands: dict[str, list[dict]]) -> dict[str, dict[str, str]]:
    """Table 3.1.2's point estimates, interleaved or printed after the ranges."""
    out: dict[str, dict[str, str]] = {}
    for route, segment in _route_segments(text).items():
        marks = list(re.finditer(r"<\s*Category\s*(\d)\s*≤", segment))
        if not marks or route not in bands:
            continue
        uppers = {b["category"]: Decimal(b["high"]) for b in bands[route]}
        points: list[Decimal] = []
        for here, nxt in itertools.pairwise(marks):
            category = here.group(1)
            atoms = _ATOM.findall(segment[here.end():nxt.start()])
            rest = _take(atoms, uppers[category])
            if rest is None:
                raise NotInTheText(f"{route}: category {category} bound not found")
            # What is left is "[point] next-lower"; the next lower is this upper.
            back = rest
            for size in range(1, min(3, len(back)) + 1):
                if _mergeable(back[-size:]) and _value(back[-size:]) == uppers[category]:
                    back = back[:-size]
                    break
            else:
                raise NotInTheText(f"{route}: next band's lower bound not found")
            if back:
                points.append(_value(back))
        last = marks[-1]
        atoms = _ATOM.findall(re.split(r"[A-Za-z]", segment[last.end():], maxsplit=1)[0])
        rest = _take(atoms, uppers[last.group(1)])
        if rest is None:
            raise NotInTheText(f"{route}: last bound not found")
        count = len(marks)
        if points:            # interleaved: one point left, after the last range
            points.append(_value(rest[:1]) if len(rest) == 1 else
                          _rising(rest, 1)[0])
        else:                 # all points after the ranges
            points = _rising(rest, count)
        if len(points) != count:
            raise NotInTheText(f"{route}: {len(points)} points for {count} categories")
        out[route] = {str(n): str(p) for n, p in enumerate(points, 1)}
    return out


def _rising_prefix(atoms: list[str], count: int) -> list[Decimal]:
    """`_rising` on the longest prefix that reads: a row's item number for the
    next route ("... 500 2 Dermal") can trail the points."""
    for end in range(len(atoms), count - 1, -1):
        try:
            return _rising(atoms[:end], count)
        except NotInTheText:
            continue
    raise NotInTheText(f"no reading of {' '.join(atoms)} as {count} rising values")


# -- the Canadian tables, which say "> a and <= b" ----------------------------------

_NUM = r"(\d{1,3}(?:\s\d{3})+(?![\d.,])|\d+(?:[.,]\d+)?)"
_HPR_BAND = re.compile(rf"(?:>\s*{_NUM}\s*and\s*)?≤\s*{_NUM}")


def _hpr_bands(english: str) -> dict[str, list[dict]]:
    """Tables 1-3 to section 8.1.1: oral, dermal, then inhalation in three columns."""
    def number(raw: str) -> Decimal:
        return _value(raw.split())

    out: dict[str, list[dict]] = {}
    for title, routes in (("TABLE 1", ("oral",)), ("TABLE 2", ("dermal",)),
                          ("TABLE 3", ("gases", "vapours", "dusts_mists"))):
        start = english.find(title)
        if start < 0:
            raise NotInTheText(f"HPR 8.1.1: {title} not found")
        end = english.find("TABLEAU", start)
        rows = re.split(r"Category\s*(\d)", english[start:end])
        for i in range(1, len(rows), 2):
            category, cells = rows[i], rows[i + 1]
            pairs = _HPR_BAND.findall(cells)[:len(routes)]
            if len(pairs) != len(routes):
                raise NotInTheText(f"HPR {title}: category {category} has {len(pairs)} bands")
            for route, (low, high) in zip(routes, pairs, strict=True):
                out.setdefault(route, []).append(
                    {"category": category, "low": str(number(low)) if low else "0",
                     "high": str(number(high))})
    return out


# -- the documents ------------------------------------------------------------------

#: Symbol-font glyphs some PDFs draw the relations with, as the characters
#: they are: U+F0A3 is "less than or equal to", U+F0B3 "greater than or equal to".
_SYMBOL = str.maketrans({"\uf0a3": "≤", "\uf0b3": "≥"})


def _pdf_pages(path: Path) -> list[tuple[int, str]]:
    import pymupdf

    with pymupdf.open(path) as pdf:
        return [(n + 1, " ".join(page.get_text().translate(_SYMBOL).split()))
                for n, page in enumerate(pdf)]


def _find(pages: list[tuple[int, str]], pattern: str, *, after: int = 0
          ) -> tuple[int | None, str, re.Match] | None:
    """The first page at or after `after` where `pattern` matches, with the match."""
    for number, text in pages:
        if number is not None and number < after:
            continue
        found = re.search(pattern, text, re.I | re.S)
        if found:
            return number, text, found
    return None


def _window(pages, start_pattern: str, end_pattern: str, *, after: int = 0,
            reach: int = 3) -> tuple[int | None, str]:
    """Text from where `start_pattern` matches to `end_pattern`, across pages."""
    found = _find(pages, start_pattern, after=after)
    if found is None:
        raise NotInTheText(f"not found: {start_pattern}")
    number, _, match = found
    joined = " ".join(t for n, t in pages
                      if n is None or (number <= n <= number + reach))
    text = joined[joined.find(match.group(0)):]
    end = re.search(end_pattern, text[len(match.group(0)):], re.I | re.S)
    return number, text[:len(match.group(0)) + end.start()] if end else text


def _sentence(pages, pattern: str, document: str, section: str) -> Cited:
    found = _find(pages, pattern)
    if found is None:
        raise NotInTheText(f"{document}: {section} not found")
    number, _, match = found
    value = next((g for g in match.groups() if g), None) if match.groups() else None
    return Cited(value=value.replace(",", ".") if value else None,
                 document=document, section=section, page=number,
                 raw=match.group(0)[:300])


_RELEVANT = (r"relevant ingredients.{0,40}?present in concentrations (?:of |≥\s*)?"
             r"(\d+(?:[.,]\d+)?)\s*%")
_UNKNOWN = (r"unknown acute toxicity is\s*(?:≤|<=|)?\s*(\d+(?:[.,]\d+)?)\s*%")
_FORMULA = r"(ATE of the mixture is determined by calculation.{0,260}?ATE\s*i\b[^.;]{0,80})"


def _ghs_like(pages, regulation: str, document: str, *, prefix: str = "",
              table_prefix: str = "") -> AcuteTable:
    """CLP Annex I, GB CLP, the GHS and OSHA Appendix A: the same chapter."""
    table = AcuteTable(regulation=regulation, document=document)
    bands_page, bands_text = _window(
        pages, rf"Table\s*{table_prefix}1\.1\s*[:.-]?\s*A(?:cute toxicity estimate|CUTE TOXICITY ESTIMATE)",
        r"Notes? to Table|\(a\)\s*The acute toxicity estimate|Note:\s*Gas concentrations")
    table.bands = bands_in(bands_text)
    table.bands_from = Cited(None, document, f"{prefix}Table {table_prefix}1.1", bands_page)
    conv_page, conv_text = _window(
        pages, r"Conversion from experimentally obtained acute toxicity range values.{0,200}?Exposure routes",
        r"NOTE\s*1\s*:|Note\s*1\s*:|Note 1 These|Note: Gases|3\.1\.4\.|A\.1\.4\b",
        after=bands_page or 0)
    _fill_from_ranges(table, conv_text, f"{prefix}Table {table_prefix}1.2")
    table.conversion = conversion_in(conv_text, table.bands)
    table.conversion_from = Cited(None, document, f"{prefix}Table {table_prefix}1.2", conv_page)
    table.relevance = _sentence(pages, _RELEVANT, document, f"{prefix}{table_prefix}1.3.3(a)")
    table.unknown_threshold = _sentence(
        pages, _UNKNOWN, document,
        f"{prefix}{table_prefix}1.3.6.2.{'4' if table_prefix == 'A.' else '3'}")
    table.formula = _sentence(pages, _FORMULA, document, f"{prefix}{table_prefix}1.3.6.1")
    return table


def _fill_from_ranges(table: AcuteTable, text: str, section: str) -> None:
    """A category Table 3.1.1 prints as one cell spanning two routes - the
    GHS's Category 5 for oral and dermal - is read from Table 3.1.2, which
    prints each route's range on its own row."""
    for route, segment in _route_segments(text).items():
        if route not in table.bands:
            continue
        held = {b["category"] for b in table.bands[route]}
        for mark in re.finditer(r"<\s*Category\s*(\d)\s*≤", segment):
            category = mark.group(1)
            if category in held:
                continue
            high = _leading(segment[mark.end():])
            low = table.bands[route][-1]["high"]
            table.bands[route].append({"category": category, "low": low,
                                       "high": str(high)})
            table.notes.append(f"{route} Category {category} band read from {section}, "
                               "where Table 3.1.1 prints one cell for two routes")


def _limits(table: AcuteTable, categories: tuple[str, ...], pages, pattern: str,
            section: str) -> None:
    """The highest ATE an ingredient may have and still enter the sum."""
    found = _find(pages, pattern)
    table.ingredient_limit_from = Cited(
        None, table.document, section, found[0] if found else None,
        raw=found[2].group(0)[:300] if found else "")
    for route, bands in table.bands.items():
        counted = [b for b in bands if b["category"] in categories]
        table.ingredient_limit[route] = counted[-1]["high"]


def _keep(table: AcuteTable, categories: tuple[str, ...]) -> None:
    for route in list(table.bands):
        table.bands[route] = [b for b in table.bands[route] if b["category"] in categories]
        table.conversion[route] = {c: v for c, v in table.conversion.get(route, {}).items()
                                   if c in categories}


def build(regulation: str, *, use_cache: bool = True) -> AcuteTable:
    if regulation == "eu_clp":
        from lingua_oracle.keys.builders.eu_clp import CELEX, _doc

        doc = _doc("eng", use_cache=use_cache)
        text = strip_markers(" ".join(" ".join(doc.itertext()).split()))
        document = f"Regulation (EC) No 1272/2008, consolidated {CELEX}"
        table = _ghs_like([(None, text)], regulation, document, prefix="Annex I, ",
                          table_prefix="3.")
        _limits(table, ("1", "2", "3", "4"), [(None, text)],
                r"include ingredients with a known acute toxicity, which fall into any of the acute hazard categories shown in Table 3\.1\.1",
                "Annex I, 3.1.3.6.1(a)")
        return table
    if regulation == "uk_clp":
        pages = [(n, re.sub(r"\[F\d+|\[|\]", "", t))
                 for n, t in _pdf_pages(sources.require("uk-gb-clp/gb_clp_full.pdf"))]
        table = _ghs_like(pages, regulation,
                          "Regulation (EC) No 1272/2008 as retained in GB law",
                          prefix="Annex I, ", table_prefix="3.")
        _limits(table, ("1", "2", "3", "4"), pages,
                r"include ingredients with a known acute toxicity, which fall into any of the acute hazard categories shown in Table 3\.1\.1",
                "Annex I, 3.1.3.6.1(a)")
        return table
    if regulation in ("un_ghs", "au_whs"):
        path = ("un-ghs/GHS_Rev11_en.pdf" if regulation == "un_ghs"
                else "ghs-rev7/GHS_Rev7_en.pdf")
        document = ("UN GHS Rev.11 (2025)" if regulation == "un_ghs"
                    else "UN GHS Rev.7 (2017), as adopted by the WHS Regulations")
        pages = _pdf_pages(sources.require(path))
        table = _ghs_like(pages, regulation, document, table_prefix="3.")
        if regulation == "au_whs":
            # The WHS Regulations exclude Category 5 from what a hazardous
            # chemical is; the guidance on file says so in terms.
            guidance = _pdf_pages(sources.require(
                "australia/swa_classification_guidance.pdf"))
            excluded = _sentence(
                guidance, r"(acute toxicity\s*[–-]\s*oral, dermal and inhalation\s*[–-]\s*category 5)",
                "Safe Work Australia, Guidance on the classification of hazardous "
                "chemicals under the WHS Regulations", "Appendix A, hazardous chemical")
            _keep(table, ("1", "2", "3", "4"))
            table.notes.append(f"Category 5 excluded: “{excluded.raw}” "
                               f"({excluded.citation})")
            _limits(table, ("1", "2", "3", "4"), pages,
                    r"include ingredients with a known acute toxicity, which fall into any of the GHS acute toxicity categories",
                    "3.1.3.6.1(a), Category 5 excluded")
        else:
            _limits(table, ("1", "2", "3", "4", "5"), pages,
                    r"include ingredients with a known acute toxicity, which fall into any of the GHS acute toxicity categories",
                    "3.1.3.6.1(a)")
        return table
    if regulation == "us_osha":
        import html as _html

        from lingua_oracle.keys.builders.mixture_rules import _osha_body

        body = _osha_body(use_cache=use_cache).decode("utf-8", "replace")
        text = " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", body)).split())
        # The appendix names Table A.1.1 before printing it; read the table.
        start = text.find("Table A.1.1 - ACUTE TOXICITY ESTIMATE")
        pages = [(None, text[start:] if start >= 0 else text)]
        table = _ghs_like(pages, regulation, "29 CFR 1910.1200 Appendix A",
                          table_prefix="A.")
        _limits(table, ("1", "2", "3", "4"), [(None, text)],
                r"(or have an oral or dermal LD50 greater than 2000 but less than or equal to 5000 mg/kg body weight)",
                "A.1.3.6.1(a)")
        _beyond_four(table)
        return table
    if regulation == "ca_whmis":
        pages = _pdf_pages(sources.require("ca-whmis/hpr_bilingual.pdf"))
        document = "Hazardous Products Regulations (SOR/2015-17)"
        joined = re.sub(r"-\s+", "", " ".join(t for _, t in pages))
        start = joined.find("TABLE 1 Oral Exposure Route")
        table = AcuteTable(regulation=regulation, document=document)
        table.bands = _hpr_bands(joined[start:start + 6000])
        table.bands_from = Cited(None, document, "section 8.1.1(3), Tables 1-3",
                                 _find(pages, r"TABLE 1 Oral Exposure Route")[0])
        # The English table is split by the French one and runs on overleaf;
        # the routes are read by their English labels, so the French rows
        # in between are passed over.
        # The heading appears in the table of contents too; the table follows
        # the occurrence in the body.
        conv = next(m.start() for m in re.finditer("Conversion from range to point estimate", joined)
                    if "Exposure Routes" in joined[m.start():m.start() + 3000])
        conv_end = conv + 8000   # the running headers name the next subpart
        table.conversion = _conversion_after_ranges(joined[conv:conv_end], table.bands)
        table.conversion_from = Cited(None, document, "section 8.1.7(2), table",
                                      _find(pages, r"TABLE Column 1 Column 2 Column 3 Item Exposure Routes")[0])
        # Line-end hyphens removed page by page, so a sentence is found on
        # its own page and cited with it.
        hpr = [(n, re.sub(r"-\s+", "", t)) for n, t in pages]
        table.relevance = _sentence(
            hpr, r"Only ingredients present at concentrations equal to or greater than the concentration limit of (\d+(?:\.\d+)?)%",
            document, "section 8.1.2(2)")
        table.unknown_threshold = _sentence(
            hpr, r"total concentration of all ingredients with unknown acute toxicity is less than or equal to (\d+(?:\.\d+)?)%",
            document, "section 8.1.6(b)(i)")
        table.formula = _sentence(
            hpr, r"(using the ATE of the mixture that is determined in respect of each applicable route of exposure by the following formula.{0,200}?ATEi is the ATE of ingredient i)",
            document, "section 8.1.5")
        _limits(table, ("1", "2", "3", "4"), hpr,
                r"(\(b\) an oral or dermal LD50 greater than 2000 mg/kg body weight but less than or equal to 5000 mg/kg body weight)",
                "section 8.1.5(b)")
        _beyond_four(table)
        return table
    raise SourceUnavailable(f"no acute toxicity rules for {regulation}: no document on file")


def _beyond_four(table: AcuteTable) -> None:
    """Oral and dermal ingredients up to 5000 mg/kg enter the sum (the text read
    by `_limits` says so); inhalation is "comparable", which gives no number."""
    raw = table.ingredient_limit_from.raw if table.ingredient_limit_from else ""
    found = re.search(r"less than or equal to (\d+) mg/kg", raw)
    if not found:
        raise NotInTheText(f"{table.document}: the 2000-5000 mg/kg sentence")
    for route in ("oral", "dermal"):
        table.ingredient_limit[route] = found.group(1)
    table.notes.append("Ingredients with an inhalation LC50 beyond Category 4 are "
                       "said to count within a “comparable” range, which the "
                       "text does not quantify: they are left out of the sum.")


def _conversion_after_ranges(text: str, bands: dict[str, list[dict]]) -> dict[str, dict[str, str]]:
    found = conversion_in_lenient(text, bands)
    if set(found) != set(bands):
        raise NotInTheText(f"conversion table: routes {sorted(found)}")
    return found


def conversion_in_lenient(text, bands):
    """`conversion_in`, allowing a row's item number to trail its points."""
    out: dict[str, dict[str, str]] = {}
    for route, segment in _route_segments(text).items():
        marks = list(re.finditer(r"<\s*Category\s*(\d)\s*≤", segment))
        if not marks or route not in bands:
            continue
        uppers = {b["category"]: Decimal(b["high"]) for b in bands[route]}
        last = marks[-1]
        atoms = _ATOM.findall(re.split(r"[A-Za-z]", segment[last.end():], maxsplit=1)[0])
        rest = _take(atoms, uppers[last.group(1)])
        if rest is None:
            raise NotInTheText(f"{route}: last bound not found")
        points = _rising_prefix(rest, len(marks))
        out[route] = {str(n): str(p) for n, p in enumerate(points, 1)}
    return out


# -- writing ------------------------------------------------------------------------

def tables_dir() -> Path:
    return data_dir() / "acute_toxicity"


def write(regulation: str, *, use_cache: bool = True) -> Path:
    table = build(regulation, use_cache=use_cache)
    tables_dir().mkdir(parents=True, exist_ok=True)
    path = tables_dir() / f"{regulation}.json"
    path.write_text(json.dumps(table.as_dict(), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path
