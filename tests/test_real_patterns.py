"""Patterns found on real documents, reproduced with fictional data.

Each test here pins a false alarm that a real SDS produced during Phase 1.5
validation. The documents themselves are company data and cannot be committed,
so every pattern is rebuilt as a synthetic fixture with invented product data.

Findings are described in docs/validation-findings.md.
"""

from __future__ import annotations

import pytest

from lingua_oracle.checks.a01_signal_word import _NEGATIVE_RE, _candidates
from lingua_oracle.models import Severity
from lingua_oracle.pipeline import check_pdf
from tests.conftest import pdf

# -- finding #2: a negative declaration read as a signal word -----------------


def test_negative_declaration_produces_no_findings():
    """"No ... signal word ... required" declares the absence of one."""
    report = check_pdf(pdf("pattern_negative_declaration"), "eu_clp")
    failures = [f for f in report.findings
                if f.severity is Severity.FAIL and not f.unverified]
    assert failures == [], [f"{f.check_id}: {f.message}" for f in failures]


@pytest.mark.parametrize(
    "line",
    [
        "No hazard pictogram, no signal word, no hazard statement(s), "
        "no precautionary statement(s) required.",
        "Signal word: None assigned",
        "Not classified according to Regulation (EC) No 1272/2008",
        "Not a hazardous substance or mixture.",
        "Ingen signalord",
        "Kein Signalwort",
        "Pas de mention d'avertissement",
        "Sin palabra de advertencia",
    ],
)
def test_negative_phrases_are_recognised(line):
    assert _NEGATIVE_RE.search(line), f"should read as a negative declaration: {line}"


@pytest.mark.parametrize(
    "line",
    ["Signal word: Danger", "Signalord: Fare", "Signalwort: Achtung",
     "Mention d'avertissement: Attention"],
)
def test_real_signal_word_declarations_are_not_swallowed(line):
    assert not _NEGATIVE_RE.search(line), f"this states a signal word: {line}"


def test_signal_word_capture_stops_at_the_value():
    """The capture must take the word, not the rest of the sentence."""
    class _Line:
        def __init__(self, text): self.text, self.page = text, 1

    class _Ctx:
        class document:  # noqa: N801
            lines = [_Line("Signal word: Danger, and other prose follows here")]

    values = [v for v, _page in _candidates(_Ctx())]
    assert values == ["Danger"]


def test_a01_still_catches_a_wrong_signal_word():
    """The fix must not blunt the check it protects."""
    report = check_pdf(pdf("defect_a01_signal"), "eu_clp")
    fired = {f.check_id for f in report.findings if f.severity is Severity.FAIL}
    assert "A-01" in fired


# -- finding #3: XXXX in a REACH registration number --------------------------


def test_reach_registration_number_is_not_a_placeholder():
    """01-2119485491-33-XXXX is the published form of the number."""
    report = check_pdf(pdf("pattern_reach_registration"), "eu_clp")
    failures = [f for f in report.findings
                if f.severity is Severity.FAIL and not f.unverified]
    assert failures == [], [f"{f.check_id}: {f.message}" for f in failures]


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Registration number 01-2119485491-33-XXXX", False),
        ("REACH No.: 01-2119471843-32-XXXX", False),
        ("01-2119485491-33-0012", False),          # a filled suffix, also fine
        ("Supplier: XXXX", True),                  # a real unfilled placeholder
        ("Emergency telephone XXXXXX", True),
        ("Batch 12-345-XXXX", True),               # not a REACH number shape
    ],
)
def test_only_the_reach_shape_is_exempt(text, flagged):
    from lingua_oracle.checks.a06_placeholders import _COMPILED, _inside_reach_number

    hit = False
    for pattern, _label in _COMPILED:
        for m in pattern.finditer(text):
            if not _inside_reach_number(text, m.start(), m.end()):
                hit = True
    assert hit is flagged, f"{text!r} should {'be' if flagged else 'not be'} flagged"


def test_a06_still_catches_a_real_placeholder():
    report = check_pdf(pdf("defect_a06_placeholder"), "eu_clp")
    fired = {f.check_id for f in report.findings if f.severity is Severity.FAIL}
    assert "A-06" in fired


# -- finding #4: a spacing-only difference reported as a wording defect --------


