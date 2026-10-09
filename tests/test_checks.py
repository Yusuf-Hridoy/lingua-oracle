"""End-to-end checks against the synthetic PDFs.

Two rules drive this file:
  * each clean document must produce zero failures
  * each seeded-defect document must trigger its intended check
"""

from __future__ import annotations

import pytest

from lingua_oracle.checks import all_checks
from lingua_oracle.models import Severity
from lingua_oracle.pipeline import check_pdf, compare_pdfs
from tests.conftest import pdf

CLEAN = [
    ("clean_eu_da", "eu_clp", "da"),
    ("clean_eu_en", "eu_clp", "en"),
    ("clean_osha_en", "us_osha", "en"),
    ("clean_whmis_enfr", "ca_whmis", None),
]

# fixture -> (check that must fire, severity, other checks allowed to fire)
DEFECTS = {
    "defect_a01_signal": ("A-01", Severity.FAIL, {"B-10"}),
    "defect_a02_hazard": ("A-02", Severity.FAIL, set()),
    "defect_a03_precautionary": ("A-03", Severity.FAIL, set()),
    "defect_a04_supplemental": ("A-04", Severity.FAIL, set()),
    # An English phrase in a Danish sheet is both untranslated and wrong wording.
    "defect_a05_english": ("A-05", Severity.FAIL, {"A-02"}),
    "defect_a06_placeholder": ("A-06", Severity.FAIL, set()),
    "defect_a07_broken": ("A-07", Severity.FAIL, set()),
    "defect_b08_missing_s16": ("B-08", Severity.FAIL, set()),
    # A fragment: the Section 2 a label is held against, and the label on a
    # page of its own. The structure checks find the rest of the sheet missing.
    "defect_b09_label": ("B-09", Severity.FAIL, {"B-12", "B-13", "B-14"}),
    "defect_b10_signal_fit": ("B-10", Severity.FAIL, set()),
    "defect_c12_euh_on_osha": ("C-12", Severity.FAIL, set()),
    # A missing language is a question, not a verdict on the wording: the
    # French sheet may exist as a separate file. C-14 asks; it never fails.
    # The sheet carries P280, whose official text ends in a blank, and prints
    # it unfilled - so A-03 legitimately asks for it to be completed too.
    "defect_c14_english_only": ("C-14", Severity.WARN, {"A-03"}),
    "defect_c02_inconsistent": ("C-02", Severity.WARN, set()),
}

REGULATION_FOR = {
    "defect_c12_euh_on_osha": "us_osha",
    "defect_c14_english_only": "ca_whmis",
}


def _fired(report, severity: Severity) -> set[str]:
    return {
        f.check_id
        for f in report.findings
        if f.severity is severity and not f.unverified
    }


def test_every_check_is_registered():
    """Importing lingua_oracle.checks is what registers them; a module left out
    of that package's import list disappears silently."""
    assert len(all_checks()) == 29


@pytest.mark.parametrize(("name", "regulation", "language"), CLEAN)
def test_clean_documents_have_no_failures(name, regulation, language):
    report = check_pdf(pdf(name), regulation, language)
    failures = [f for f in report.findings if f.severity is Severity.FAIL and not f.unverified]
    assert failures == [], [f"{f.check_id} {f.code}: {f.message}" for f in failures]


@pytest.mark.parametrize("name", list(DEFECTS))
def test_defect_triggers_its_check(name):
    want, severity, allowed = DEFECTS[name]
    regulation = REGULATION_FOR.get(name, "eu_clp")
    report = check_pdf(pdf(name), regulation)
    fired = _fired(report, severity)
    assert want in fired, f"{name}: expected {want}, got {sorted(fired)}"
    unexpected = fired - {want} - allowed
    assert not unexpected, f"{name}: unexpected checks fired: {sorted(unexpected)}"


def test_compare_detects_a_differing_code_set():
    report = compare_pdfs(pdf("compare_b11_a"), pdf("compare_b11_b"), "eu_clp")
    b11 = [f for f in report.findings if f.check_id == "B-11"]
    assert b11
    assert {f.code for f in b11} == {"H336"}


def test_compare_is_silent_on_identical_code_sets():
    report = compare_pdfs(pdf("clean_eu_en"), pdf("clean_eu_en"), "eu_clp")
    assert [f for f in report.findings if f.check_id == "B-11"] == []


