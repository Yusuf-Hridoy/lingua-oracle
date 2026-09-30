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


def test_the_licence_is_scoped_to_the_regulation_that_needs_it():
    """Only a regulation whose own text lacks the terminator gets the licence."""
    from lingua_oracle.registry import load_registry

    registry = load_registry()
    relaxed = {k for k, r in registry.regulations.items()
               if r.statements_lack_terminal_punctuation}
    assert relaxed == {"us_osha"}, relaxed


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


def test_a_language_with_no_key_is_unverified_not_failed():
    """Tier C says "not checked". It must never say "wrong"."""
    report = check_pdf(pdf("pattern_language_outside_regulation"))
    fails = [f for f in report.findings
             if f.severity is Severity.FAIL and not f.unverified]
    assert fails == [], [f"{f.check_id} {f.code}: {f.message}" for f in fails]
    assert any(f.unverified for f in report.findings), (
        "nothing was reported as unverified, so the absent key went unnoticed"
    )


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