def test_spacing_only_difference_is_not_a_wording_defect():
    """Where the spaces fall is not something a regulation legislates."""
    report = check_pdf(pdf("pattern_spacing_variant"), "un_ghs")
    wording = [f for f in report.findings
               if f.check_id in ("A-02", "A-03", "A-04")
               and f.severity in (Severity.FAIL, Severity.WARN)
               and not f.unverified
               # The fixture deliberately leaves P370+P378's slot empty; that
               # warning is correct and belongs to the fill-in tests below.
               and "not filled in" not in f.message.lower()]
    assert wording == [], [f"{f.check_id} {f.code}: {f.message}" for f in wording]


def test_an_unfilled_ellipsis_is_still_reported():
    """A clean spacing pass must not swallow a fill-in the author never filled."""
    report = check_pdf(pdf("pattern_spacing_variant"), "un_ghs")
    fillin = [f for f in report.findings
              if f.code == "P370+P378" and "not filled in" in f.message.lower()]
    assert fillin, "the unfilled '…' in P370+P378 was reported nowhere"


@pytest.mark.parametrize(
    ("template", "found", "should_match"),
    [
        ("In case of fire: Use… to extinguish.",
         "In case of fire: Use … to extinguish.", True),
        ("Protect from sunlight. Do not expose to temperatures exceeding 50°C/122°F.",
         "Protect from sunlight. Do not expose to temperatures exceeding 50 °C/122°F.", True),
        # Spacing tolerance must not reach further than spacing.
        ("Do not breathe dust/fume/gas/mist/vapours/spray.",
         "Do not breathe dust/fume/gas/mist/vapors/spray.", False),
        ("Keep away from heat, hot surfaces, sparks.",
         "Keep away from heat, hot surface, sparks.", False),
        ("Wash … thoroughly after handling.",
         "Wash thoroughly after handling.", False),
        # French puts a space before ':'. That licence is for comparing editions
        # of a source, never for judging a document, so it must not match here.
        ("EN CAS DE CONTACT AVEC LA PEAU : Rincer.",
         "EN CAS DE CONTACT AVEC LA PEAU: Rincer.", "not-exact"),
    ],
)
def test_spacing_tolerance_stops_at_spacing(template, found, should_match):
    from lingua_oracle.match.template import MatchKind, match

    result = match(found, template)
    if should_match == "not-exact":
        assert result.kind is not MatchKind.EXACT
    else:
        assert result.matched is should_match


# -- finding #5: a fill-in nested inside an optional group ---------------------


def test_filled_optional_group_matches():
    """Keeping "[and…]" and supplying a value is correct use of the template."""
    report = check_pdf(pdf("pattern_optional_fillin"), "un_ghs")
    wording = [f for f in report.findings
               if f.check_id == "A-03" and f.severity is Severity.FAIL
               and not f.unverified]
    assert wording == [], [f"{f.code}: {f.message}" for f in wording]


def test_the_supplied_value_is_reported_for_review():
    report = check_pdf(pdf("pattern_optional_fillin"), "un_ghs")
    values = [f.message for f in report.findings
              if f.code == "P264+P265" and "filled in:" in f.message.lower()]
    assert values, "the value supplied for the optional fill-in was not reported"


@pytest.mark.parametrize(
    ("found", "should_match"),
    [
        ("Wash hands and other specified body parts thoroughly after handling. "
         "Do not touch eyes.", True),
        ("Wash hands and forearms thoroughly after handling. Do not touch eyes.", True),
        ("Wash hands thoroughly after handling. Do not touch eyes.", True),
        # Tolerating the space must not tolerate different wording.
        ("Wash hands thoroughly after handling. Do not touch nose.", False),
        ("Rinse hands thoroughly after handling. Do not touch eyes.", False),
    ],
)
def test_optional_group_tolerance_stops_at_the_space(found, should_match):
    from lingua_oracle.match.template import match

    template = "Wash hands [and…] thoroughly after handling. Do not touch eyes."
    assert match(found, template).matched is should_match


# -- finding #6: a closing full stop OSHA's own rendering omits ----------------


def test_osha_sheet_may_end_its_sentences():
    """osha.gov prints Appendix C without a closing full stop; sheets don't."""
    report = check_pdf(pdf("pattern_osha_terminator"), "us_osha")
    wording = [f for f in report.findings
               if f.check_id in ("A-02", "A-03") and not f.unverified
               and f.severity in (Severity.FAIL, Severity.WARN)]
    assert wording == [], [f"{f.check_id} {f.code}: {f.message}" for f in wording]


