"""The structure each regulation requires of a safety data sheet.

Not an answer key: data/sds_structure/<reg>.json, read out of each
regulation's own text on safety data sheets, with every rule quoted and
located. The check (B-12 to B-14) applies only what is here.

* EU - REACH Annex II, consolidated on CELLAR, Part B headings and
  sub-headings in each language from that language's own act (Irish has no
  consolidated text: its wording is pending, the numbers still apply).
* GB - GB REACH Annex II, Part B, from the legislation.gov.uk PDF.
* US - 29 CFR 1910.1200(g)(2) for the headings, their numbers and order
  (eCFR), Appendix D, Table D.1 for each section's content.
* Canada - HPR section 4 and Schedule 1, English and French, read by column.
* UN GHS - Rev.11 Annex 4, A4.2.3.1 and A4.3.
* Australia - Model WHS Regulations, Schedule 7, clause 1.

A rule binds where its own verb does ("shall", "must"); where the text says
"should" (the GHS), it is a rule to check, not a fault. A rule the text does
not state is not written here - in particular, no order rule for a
regulation whose text gives none.

The items checked are those whose presence is objective - a telephone
number, an e-mail address, a date, page numbering, a blank sub-section -
each quoted from the paragraph that requires it. The quality of free text
is not a requirement this tool can judge, and is not written here.
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

#: 29 CFR 1910.1200 on eCFR, at the version read. Pinned like the EU
#: consolidations, so a rebuild is deterministic.
ECFR_DATE = "2026-02-13"
ECFR_URL = (f"https://www.ecfr.gov/api/versioner/v1/full/{ECFR_DATE}/title-29.xml"
            "?part=1910&section=1910.1200")


@dataclass
class Rule:
    """One requirement, as the text states it."""

    binding: bool          # "shall"/"must" - or "should"
    quote: str
    citation: str


@dataclass
class Item:
    """Something a section (or the whole sheet) must carry, objectively."""

    id: str
    kind: str              # telephone / emergency_telephone / email / date / page_numbering
    scope: str             # "document", "first_page", a section "1" or sub-section "1.3"
    rule: Rule


@dataclass
class Subsection:
    number: str
    heading: dict[str, str] = field(default_factory=dict)


@dataclass
class Section:
    number: str
    #: The heading per language, as the text prints it, number and label off.
    heading: dict[str, str] = field(default_factory=dict)
    #: The label the text puts around the number, per language: "SECTION {n}:".
    label: dict[str, str] = field(default_factory=dict)
    required: bool = True
    #: Where a section's heading is required but its content may be omitted.
    content_optional: bool = False
    subsections: list[Subsection] = field(default_factory=list)


@dataclass
class Structure:
    regulation: str
    document: str
    status: str = "ok"                     # ok / pending_source
    why: str = ""
    headings: Rule | None = None           # headings (and their wording) required
    subheadings: Rule | None = None        # sub-headings required, where the text has them
    order: Rule | None = None              # only where the text states an order
    empty: Rule | None = None              # what the text says of an empty part
    empty_scope: str = ""                  # "subsection" or "section"
    optional: Rule | None = None           # sections the text makes optional
    one_of: list[list[str]] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    #: Languages whose wording is on file, and those that are not.
    languages: list[str] = field(default_factory=list)
    pending_languages: dict[str, str] = field(default_factory=dict)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _verb(quote: str) -> bool:
    """Whether a sentence binds: its own verb, read from the sentence."""
    lowered = quote.lower()
    if re.search(r"\b(shall|must)\b", lowered):
        return True
    if re.search(r"\bshould\b", lowered):
        return False
    raise SourceUnavailable(f"no binding verb in {quote[:80]!r}")


def _rule(quote: str, citation: str) -> Rule:
    return Rule(_verb(quote), quote, citation)


def _sentence(text: str, pattern: str, what: str) -> str:
    found = re.search(pattern, text)
    if found is None:
        raise SourceUnavailable(f"{what} not found; the text's layout has changed")
    return _flat(found.group(0))


def _pdf_pages(path: Path) -> list[tuple[int, str]]:
    import pymupdf

    with pymupdf.open(path) as doc:
        return [(n + 1, _flat(page.get_text())) for n, page in enumerate(doc)]


def _page_of(pages: list[tuple[int, str]], needle: str) -> int | None:
    return next((n for n, t in pages if needle in t), None)


# -- EU ------------------------------------------------------------------------------

def _eu_part_b(raw: bytes) -> tuple[list[tuple[str, list[tuple[str, str]]]], str]:
    """Part B's sixteen titles and their sub-headings, as one language prints
    them. Found by shape, not by word: sixteen consecutive section titles
    numbered 1 to 16, each followed by its numbered sub-headings, after the
    paragraph that introduces them."""
    from lxml import html as LH

    def text(e) -> str:
        return strip_markers(_flat(e.text_content()))

    titles = LH.fromstring(raw).xpath('//p[contains(@class,"title-gr-seq-level-2")]')
    for start in range(len(titles) - 15):
        run = titles[start:start + 16]
        numbers = [re.search(r"\b(\d{1,2})\b", text(t)) for t in run]
        if not all(n and int(n.group(1)) == k + 1 for k, n in enumerate(numbers)):
            continue
        out = []
        for title in run:
            subs = []
            for sibling in title.itersiblings():
                if sibling.tag == "p" and "title-gr-seq" in (sibling.get("class") or ""):
                    break
                found = re.match(r"^(\d{1,2}\.\d{1,2})\.?\s*(.+)$", text(sibling))
                if found:
                    subs.append((found.group(1), found.group(2).strip()))
            out.append((text(title), subs))
        if sum(len(s) for _, s in out) >= 40:          # Part B, not Part A
            intro = run[0].getprevious()
            return out, text(intro) if intro is not None else ""
    raise SourceUnavailable("REACH Annex II Part B not found")


def _split_title(title: str, number: str) -> tuple[str, str]:
    """('SECTION 1: Identification of ...', '1') -> ('SECTION {n}:', 'Identification of ...')."""
    found = re.search(rf"(?<!\d){number}(?!\d)", title)
    if found is None:
        raise SourceUnavailable(f"section number {number} not in {title!r}")
    before, after = title[:found.start()], title[found.end():]
    lead = re.match(r"^\s*[.:)—–-]*\s*", after).group(0)
    words = after[len(lead):]
    # "1. JAGU. Aine ..." / "1 SKIRSNIS. Medžiagos ..." / "1. SZAKASZ: Az ...":
    # a label word after the number belongs to the label.
    if not before.strip():
        label_word = re.match(r"^([^\W\d_]+[.:]?)\s+", words)
        if label_word and label_word.group(1).upper() == label_word.group(1):
            lead += label_word.group(0)
            words = words[len(label_word.group(0)):]
    label = f"{before}{{n}}{lead}".strip()
    return label, words.strip().rstrip(".")


def _eu(use_cache: bool) -> Structure:
    from lingua_oracle.keys.builders.eu_clp import LANGS
    from lingua_oracle.keys.builders.section16 import REACH_CELEX, REACH_URL

    document = f"Regulation (EC) No 1907/2006 (REACH), consolidated {REACH_CELEX}"
    structure = Structure("eu_clp", document)
    english_raw = None
    parsed: dict[str, list] = {}
    for language, iso3 in LANGS.items():
        try:
            raw = fetch(REACH_URL, headers={"Accept": "application/xhtml+xml",
                                            "Accept-Language": iso3}, use_cache=use_cache)
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            structure.pending_languages[language] = (
                f"no consolidated text in this language on CELLAR ({str(exc)[:60]})")
            continue
        parsed[language], intro = _eu_part_b(raw)
        if language == "en":
            english_raw, english_intro = raw, intro
    if english_raw is None:
        raise SourceUnavailable("REACH English text not available")
    structure.languages = sorted(parsed)
    structure.sections = []
    for index in range(16):
        number = str(index + 1)
        # The English act sets which sub-sections exist; every language's own
        # act gives their wording, matched by number.
        section = Section(number, subsections=[Subsection(n) for n, _ in parsed["en"][index][1]])
        for language, run in parsed.items():
            title, subs = run[index]
            label, heading = _split_title(title, number)
            section.label[language] = " ".join(label.split())
            section.heading[language] = heading
            for sub in section.subsections:
                match = next((h for n, h in subs if n == sub.number), None)
                if match is not None:
                    sub.heading[language] = match.rstrip(".")
        structure.sections.append(section)

    from lxml import html as LH

    text = strip_markers(_flat(" ".join(LH.fromstring(english_raw).itertext())))
    annex = [m.start() for m in re.finditer(
        "ANNEX II REQUIREMENTS FOR THE COMPILATION OF SAFETY DATA SHEETS", text)][-1]
    body = text[annex:]
    _reach_rules(structure, body, english_intro, "Annex II")
    return structure


def _reach_rules(structure: Structure, body: str, intro: str, annex: str) -> None:
    """The rules REACH Annex II states - EU and GB alike, each from its own text."""
    structure.headings = _rule(intro, f"{annex}, Part B")
    structure.subheadings = structure.headings
    structure.one_of = [["3.1", "3.2"]]
    structure.empty = _rule(_sentence(
        body, r"The safety data sheet shall not contain blank subsections\.", "0.4"),
        f"{annex}, Part A, 0.4")
    structure.empty_scope = "subsection"
    date = _sentence(body, r"The date of compilation of the safety data sheet shall be "
                           r"given on the first page\.", "0.2.5")
    pages = _sentence(body, r"All pages of a safety data sheet, including any annexes, "
                            r"shall be numbered and shall bear.*?\)\.", "0.3.2")
    supplier = _sentence(body, r"The full address and telephone number of the supplier "
                               r"shall be given as well as an e-?mail address for a "
                               r"competent person responsible for the safety data sheet\.",
                         "1.3")
    emergency = _sentence(body, r"References to emergency information services shall be "
                                r"provided\.", "1.4")
    structure.items = [
        Item("date_of_compilation", "date", "first_page",
             _rule(date, f"{annex}, Part A, 0.2.5")),
        Item("page_numbering", "page_numbering", "document",
             _rule(pages, f"{annex}, Part A, 0.3.2")),
        Item("supplier_telephone", "telephone", "1.3",
             _rule(supplier, f"{annex}, Part A, 1.3")),
        Item("supplier_email", "email", "1.3", _rule(supplier, f"{annex}, Part A, 1.3")),
        Item("emergency_telephone", "telephone", "1.4",
             _rule(emergency, f"{annex}, Part A, 1.4")),
    ]


# -- GB ------------------------------------------------------------------------------

def _gb() -> Structure:
    source = sources.BY_PATH["uk-gb-reach/gb_reach_annex_ii.pdf"]
    document = ("GB REACH (Regulation (EC) No 1907/2006 as retained), "
                "legislation.gov.uk, document generated 2026-10-08")
    structure = Structure("uk_clp", document)
    if not source.where.exists():
        structure.status, structure.why = "pending_source", sources.describe(source.path)
        return structure
    pages = _pdf_pages(source.where)
    # Running heads and footnote markers interrupt the text; take them out.
    body = " ".join(t for _, t in pages)
    # A page number sits before or after the running head; one followed by
    # "." is a sub-section number and stays.
    body = re.sub(r"(?:\b\d{1,3} )?Regulation \(EC\) No 1907/2006 of the European Parliament "
                  r"and of the Council of\.\.\.(?: ANNEX II PART A)? Document Generated: "
                  r"\d{4}-\d{2}-\d{2}(?: \d+(?![.\d]))? Changes to legislation:.*?\(See end "
                  r"of Document for details\)(?: \d{1,3}(?![.\d]))?", " ", body)
    body = re.sub(r"\[X\d+|\[F\d+|\]|F\d+\.\.\.", "", body)
    body = _flat(body)
    start = body.find("PART B The safety data sheet shall include")
    end = body.find("SECTION 16: Other information", start)
    if start < 0 or end < 0:
        raise SourceUnavailable("GB REACH Annex II Part B not found")
    part_b = body[start:end + len("SECTION 16: Other information")]
    intro = _sentence(part_b, r"The safety data sheet shall include the following 16 "
                              r"headings.*?as appropriate:", "GB Part B")
    titles = list(re.finditer(r"SECTION (\d{1,2}): ", part_b))
    for k, found in enumerate(titles):
        number = found.group(1)
        chunk = part_b[found.end():titles[k + 1].start() if k + 1 < len(titles) else None]
        heading = re.split(rf"\s{number}\.\d{{1,2}}\.\s", chunk)[0].strip().rstrip(":")
        subs = re.findall(rf"(?<![\d.])({number}\.\d{{1,2}})\.\s(.+?)(?=\s{number}\.\d{{1,2}}\.\s|$)",
                          chunk)
        structure.sections.append(Section(
            number, heading={"en": heading}, label={"en": "SECTION {n}:"},
            subsections=[Subsection(n, {"en": h.strip()}) for n, h in subs]))
    if [s.number for s in structure.sections] != [str(n) for n in range(1, 17)]:
        raise SourceUnavailable("GB REACH Part B does not list sections 1 to 16")
    structure.languages = ["en"]
    annex_start = body.find("ANNEX II")
    _reach_rules(structure, body[annex_start:], intro, "Annex II")
    page = _page_of(pages, "PART B The safety data sheet shall include")
    for rule in (structure.headings,):
        rule.citation += f", page {page}" if page else ""
    return structure


# -- US ------------------------------------------------------------------------------

def _osha(use_cache: bool) -> Structure:
    from lingua_oracle.keys.builders.section16 import APPENDIX_D_URL

    document = "29 CFR 1910.1200 Appendix D"
    local = sources.BY_PATH["us-osha/appendix_d.html"].where
    raw = local.read_bytes() if local.exists() else fetch(
        APPENDIX_D_URL, headers={"User-Agent": BROWSER_UA}, use_cache=use_cache)
    text = _flat(_html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace"))))
    structure = Structure("us_osha", "29 CFR 1910.1200(g)(2) and Appendix D",
                          languages=["en"])
    # The headings, their numbers and their order are required by the
    # standard itself, (g)(2); Appendix D gives each section's content.
    standard = _flat(re.sub(r"<[^>]+>", " ", fetch(ECFR_URL, use_cache=use_cache)
                            .decode("utf-8", "replace")))
    g2 = _sentence(standard, r"\(2\) The chemical manufacturer or importer shall ensure that "
                             r"the safety data sheet is in English .*?Section 16, Other "
                             r"information, including date of preparation or last revision\.",
                   "1910.1200(g)(2)")
    lead = g2[:g2.index(": (i)") + 1]
    cited = f"29 CFR 1910.1200(g)(2), eCFR as of {ECFR_DATE}"
    structure.headings = _rule(lead, cited)
    structure.order = structure.headings
    structure.empty = _rule(_sentence(
        text, r"If no relevant information is found for any given subheading within a "
              r"section, the SDS shall clearly indicate that no applicable information is "
              r"available\.", "App D empty"), f"{document}, introduction")
    structure.empty_scope = "section"
    optional = _sentence(text, r"Sections 12-15 may be included in the SDS, but are not "
                               r"mandatory\.", "App D 12-15")
    structure.optional = Rule(True, optional, f"{document}, introduction")
    table = text[text.find("Table D.1—Minimum Information for an SDS"):]
    for number, heading in re.findall(r"\([xvi]+\) Section (\d{1,2}), (.+?)(?:;|\.(?= \(x)| and"
                                      r"(?= \(xvi\))|\.$)", g2[len(lead):]):
        number = int(number)
        # Section 16's heading runs on into what it must contain: "including
        # date of preparation or last revision" is checked as an item.
        heading = heading.strip().split(", including")[0]
        structure.sections.append(Section(
            str(number), heading={"en": heading}, label={"en": "Section {n},"},
            required=not 12 <= number <= 15))
    if [s.number for s in structure.sections] != [str(n) for n in range(1, 17)]:
        raise SourceUnavailable("Table D.1 does not list headings 1 to 16")
    item1 = table[table.find("1. Identification"):table.find("2. Hazard Identification")]
    supplier = _sentence(item1, r"\(d\) Name, U\.S\. address, and U\.S\. telephone number of "
                                r"the chemical manufacturer, importer, or other responsible "
                                r"party;", "D.1 1(d)")
    emergency = _sentence(item1, r"\(e\) Emergency phone number\.", "D.1 1(e)")
    sixteen = _sentence(table, r"16\. Other information, including date of preparation or "
                               r"last revision The date of preparation of the SDS or the last "
                               r"change to it\.", "D.1 16")
    # Table D.1 lists items, not sentences: they bind through the introduction's
    # "shall include the information specified in Table D.1".
    binding = structure.headings.binding
    structure.items = [
        Item("supplier_telephone", "telephone", "1",
             Rule(binding, supplier, f"{document}, Table D.1, 1(d)")),
        Item("emergency_telephone", "emergency_telephone", "1",
             Rule(binding, emergency, f"{document}, Table D.1, 1(e)")),
        Item("date_of_revision", "date", "16",
             Rule(binding, sixteen, f"{document}, Table D.1, 16")),
    ]
    return structure


# -- Canada --------------------------------------------------------------------------

def _hpr_headings(path: Path) -> dict[str, dict[str, str]]:
    """Schedule 1's column 1, read by position: English item and heading
    columns on the left of the page, French on the right."""
    import pymupdf

    out: dict[str, dict[str, str]] = {"en": {}, "fr": {}}
    columns = {"en": (40, 70, 155), "fr": (310, 345, 425)}   # item x, heading x0, x1
    with pymupdf.open(path) as doc:
        for page in doc:
            text = page.get_text()
            if "Specific Information Elements" not in text and \
               "Éléments d’information spécifiques" not in text:
                continue
            if "SCHEDULE 1" not in text and "ANNEXE 1" not in text:
                continue
            if "Biohazardous" in text or "Section I —" in text:
                continue
            words = page.get_text("words")
            # The running footer ("Current to ... Last amended on ...") sits in
            # the same columns; nothing at or below it is a heading.
            footer = min((w[1] for w in words if w[4] in ("Current", "Last", "À", "Dernière")
                          and w[1] > page.rect.height * 0.8), default=page.rect.height)
            for language, (item_x, x0, x1) in columns.items():
                items = sorted((w for w in words if abs(w[0] - (item_x + 10)) < 12
                                and re.fullmatch(r"\d{1,2}", w[4])
                                and w[1] > 100), key=lambda w: w[1])
                for k, item in enumerate(items):
                    bottom = items[k + 1][1] if k + 1 < len(items) else footer
                    bottom = min(bottom, footer)
                    heading = [w for w in words if x0 - 2 <= w[0] < x1
                               and item[1] - 2 <= w[1] < bottom - 2]
                    heading.sort(key=lambda w: (round(w[1]), w[0]))
                    joined = re.sub(r"-\s+", "", " ".join(w[4] for w in heading))
                    joined = re.sub(r"/\s+", "/", joined).strip()
                    # A footnote reference printed against the last word.
                    joined = re.sub(r"(?<=[^\W\d_])\d$", "", joined)
                    if joined and item[4] not in out[language]:
                        out[language][item[4]] = joined
    return out


def _hpr() -> Structure:
    path = sources.require("ca-whmis/hpr_bilingual.pdf")
    document = "Hazardous Products Regulations (SOR/2015-17)"
    structure = Structure("ca_whmis", document, languages=["en", "fr"])
    pages = _pdf_pages(path)
    body = " ".join(re.sub(r"-\s+", "", t) for _, t in pages)
    headings = _sentence(body, r"the safety data sheet of a hazardous product must provide, "
                               r"in respect of the hazardous product, the following information "
                               r"elements: \(a\) the headings set out in column 1 of Schedule 1, "
                               r"in the order they are presented, including the corresponding "
                               r"item number, which is to be placed immediately before the "
                               r"heading;", "HPR 4(1)(a)")
    page = _page_of(pages, "Information elements Éléments d’information 4 (1)")
    where = f"{document}, section 4(1)(a)" + (f", page {page}" if page else "")
    structure.headings = _rule(headings, where)
    structure.order = structure.headings
    structure.empty = _rule(_sentence(
        body, r"if any of the information — except that required by paragraphs 3\(1\)\(a\) "
              r"and \(2\)\(a\) and \(d\) of that Schedule — is not available or not "
              r"applicable, an indication to that effect must be clearly stated in lieu of "
              r"the required specific information element", "HPR 4(1)(b)(i)"),
        f"{document}, section 4(1)(b)(i)")
    structure.empty_scope = "section"
    # A permission, not a duty: recorded as the text gives it.
    structure.optional = Rule(True, _sentence(
        body, r"Despite subsection \(1\), under each heading set out for items 12 to 15 of "
              r"Schedule 1, the content of the specific information elements in that "
              r"Schedule may be omitted\.", "HPR 4(2)"), f"{document}, section 4(2)")
    columns = _hpr_headings(path)
    for number in range(1, 17):
        key = str(number)
        if key not in columns["en"] or key not in columns["fr"]:
            raise SourceUnavailable(f"Schedule 1 item {number} heading not read")
        structure.sections.append(Section(
            key, heading={"en": columns["en"][key], "fr": columns["fr"][key]},
            label={"en": "{n}", "fr": "{n}"}, content_optional=12 <= number <= 15))
    schedule = body[body.find("Information Elements on Safety Data Sheet"):]
    supplier = _sentence(schedule, r"\(d\) initial supplier identifier;", "Sch.1 1(d)")
    definition = _sentence(body, r"initial supplier identifier means the name, address and "
                                 r"telephone number of \(a\) the manufacturer; or \(b\) the "
                                 r"importer of the hazardous product who operates in Canada\.",
                           "HPR s.1 definition")
    emergency = _sentence(schedule, r"\(e\) emergency telephone number and any restrictions "
                                    r"on the use of that number, if applicable", "Sch.1 1(e)")
    sixteen = _sentence(schedule, r"16 Other information Date of the latest revision of the "
                                  r"safety data sheet", "Sch.1 16")
    binding = structure.headings.binding
    structure.items = [
        Item("supplier_telephone", "telephone", "1",
             Rule(binding, f"{supplier} - {definition}",
                  f"{document}, Schedule 1, item 1(d); section 1")),
        Item("emergency_telephone", "emergency_telephone", "1",
             Rule(binding, emergency, f"{document}, Schedule 1, item 1(e)")),
        Item("date_of_revision", "date", "16",
             Rule(binding, sixteen, f"{document}, Schedule 1, item 16")),
    ]
    return structure


# -- UN GHS --------------------------------------------------------------------------

def _ghs() -> Structure:
    path = sources.require("un-ghs/GHS_Rev11_en.pdf")
    document = "UN GHS Rev.11 (2025)"
    pages = _pdf_pages(path)
    annex = " ".join(t for n, t in pages if 410 <= n <= 445)
    structure = Structure("un_ghs", document, languages=["en"])
    listing = _sentence(annex, r"A4\.2\.3\.1 The information in the SDS should be presented "
                               r"using the following 16 headings in the order given below "
                               r"\(see also 1\.5\.3\.2\.1\):.*?16\. Other information", "A4.2.3.1")
    page = _page_of(pages, "A4.2.3.1 The information in the SDS")
    where = f"{document}, Annex 4, A4.2.3.1" + (f", page {page}" if page else "")
    intro = listing[:listing.find(":") + 1]
    structure.headings = _rule(intro, where)
    structure.order = structure.headings
    for number, heading in re.findall(r"(\d{1,2})\. ([^;]+?)(?:;|$)", listing[len(intro):]):
        structure.sections.append(Section(number, heading={"en": heading.strip()},
                                          label={"en": "{n}."}))
    if [s.number for s in structure.sections] != [str(n) for n in range(1, 17)]:
        raise SourceUnavailable("A4.2.3.1 does not list 16 headings")
    structure.empty = _rule(_sentence(annex, r"The SDS should not contain any blanks\.",
                                      "A4.2.4.2"), f"{document}, Annex 4, A4.2.4.2")
    structure.empty_scope = "section"
    date = _sentence(annex, r"The date of issue of the SDS should be stated and be very "
                            r"apparent\.", "A4.2.2.4")
    numbering = _sentence(annex, r"All pages of an SDS should be numbered and some indication "
                                 r"of the end of the SDS should be given.*?\)\.", "A4.2.3.3")
    supplier = _sentence(annex, r"The name, full address and phone number\(s\) of the supplier "
                                r"should be included on the SDS\.", "A4.3.1.4")
    emergency = _sentence(annex, r"References to emergency information services should be "
                                 r"included in all SDS\.", "A4.3.1.5")
    structure.items = [
        Item("date_of_issue", "date", "document",
             _rule(date, f"{document}, Annex 4, A4.2.2.4")),
        Item("page_numbering", "page_numbering", "document",
             _rule(numbering, f"{document}, Annex 4, A4.2.3.3")),
        Item("supplier_telephone", "telephone", "1",
             _rule(supplier, f"{document}, Annex 4, A4.3.1.4")),
        Item("emergency_telephone", "emergency_telephone", "1",
             _rule(emergency, f"{document}, Annex 4, A4.3.1.5")),
    ]
    return structure


# -- Australia -----------------------------------------------------------------------

def _au() -> Structure:
    source = sources.BY_PATH["australia/model_whs_regulations_2025-12-05.pdf"]
    document = source.version
    structure = Structure("au_whs", document, languages=["en"])
    if not source.where.exists():
        structure.status, structure.why = "pending_source", sources.describe(source.path)
        return structure
    pages = _pdf_pages(source.where)
    schedule = " ".join(t for _, t in pages if "Schedule 7 Safety data sheets" in t)
    schedule = re.sub(r"Model Work Health and Safety Regulations Schedule 7 Safety data "
                      r"sheets OFFICIAL OFFICIAL ", "", schedule)
    page = _page_of(pages, "1 Safety data sheets—content (1)")
    on_page = f", page {page}" if page else ""
    listing = _sentence(schedule, r"\(2\) A safety data sheet for a hazardous chemical must "
                                  r"state the following information about the chemical:.*?"
                                  r"Section 16: Any other relevant information\.", "Sch.7 1(2)")
    for number, heading in re.findall(r"\([a-p]\) Section (\d{1,2}): (.+?)(?=;| and \(| in "
                                      r"accordance|\.$)", listing):
        structure.sections.append(Section(number, heading={"en": heading.strip().rstrip(",")},
                                          label={"en": "Section {n}:"}))
    if [s.number for s in structure.sections] != [str(n) for n in range(1, 17)]:
        raise SourceUnavailable("Schedule 7 1(2) does not list 16 headings")
    headings = _sentence(schedule, r"\(3\) The safety data sheet must use the headings and be "
                                   r"set out in the order set out in subclause \(2\)\.",
                         "Sch.7 1(3)")
    structure.headings = _rule(headings, f"{document}, Schedule 7, clause 1(3){on_page}")
    structure.order = structure.headings
    date = _sentence(schedule, r"\(b\) state the date it was last reviewed or, if it has not "
                               r"been reviewed, the date it was prepared;", "Sch.7 1(1)(b)")
    supplier = _sentence(schedule, r"\(c\) state the name, and the Australian address and "
                                   r"business telephone number of: \(i\) the manufacturer; or "
                                   r"\(ii\) the importer;", "Sch.7 1(1)(c)")
    emergency = _sentence(schedule, r"\(d\) state an Australian business telephone number from "
                                    r"which information about the chemical can be obtained in "
                                    r"an emergency;", "Sch.7 1(1)(d)")
    lead = _sentence(schedule, r"\(1\) A safety data sheet for a hazardous chemical must:",
                     "Sch.7 1(1)")
    structure.items = [
        Item("date_reviewed", "date", "document",
             _rule(f"{lead} {date}", f"{document}, Schedule 7, clause 1(1)(b){on_page}")),
        Item("supplier_telephone", "telephone", "document",
             _rule(f"{lead} {supplier}", f"{document}, Schedule 7, clause 1(1)(c){on_page}")),
        Item("emergency_telephone", "emergency_telephone", "document",
             _rule(f"{lead} {emergency}", f"{document}, Schedule 7, clause 1(1)(d){on_page}")),
    ]
    return structure


def build(regulation: str, *, use_cache: bool = True) -> Structure:
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
            return _au()
    raise ValueError(f"no SDS structure source for {regulation}")


def structure_dir() -> Path:
    return data_dir() / "sds_structure"


def write(regulation: str, *, use_cache: bool = True) -> Path:
    structure = build(regulation, use_cache=use_cache)
    structure_dir().mkdir(parents=True, exist_ok=True)
    path = structure_dir() / f"{regulation}.json"
    path.write_text(json.dumps(asdict(structure), indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path
