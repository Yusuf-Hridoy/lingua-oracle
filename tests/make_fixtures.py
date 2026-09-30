"""Generate the synthetic PDFs the test suite runs against.

Everything here is invented: the products, companies and CAS numbers are fake.
The only real text is the official regulatory wording, which is pulled from the
answer keys rather than typed out, so a fixture can never drift from the key.

Run directly to regenerate:  uv run python tests/make_fixtures.py
"""

from __future__ import annotations

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

    def __init__(self, path: Path):
        self.canvas = canvas.Canvas(str(path), pagesize=A4)
        self.y = TOP
        self.canvas.setFont("Helvetica", 9)

    def line(self, text: str = "", *, bold: bool = False, size: int = 9) -> None:
        if self.y < 60:
            self.canvas.showPage()
            self.y = TOP
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

    def blank(self, n: int = 1) -> None:
        self.y -= LINE * n

    def page_break(self) -> None:
        self.canvas.showPage()
        self.y = TOP

    def save(self) -> None:
        self.canvas.save()


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
) -> Path:
    """Write a minimal but realistic three-section SDS."""
    head = HEADINGS[language]
    supplemental = supplemental or []
    overrides = overrides or {}
    omit_from_s16 = omit_from_s16 or set()
    all_codes = h_codes + p_codes + supplemental
    official = texts(regulation, language, all_codes)
    official.update({k: v for k, v in overrides.items() if k in official})

    sheet = Sheet(path)
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.blank()

    sheet.line(head["2"], bold=True, size=11)
    sheet.line(f"{head['signal']}: {signal_override or signal_text(regulation, language, danger)}")
    sheet.blank()
    sheet.line(head["haz"], bold=True)
    for code in h_codes + supplemental:
        sheet.line(f"{code} {official[code]}")
    sheet.blank()
    sheet.line(head["prec"], bold=True)
    for code in p_codes:
        sheet.line(f"{code} {official[code]}")
    for extra in extra_lines_s2 or []:
        sheet.line(extra)
    sheet.blank()

    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.line("Classification: " + ", ".join(h_codes))
    sheet.blank()

    if include_s16:
        sheet.line(head["16"], bold=True, size=11)
        for code in h_codes + supplemental:
            if code in omit_from_s16:
                continue
            sheet.line(f"{code} {official[code]}")
        for extra in extra_lines_s16 or []:
            sheet.line(extra)
    sheet.save()
    return path


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

    add("defect_b08_missing_s16", write_sds(
        FIXTURES / "defect_b08_missing_s16.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P, omit_from_s16={"H336"}))

    add("defect_b09_label", _label_mismatch(FIXTURES / "defect_b09_label.pdf"))

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
    add("defect_c15_newer_ghs", _newer_ghs_codes(
        FIXTURES / "defect_c15_newer_ghs.pdf"))
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

    # C-02: the same code written two different ways.
    add("defect_c02_inconsistent", write_sds(
        FIXTURES / "defect_c02_inconsistent.pdf", regulation="eu_clp", language="da",
        h_codes=EU_H, p_codes=EU_P,
        extra_lines_s16=[f"H336 {texts('eu_clp','da',['H336'])['H336'].rstrip('.')} i hovedet."]))

    return built



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
    official = texts("eu_clp", "da", codes[0] + codes[1])

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
    sheet = Sheet(path)
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


def _negative_declaration(path: Path) -> Path:
    """An unclassified sheet that says it has no signal word and no statements.

    Pattern found on a real document: an SDS for a non-hazardous product states
    "No hazard pictogram, no signal word, no hazard statement(s), no
    precautionary statement(s) required." The signal-word reader matched the
    words "signal word" and took the rest of the sentence as the value, turning a
    declaration that there is NO signal word into a claim that there is one.
    """
    sheet = Sheet(path)
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
    sheet = Sheet(path)
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
    """
    en = texts("ca_whmis", "en", EU_H + EU_P)
    fr = texts("ca_whmis", "fr", EU_H + EU_P)
    sheet = Sheet(path)
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line("Hazardous Products Regulations (SOR/2015-17) - WHMIS", size=8)
    sheet.blank()
    sheet.line(HEADINGS["en"]["2"], bold=True, size=11)
    sheet.line(f"Signal word: {signal_text('ca_whmis','en')}")
    for code in EU_H:
        sheet.line(f"{code} {en[code]}")
    for code in EU_P:
        sheet.line(f"{code} {en[code]}")
    sheet.blank()
    sheet.line(HEADINGS["fr"]["2"], bold=True, size=11)
    sheet.line(f"Mention d'avertissement: {signal_text('ca_whmis','fr')}")
    for code in EU_H:
        sheet.line(f"{code} {fr[code]}")
    for code in EU_P:
        sheet.line(f"{code} {fr[code]}")
    sheet.blank()
    sheet.line(HEADINGS["en"]["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.line("Classification: " + ", ".join(EU_H))
    sheet.blank()
    sheet.line(HEADINGS["en"]["16"], bold=True, size=11)
    for code in EU_H:
        sheet.line(f"{code} {en[code]}")
        sheet.line(f"{code} {fr[code]}")
    sheet.save()
    return path


def _whmis_english_only(path: Path) -> Path:
    en = texts("ca_whmis", "en", EU_H + EU_P)
    sheet = Sheet(path)
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
    sheet = Sheet(path)
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