def test_the_licence_is_scoped_to_the_keys_that_need_it():
    """Only regulations whose own published text lacks the terminator.

    The four built from the GHS Annex 3 tables, which print statements without
    a closing full stop. EU CLP and GB CLP publish theirs with one, so they get
    no licence and a missing full stop there is still reported.
    """
    from lingua_oracle.registry import load_registry

    registry = load_registry()
    relaxed = {k for k, r in registry.regulations.items()
               if r.statements_lack_terminal_punctuation}
    assert relaxed == {"us_osha", "ca_whmis", "au_whs", "un_ghs"}, relaxed


@pytest.mark.parametrize(
    ("template", "found", "with_flag", "without_flag"),
    [
        # Supplying the terminator OSHA omits: fine, but only for OSHA.
        ("In case of fire: Use … to extinguish",
         "In case of fire: Use water spray to extinguish.", True, False),
        # Dropping a terminator the official text HAS is not licensed either way.
        ("Keep away from heat.", "Keep away from heat", False, False),
        # The licence covers the terminator, nothing else.
        ("Use non-sparking tools", "Use only non-sparking tools.", False, False),
    ],
)
def test_terminator_licence_is_one_way_and_narrow(template, found, with_flag, without_flag):
    from lingua_oracle.match.template import match

    assert match(found, template, optional_terminator=True).is_clean is with_flag
    assert match(found, template).is_clean is without_flag


# -- finding #7: capitalisation is a warning, never a pass and never a fail ----


def test_odd_capitalisation_warns():
    report = check_pdf(pdf("pattern_capitalisation"), "eu_clp")
    hits = [f for f in report.findings if f.code == "P303+P361+P353"]
    assert hits, "a capitalisation difference was passed over silently"
    assert all(f.severity is Severity.WARN for f in hits), [
        (f.severity.value, f.message) for f in hits
    ]
    assert any("capitalisation" in f.message for f in hits), [f.message for f in hits]


def test_odd_capitalisation_is_never_a_failure():
    report = check_pdf(pdf("pattern_capitalisation"), "eu_clp")
    fails = [f for f in report.findings
             if f.severity is Severity.FAIL and not f.unverified]
    assert fails == [], [f"{f.check_id} {f.code}: {f.message}" for f in fails]


def test_a01_still_reports_a_miscapitalised_signal_word():
    """A-01 stays case-sensitive: the signal word is a prescribed token."""
    from lingua_oracle.keys.store import load_key
    from lingua_oracle.match.template import match
    from lingua_oracle.models import SIGNAL_DANGER

    official = load_key("eu_clp", "en").by_code()[SIGNAL_DANGER].text
    result = match(official.lower(), official)
    assert result.matched and not result.is_clean, (
        "a lower-case signal word must still be reported"
    )


def test_a_capitalisation_match_cannot_be_clean():
    """Whatever route it takes, a case difference must not report as clean."""
    from lingua_oracle.match.template import match

    pairs = [
        ("IF ON SKIN (or hair): Take off immediately all contaminated clothing.",
         "IF ON SKIN (or hair): Take off Immediately all contaminated clothing."),
        ("Keep away from heat.", "keep away from heat."),
        ("Wash hands thoroughly after handling.", "WASH HANDS THOROUGHLY AFTER HANDLING."),
    ]
    for template, found in pairs:
        result = match(found, template)
        assert result.matched, f"{found!r} should still match {template!r}"
        assert not result.is_clean, f"{found!r} passed silently against {template!r}"


# -- finding #1: language detection restricted to the regulation's languages ---


def test_a_danish_sheet_against_un_ghs_is_read_as_danish():
    """UN GHS is not published in Danish; a Danish UN GHS sheet is still Danish."""
    report = check_pdf(pdf("pattern_language_outside_regulation"))
    assert report.regulation == "un_ghs"
    assert report.language == "da", (
        f"read as {report.language!r}; restricting detection to the regulation's "
        "own languages is what this fixture exists to prevent"
    )