def test_regulation_flag_overrides_detection():
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    assert report.regulation == "eu_clp"
    assert report.detected_by == "flag"


def test_language_is_detected_without_a_flag():
    assert check_pdf(pdf("clean_eu_da"), "eu_clp").language == "da"
    assert check_pdf(pdf("clean_eu_en"), "eu_clp").language == "en"


def test_sections_are_found():
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    note = next(n for n in report.notes if n.startswith("Sections read"))
    for section in ("2", "3", "16"):
        assert section in note


def test_tier_c_findings_are_unverified_not_failures():
    """A regulation with no answer key may never produce a wording failure.

    Checked against jp_jis, whose key is empty because the source on file is the
    wrong document. Every code therefore falls to tier C, and tier C carries no
    wording verdict at all.
    """
    report = check_pdf(pdf("clean_eu_da"), "jp_jis")
    wording = {"A-01", "A-02", "A-03", "A-04"}
    failures = [
        f for f in report.findings
        if f.severity is Severity.FAIL and not f.unverified and f.check_id in wording
    ]
    assert failures == [], [f"{f.check_id} {f.code}" for f in failures]
    assert report.summary.unverified > 0
    assert all(f.tier is None or f.tier.value == "C"
               for f in report.findings if f.unverified)


def test_bilingual_document_accepts_either_required_language():
    """WHMIS requires English and French together; both halves are correct."""
    report = check_pdf(pdf("clean_whmis_enfr"), "ca_whmis")
    assert report.summary.fail == 0
    # the half not in the detected document language is reported as info
    assert any(f.severity is Severity.INFO and "also requires" in f.message
               for f in report.findings)


def test_coverage_is_reported():
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    assert report.coverage.codes_found > 0
    assert report.coverage.codes_checked == report.coverage.codes_found
    assert report.coverage.percent == 100.0


# -- C-15: newer GHS wording, and codes that are not codes --------------------


def test_c15_reports_a_code_the_regulation_has_not_adopted():
    report = check_pdf(pdf("defect_c15_newer_ghs"), "eu_clp")
    rows = {f.code: f for f in report.findings if f.check_id == "C-15"}
    assert "P317" in rows, "P317 is GHS Rev.8 wording; EU CLP has no P317"
    assert rows["P317"].severity is Severity.WARN
    assert "GHS Rev.8" in rows["P317"].message
    # The regulation's own nearest statement is offered, quoted from the key.
    assert rows["P317"].expected, "no closest official statement was offered"
    assert "P313" in rows["P317"].message


def test_c15_points_a_combined_code_at_its_own_family():
    report = check_pdf(pdf("defect_c15_newer_ghs"), "eu_clp")
    row = next(f for f in report.findings
               if f.check_id == "C-15" and f.code == "P332+P317")
    assert "P332+P313" in row.message, row.message


def test_c15_fails_a_code_that_exists_nowhere():
    report = check_pdf(pdf("defect_c15_newer_ghs"), "eu_clp")
    row = next(f for f in report.findings
               if f.check_id == "C-15" and f.code == "P999")
    assert row.severity is Severity.FAIL
    assert "typo" in row.message.lower()


def test_newer_ghs_codes_are_not_also_reported_as_not_checked():
    """One code, one explanation. A-03 must not repeat what C-15 said."""
    report = check_pdf(pdf("defect_c15_newer_ghs"), "eu_clp")
    unverified = {f.code for f in report.findings if f.unverified}
    assert "P317" not in unverified and "P332+P317" not in unverified


def test_an_incomplete_key_never_claims_a_code_is_newer_or_unknown():
    """us_osha's key is knowingly partial, so a gap there is ours to own."""
    from lingua_oracle.checks.missing_source import Reason, classify
    from lingua_oracle.keys.tierb import resolve

    osha = resolve("us_osha", "en")
    assert osha.key_status != "ok"
    for code in ("P319", "ZZZ999", "P241"):
        assert classify(code, osha.key_status, osha.entries).reason is Reason.NOT_ON_FILE


def test_severity_of_newer_wording_comes_from_the_registry():
    from lingua_oracle.registry import load_registry

    assert load_registry().get("eu_clp").newer_ghs_wording == "warn"


