"""Generate the synthetic PDFs the test suite runs against.

Everything here is invented: the products, companies and CAS numbers are fake.
The only real text is the official regulatory wording, which is pulled from the
answer keys rather than typed out, so a fixture can never drift from the key.

Run directly to regenerate:  uv run python tests/make_fixtures.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lingua_oracle.keys.store import load_key  # noqa: E402
from lingua_oracle.models import SIGNAL_DANGER, SIGNAL_WARNING  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
WIDTH, HEIGHT = A4
LEFT, TOP, LINE = 50, HEIGHT - 60, 13

# Fake products, deliberately not resembling anything real.
PRODUCT = "Synthetic Test Solvent SDS-TEST-001"
SUPPLIER = "Nonexistent Chemicals Ltd, 1 Imaginary Road"

HEADINGS = {
    "da": {"2": "PUNKT 2: Fareidentifikation",
           "3": "PUNKT 3: Sammensætning af/oplysning om indholdsstoffer",
           "16": "PUNKT 16: Andre oplysninger",
           "signal": "Signalord", "haz": "Faresætninger", "prec": "Sikkerhedssætninger"},
    "en": {"2": "SECTION 2: Hazards identification",
           "3": "SECTION 3: Composition/information on ingredients",
           "16": "SECTION 16: Other information",
           "signal": "Signal word", "haz": "Hazard statements",
           "prec": "Precautionary statements"},
    "fr": {"2": "RUBRIQUE 2: Identification des dangers",
           "3": "RUBRIQUE 3: Composition/informations sur les composants",
           "16": "RUBRIQUE 16: Autres informations",
           "signal": "Mention d'avertissement", "haz": "Mentions de danger",
           "prec": "Conseils de prudence"},
    "de": {"2": "ABSCHNITT 2: Mögliche Gefahren",
           "3": "ABSCHNITT 3: Zusammensetzung/Angaben zu Bestandteilen",
           "16": "ABSCHNITT 16: Sonstige Angaben",
           "signal": "Signalwort", "haz": "Gefahrenhinweise",
           "prec": "Sicherheitshinweise"},
}


class Sheet:
    """A very small PDF text layout helper."""

    def __init__(self, path: Path, *, numbered: bool = False,
                 structure: tuple[str, str] | None = None,
                 composition: str = "mixture"):
        self.canvas = canvas.Canvas(str(path), pagesize=A4)
        self.y = TOP
        self.canvas.setFont("Helvetica", 9)
        # A fragment written section by section can be made a whole sheet: with
        # `structure` set, every section, sub-section and item the regulation's
        # text requires that the builder does not write is filled in around it,
        # from data/sds_structure/ - see _Completion.
        self.completion = _Completion(self, *structure, composition) if structure else None
        numbered = numbered or structure is not None
        # "SDS 1 / 3" at the foot of every page, the total filled in at save.
        # Not opening with a digit - "2 / 3" would read as a Section 2 heading -
        # and in capitals, so it is never taken as the end of a statement.
        self.numbered = numbered
        self.page = 1

    def _footer(self) -> None:
        if not self.numbered:
            return
        self.canvas.setFont("Helvetica", 7)
        self.canvas.drawString(WIDTH / 2 - 20, 30, f"SDS {self.page} / ")
        self.canvas.doForm("page_total")
        self.canvas.setFont("Helvetica", 9)

    def _new_page(self) -> None:
        self._footer()
        self.canvas.showPage()
        self.page += 1
        self.y = TOP

    def line(self, text: str = "", *, bold: bool = False, size: int = 9) -> None:
        if self.completion is not None and self.completion.heading(text):
            return
        self._draw(text, bold=bold, size=size)

    def _draw(self, text: str = "", *, bold: bool = False, size: int = 9) -> None:
        self.drawn = getattr(self, "drawn", set()) | set(re.findall(r"\bH\d{3}\b", text or ""))
        if self.y < 60:
            self._new_page()
        font = "Helvetica-Bold" if bold else "Helvetica"
        # Keep a statement on one line, shrinking the type to fit, the way a real
        # SDS fits text into a table cell. Wrapping a long statement would split
        # it at a sentence boundary, and a continuation that starts a new sentence
        # is indistinguishable from the next statement - so the fixture would
        # embed an extraction limitation rather than test the checks.
        usable = WIDTH - 2 * LEFT
        while size > 4 and self.canvas.stringWidth(text, font, size) > usable:
            size -= 1
        self.canvas.setFont(font, size)
        self.canvas.drawString(LEFT, self.y, text)
        self.y -= LINE

    def table(self, header: list[str], rows: list[list[str]]) -> None:
        """A ruled table, the way Section 3 is actually drawn.

        Ruled rather than laid out with spaces: the ingredient reader takes the
        columns the sheet drew, because a line-based reading of a composition
        table picks up whatever else is nearby. A fixture made of bare text
        would test a code path the real sheets do not use.
        """
        usable = WIDTH - 2 * LEFT
        widths = [usable * w for w in (0.28, 0.16, 0.18, 0.38)][:len(header)]
        widths[-1] += usable - sum(widths)
        size = 7
        self.canvas.setFont("Helvetica", size)

        def row_height(cells: list[str]) -> float:
            lines = 1
            for text, width in zip(cells, widths, strict=False):
                lines = max(lines, len(self._wrap(text, width - 6, size)))
            return lines * (size + 2) + 6

        for cells, bold in [(header, True), *[(r, False) for r in rows]]:
            height = row_height(cells)
            if self.y - height < 60:
                self.page_break()
            top, bottom = self.y + size, self.y + size - height
            x = LEFT
            self.canvas.setFont("Helvetica-Bold" if bold else "Helvetica", size)
            for text, width in zip(cells, widths, strict=False):
                self.canvas.rect(x, bottom, width, height, stroke=1, fill=0)
                text_y = top - size - 1
                for part in self._wrap(text, width - 6, size):
                    self.canvas.drawString(x + 3, text_y, part)
                    text_y -= size + 2
                x += width
            self.y = bottom - 2
        self.canvas.setFont("Helvetica", 9)
        self.y -= LINE

    def _wrap(self, text: str, width: float, size: int) -> list[str]:
        out, line = [], ""
        for word in (text or "").split():
            trial = f"{line} {word}".strip()
            if self.canvas.stringWidth(trial, "Helvetica", size) <= width:
                line = trial
                continue
            if line:
                out.append(line)
            line = word
        out.append(line)
        return out or [""]

    def blank(self, n: int = 1) -> None:
        self.y -= LINE * n

    def page_break(self) -> None:
        self._new_page()

    def save(self) -> None:
        if self.completion is not None:
            self.completion.finish()
        self._footer()
        if self.numbered:
            self.canvas.beginForm("page_total")
            self.canvas.setFont("Helvetica", 7)
            self.canvas.drawString(WIDTH / 2 - 20 + self.canvas.stringWidth(
                f"SDS {self.page} / ", "Helvetica", 7), 30, f"{self.page}")
            self.canvas.endForm()
        self.canvas.save()


_SECTION_LINE_RE = re.compile(
    r"^\s*(?:SECTION|PUNKT|AFSNIT|ABSCHNITT|RUBRIQUE|SECCIÓN)\s+(\d{1,2})\s*[:.]")


class _Completion:
    """Completes a fragment into a whole sheet, as its regulation's text requires.

    The builder writes the sections it is about ("SECTION 2: ...", "SECTION
    3: ..."); everything else - the sections between them, the sub-section
    headings around its content, the contact items, the date - is drawn from
    the structure table in the same order a real sheet has them. A builder's
    heading is printed in the table's own wording. Section 3 takes 3.1 or 3.2
    as `composition` says.
    """

    def __init__(self, sheet: Sheet, regulation: str, language: str, composition: str):
        self.sheet, self.regulation, self.language = sheet, regulation, language
        self.table = structure_table(regulation)
        self.composition = composition
        self.last = 0
        self.pending: list[dict] = []
        self.started = False

    def _subs(self, number: str) -> list[dict]:
        subs = list(self.table["sections"][int(number) - 1].get("subsections") or [])
        for group in self.table.get("one_of", []):
            if any(x["number"] in group for x in subs):
                keep = "3.1" if self.composition == "substance" else group[-1]
                subs = [x for x in subs if x["number"] not in group or x["number"] == keep]
        return subs

    def _sub_heading(self, sub: dict) -> None:
        tag = self.language.split("-")[0].split("+")[0]
        words = sub["heading"].get(tag) or sub["heading"]["en"]
        self.sheet._draw(f"{sub['number']}. {words}", bold=True)

    def _items(self, scope: str) -> list[str]:
        return _item_lines(self.table, self.language, scope)

    def _open(self, number: str, *, whole: bool) -> None:
        """A section's heading, and its sub-sections up to where the
        builder's own content goes; the rest wait for the next heading."""
        self.sheet._draw(section_title(self.regulation, self.language, number),
                         bold=True, size=11)
        subs = self._subs(number)
        self.pending = []
        extra = flash_lines(self.language, getattr(self.sheet, "drawn", set())) \
            if number == "9" else []
        if not subs:
            for line in self._items(number) + extra:
                self.sheet._draw(line)
            if whole and not extra:
                self.sheet._draw(FILLER)
            return
        self.extra = extra if whole else []
        if whole:
            self.pending = subs
            self._close()
            return
        numbers = [x["number"] for x in subs]
        body_at = _BODY_AT.get(number, numbers[0])
        at = numbers.index(body_at) if body_at in numbers else 0
        self.pending = subs[:at]
        self._close()
        self._sub_heading(subs[at])
        for line in self._items(subs[at]["number"]) + (extra if subs[at]["number"] == "9.1"
                                                       else []):
            self.sheet._draw(line)
        self.pending = subs[at + 1:]

    def _close(self) -> None:
        for sub in self.pending:
            self._sub_heading(sub)
            lines = self._items(sub["number"])
            # Section 9.1, basic properties: where a flash point belongs.
            if sub["number"] == "9.1":
                lines = lines + getattr(self, "extra", [])
            for line in lines or [FILLER]:
                self.sheet._draw(line)
        self.pending = []

    def _start(self) -> None:
        if not self.started:
            self.started = True
            for line in self._items("first_page") + self._items("document"):
                self.sheet._draw(line)

    def heading(self, text: str) -> bool:
        found = _SECTION_LINE_RE.match(text or "")
        if found is None:
            return False
        number = int(found.group(1))
        if not 1 <= number <= 16 or number <= self.last:
            return False
        self._start()
        self._close()
        for between in range(self.last + 1, number):
            self._open(str(between), whole=True)
        self._open(str(number), whole=False)
        self.last = number
        return True

    def finish(self) -> None:
        if not self.started:
            return
        self._close()
        for after in range(self.last + 1, 17):
            self._open(str(after), whole=True)
        self.last = 16


def _wrap(text: str, width: int) -> list[str]:
    if len(text) <= width:
        return [text]
    words, out, cur = text.split(" "), [], ""
    for word in words:
        if len(cur) + len(word) + 1 > width:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        out.append(cur)
    return out


def texts(regulation: str, language: str, codes: list[str]) -> dict[str, str]:
    key = load_key(regulation, language)
    if key is None:
        raise SystemExit(f"missing answer key {regulation}/{language}; run `lingua keys build`")
    by_code = key.by_code()
    missing = [c for c in codes if c not in by_code]
    if missing:
        raise SystemExit(f"{regulation}/{language} has no entry for {missing}")
    return {c: by_code[c].text for c in codes}


def signal_text(regulation: str, language: str, danger: bool = True) -> str:
    key = load_key(regulation, language)
    code = SIGNAL_DANGER if danger else SIGNAL_WARNING
    entry = (key.by_code() if key else {}).get(code)
    if entry is None:
        raise SystemExit(f"no {code} for {regulation}/{language}")
    return entry.text


_OPEN_OPTION_RE = re.compile(r"\s*/\s*…\s*$")


def close_open_options(text: str) -> str:
    """Write out a statement that ends in an open option, as a sheet would.

    ".../hearing protection/…" invites the author to add their own and has no
    full stop. A real sheet keeps the options that apply and ends the sentence.
    Fixtures that are meant to be correct have to do the same, or they ship an
    unfilled blank and are not correct at all.
    """
    closed = _OPEN_OPTION_RE.sub("", text or "")
    if closed == text:
        return text
    return closed if closed.endswith((".", "!", "?")) else closed + "."


# -- the 16 sections, as each regulation's own text requires them -------------------
#
# Headings, labels and sub-headings come from data/sds_structure/, which is read
# out of the regulation's text, the way statement wording comes from the answer
# keys: a fixture cannot drift from what it is judged against. The contact
# details are fictional and cannot be dialled or mailed.

STRUCTURE_DATE = "2026-01-15"
PHONE = "+00 000 000 000"
EMERGENCY_PHONE = "+00 000 000 999"
EMAIL = "sds@example.invalid"
FILLER = "—"
_EMERGENCY_WORD = {"en": "Emergency telephone", "fr": "Numéro d'urgence",
                   "es": "Teléfono de emergencia"}
#: Where a section's own content goes when its text has sub-sections.
_BODY_AT = {"1": "1.1", "2": "2.2", "3": "3.2", "9": "9.1", "11": "11.1", "12": "12.1"}


_FLASH_WORDS = {"en": ("Flash point", "Initial boiling point"),
                "da": ("Flammepunkt", "Kogepunkt"), "de": ("Flammpunkt", "Siedebeginn"),
                "fr": ("Point d'éclair", "Point initial d'ébullition")}
#: A flash point and boiling point in each flammable-liquid category - inside
#: every regulation's bands, which agree on these points.
_FLASH = {"H224": ("10", "30"), "H225": ("10", "80"), "H226": ("40", ""), "H227": ("75", "")}


def flash_lines(language: str, codes) -> list[str]:
    """Section 9's flash point (and boiling point) for the flammable-liquid
    code a sheet prints, in its language: a sheet that says H225 says why."""
    code = next((c for c in ("H224", "H225", "H226", "H227") if c in codes), None)
    if code is None:
        return []
    flash, boiling = _FLASH[code]
    words = _FLASH_WORDS.get(language.split("-")[0].split("+")[0], _FLASH_WORDS["en"])
    return [f"{words[0]}: {flash} °C"] + ([f"{words[1]}: {boiling} °C"] if boiling else [])


def structure_table(regulation: str) -> dict:
    from lingua_oracle.structure.reader import load

    table = load(regulation)
    if table is None:
        raise SystemExit(f"no SDS structure for {regulation}; run `lingua keys build sds_structure`")
    return table


def section_title(regulation: str, language: str, number: str) -> str:
    """A section's heading, label and number as the text prints them."""
    section = structure_table(regulation)["sections"][int(number) - 1]
    heading = section["heading"]
    if regulation == "ca_whmis":
        # The item number, then the heading - in both languages for a sheet
        # written in both ("en+fr"). Printed "3." rather than "3": a bare number
        # opening a line reads as the rest of the line above to a text reader,
        # on a real sheet as here.
        if "+" in language:
            return f"{number}. {heading['en']} / {heading['fr']}"
        return f"{number}. {heading[language.split('-')[0]]}"
    lang = language if language in heading else "en"
    label = section["label"].get(lang) or section["label"]["en"]
    # "Hazard(s)" is either; a sheet prints one of them.
    return f"{label.replace('{n}', number)} {heading[lang].replace('(s)', 's')}".strip()


def _item_lines(table: dict, language: str, scope: str) -> list[str]:
    out = []
    for item in table.get("items", []):
        if item["scope"] != scope:
            continue
        kind = item["kind"]
        if kind == "telephone":
            out.append(f"Tel.: {EMERGENCY_PHONE if scope.endswith('.4') else PHONE}")
        elif kind == "emergency_telephone":
            word = _EMERGENCY_WORD.get(language.split("-")[0].split("+")[0],
                                       _EMERGENCY_WORD["en"])
            out.append(f"{word}: {EMERGENCY_PHONE}")
        elif kind == "email":
            out.append(EMAIL)
        elif kind == "date":
            out.append(STRUCTURE_DATE)
    return list(dict.fromkeys(out))


def structured_sheet(path: Path, *, regulation: str, language: str,
                     bodies: dict[str, list] | None = None,
                     omit: set[str] | None = None, order: list[str] | None = None,
                     printed: dict[str, str] | None = None,
                     headings: dict[str, str] | None = None,
                     blank: set[str] | None = None) -> Path:
    """A sheet with every section and sub-section the regulation's text
    requires, each carrying its own content or a filler, and the items where
    the text puts them. `bodies` maps a section number to its lines - plain
    text, or (text, {"bold": True, "size": 11}) - placed under the
    section's first content sub-section where the text has sub-sections.

    For the structure tests, a sheet can be made wrong on purpose: `omit`
    leaves out sections, sub-sections or items (by number or item id),
    `order` prints the sections in another order, `printed` prints a
    section under another number, `headings` gives a section other words,
    `blank` prints sub-sections (or sections) with nothing under them."""
    table = structure_table(regulation)
    bodies = dict(bodies or {})
    printed_codes = set(re.findall(r"\bH\d{3}\b", " ".join(
        line if isinstance(line, str) else line[0] for body in bodies.values() for line in body)))
    if "9" not in bodies:
        bodies["9"] = flash_lines(language, printed_codes)
    omit, printed, headings = omit or set(), printed or {}, headings or {}
    blank = blank or set()
    if omit & {i["id"] for i in table.get("items", [])}:
        table = dict(table, items=[i for i in table["items"] if i["id"] not in omit])
    tag = language.split("-")[0].split("+")[0]
    sheet = Sheet(path, numbered=True)
    sheet.line(PRODUCT, bold=True, size=12)
    for line in _item_lines(table, language, "first_page") + _item_lines(
            table, language, "document"):
        sheet.line(line)

    def write(lines):
        for line in lines:
            if isinstance(line, tuple):
                sheet.line(line[0], **line[1])
            elif line == "":
                sheet.blank()
            else:
                sheet.line(line)

    sections = {s["number"]: s for s in table["sections"]}
    for number in order or list(sections):
        section = sections[number]
        if number in omit:
            continue
        title = section_title(regulation, language, number)
        if number in headings:
            words = section["heading"].get(language.split("-")[0]) or section["heading"]["en"]
            title = title.replace(words.replace("(s)", "s"), headings[number])
        if number in printed:
            title = re.sub(rf"(?<!\d){number}(?!\d)", printed[number], title, count=1)
        sheet.line(title, bold=True, size=11)
        body = list(bodies.get(number, []))
        subs = section.get("subsections") or []
        if not subs:
            # Items first: a statement printed last would otherwise run on into
            # them, the way an unpunctuated line runs into the next.
            if number not in blank:
                write(_item_lines(table, language, number) + body or [FILLER])
            sheet.blank()
            continue
        skip = set()
        for group in table.get("one_of", []):
            if subs[0]["number"] in group or any(x["number"] in group for x in subs):
                keep = _BODY_AT.get(number, group[-1])
                skip |= {n for n in group if n != keep}
        shown = [x["number"] for x in subs if x["number"] not in skip | omit]
        body_at = _BODY_AT.get(number) or (shown[0] if shown else None)
        for sub in subs:
            if sub["number"] in skip or sub["number"] in omit:
                continue
            words = sub["heading"].get(tag) or sub["heading"]["en"]
            sheet.line(f"{sub['number']}. {words}", bold=True)
            content = _item_lines(table, language, sub["number"]) + \
                (body if body_at == sub["number"] else [])
            if sub["number"] not in blank:
                write(content or [FILLER])
        sheet.blank()
    sheet.save()
    return path


def write_sds(
    path: Path,
    *,
    regulation: str,
    language: str,
    h_codes: list[str],
    p_codes: list[str],
    supplemental: list[str] | None = None,
    danger: bool = True,
    overrides: dict[str, str] | None = None,
    signal_override: str | None = None,
    omit_from_s16: set[str] | None = None,
    extra_lines_s2: list[str] | None = None,
    extra_lines_s16: list[str] | None = None,
    include_s16: bool = True,
    bare_in_s3: list[str] | None = None,
) -> Path:
    """Write a complete SDS: all 16 sections as the regulation's text requires.

    `bare_in_s3` codes are printed in Section 3's classification only, as
    codes, and nowhere else. `include_s16=False` leaves Section 16's
    statements out (its heading stays: the structure is not what is tested).
    """
    head = HEADINGS[language]
    supplemental = supplemental or []
    overrides = overrides or {}
    omit_from_s16 = omit_from_s16 or set()
    all_codes = h_codes + p_codes + supplemental
    official = texts(regulation, language, all_codes)
    official = {code: close_open_options(text) for code, text in official.items()}
    official.update({k: v for k, v in overrides.items() if k in official})

    two = [f"{head['signal']}: {signal_override or signal_text(regulation, language, danger)}",
           "", (head["haz"], {"bold": True})]
    two += [f"{code} {official[code]}" for code in h_codes + supplemental]
    two += ["", (head["prec"], {"bold": True})]
    two += [f"{code} {official[code]}" for code in p_codes]
    two += list(extra_lines_s2 or [])
    three = ["Synthetic component A  CAS 000-00-0  30-60%",
             "Classification: " + ", ".join(h_codes + (bare_in_s3 or []))]
    sixteen = []
    if include_s16:
        sixteen = [f"{code} {official[code]}" for code in h_codes + supplemental
                   if code not in omit_from_s16]
        sixteen += list(extra_lines_s16 or [])
    # Section 1's product identifier, which is where the product name is read
    # from. A sheet without one cannot be matched to anything.
    one = [f"Product name: {PRODUCT}", SUPPLIER]
    return structured_sheet(path, regulation=regulation, language=language,
                            bodies={"1": one, "2": two, "3": three, "16": sixteen})


# --------------------------------------------------------------------------
# The fixture set
# --------------------------------------------------------------------------

EU_H = ["H225", "H319", "H336"]
EU_P = ["P210", "P280", "P305+P351+P338"]
EU_EUH = ["EUH066"]


def build_all() -> dict[str, Path]:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    built: dict[str, Path] = {}

    def add(name: str, path: Path) -> None:
        built[name] = path

    # ---- clean documents -------------------------------------------------
    add("clean_eu_da", write_sds(
        FIXTURES / "clean_eu_da.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P, supplemental=EU_EUH))

    add("clean_eu_en", write_sds(
        FIXTURES / "clean_eu_en.pdf", regulation="eu_clp", language="en",
        h_codes=EU_H, p_codes=EU_P, supplemental=EU_EUH))

    # OSHA: only codes the OSHA key actually holds are used, so the fixture
    # never depends on text the source did not provide.
    osha_key = load_key("us_osha", "en")
    osha_codes = [c for c in ("H228", "H240", "H241") if c in (osha_key.by_code() if osha_key else {})]
    add("clean_osha_en", write_sds(
        FIXTURES / "clean_osha_en.pdf", regulation="us_osha", language="en",
        h_codes=osha_codes, p_codes=[], danger=True,
        extra_lines_s2=["Prepared under 29 CFR 1910.1200 (Hazard Communication)."]))

    # WHMIS en+fr: one document carrying both required languages.
    add("clean_whmis_enfr", _whmis_bilingual(FIXTURES / "clean_whmis_enfr.pdf"))

    # ---- one seeded defect per check ------------------------------------
    add("defect_a01_signal", write_sds(
        FIXTURES / "defect_a01_signal.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P, signal_override="Gøre"))

    da_h225 = texts("eu_clp", "da", ["H225"])["H225"]
    add("defect_a02_hazard", write_sds(
        FIXTURES / "defect_a02_hazard.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P,
        overrides={"H225": da_h225.replace("Meget", "Ekstremt")}))

    da_p210 = texts("eu_clp", "da", ["P210"])["P210"]
    add("defect_a03_precautionary", write_sds(
        FIXTURES / "defect_a03_precautionary.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P,
        overrides={"P210": da_p210.replace("Holdes", "Holdt") if "Holdes" in da_p210
                   else da_p210 + " Undgå alting."}))

    da_euh = texts("eu_clp", "da", ["EUH066"])["EUH066"]
    add("defect_a04_supplemental", write_sds(
        FIXTURES / "defect_a04_supplemental.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P, supplemental=EU_EUH,
        overrides={"EUH066": da_euh.replace("Gentagen", "Gentaget")}))

    # A-05: an English statement left inside a Danish document.
    en_h319 = texts("eu_clp", "en", ["H319"])["H319"]
    add("defect_a05_english", write_sds(
        FIXTURES / "defect_a05_english.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P, overrides={"H319": en_h319}))

    add("defect_a06_placeholder", write_sds(
        FIXTURES / "defect_a06_placeholder.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P,
        extra_lines_s2=["Leverandør: {0}", "Nødtelefon: {0}"]))

    add("defect_a07_broken", write_sds(
        FIXTURES / "defect_a07_broken.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P,
        extra_lines_s2=["Brandfarlig vÃ¦ske og damp ved opvarmning."]))

    # B-08: H302 is given in Section 3 only as a code, and Section 16 does
    # not write it out - so the sheet never gives its text. (A code Section 2
    # writes out in full needs nothing in Section 16: REACH Annex II, 16(e).)
    add("defect_b08_missing_s16", write_sds(
        FIXTURES / "defect_b08_missing_s16.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P, bare_in_s3=["H302"]))

    add("defect_b09_label", _label_mismatch(FIXTURES / "defect_b09_label.pdf"))

    # A complete sheet that names no regulation anywhere: GHS headings are
    # everyone's, so nothing on it says which regulation governs it.
    add("pattern_undetectable", write_sds(
        FIXTURES / "pattern_undetectable.pdf", regulation="un_ghs", language="en",
        h_codes=["H225", "H319"], p_codes=["P210"]))

    # B-10: H225 requires Danger, but the document states Warning.
    add("defect_b10_signal_fit", write_sds(
        FIXTURES / "defect_b10_signal_fit.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P, danger=False))

    # B-11: a translated pair whose code sets differ.
    add("compare_b11_a", write_sds(
        FIXTURES / "compare_b11_a.pdf", regulation="eu_clp", language="en",
        h_codes=EU_H, p_codes=EU_P))
    add("compare_b11_b", write_sds(
        FIXTURES / "compare_b11_b.pdf", regulation="eu_clp", language="da",
        h_codes=["H225", "H319"], p_codes=EU_P))

    # C-12: an EUH statement on an OSHA document.
    add("defect_c12_euh_on_osha", _euh_on_osha(FIXTURES / "defect_c12_euh_on_osha.pdf"))

    # C-14: a WHMIS document in English only.
    add("defect_c14_english_only", _whmis_english_only(
        FIXTURES / "defect_c14_english_only.pdf"))

    # Patterns found on real documents, reproduced with fictional data.
    add("pattern_only_says_ghs", _only_says_ghs(
        FIXTURES / "pattern_only_says_ghs.pdf"))
    add("pattern_out_of_scope", _out_of_scope(
        FIXTURES / "pattern_out_of_scope.pdf"))
    add("pattern_unfilled_blanks", _unfilled_blanks(
        FIXTURES / "pattern_unfilled_blanks.pdf"))
    add("pattern_classification_table", _classification_table(
        FIXTURES / "pattern_classification_table.pdf"))
    add("pattern_conditional_slots", _conditional_slots(
        FIXTURES / "pattern_conditional_slots.pdf"))
    add("pattern_legend_after_statement", _legend_after_statement(
        FIXTURES / "pattern_legend_after_statement.pdf"))
    add("defect_c15_newer_ghs", _newer_ghs_codes(
        FIXTURES / "defect_c15_newer_ghs.pdf"))
    add("defect_c15_osha_partial_key", _newer_ghs_on_osha(
        FIXTURES / "defect_c15_osha_partial_key.pdf"))
    add("pattern_language_outside_regulation", _language_outside_the_regulation(
        FIXTURES / "pattern_language_outside_regulation.pdf"))
    add("pattern_spacing_variant", _spacing_variant(
        FIXTURES / "pattern_spacing_variant.pdf"))
    add("pattern_optional_fillin", _optional_group_filled(
        FIXTURES / "pattern_optional_fillin.pdf"))
    add("pattern_osha_terminator", _osha_terminator(
        FIXTURES / "pattern_osha_terminator.pdf"))
    add("pattern_capitalisation", _odd_capitalisation(
        FIXTURES / "pattern_capitalisation.pdf"))
    add("pattern_negative_declaration", _negative_declaration(
        FIXTURES / "pattern_negative_declaration.pdf"))
    add("pattern_reach_registration", _reach_registration_number(
        FIXTURES / "pattern_reach_registration.pdf"))
    add("pattern_label_only", _label_only(FIXTURES / "pattern_label_only.pdf"))
    add("pattern_supplier_ingredients", _supplier_ingredients(
        FIXTURES / "pattern_supplier_ingredients.pdf"))
    add("pattern_substance_2_propanol", _substance_sheet(
        FIXTURES / "pattern_substance_2_propanol.pdf",
        classes=["Flam. Liq. 2", "Eye Irrit. 2", "STOT SE 3"],
        codes=["H225", "H319", "H336"]))
    add("pattern_substance_missing_h336", _substance_sheet(
        FIXTURES / "pattern_substance_missing_h336.pdf",
        classes=["Flam. Liq. 2", "Eye Irrit. 2"], codes=["H225", "H319"]))
    add("pattern_mixture_no_concentrations", _no_concentrations(
        FIXTURES / "pattern_mixture_no_concentrations.pdf"))
    add("pattern_glycol_coolant_gb", _glycol_coolant(
        FIXTURES / "pattern_glycol_coolant_gb.pdf"))
    # The same table, on a sheet that names its product the way ours do. Where
    # the product is one of ours its record is what gets checked, and this is
    # the fixture that can tell the two apart: the table here is nothing like
    # the record the test puts in the application.
    add("pattern_named_with_ingredients", _supplier_ingredients(
        FIXTURES / "pattern_named_with_ingredients.pdf", labelled=True))
    # The same sheet, stating an aquatic classification in Section 2. Under a
    # regulation that has aquatic classes that is something to check; under one
    # that has none - OSHA, WHMIS - it is not a finding, and the report has to
    # say which of those it is.
    # The same mixture, said to be a liquid on one sheet and a gas on the
    # other. CLP sets a respiratory sensitiser's limit at 1,0 % for a solid or
    # a liquid and 0,2 % for a gas, so 0,5 % of one classifies the gas and not
    # the liquid - and a sheet that does not say cannot be told either way.
    for state in ("liquid", "gas", None):
        add(f"pattern_sensitiser_{state or 'unstated'}", _sensitiser_sheet(
            FIXTURES / f"pattern_sensitiser_{state or 'unstated'}.pdf", state))
    # The shape of a real WHMIS sheet that the per-class comparison got wrong:
    # Section 2 is stricter than the declared ingredients, and 39 % of the
    # mixture is not declared at all. Compared per class it produced three
    # contradictions and two unanswerables; compared per hazard family it is a
    # sheet that is stricter about the skin and the eye than the part of the
    # mixture it discloses.
    add("pattern_stricter_than_declared", _stricter_sheet(
        FIXTURES / "pattern_stricter_than_declared.pdf"))
    # A Section 3 that gives a share and no CAS number: a trade secret is
    # part of the mixture and nothing can classify it.
    # A sheet whose Section 3 names a substance the Australian list
    # contradicts itself about, so the report has something to say about the
    # list rather than about the sheet.
    add("pattern_contradicted_substance", _one_substance_sheet(
        FIXTURES / "pattern_contradicted_substance.pdf",
        name="Synthetic component T", cas="108-88-3", share="40 %",
        classification="Flam. Liq. 2, H225"))
    add("pattern_trade_secret", _trade_secret_sheet(
        FIXTURES / "pattern_trade_secret.pdf"))
    add("pattern_aquatic_statement", _supplier_ingredients(
        FIXTURES / "pattern_aquatic_statement.pdf",
        classification="Flam. Liq. 2, H225; Aquatic Chronic 2, H411"))
    # A sheet whose statement text is markup. Nothing about this is plausible
    # as chemistry; it is here because the report prints text taken out of a
    # PDF, and a PDF is a file somebody else wrote.
    add("pattern_markup_in_text", write_sds(
        FIXTURES / "pattern_markup_in_text.pdf", regulation="eu_clp",
        language="en", h_codes=["H225", "H319"], p_codes=["P210", "P280"],
        overrides={"H319": "Causes serious <script>alert(1)</script> irritation",
                   "P210": "Keep away from <b>x</b> heat and open flames."}))
    # A statement OSHA has not adopted, printed with its optional bracket still
    # holding the blank. The wording is GHS's own, so it is checked against GHS -
    # and the unfinished slot has to be reported there too.
    add("pattern_unfilled_bracket_ghs", write_sds(
        FIXTURES / "pattern_unfilled_bracket_ghs.pdf",
        regulation="us_osha", language="en",
        h_codes=["H225", "H319"], p_codes=["P210", "P280"],
        extra_lines_s2=["P264+P265 Wash hands [and …] thoroughly after handling. "
                        "Do not touch eyes."]))
    # The same statement, dropping the optional group and shouting one word.
    # The wording is GHS's, but not to the letter, and the report must not say
    # it is.
    add("pattern_ghs_case_difference", write_sds(
        FIXTURES / "pattern_ghs_case_difference.pdf",
        regulation="us_osha", language="en",
        h_codes=["H225", "H319"], p_codes=["P210", "P280"],
        extra_lines_s2=["P264+P265 Wash HANDS thoroughly after handling. "
                        "Do not touch eyes."]))

    # C-02: the same code written two different ways.
    add("defect_c02_inconsistent", write_sds(
        FIXTURES / "defect_c02_inconsistent.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P,
        extra_lines_s16=[f"H336 {texts('eu_clp','da',['H336'])['H336'].rstrip('.')} i hovedet."]))

    # The official German P280 stops without a full stop - in Regulation (EU)
    # 2019/521 as well as in the consolidation. These two sheets differ only by
    # the full stop an author naturally writes, and neither may be failed.
    subset = "Schutzhandschuhe/Augenschutz tragen"
    for name, text in (("pattern_de_no_terminator", subset),
                       ("pattern_de_terminator", subset + ".")):
        add(name, write_sds(
            FIXTURES / f"{name}.pdf", regulation="eu_clp", language="de",
            h_codes=["H225", "H319"], p_codes=["P210", "P280"],
            overrides={"P280": text}))

    return built



def _one_substance_sheet(path: Path, *, name: str, cas: str, share: str,
                         classification: str) -> Path:
    """One named ingredient, one concentration, one classification."""
    head = HEADINGS["en"]
    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Classification: Flam. Liq. 2, H225")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.table(["Chemical name", "CAS No", "Concentration", "Classification"],
                [[name, cas, share, classification]])
    sheet.save()
    return path


def _trade_secret_sheet(path: Path) -> Path:
    """Half the mixture named, half of it withheld."""
    head = HEADINGS["en"]
    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Classification: Flam. Liq. 2, H225")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.table(
        ["Chemical name", "CAS No", "Concentration", "Classification"],
        [["Synthetic component H", "67-64-1", "20 %", "Flam. Liq. 2, H225"],
         ["Proprietary fragrance", "Trade Secret", "50 %", "Trade Secret"]])
    sheet.save()
    return path


def _stricter_sheet(path: Path) -> Path:
    """Section 2 stricter than Section 3, with most of the mixture undisclosed.

    Two ingredients at 31 % and 30 %, each irritant to skin and eye and each
    narcotic; Section 2 says the mixture is corrosive and a category 1 target
    organ toxicant. Both can be true: 39 % of the mixture is not declared.
    """
    head = HEADINGS["en"]
    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Classification: Skin Corr. 1, H314; STOT SE 1, H370")
    sheet.line("Signal word: Danger")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.table(
        ["Chemical name", "CAS No", "Concentration", "Classification"],
        [["Synthetic component F", "100-00-1", "31 %",
          "Skin Irrit. 2, H315; Eye Irrit. 2, H319; STOT SE 3, H336"],
         ["Synthetic component G", "100-00-2", "30 %",
          "Skin Irrit. 2, H315; Eye Irrit. 2, H319; STOT SE 3, H336"]])
    sheet.blank()
    sheet.line("SECTION 9: Physical and chemical properties", bold=True, size=11)
    sheet.line("Physical state : liquid")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    sheet.line("H314 Causes severe skin burns and eye damage.")
    sheet.save()
    return path


def _sensitiser_sheet(path: Path, state: str | None) -> Path:
    """A mixture with one respiratory sensitiser in it, at half a per cent.

    Section 9 says what it is, or says nothing, which is the whole point of
    the fixture: the limit it has to clear depends on that answer.
    """
    head = HEADINGS["en"]
    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Classification: Flam. Liq. 2, H225")
    sheet.line("Signal word: Danger")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.table(
        ["Chemical name", "CAS No", "Concentration", "Classification"],
        [["Synthetic component D", "584-84-9", "0,5 %", "Resp. Sens. 1, H334"],
         ["Synthetic component E", "67-64-1", "40 %", "Flam. Liq. 2, H225"]])
    sheet.blank()
    sheet.line("SECTION 9: Physical and chemical properties", bold=True, size=11)
    sheet.line("9.1 Information on basic physical and chemical properties")
    if state:
        sheet.line(f"Physical state : {state}")
    sheet.line("Odour : characteristic")
    sheet.blank()
    sheet.line("SECTION 10: Stability and reactivity", bold=True, size=11)
    sheet.line("No dangerous reactions known.")
    sheet.save()
    return path


def _supplier_ingredients(path: Path, *, labelled: bool = False,
                          classification: str = "") -> Path:
    """A supplier's sheet whose Section 3 prints a real composition table.

    Not one of ours - no product id in the name, no matching product - so the
    ingredient check has to read the sheet itself. The CAS numbers are real
    substances with harmonised entries, because Annex VI is public law; the
    product and the company are invented.
    """
    head = HEADINGS["en"]
    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    if labelled:
        sheet.line(f"Product name: {PRODUCT}")
    sheet.line(SUPPLIER)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    if classification:
        sheet.line(f"Classification: {classification}")
    sheet.line("Signal word: Danger")
    sheet.blank()
    official = texts("eu_clp", "en", ["H225", "H319"])
    sheet.line(head["haz"], bold=True)
    for code in ("H225", "H319"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.table(
        ["Chemical name", "CAS No", "Concentration", "Classification"],
        [["Synthetic component A", "67-64-1", "30 - 60 %",
          "Flam. Liq. 2, H225; Eye Irrit. 2, H319; STOT SE 3, H336; EUH066"],
         ["Synthetic component B", "1333-74-0", "5 - 10 %",
          "Flam. Gas 1, H220; Press. Gas"],
         ["Synthetic component C", "7439-93-2", "< 1 %",
          "Water-react. 1, H260"]])
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in ("H225", "H319"):
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path


def _substance_sheet(path: Path, *, classes: list[str], codes: list[str]) -> Path:
    """A substance: 2-propanol on its own, as a supplier would write it.

    Annex VI 603-117-00-0 classifies 2-propanol (CAS 67-63-0) Flam. Liq. 2,
    Eye Irrit. 2, STOT SE 3 - H225, H319, H336. The substance and its entry are
    public law; the supplier is invented. Section 3 says "3.1 Substances" and
    lists the one CAS number at 100 %, so either rule finds it a substance.
    """
    head = HEADINGS["en"]
    official = texts("eu_clp", "en", codes + ["P210", "P233"])
    sheet = Sheet(path, structure=("eu_clp", "en"), composition="substance")
    sheet.line("2-Propanol", bold=True, size=12)
    sheet.line("SECTION 1: Identification of the substance/mixture")
    sheet.line("Product name: 2-Propanol")
    sheet.line("CAS number: 67-63-0")
    sheet.line(SUPPLIER)
    sheet.line("Prepared according to Regulation (EC) No 1272/2008.", size=8)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("2.1 Classification of the substance or mixture")
    for hazard_class, code in zip(classes, codes, strict=True):
        sheet.line(f"{hazard_class}; {code}")
    sheet.line("2.2 Label elements")
    sheet.line(f"{head['signal']}: {signal_text('eu_clp', 'en')}")
    sheet.line(head["haz"], bold=True)
    for code in codes:
        sheet.line(f"{code} {official[code]}")
    sheet.line(head["prec"], bold=True)
    for code in ("P210", "P233"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("3.1 Substances")
    sheet.table(["Chemical name", "CAS No", "Concentration", "Classification"],
                [["2-Propanol", "67-63-0", "100 %", ", ".join(codes)]])
    sheet.blank()
    sheet.line("SECTION 9: Physical and chemical properties", bold=True, size=11)
    sheet.line("Physical state : liquid")
    sheet.blank()
    sheet.line("SECTION 10: Stability and reactivity", bold=True, size=11)
    sheet.line("Stable under normal conditions.")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in codes:
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path


def _no_concentrations(path: Path) -> Path:
    """A mixture whose Section 3 names its ingredients and gives no shares.

    Nothing can be summed, and there are no codes to compare - but each CAS
    number still has an entry worth showing. Real substances, invented product.
    """
    head = HEADINGS["en"]
    official = texts("eu_clp", "en", ["H225", "H319"])
    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Prepared according to Regulation (EC) No 1272/2008.", size=8)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Classification: Flam. Liq. 2, H225")
    sheet.line("Signal word: Danger")
    for code in ("H225", "H319"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("3.2 Mixtures")
    sheet.table(["Chemical name", "CAS No"],
                [["Synthetic component A", "67-64-1"],
                 ["Synthetic component F", "64-17-5"]])
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in ("H225", "H319"):
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path


def _glycol_coolant(path: Path, *, section_eleven: list[str] | None = None,
                    section_two: list[tuple[str, str]] | None = None,
                    extra_s2: list[str] | None = None) -> Path:
    """A GB CLP engine coolant in the shape real ones take.

    Ethylene glycol 40-60 %, water 40-60 %, diethylene glycol < 2.5 % and two
    minor salts. The upper bounds add up to more than 100 %, so nothing is
    undisclosed: the uncertainty is the ranges'. The substances are real and
    their GB MCL entries public; the product and supplier are invented.
    """
    head = HEADINGS["en"]
    classified = section_two or [("Acute Tox. 4", "H302"), ("STOT RE 2", "H373")]
    codes = [code for _, code in classified]
    official = texts("uk_clp", "en", codes + ["P260", "P301+P312"])
    sheet = Sheet(path, structure=("uk_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line("SECTION 1: Identification of the substance/mixture")
    sheet.line(f"Product name: {PRODUCT}")
    sheet.line(SUPPLIER)
    sheet.line("Classified according to GB CLP.", size=8)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("2.1 Classification of the substance or mixture")
    for hazard_class, code in classified:
        sheet.line(f"{hazard_class}; {code}")
    for extra in extra_s2 or []:
        sheet.line(extra)
    sheet.line("2.2 Label elements")
    sheet.line(f"{head['signal']}: {signal_text('uk_clp', 'en', danger=False)}")
    sheet.line(head["haz"], bold=True)
    for code in codes:
        sheet.line(f"{code} {official[code]}")
    sheet.line(head["prec"], bold=True)
    for code in ("P260", "P301+P312"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("3.2 Mixtures")
    sheet.table(["Chemical name", "CAS No", "Concentration", "Classification"],
                [["Ethylene glycol", "107-21-1", "40 - 60 %", "Acute Tox. 4, H302"],
                 ["Water", "7732-18-5", "40 - 60 %", ""],
                 ["Diethylene glycol", "111-46-6", "< 2.5 %", "Acute Tox. 4, H302"],
                 ["Sodium benzoate", "532-32-1", "< 1 %", ""],
                 ["Disodium sebacate", "17265-14-4", "< 1 %", ""]])
    sheet.blank()
    sheet.line("SECTION 9: Physical and chemical properties", bold=True, size=11)
    sheet.line("Physical state : Liquid")
    sheet.line("Colour : green")
    sheet.blank()
    sheet.line("SECTION 10: Stability and reactivity", bold=True, size=11)
    sheet.line("Stable under normal conditions.")
    sheet.blank()
    sheet.line("SECTION 11: Toxicological information", bold=True, size=11)
    for line in section_eleven or ["No data available for the mixture."]:
        sheet.line(line)
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in codes:
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path


def _label_only(path: Path) -> Path:
    """Label artwork with no SDS behind it.

    A print file for a container label: the product, the signal word, the
    statements, the supplier. It carries a block title that reads like Section 2
    and a line naming the label, so both parts are recognised - but there is no
    safety data sheet here, and comparing "Section 2" with "the label" when they
    are the same piece of artwork reported every statement as missing from the
    other.
    """
    sheet = Sheet(path)
    official = texts("us_osha", "en", ["H225", "H319", "P210", "P280", "P264"])
    sheet.line(PRODUCT, bold=True, size=14)
    sheet.blank()
    sheet.line("Hazards Identification", bold=True, size=11)
    sheet.line("DANGER")
    for code in ("H225", "H319"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line("Label elements", bold=True)
    for code in ("P210", "P280", "P264"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(SUPPLIER)
    sheet.save()
    return path


def _spacing_variant(path: Path) -> Path:
    """A sheet whose statements differ from the key only in where spaces fall.

    Real authoring tools and PDF producers move spaces around: a space appears
    before an ellipsis, or between a number and its unit. The wording is the
    official wording, so none of this may be reported as a wording defect.

    The variants are derived from the key rather than typed out, so they cannot
    drift from it - only the whitespace is changed.
    """
    official = texts("un_ghs", "en", ["P370+P378", "P410+P412"])
    fire = official["P370+P378"].replace(" …", "…")        # space removed
    heat = official["P410+P412"].replace("50°C", "50 °C")  # space added
    if fire == official["P370+P378"] or heat == official["P410+P412"]:
        raise SystemExit("spacing fixture: the key text no longer has the expected shape")
    return write_sds(
        path, regulation="un_ghs", language="en",
        h_codes=["H225", "H319"], p_codes=["P210", "P370+P378", "P410+P412"],
        overrides={"P370+P378": fire, "P410+P412": heat},
    )



def _optional_group_filled(path: Path) -> Path:
    """A sheet that keeps an optional group AND fills the slot inside it.

    P264+P265 reads "Wash hands [and…] thoroughly after handling." - a fill-in
    nested in an optional group. An author who keeps the group has to write a
    space before the value they supply, which the template does not contain.
    """
    official = texts("un_ghs", "en", ["P264+P265"])["P264+P265"]
    filled = official.replace("[and…]", "and other specified body parts")
    if filled == official:
        raise SystemExit("optional-fill-in fixture: the key text no longer has '[and…]'")
    return write_sds(
        path, regulation="un_ghs", language="en",
        h_codes=["H225", "H319"], p_codes=["P210", "P264+P265"],
        overrides={"P264+P265": filled},
    )



def _osha_terminator(path: Path) -> Path:
    """An OSHA sheet that ends its statements with a full stop.

    osha.gov prints Appendix C without closing punctuation. A sheet that writes
    the sentences normally has not changed the wording, so it must pass - and
    the fill-in it supplies must still be reported for review.
    """
    codes = ["P210", "P370+P378", "P501"]
    official = texts("us_osha", "en", codes)
    if any(official[c].endswith(".") for c in ("P370+P378", "P501")):
        raise SystemExit("osha terminator fixture: the key now has terminal punctuation")
    overrides = {
        "P370+P378": official["P370+P378"].replace("…", "appropriate extinguishing media") + ".",
        "P501": official["P501"].replace("…", "an approved waste disposal facility") + ".",
    }
    return write_sds(
        path, regulation="us_osha", language="en",
        h_codes=["H225", "H319"], p_codes=codes, overrides=overrides,
    )



def _odd_capitalisation(path: Path) -> Path:
    """A sheet whose wording is right but whose capitals are not.

    Authoring tools that substitute values mid-sentence produce things like
    "Take off Immediately" and "Rinse SKIN". The words are the official words,
    so this is not a wording failure - but it is not nothing either, and it
    must never pass silently.
    """
    code = "P303+P361+P353"
    official = texts("eu_clp", "en", [code])[code]
    odd = official.replace(" immediately", " Immediately").replace("Rinse skin", "Rinse SKIN")
    if odd == official:
        raise SystemExit("capitalisation fixture: the key text no longer has the expected shape")
    return write_sds(
        path, regulation="eu_clp", language="en",
        h_codes=["H225", "H319"], p_codes=["P210", code],
        overrides={code: odd},
    )



def _language_outside_the_regulation(path: Path) -> Path:
    """A Danish sheet issued against UN GHS.

    UN GHS is published in six languages and Danish is not one of them, but a
    company may perfectly well issue a UN GHS sheet in Danish. The document's
    Danish wording is taken from EU CLP, which publishes Danish officially -
    the point of the fixture is the language, not the wording.

    Detection used to be restricted to the regulation's own languages, so this
    document came back as English and every statement failed against the
    English key.
    """
    head = HEADINGS["da"]
    codes = ["H225", "H319"], ["P210", "P280"]
    official = {c: close_open_options(t)
                for c, t in texts("eu_clp", "da", codes[0] + codes[1]).items()}

    sheet = Sheet(path)
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Udarbejdet efter UN Globally Harmonized System (GHS Rev. 11)")
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line(f"{head['signal']}: {signal_text('eu_clp', 'da', True)}")
    sheet.blank()
    sheet.line(head["haz"], bold=True)
    for code in codes[0]:
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["prec"], bold=True)
    for code in codes[1]:
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Syntetisk komponent A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in codes[0]:
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path



def _newer_ghs_codes(path: Path) -> Path:
    """An EU CLP sheet citing P317-family codes, which CLP has not adopted.

    The statements are GHS Rev.8's own wording, read from the committed GHS
    index rather than typed out. A made-up code is included too, so the fixture
    covers both halves of C-15: ahead of the regulation, and not a code at all.
    """
    from lingua_oracle.keys import ghs_index

    newer = {}
    for code in ("P317", "P332+P317"):
        text = ghs_index.text_in(code, "GHS Rev.8")
        if not text:
            raise SystemExit(f"C-15 fixture: {code} is not in the GHS index")
        newer[code] = text

    head = HEADINGS["en"]
    official = texts("eu_clp", "en", ["H225", "H319", "P210"])
    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Classified under Regulation (EC) No 1272/2008 (CLP)")
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line(f"{head['signal']}: {signal_text('eu_clp', 'en', True)}")
    sheet.blank()
    sheet.line(head["haz"], bold=True)
    for code in ("H225", "H319"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["prec"], bold=True)
    sheet.line(f"P210 {official['P210']}")
    for code, text in newer.items():
        sheet.line(f"{code} {text}")
    sheet.line("P999 Consult the imaginary appendix before use.")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in ("H225", "H319"):
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path



def _newer_ghs_on_osha(path: Path) -> Path:
    """An OSHA sheet citing P317-family codes, against a knowingly partial key.

    The interesting case. us_osha's key does not hold every statement in
    Appendix C, so "missing from the key" cannot decide anything on its own:
    P243 is missing from the key and IS in Appendix C, while P317 is missing
    from the key and is nowhere in it. The first is our gap, the second is a
    sheet ahead of the regulation, and the fixture carries both.
    """
    from lingua_oracle.keys import ghs_index

    head = HEADINGS["en"]
    official = texts("us_osha", "en", ["H225", "H319", "P210"])
    newer = {}
    for code in ("P317", "P319", "P332+P317"):
        text = ghs_index.text_in(code, "GHS Rev.8")
        if not text:
            raise SystemExit(f"OSHA C-15 fixture: {code} is not in the GHS index")
        newer[code] = text
    # In Appendix C but not in our key: must stay "not checked", never C-15.
    p243 = ghs_index.text_in("P243", "GHS Rev.7")

    sheet = Sheet(path, structure=("us_osha", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Prepared under 29 CFR 1910.1200 (OSHA Hazard Communication)")
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line(f"{head['signal']}: {signal_text('us_osha', 'en', True)}")
    sheet.blank()
    sheet.line(head["haz"], bold=True)
    for code in ("H225", "H319"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["prec"], bold=True)
    sheet.line(f"P210 {official['P210']}")
    sheet.line(f"P243 {p243}")
    for code, text in newer.items():
        sheet.line(f"{code} {text}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in ("H225", "H319"):
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path



def _legend_after_statement(path: Path) -> Path:
    """A WHMIS sheet whose Section 16 puts a glossary right after a statement.

    Real sheets end Section 16 with an abbreviation legend, a footnote marker
    and a revision note. The statement must stop where it stops; swallowing the
    glossary makes it fail against wording it never claimed.
    """
    head = HEADINGS["en"]
    codes = ["H302", "H373"]
    official = texts("ca_whmis", "en", codes + ["P262", "P270"])

    sheet = Sheet(path, structure=("ca_whmis", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Prepared under the Hazardous Products Regulations (WHMIS 2015)")
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line(f"{head['signal']}: {signal_text('ca_whmis', 'en', False)}")
    sheet.blank()
    sheet.line(head["haz"], bold=True)
    for code in codes:
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["prec"], bold=True)
    for code in ("P262", "P270"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in codes:
        sheet.line(f"{code} {official[code]}")
    # The shapes that leaked into the statement above.
    sheet.line("Abbreviation legend: ACGIH = American Conference of Governmental")
    sheet.line("Industrial Hygienists; TWA = Time Weighted Average")
    sheet.line("* indicates a section revised since the previous issue")
    sheet.save()
    return path



def _conditional_slots(path: Path) -> Path:
    """A WHMIS sheet that leaves the "if known" parts of H373 out.

    H373 reads "May cause damage to organs (state all organs affected, if
    known) through prolonged or repeated exposure (state route of exposure if
    it is conclusively proven ...)". Both slots are conditional in the source's
    own words, so a sheet that omits them is correct. It also ends the sentence
    with a full stop, which the GHS tables do not print.
    """
    head = HEADINGS["en"]
    official = texts("ca_whmis", "en", ["H302", "H373", "P262", "P270"])
    bare = "May cause damage to organs through prolonged or repeated exposure."

    sheet = Sheet(path, structure=("ca_whmis", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Prepared under the Hazardous Products Regulations (WHMIS 2015)")
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line(f"{head['signal']}: {signal_text('ca_whmis', 'en', False)}")
    sheet.blank()
    sheet.line(head["haz"], bold=True)
    sheet.line(f"H302 {official['H302']}.")          # terminator the key lacks
    sheet.line(f"H373 {bare}")                       # both slots omitted
    sheet.blank()
    sheet.line(head["prec"], bold=True)
    for code in ("P262", "P270"):
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    sheet.line(f"H302 {official['H302']}.")
    sheet.line(f"H373 {bare}")
    sheet.save()
    return path



def _classification_table(path: Path) -> Path:
    """A sheet whose Section 2 lists codes beside their hazard class.

    Real sheets lay the classification out as a table, so the code lands on one
    line and the CLASS on the next - "EUH018 / Supplemental" - while the
    statements table a few lines down has the code and its actual wording. The
    class is not a statement, and attaching it reported correct sheets as
    wrong.
    """
    head = HEADINGS["en"]
    codes = ["H225", "H319", "H336", "EUH018", "EUH066"]
    official = texts("eu_clp", "en", codes + ["P210"])

    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Classified under Regulation (EC) No 1272/2008 (CLP)")
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Classification")
    # The classification table: code, then its class, one per line.
    sheet.line("H225")
    sheet.line("Flam. Liq. 2")
    sheet.line("H319")
    sheet.line("Eye Irrit. 2")
    sheet.line("EUH018")
    sheet.line("Supplemental")
    sheet.line("EUH066")
    sheet.line("Supplemental")
    # One row whose class appears under no other code, so the repeated-value
    # rule cannot help and only the plausibility check rejects it.
    sheet.line("H336")
    sheet.line("STOT SE 3")
    sheet.blank()
    # The statements table: code, then its wording, one per line.
    sheet.line(head["haz"], bold=True)
    for code in codes:
        sheet.line(code)
        sheet.line(official[code])
    sheet.blank()
    sheet.line(head["prec"], bold=True)
    sheet.line("P210")
    sheet.line(official["P210"])
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in codes:
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path



def _unfilled_blanks(path: Path) -> Path:
    """A sheet issued with its placeholders still in it.

    P501 ends in a blank for the disposal route and P280 in a slash list with a
    trailing one. Both are correct wording with something missing, which is a
    different thing from wording that disagrees - and the card has to say what
    goes in the blank rather than show the same sentence twice.
    """
    head = HEADINGS["en"]
    codes = ["H225", "H319"]
    official = texts("us_osha", "en", codes + ["P210", "P280", "P501"])

    sheet = Sheet(path, structure=("us_osha", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Prepared under 29 CFR 1910.1200 (OSHA Hazard Communication)")
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line(f"{head['signal']}: {signal_text('us_osha', 'en', True)}")
    sheet.blank()
    sheet.line(head["haz"], bold=True)
    for code in codes:
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["prec"], bold=True)
    sheet.line(f"P210 {official['P210']}")
    # Both printed exactly as the official text has them: blanks and all.
    sheet.line(f"P280 {official['P280']}")
    sheet.line(f"P501 {official['P501']}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    for code in codes:
        sheet.line(f"{code} {official[code]}")
    sheet.save()
    return path



def _out_of_scope(path: Path) -> Path:
    """An OSHA sheet carrying codes OSHA does not cover.

    H303 and P273 are GHS codes outside HazCom's scope - acute toxicity
    Category 5 and environmental hazards. A sheet may carry them as extra
    information, and correct GHS wording is not something to report. Wording
    that does NOT match GHS still is, which is what P273 is here for.
    """
    from lingua_oracle.keys import ghs_index

    head = HEADINGS["en"]
    official = texts("us_osha", "en", ["H225", "P210"])
    h303 = ghs_index.text_in("H303", "GHS Rev.7")
    p273 = ghs_index.text_in("P273", "GHS Rev.7")
    if not h303 or not p273:
        raise SystemExit("out-of-scope fixture: H303/P273 missing from the GHS index")

    sheet = Sheet(path, structure=("us_osha", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Prepared under 29 CFR 1910.1200 (OSHA Hazard Communication)")
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line(f"{head['signal']}: {signal_text('us_osha', 'en', True)}")
    sheet.blank()
    sheet.line(head["haz"], bold=True)
    sheet.line(f"H225 {official['H225']}")
    sheet.line(f"H303 {h303}")                       # correct GHS wording
    sheet.blank()
    sheet.line(head["prec"], bold=True)
    sheet.line(f"P210 {official['P210']}")
    sheet.line("P273 Avoid release into the environment.")   # GHS says "to the"
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    sheet.line(f"H225 {official['H225']}")
    sheet.save()
    return path



def _only_says_ghs(path: Path) -> Path:
    """A sheet that names no regulation, from an address that suggests one.

    "GHS Classification" is what a great many supplier sheets say and it
    identifies nothing. The address and telephone number place the supplier in
    Australia, which is somewhere to start - not an answer.
    """
    from lingua_oracle.keys import ghs_index

    head = HEADINGS["en"]
    h225 = ghs_index.text_in("H225", "GHS Rev.7")
    h319 = ghs_index.text_in("H319", "GHS Rev.7")

    sheet = Sheet(path)
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line("Nonexistent Chemicals Pty Ltd")
    sheet.line("Level 1, 11 Imaginary Road, MACQUARIE PARK NSW 2113, AUSTRALIA")
    sheet.line("Telephone: +61 1800 000 000")
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("GHS Classification")
    sheet.line(f"{head['signal']}: Danger")
    sheet.blank()
    sheet.line(head["haz"], bold=True)
    sheet.line(f"H225 {h225}")
    sheet.line(f"H319 {h319}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.save()
    return path


def _negative_declaration(path: Path) -> Path:
    """An unclassified sheet that says it has no signal word and no statements.

    Pattern found on a real document: an SDS for a non-hazardous product states
    "No hazard pictogram, no signal word, no hazard statement(s), no
    precautionary statement(s) required." The signal-word reader matched the
    words "signal word" and took the rest of the sentence as the value, turning a
    declaration that there is NO signal word into a claim that there is one.
    """
    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.blank()
    sheet.line(HEADINGS["en"]["2"], bold=True, size=11)
    sheet.line("Classification: Not a hazardous substance or mixture according to "
               "Regulation (EC) No 1272/2008.")
    sheet.line("No hazard pictogram, no signal word, no hazard statement(s), "
               "no precautionary statement(s) required.")
    sheet.blank()
    sheet.line(HEADINGS["en"]["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(HEADINGS["en"]["16"], bold=True, size=11)
    sheet.line("Full text of hazard statements: none assigned.")
    sheet.save()
    return path


def _reach_registration_number(path: Path) -> Path:
    """A sheet carrying a REACH registration number ending in XXXX.

    Pattern found on a real document: REACH registration numbers are printed as
    01-2119485491-33-XXXX, where the trailing XXXX is the standard
    company-specific suffix, not an unfilled placeholder.
    """
    en = texts("eu_clp", "en", EU_H + EU_P)
    sheet = Sheet(path, structure=("eu_clp", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line("REACH registration number: 01-2119485491-33-XXXX")
    sheet.blank()
    sheet.line(HEADINGS["en"]["2"], bold=True, size=11)
    sheet.line(f"Signal word: {signal_text('eu_clp', 'en')}")
    for code in EU_H:
        sheet.line(f"{code} {en[code]}")
    for code in EU_P:
        sheet.line(f"{code} {en[code]}")
    sheet.blank()
    sheet.line(HEADINGS["en"]["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.line("Registration number 01-2119485491-33-XXXX")
    sheet.line("Classification: " + ", ".join(EU_H))
    sheet.blank()
    sheet.line(HEADINGS["en"]["16"], bold=True, size=11)
    for code in EU_H:
        sheet.line(f"{code} {en[code]}")
    sheet.save()
    return path


def _whmis_bilingual(path: Path) -> Path:
    """A WHMIS sheet carrying both required languages, in WHMIS's own wording.

    WHMIS statements are GHS Rev.7 statements, which differ from EU CLP's, so the
    text has to come from the WHMIS key or the sheet would fail its own check.
    Each heading is printed in both languages, as Schedule 1 gives them.
    """
    en = texts("ca_whmis", "en", EU_H + EU_P)
    fr = texts("ca_whmis", "fr", EU_H + EU_P)
    two = [f"Signal word: {signal_text('ca_whmis','en')}"]
    two += [f"{code} {en[code]}" for code in EU_H + EU_P]
    two += ["", f"Mention d'avertissement: {signal_text('ca_whmis','fr')}"]
    two += [f"{code} {fr[code]}" for code in EU_H + EU_P]
    three = ["Synthetic component A  CAS 000-00-0  30-60%",
             "Classification: " + ", ".join(EU_H)]
    sixteen = [line for code in EU_H for line in (f"{code} {en[code]}", f"{code} {fr[code]}")]
    one = [f"Product name: {PRODUCT}", SUPPLIER,
           "Hazardous Products Regulations (SOR/2015-17) - WHMIS"]
    return structured_sheet(path, regulation="ca_whmis", language="en+fr",
                            bodies={"1": one, "2": two, "3": three, "16": sixteen})


def _whmis_english_only(path: Path) -> Path:
    en = texts("ca_whmis", "en", EU_H + EU_P)
    sheet = Sheet(path, structure=("ca_whmis", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line("Hazardous Products Regulations (SOR/2015-17) - WHMIS", size=8)
    sheet.blank()
    sheet.line(HEADINGS["en"]["2"], bold=True, size=11)
    sheet.line(f"Signal word: {signal_text('ca_whmis','en')}")
    for code in EU_H + EU_P:
        sheet.line(f"{code} {en[code]}")
    sheet.blank()
    sheet.line(HEADINGS["en"]["16"], bold=True, size=11)
    for code in EU_H:
        sheet.line(f"{code} {en[code]}")
    sheet.save()
    return path


def _label_mismatch(path: Path) -> Path:
    """Section 2 and a label block that disagree about which codes apply."""
    da = texts("eu_clp", "da", EU_H + EU_P)
    sheet = Sheet(path)
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.blank()
    sheet.line(HEADINGS["da"]["2"], bold=True, size=11)
    sheet.line(f"Signalord: {signal_text('eu_clp','da')}")
    for code in EU_H:
        sheet.line(f"{code} {da[code]}")
    sheet.blank()
    sheet.line(HEADINGS["da"]["16"], bold=True, size=11)
    for code in EU_H:
        sheet.line(f"{code} {da[code]}")
    # The label lives on its own page with no numbered heading.
    sheet.page_break()
    sheet.line("ETIKET / LABEL", bold=True, size=12)
    sheet.line(f"Signalord: {signal_text('eu_clp','da')}")
    for code in ["H225", "H319"]:  # H336 is missing from the label
        sheet.line(f"{code} {da[code]}")
    sheet.save()
    return path


def _euh_on_osha(path: Path) -> Path:
    key = load_key("us_osha", "en")
    by_code = key.by_code() if key else {}
    codes = [c for c in ("H228", "H240") if c in by_code]
    sheet = Sheet(path, structure=("us_osha", "en"))
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line("Prepared under 29 CFR 1910.1200 (Hazard Communication).", size=8)
    sheet.blank()
    sheet.line(HEADINGS["en"]["2"], bold=True, size=11)
    sheet.line(f"Signal word: {by_code['SIGNAL_DANGER'].text}")
    for code in codes:
        sheet.line(f"{code} {by_code[code].text}")
    # An EU-only supplemental statement that does not belong on an OSHA sheet.
    sheet.line(f"EUH066 {texts('eu_clp','en',['EUH066'])['EUH066']}")
    sheet.blank()
    sheet.line(HEADINGS["en"]["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.line("Classification: " + ", ".join(codes))
    sheet.blank()
    sheet.line(HEADINGS["en"]["16"], bold=True, size=11)
    for code in codes:
        sheet.line(f"{code} {by_code[code].text}")
    sheet.save()
    return path


if __name__ == "__main__":
    for name, path in sorted(build_all().items()):
        print(f"{name:28s} {path}")