def test_a_language_with_no_key_produces_no_failures():
    """UN GHS publishes no Danish, and the sheet must still come out clean.

    Every code here now resolves through tier B - EU CLP publishes Danish, and
    its English matches UN GHS's for these codes - which is the tier system
    doing its job. P280 only became borrowable once the key carried the 2019
    amendment; before that it was tier C.
    """
    report = check_pdf(pdf("pattern_language_outside_regulation"))
    fails = [f for f in report.findings
             if f.severity is Severity.FAIL and not f.unverified]
    assert fails == [], [f"{f.check_id} {f.code}: {f.message}" for f in fails]
    assert report.coverage.percent == 100.0
    assert all(v.status == "correct" for v in report.statements), [
        (v.code, v.status) for v in report.statements
    ]


def test_a_code_with_no_reference_is_unverified_not_failed():
    """Tier C says "not checked". It must never say "wrong"."""
    report = check_pdf(pdf("defect_c12_euh_on_osha"), "us_osha")
    unverified = [f for f in report.findings if f.unverified]
    assert unverified, "the absent key went unnoticed"
    assert all(f.severity is not Severity.FAIL for f in unverified)


def test_official_languages_only_break_a_tie():
    """They may choose between close readings; they may never exclude one."""
    from lingua_oracle.detect.language import detect_language

    danish = (
        "Brandfarlig væske og damp. Forårsager alvorlig øjenirritation. "
        "Holdes væk fra varme, varme overflader, gnister, åben ild og andre "
        "antændelseskilder. Rygning forbudt. Bær beskyttelseshandsker."
    )
    un_ghs_languages = ("ar", "zh", "en", "fr", "ru", "es")
    assert detect_language(danish, None, un_ghs_languages)[0] == "da"
    assert detect_language(danish, None, None)[0] == "da"
    # A flag still wins outright.
    assert detect_language(danish, "en", un_ghs_languages) == ("en", "flag")


# -- finding #10: a statement swallowed the glossary printed after it ----------


def test_a_statement_stops_where_it_stops():
    """Section 16 ends with a legend; the statement must not absorb it."""
    report = check_pdf(pdf("pattern_legend_after_statement"), "ca_whmis")
    wording = [f for f in report.findings
               if f.check_id in ("A-02", "A-03") and not f.unverified
               and f.severity in (Severity.FAIL, Severity.WARN)]
    assert wording == [], [f"{f.check_id} {f.code}: {f.found!r}" for f in wording]


def test_no_finding_quotes_the_glossary():
    report = check_pdf(pdf("pattern_legend_after_statement"), "ca_whmis")
    for f in report.findings:
        assert "ACGIH" not in (f.found or ""), f"{f.check_id} swallowed the legend"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("May cause damage to organs. ACGIH = American Conference",
         "May cause damage to organs."),
        ("May cause damage to organs. Abbreviation legend: ACGIH = x",
         "May cause damage to organs."),
        ("May cause damage to organs. * indicates a revised section",
         "May cause damage to organs."),
        ("May cause damage to organs. Prepared by: Regulatory Affairs",
         "May cause damage to organs."),
        # A statement that merely contains a capitalised lead-in is untouched.
        ("IF SWALLOWED: Rinse mouth. Do NOT induce vomiting.",
         "IF SWALLOWED: Rinse mouth. Do NOT induce vomiting."),
        ("IF IN EYES: Rinse cautiously with water. Continue rinsing.",
         "IF IN EYES: Rinse cautiously with water. Continue rinsing."),
    ],
)
def test_cut_at_new_item(text, expected):
    from lingua_oracle.extract.rejoin import cut_at_new_item

    assert cut_at_new_item(text) == expected


def test_the_cut_truncates_no_official_statement():
    """The guard that matters: 7500+ official texts, none shortened."""
    from lingua_oracle.extract.rejoin import cut_at_new_item
    from lingua_oracle.keys.store import iter_all_keys

    for key in iter_all_keys():
        for entry in key.entries:
            if entry.text:
                assert cut_at_new_item(entry.text) == entry.text, (
                    f"{key.regulation}/{key.language} {entry.code}"
                )


# -- finding #11: conditional slots, and a full stop the GHS tables omit -------