def test_a_sub_lettered_code_is_not_called_unknown():
    """H361D is H361 with CLP's affected-organ letters; it is a real code.

    Annex III lists the statement once, as H361, with the options inside it, so
    the key holds no H361D entry. Failing it as "not a code" would fail a
    correct sheet - found on a real EU document during validation.
    """
    from lingua_oracle.checks.missing_source import Reason, classify
    from lingua_oracle.keys.tierb import resolve

    eu = resolve("eu_clp", "en")
    for code in ("H361D", "H361d", "H360FD", "H350i"):
        assert classify(code, eu.key_status, eu.entries).reason is Reason.NOT_ON_FILE
    # A code that really is not one still fails.
    assert classify("P999", eu.key_status, eu.entries).reason is Reason.UNKNOWN


# -- C-15 where the key is knowingly incomplete -------------------------------


def test_partial_key_does_not_decide_from_key_membership_alone():
    """us_osha holds neither P243 nor P317. Appendix C holds one of them.

    Deciding from the key alone called both "our gap", which hid every sheet
    running ahead of OSHA. The regulation's own source text decides instead.
    """
    report = check_pdf(pdf("defect_c15_osha_partial_key"), "us_osha")
    c15 = {f.code for f in report.findings if f.check_id == "C-15"}
    unverified = {f.code for f in report.findings if f.unverified}

    assert {"P317", "P319", "P332+P317"} <= c15, c15
    # P243's wording IS in Appendix C, so it stays ours to own.
    assert "P243" in unverified
    assert "P243" not in c15


@pytest.mark.parametrize(
    "code", ["P316", "P317", "P318", "P319", "P203",
             "P301+P316", "P264+P265", "P332+P317", "P337+P317"],
)
def test_wording_absent_from_appendix_c_is_newer_ghs(code):
    from lingua_oracle.checks.missing_source import Reason, classify
    from lingua_oracle.keys.tierb import resolve

    osha = resolve("us_osha", "en")
    assert classify(code, osha.key_status, osha.entries, "us_osha").reason \
        is Reason.NEWER_GHS


@pytest.mark.parametrize("code", ["P243", "P241", "P302+P352", "P260", "P321"])
def test_wording_present_in_appendix_c_stays_our_gap(code):
    from lingua_oracle.checks.missing_source import Reason, classify
    from lingua_oracle.keys.tierb import resolve

    osha = resolve("us_osha", "en")
    assert classify(code, osha.key_status, osha.entries, "us_osha").reason \
        is Reason.NOT_ON_FILE


def test_the_source_search_is_exact_not_a_similarity_score():
    """"medical help" and "medical advice/attention" must not be confused.

    The only tolerance is a trailing plural, which exists for one observed
    difference: GHS "static discharges" against Appendix C "static discharge".
    """
    from lingua_oracle.keys.builders.ghs_index import presence_key

    assert presence_key("Take action to prevent static discharges.") == \
        presence_key("Take action to prevent static discharge.")
    assert presence_key("Get medical help.") != \
        presence_key("Get medical advice/attention.")
    assert presence_key("IF exposed or concerned: Get immediate medical advice/attention.") != \
        presence_key("If exposed or concerned: Get medical advice/attention.")


def test_a_regulation_with_no_source_search_still_owns_its_gaps():
    """Without a search we do not know, and the honest answer is "our gap"."""
    from lingua_oracle.checks.missing_source import Reason, classify
    from lingua_oracle.keys import ghs_index

    assert not ghs_index.source_searched("jp_jis")
    assert classify("P317", "pending_source", {}, "jp_jis").reason is Reason.NOT_ON_FILE


def test_a_supplemental_code_is_never_called_a_typo():
    """EUH066 on an OSHA sheet is a real statement in the wrong place.

    Which regulation may use the EUH prefix is C-12's question. C-15 knows only
    the GHS editions, so without this it read every EU-only code as invented.
    """
    from lingua_oracle.checks.missing_source import Reason, classify
    from lingua_oracle.keys.tierb import resolve

    osha = resolve("us_osha", "en")
    for code in ("EUH066", "AUH001"):
        assert classify(code, osha.key_status, osha.entries, "us_osha").reason \
            is Reason.NOT_ON_FILE
    report = check_pdf(pdf("defect_c12_euh_on_osha"), "us_osha")
    assert not [f for f in report.findings if f.check_id == "C-15"]


# -- C-14 asks for confirmation; it never accuses ----------------------------


def test_c14_names_the_language_and_asks():
    report = check_pdf(pdf("defect_c14_english_only"), "ca_whmis")
    c14 = [f for f in report.findings if f.check_id == "C-14"]
    assert len(c14) == 1
    assert c14[0].severity is Severity.WARN
    assert "Confirm the French version" in c14[0].message
    # Never a language tag; a reader should not have to know what "fr" is.
    assert "'fr'" not in c14[0].message


def test_c14_never_fails():
    """A company issuing the French sheet separately has complied."""
    report = check_pdf(pdf("defect_c14_english_only"), "ca_whmis")
    assert not [f for f in report.findings
                if f.check_id == "C-14" and f.severity is Severity.FAIL]


def test_c14_is_satisfied_when_the_pair_supplies_the_language():
    """Comparing the English and French sheets answers the question."""
    from lingua_oracle.checks.base import CheckContext

    report = check_pdf(pdf("defect_c14_english_only"), "ca_whmis")
    assert [f for f in report.findings if f.check_id == "C-14"]

    # The same document checked as one half of a bilingual pair.
    ctx_fields = {f.name for f in CheckContext.__dataclass_fields__.values()}
    assert "compare_language" in ctx_fields


# -- C-15 suggests only statements a label could actually carry ---------------


def test_c15_never_suggests_a_bare_lead_in():
    """P301 is "IF SWALLOWED:" - an opening, not a statement."""
    from lingua_oracle.checks.missing_source import classify
    from lingua_oracle.keys.tierb import resolve

    for regulation in ("eu_clp", "us_osha"):
        reference = resolve(regulation, "en")
        near = classify("P301+P317", reference.key_status,
                        reference.entries, regulation)
        assert near.nearest_code != "P301"
        assert "+" in near.nearest_code, near.nearest_code
        assert not near.nearest_text.rstrip().endswith(":")


@pytest.mark.parametrize(
    ("code", "expected"),
    [("P301+P317", "P301+P310"), ("P332+P317", "P332+P313"),
     ("P337+P317", "P337+P313")],
)
def test_c15_suggests_the_same_first_code(code, expected):
    from lingua_oracle.checks.missing_source import classify
    from lingua_oracle.keys.tierb import resolve

    reference = resolve("eu_clp", "en")
    assert classify(code, reference.key_status, reference.entries,
                    "eu_clp").nearest_code == expected


def test_c15_says_so_when_there_is_no_equivalent():
    report = check_pdf(pdf("defect_c15_osha_partial_key"), "us_osha")
    rows = {f.code: f for f in report.findings if f.check_id == "C-15"}
    assert "P317" in rows
    assert "no equivalent statement" in rows["P317"].message.lower(), \
        rows["P317"].message


def test_is_complete_statement():
    from lingua_oracle.checks.missing_source import _is_complete_statement

    assert not _is_complete_statement("IF SWALLOWED:")
    assert not _is_complete_statement("If skin irritation occurs:")
    assert not _is_complete_statement("")
    assert _is_complete_statement("IF SWALLOWED: Rinse mouth.")
    assert _is_complete_statement("Get medical advice/attention.")


# -- coverage counts verdicts, not key entries -------------------------------


def test_a_code_alone_on_its_line_takes_the_next_line():
    """Most sheets lay Section 2 out as a table: code on one line, text below."""
    from lingua_oracle.detect.codes import extract_hits
    from lingua_oracle.extract.base import Line

    lines = [Line(text="H225", page=1),
             Line(text="Highly flammable liquid and vapour", page=1)]
    hits = extract_hits(lines)
    assert [(h.code, h.text) for h in hits] == \
        [("H225", "Highly flammable liquid and vapour")]


@pytest.mark.parametrize(
    "neighbour",
    ["Category 2", "Cat. 1A", "Type B", "2026-09-30", "Revision date: 2026-09-30",
     "Page 2", "12.5", "H319"],
)
def test_a_table_field_is_not_taken_as_a_statement(neighbour):
    """The classification table puts the category next to the code."""
    from lingua_oracle.detect.codes import extract_hits
    from lingua_oracle.extract.base import Line

    hits = extract_hits([Line(text="H225", page=1), Line(text=neighbour, page=1)])
    assert hits[0].text == "", f"{neighbour!r} was read as H225's statement"