def test_conditional_slots_may_be_left_out():
    """H373's slots say "if known" and "if it is conclusively proven"."""
    report = check_pdf(pdf("pattern_conditional_slots"), "ca_whmis")
    wording = [f for f in report.findings
               if f.check_id in ("A-02", "A-03") and not f.unverified
               and f.severity in (Severity.FAIL, Severity.WARN)]
    assert wording == [], [f"{f.check_id} {f.code}: {f.message}" for f in wording]


def test_nothing_needs_a_person_when_nothing_was_filled_in():
    report = check_pdf(pdf("pattern_conditional_slots"), "ca_whmis")
    filled = [f for f in report.findings if "filled in" in f.message.lower()]
    assert filled == [], [f.message for f in filled]


def test_a_filled_conditional_slot_is_reported_for_review():
    from lingua_oracle.keys.store import load_key
    from lingua_oracle.match.template import match

    template = load_key("ca_whmis", "en").by_code()["H373"].text
    result = match(
        "May cause damage to organs (liver) through prolonged or repeated exposure.",
        template, optional_terminator=True,
    )
    assert result.matched and "(liver)" in result.fillins


@pytest.mark.parametrize("regulation", ["ca_whmis", "au_whs", "un_ghs", "eu_clp"])
def test_h373_passes_without_its_conditional_parts(regulation):
    from lingua_oracle.keys.store import load_key
    from lingua_oracle.match.template import match
    from lingua_oracle.registry import load_registry

    entry = load_key(regulation, "en").by_code()["H373"]
    loose = load_registry().get(regulation).statements_lack_terminal_punctuation
    result = match("May cause damage to organs through prolonged or repeated exposure.",
                   entry.text, optional_terminator=loose)
    assert result.is_clean, f"{regulation}: {result.kind} {result.message}"


def test_a_mandatory_slot_is_still_mandatory():
    """Only "if known" / "if it is conclusively proven" slots became optional."""
    from lingua_oracle.match.template import match

    template = "Contains <name of sensitising substance>. May produce an allergic reaction."
    assert not match("Contains. May produce an allergic reaction.", template).matched


# -- finding #12: a hazard class read as the statement beside it ---------------


def test_a_class_repeated_under_several_codes_is_not_a_statement():
    """"EUH018 / Supplemental / EUH066 / Supplemental" - the class, not wording.

    Found on a real EU sheet, which reported five "Wrong wording" cards quoting
    the word "Supplemental".
    """
    report = check_pdf(pdf("pattern_classification_table"), "eu_clp")
    by_code = {v.code: v for v in report.statements}
    for code in ("EUH018", "EUH066"):
        assert by_code[code].status == "correct", (
            f"{code}: {by_code[code].status} {by_code[code].found!r}"
        )
        assert "Supplemental" not in by_code[code].found


def test_no_finding_quotes_the_hazard_class():
    report = check_pdf(pdf("pattern_classification_table"), "eu_clp")
    for finding in report.findings:
        assert "Supplemental" not in (finding.found or ""), finding.message


def test_repeated_column_values_are_detected():
    from lingua_oracle.detect.codes import _repeated_column_values
    from lingua_oracle.extract.base import Line

    lines = [Line(text=t, page=1) for t in
             ["EUH018", "Supplemental", "EUH066", "Supplemental",
              "H225", "Highly flammable liquid and vapour"]]
    assert _repeated_column_values(lines) == {"Supplemental"}


# -- finding #13: a class that appears under only one code --------------------


def test_a_class_under_a_single_code_is_not_a_statement():
    """The repeated-value rule cannot see "H336 / STOT SE 3": one row only.

    A class shares no wording with the statement it classifies, so the text is
    only attached when it could plausibly be that code's statement.
    """
    report = check_pdf(pdf("pattern_classification_table"), "eu_clp")
    by_code = {v.code: v for v in report.statements}
    for code in ("H225", "H319", "H336", "EUH018", "EUH066"):
        assert by_code[code].status == "correct", (
            f"{code}: {by_code[code].status} {by_code[code].found!r}"
        )
    assert report.coverage.percent == 100.0