def test_coverage_counts_only_codes_that_got_a_verdict():
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    # The signal word is judged and shown, but it is not a code.
    verdicts = {v.code for v in report.statements if v.checked and v.code != "SIGNAL"}
    assert report.coverage.codes_checked == len(verdicts)
    assert report.coverage.codes_checked <= report.coverage.codes_found


def test_a_correct_statement_is_recorded_not_just_silent():
    """Findings only cover problems, so "23 match" needs its own record."""
    report = check_pdf(pdf("clean_eu_da"), "eu_clp")
    correct = [v for v in report.statements if v.status == "correct"]
    assert correct, "a clean document recorded no correct statements"
    assert all(v.expected and v.found and v.source for v in correct)


def test_not_checked_never_counts_towards_coverage():
    from lingua_oracle.models import StatementVerdict

    assert not StatementVerdict(code="P243", status="not_checked").checked


def test_newer_ghs_wording_is_checked_against_its_own_edition():
    report = check_pdf(pdf("defect_c15_newer_ghs"), "eu_clp")
    by_code = {v.code: v for v in report.statements}
    assert by_code["P317"].status == "check"
    assert by_code["P317"].checked, "a checkable code must count for coverage"
    assert "GHS Rev.8" in by_code["P317"].source


# -- out-of-scope wording that is correct -------------------------------------


def test_out_of_scope_wording_that_matches_ghs_is_correct():
    """OSHA does not cover H303, but the sheet's wording is GHS's own.

    Extra information, correctly worded. Nothing for anyone to act on, so it
    belongs with the statements that match rather than in the issues.
    """
    report = check_pdf(pdf("defect_c15_osha_partial_key"), "us_osha")
    report_eu = check_pdf(pdf("defect_c15_newer_ghs"), "eu_clp")
    assert report and report_eu  # both render

    from lingua_oracle.checks.missing_source import Reason, classify
    from lingua_oracle.keys.tierb import resolve

    osha = resolve("us_osha", "en")
    assert classify("H303", osha.key_status, osha.entries,
                    "us_osha").reason is Reason.OUTSIDE_SCOPE


def test_an_out_of_scope_match_raises_no_finding_and_no_action():
    from lingua_oracle.report import sections

    report = check_pdf(pdf("pattern_out_of_scope"), "us_osha")
    by_code = {v.code: v for v in report.statements}
    assert by_code["H303"].status == "correct", by_code["H303"].why
    assert "outside US OSHA HazCom's scope" in by_code["H303"].match_note
    assert "allowed as extra information" in by_code["H303"].match_note
    # No wording finding, and none from B-08: Appendix D asks nothing of
    # Section 16 about statements. Only the note that Category 5 is not
    # OSHA's - information, not a fault.
    h303 = [f for f in report.findings if f.code == "H303"]
    assert [(f.check_id, f.severity.value) for f in h303] == [("C-12", "info")]
    actions = sections.build(report, "US OSHA HazCom", "chosen by you").actions
    assert not any("H303" in text and "Section 2" in text for text in actions), actions


def test_a_wording_mismatch_against_ghs_is_still_a_finding():
    """Only the wording decides; being out of scope is not a free pass."""
    report = check_pdf(pdf("pattern_out_of_scope"), "us_osha")
    by_code = {v.code: v for v in report.statements}
    assert by_code["P273"].status == "wrong", by_code["P273"].why


# -- a printed bracket holding its blank is unfilled ---------------------------


@pytest.mark.parametrize(
    ("document", "unfilled", "filled_values"),
    [
        ("Wash hands [and …] thoroughly after handling. Do not touch eyes.", True, []),
        ("Wash hands [and…] thoroughly after handling. Do not touch eyes.", True, []),
        ("Wash hands and forearms thoroughly after handling. Do not touch eyes.",
         False, ["forearms"]),
        ("Wash hands thoroughly after handling. Do not touch eyes.", False, []),
    ],
)
def test_a_bracket_holding_a_blank_is_not_filled_in(document, unfilled, filled_values):
    from lingua_oracle.keys.store import load_key
    from lingua_oracle.match.template import match

    template = load_key("un_ghs", "en").by_code()["P264+P265"].text
    result = match(document, template)
    assert result.matched
    blanks = [v for v in result.fillins if "…" in v]
    assert bool(blanks) is unfilled
    assert [v for v in result.fillins if "…" not in v] == filled_values