@pytest.mark.parametrize(
    ("text", "official", "attaches"),
    [
        # Hazard classes: no significant word in common with the statement.
        ("Supplemental", "In use may form flammable/explosive vapour-air mixture.", False),
        ("Flam. Liq. 2", "Highly flammable liquid and vapour.", False),
        ("Eye Irrit. 2", "Causes serious eye irritation.", False),
        ("STOT SE 3", "May cause drowsiness or dizziness.", False),
        # A real statement attaches, however it is spelled.
        ("Highly flammable liquid and vapour.", "Highly flammable liquid and vapour.", True),
        ("Highly Flammable liquid and vapor", "Highly flammable liquid and vapour.", True),
        # Wording that is WRONG must still attach, or it could never be caught.
        ("Ground/bond container and receiving equipment.",
         "Ground and bond container and receiving equipment.", True),
        ("Take precautionary measures against static discharge.",
         "Take action to prevent static discharges.", True),
    ],
)
def test_plausible_statement(text, official, attaches):
    from lingua_oracle.detect.codes import plausible_statement

    assert plausible_statement(text, [official]) is attaches


def test_with_nothing_on_file_the_text_is_kept():
    """Silence about a code we hold no wording for is worse than a difference."""
    from lingua_oracle.detect.codes import plausible_statement

    assert plausible_statement("Anything at all here", []) is True


def test_a_bare_reference_takes_its_verdict_from_another_occurrence():
    """Section 2 lists the class; Section 16 writes the statement out."""
    from lingua_oracle.detect.codes import extract_hits
    from lingua_oracle.extract.base import Line

    official = {"H225": ["Highly flammable liquid and vapour."]}
    lines = [Line(text=t, page=1) for t in
             ["H225", "Flam. Liq. 2", "H225", "Highly flammable liquid and vapour."]]
    hits = extract_hits(lines, official)
    assert [h.text for h in hits] == ["", "Highly flammable liquid and vapour."]


# -- finding #14: a class that shares its words with the statement -------------


def _clp_class_codes() -> list[str]:
    import json

    from lingua_oracle.registry import data_dir

    path = data_dir() / "hazard_classes" / "eu_clp.json"
    return json.loads(path.read_text(encoding="utf-8"))["codes"]


def test_the_class_list_comes_from_the_act():
    """Read from Annex VI Table 1.1 at build time, not typed from memory."""
    import json

    from lingua_oracle.registry import data_dir

    data = json.loads(
        (data_dir() / "hazard_classes" / "eu_clp.json").read_text(encoding="utf-8")
    )
    assert data["source"].startswith("02008R1272")
    assert len(data["codes"]) > 80
    for code in ("Skin Irrit. 2", "Aquatic Chronic 3", "Flam. Liq. 2",
                 "Acute Tox. 4", "STOT SE 3", "Skin Corr. 1B"):
        assert code in data["codes"], code


@pytest.mark.parametrize("code", _clp_class_codes())
def test_no_clp_class_code_is_taken_as_a_statement(code):
    """Every class in the act, against every statement we hold for any code."""
    from lingua_oracle.detect.codes import plausible_statement
    from lingua_oracle.keys.store import load_key

    key = load_key("eu_clp", "en")
    texts = [e.text for e in key.entries if e.text]
    assert not plausible_statement(code, texts), code


@pytest.mark.parametrize(
    "text",
    [
        # The four that passed the word-overlap guard, with the statement they
        # share vocabulary with.
        "Skin Irrit. 2", "Skin Sens. 1", "Aquatic Chronic 3", "Aquatic Acute 1",
        # Long-form GHS/OSHA classes ending in a category.
        "Skin corrosion/irritation Category 2",
        "Acute toxicity, oral Category 4",
        "Serious eye damage/eye irritation Category 1A",
        "Specific target organ toxicity, single exposure Category 3",
    ],
)
def test_a_hazard_class_is_never_a_statement(text):
    from lingua_oracle.detect.hazard_classes import is_hazard_class

    assert is_hazard_class(text), text


@pytest.mark.parametrize(
    "text",
    [
        "Causes skin irritation.",
        "May cause an allergic skin reaction.",
        "Harmful to aquatic life with long lasting effects.",
        "Very toxic to aquatic life.",
        "Highly flammable liquid and vapour.",
        "IF SWALLOWED: Rinse mouth. Do NOT induce vomiting.",
        "Ground/bond container and receiving equipment.",
        "May cause damage to organs through prolonged or repeated exposure.",
    ],
)
def test_a_statement_is_never_a_hazard_class(text):
    from lingua_oracle.detect.hazard_classes import is_hazard_class

    assert not is_hazard_class(text), text


def test_a_single_row_class_does_not_attach_but_the_statement_does():
    """The shape the guard exists for: one row, class beside the code."""
    from lingua_oracle.detect.codes import extract_hits
    from lingua_oracle.extract.base import Line
    from lingua_oracle.keys.store import load_key

    key = load_key("eu_clp", "en").by_code()
    official = {code: [key[code].text] for code in ("H315", "H317", "H412")}
    lines = [Line(text=t, page=1) for t in [
        "H315", "Skin Irrit. 2",
        "H317", "Skin Sens. 1",
        "H412", "Aquatic Chronic 3",
        "H315", key["H315"].text,
    ]]
    hits = extract_hits(lines, official)
    assert [h.text for h in hits] == ["", "", "", key["H315"].text]


# -- the stamp has to cover everything a fixture is built from -----------------


def test_the_fixture_stamp_covers_the_answer_keys(tmp_path, monkeypatch):
    """Fixtures quote the keys, so a key change has to rebuild them.

    Hashing only make_fixtures.py was not enough: amending P280 changed what a
    correct sheet says, the fixtures kept the old wording, and the suite passed
    against documents that no longer matched the law.
    """
    import json

    from tests import conftest

    before = conftest._inputs_digest()
    key_path = conftest.DATA / "answer_keys" / "au_whs" / "en.json"
    original = key_path.read_bytes()
    try:
        data = json.loads(original)
        data["entries"][0]["text"] += " "
        key_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        assert conftest._inputs_digest() != before, (
            "a changed answer key left the fixture digest unmoved"
        )
    finally:
        key_path.write_bytes(original)
    assert conftest._inputs_digest() == before


def test_the_stamp_also_covers_the_generator():
    from tests import conftest

    before = conftest._inputs_digest()
    original = conftest.MAKER.read_bytes()
    try:
        conftest.MAKER.write_bytes(original + b"\n# touched\n")
        assert conftest._inputs_digest() != before
    finally:
        conftest.MAKER.write_bytes(original)
    assert conftest._inputs_digest() == before


# -- a full stop the official German text does not have -----------------------


@pytest.mark.parametrize("fixture", ["pattern_de_no_terminator",
                                     "pattern_de_terminator"])
def test_a_german_sheet_is_never_failed_over_a_final_full_stop(fixture):
    """The two sheets differ by one character: the full stop after "tragen".

    The official German P280 stops without one - in Regulation (EU) 2019/521 as
    well as in the consolidation - so an author who writes the sentence out
    properly disagrees with the act. The key records that its own text is
    missing the stop, so the sheet is right and is marked correct.
    """
    report = check_pdf(pdf(fixture), "eu_clp")
    assert report.language == "de"
    verdict = next(s for s in report.statements if s.code == "P280")
    assert verdict.status == "correct", verdict.why
    assert not [f for f in report.findings
                if f.code == "P280" and f.severity == Severity.FAIL]


def test_the_sheet_that_adds_the_full_stop_says_why_it_passed():
    """Correct, but not silent: the allowance is named in the technical notes."""
    report = check_pdf(pdf("pattern_de_terminator"), "eu_clp")
    assert any("the official text omits the final full stop" in note
               and "the sheet's full stop is correct" in note
               for note in report.notes), report.notes


def test_the_note_is_only_made_where_the_allowance_was_used():
    report = check_pdf(pdf("pattern_de_no_terminator"), "eu_clp")
    assert not any("omits the final full stop" in note for note in report.notes)


def test_the_two_german_sheets_differ_only_in_that_full_stop():
    with_stop = check_pdf(pdf("pattern_de_terminator"), "eu_clp")
    without = check_pdf(pdf("pattern_de_no_terminator"), "eu_clp")
    assert {s.code for s in with_stop.statements} == {
        s.code for s in without.statements}
    assert all(s.status in {"correct", "check"} for s in with_stop.statements)


def test_the_allowance_is_tied_to_the_recorded_defect():
    """Nothing else moves: this is the one entry the act printed short."""
    from lingua_oracle.keys.store import load_key

    german = load_key("eu_clp", "de").by_code()
    assert any(d.startswith("terminator") for d in german["P280"].text_defects)
    assert german["P210"].text_defects == []


# -- a label with no safety data sheet behind it ------------------------------


def test_a_label_only_document_gets_no_section_2_comparison():
    """B-09 compares two halves of a document. Artwork has only one.

    Label artwork carries a block title - "Hazards Identification" - that reads
    exactly like Section 2's heading, so the comparison ran and reported every
    statement as missing from the other half.
    """
    report = check_pdf(pdf("pattern_label_only"), "us_osha")
    assert [f for f in report.findings if f.check_id == "B-09"] == []


def test_the_label_only_document_says_why_the_comparison_was_skipped():
    report = check_pdf(pdf("pattern_label_only"), "us_osha")
    assert any("Label only" in note and "not applicable" in note
               for note in report.notes), report.notes


def test_a_real_sheet_still_gets_its_label_comparison():
    """The skip must not switch the check off for documents that have both."""
    from lingua_oracle.checks.b09_label_vs_section2 import _SDS_SECTIONS_NEEDED

    assert _SDS_SECTIONS_NEEDED == 2
    report = check_pdf(pdf("clean_osha_en"), "us_osha")
    assert not any("Label only" in note for note in report.notes)


def test_the_label_comparison_reports_each_code_once():
    from lingua_oracle.checks.b09_label_vs_section2 import CHECK_ID

    report = check_pdf(pdf("clean_eu_en"), "eu_clp")
    seen = [(f.section, f.code) for f in report.findings if f.check_id == CHECK_ID]
    assert len(seen) == len(set(seen))


# -- OSHA's conditional route slot --------------------------------------------


@pytest.mark.parametrize("statement", [
    "Suspected of causing cancer",
    "Suspected of causing cancer.",
    "May cause cancer",
    "Suspected of causing cancer (inhalation)",
])
def test_an_osha_route_slot_may_be_left_out(statement):
    """OSHA explains the slot in a footnote: state the route *if no other route*
    causes the hazard. A label for a substance hazardous by several routes
    correctly omits it, and used to fail for doing so."""
    from lingua_oracle.keys.store import load_key
    from lingua_oracle.match.template import match

    code = "H350" if statement.startswith("May") else "H351"
    entry = load_key("us_osha", "en").by_code()[code]
    assert "if no other routes of exposure" in entry.text
    assert match(statement, entry.text, optional_terminator=True).matched


def test_the_slot_still_carries_what_an_author_writes_into_it():
    from lingua_oracle.keys.store import load_key
    from lingua_oracle.match.template import match

    entry = load_key("us_osha", "en").by_code()["H351"]
    assert match("Suspected of causing cancer (inhalation)",
                 entry.text).fillins == ["(inhalation)"]


def test_a_full_stop_is_never_reported_as_a_filled_in_value():
    from lingua_oracle.match.template import match

    result = match("Suspected of causing cancer.",
                   "Suspected of causing cancer <state route of exposure "
                   "if no other routes of exposure cause the hazard>")
    assert result.matched
    assert result.fillins == []


def test_every_osha_statement_with_a_slot_explains_it():
    """No entry may keep the bare "<…>" the footnote was meant to fill."""
    from lingua_oracle.keys.store import load_key

    for entry in load_key("us_osha", "en").entries:
        assert "<…>" not in entry.text, entry.code
        assert "<<" not in entry.text, entry.code


# -- the newer-GHS path reports an unfinished blank the same way --------------


def test_an_unfilled_bracket_is_a_placeholder_on_the_ghs_path_too():
    report = check_pdf(pdf("pattern_unfilled_bracket_ghs"), "us_osha")
    verdict = next(s for s in report.statements if s.code == "P264+P265")
    assert verdict.blank_unfilled is True
    assert verdict.fillins == []
    assert any(f.code == "P264+P265" and "Not filled in" in f.message
               for f in report.findings)
    assert not any("You filled in" in (f.message or "") for f in report.findings)


def test_the_ghs_wording_claim_is_only_made_when_it_is_true():
    exact = check_pdf(pdf("pattern_unfilled_bracket_ghs"), "us_osha")
    loose = check_pdf(pdf("pattern_ghs_case_difference"), "us_osha")
    exact_note = next(s.match_note for s in exact.statements
                      if s.code == "P264+P265")
    loose_note = next(s.match_note for s in loose.statements
                      if s.code == "P264+P265")
    assert exact_note.endswith("wording exactly")
    assert loose_note.endswith("except punctuation/capital letters")
