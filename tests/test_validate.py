"""Tests for the validation harness.

The harness runs against real company documents, which cannot be committed, so
these exercise it with the synthetic fixtures instead — standing in for real
files with the same shapes.
"""

from __future__ import annotations

import json

import pytest
import yaml
from typer.testing import CliRunner

from lingua_oracle.cli import app
from lingua_oracle.validate import finding_id, load_cases, run
from lingua_oracle.validate.report import render_html, to_dict
from lingua_oracle.validate.runner import TARGETS

FIXTURES = ["clean_eu_da", "defect_a01_signal", "clean_osha_en"]


@pytest.fixture()
def valdir(tmp_path, monkeypatch):
    """A validation directory holding synthetic stand-ins for real documents."""
    import shutil
    from pathlib import Path

    src = Path(__file__).parent / "fixtures"
    for name in FIXTURES:
        shutil.copy(src / f"{name}.pdf", tmp_path / f"{name}.pdf")
    monkeypatch.setenv("LINGUA_VALIDATION_DIR", str(tmp_path))
    return tmp_path


def write_cases(valdir, cases, *, confirmed=True):
    """Write a case file. Cases are confirmed unless a test says otherwise."""
    payload = [{"confirmed": confirmed, **c} for c in cases]
    (valdir / "cases.yaml").write_text(
        yaml.safe_dump({"cases": payload}, allow_unicode=True), encoding="utf-8"
    )


def test_clean_documents_meet_every_target(valdir):
    write_cases(valdir, [
        {"file": "clean_eu_da.pdf", "regulation": "eu_clp", "language": "da",
         "known_good": True,
         "expected_codes": ["H225", "H319", "H336", "P210", "P280",
                            "P305+P351+P338", "EUH066"]},
    ])
    summary = run()
    assert summary.code_recall == 1.0
    assert summary.false_alarms == []
    targets = {t["name"]: t for t in summary.targets()}
    assert targets["Code recall"]["passed"]
    assert targets["False alarms on known_good documents"]["passed"]
    # Overall pass is withheld while a target is unmeasured: the spot check has
    # not been done, and "not measured" must not read as "met".
    assert targets["Answer-key spot check"]["skipped"]
    assert summary.passed is False


def test_missed_code_lowers_recall_below_target(valdir):
    write_cases(valdir, [
        {"file": "clean_eu_da.pdf", "regulation": "eu_clp", "language": "da",
         "known_good": True, "expected_codes": ["H225", "H400"]},
    ])
    summary = run()
    assert summary.code_recall == 0.5
    assert summary.results[0].missed == {"H400"}
    assert not {t["name"]: t for t in summary.targets()}["Code recall"]["passed"]


def test_known_defect_must_be_caught(valdir):
    write_cases(valdir, [
        {"file": "defect_a01_signal.pdf", "regulation": "eu_clp", "language": "da",
         "known_good": False, "expected_codes": ["H225"],
         "known_defects": [{"check": "A-01", "code": "SIGNAL",
                            "note": "wrong signal word"}]},
    ])
    summary = run()
    assert summary.defects_caught == 1
    assert summary.defects_expected == 1
    assert summary.results[0].defects_missed == []


def test_undetected_known_defect_fails_the_target(valdir):
    write_cases(valdir, [
        {"file": "clean_eu_da.pdf", "regulation": "eu_clp", "language": "da",
         "known_good": False, "expected_codes": ["H225"],
         "known_defects": [{"check": "A-06", "code": "H225", "note": "not present"}]},
    ])
    summary = run()
    assert summary.defects_caught == 0
    assert not {t["name"]: t for t in summary.targets()}["Known defects caught"]["passed"]


def test_unclassified_finding_on_a_known_good_document_is_a_false_alarm(valdir):
    """A finding on a document believed correct counts until someone triages it."""
    write_cases(valdir, [
        {"file": "defect_a01_signal.pdf", "regulation": "eu_clp", "language": "da",
         "known_good": True, "expected_codes": ["H225"]},
    ])
    summary = run()
    assert summary.false_alarms, "findings on a known_good document must be counted"
    assert not {t["name"]: t
                for t in summary.targets()}["False alarms on known_good documents"]["passed"]


def test_triage_clears_a_false_alarm_only_once_marked_fixed(valdir):
    write_cases(valdir, [
        {"file": "defect_a01_signal.pdf", "regulation": "eu_clp", "language": "da",
         "known_good": True, "expected_codes": ["H225"]},
    ])
    ids = [f["id"] for r in run().results for f in r.findings]
    assert ids

    # classifying as a real bug takes it out of the false-alarm count
    (valdir / "triage.yaml").write_text(
        yaml.safe_dump({"findings": [
            {"id": i, "classification": "real_bug", "note": "genuine defect"} for i in ids
        ]}), encoding="utf-8")
    assert run().false_alarms == []

    # classifying as the tool's fault keeps it counted until it is fixed
    (valdir / "triage.yaml").write_text(
        yaml.safe_dump({"findings": [
            {"id": i, "classification": "false_alarm", "note": "tool error"} for i in ids
        ]}), encoding="utf-8")
    assert run().false_alarms, "an unfixed false_alarm must still count"

    (valdir / "triage.yaml").write_text(
        yaml.safe_dump({"findings": [
            {"id": i, "classification": "false_alarm", "note": "fixed", "fixed": True}
            for i in ids
        ]}), encoding="utf-8")
    assert run().false_alarms == []


def test_finding_ids_are_stable_and_quote_no_document_text():
    """A triage verdict must survive a re-run, without naming the product."""
    a = finding_id("Some Product Sheet.pdf", "A-02", "H225", "wording does not match")
    b = finding_id("Some Product Sheet.pdf", "A-02", "H225", "wording does not match")
    assert a == b
    assert "wording" not in a
    assert a.startswith("Some Product Sheet:A-02:H225:")


def test_missing_file_is_reported_not_crashed(valdir):
    write_cases(valdir, [
        {"file": "nope.pdf", "regulation": "eu_clp", "expected_codes": ["H225"]},
    ])
    summary = run()
    assert "file not found" in summary.results[0].error
    assert summary.code_recall == 0.0


def test_summary_renders_to_json_and_self_contained_html(valdir):
    write_cases(valdir, [
        {"file": "clean_eu_da.pdf", "regulation": "eu_clp", "language": "da",
         "known_good": True, "expected_codes": ["H225"]},
    ])
    summary = run()
    blob = json.loads(json.dumps(to_dict(summary)))
    assert blob["documents"][0]["file"] == "clean_eu_da.pdf"
    page = render_html(summary)
    assert "<style>" in page
    assert "src=" not in page and "<link" not in page
    assert "Code recall" in page


def test_cli_validate_init_refuses_an_untracked_but_unignored_directory(tmp_path, monkeypatch):
    """The folder must be gitignored before any real document can be put in it."""
    monkeypatch.setenv("LINGUA_VALIDATION_DIR", str(tmp_path / "not-ignored"))
    result = CliRunner().invoke(app, ["validate", "init"])
    assert result.exit_code == 2
    assert "REFUSING" in result.output


def test_targets_are_the_agreed_numbers():
    assert TARGETS["code_recall"] == 0.98
    assert TARGETS["false_alarms_on_known_good"] == 0
    assert TARGETS["known_defects_caught"] == 1.0
    assert TARGETS["spot_check_correct"] == 20


def test_example_template_parses_as_a_case_file():
    from lingua_oracle.validate import template_path

    cases = load_cases(template_path())
    assert len(cases.cases) >= 2
    assert any(c.known_defects for c in cases.cases)


def test_unconfirmed_cases_are_not_scored(valdir):
    """A case the tool drafted is not evidence until a human checks it."""
    write_cases(valdir, [
        {"file": "clean_eu_da.pdf", "regulation": "eu_clp", "language": "da",
         "known_good": True, "expected_codes": ["H225", "H400"]},
    ], confirmed=False)
    summary = run()
    assert len(summary.unconfirmed) == 1
    assert summary.scored == []
    # the missed H400 must NOT drag recall down, because nothing was scored
    assert summary.code_recall is None
    assert summary.false_alarms == []
    assert summary.passed is False, "an unconfirmed case must withhold the pass"


def test_confirming_a_case_makes_it_count(valdir):
    case = {"file": "clean_eu_da.pdf", "regulation": "eu_clp", "language": "da",
            "known_good": True, "expected_codes": ["H225"]}
    write_cases(valdir, [case], confirmed=False)
    assert run().code_recall is None
    write_cases(valdir, [case], confirmed=True)
    assert run().code_recall == 1.0


def test_a_mixed_file_scores_only_the_confirmed_cases(valdir):
    (valdir / "cases.yaml").write_text(yaml.safe_dump({"cases": [
        {"file": "clean_eu_da.pdf", "regulation": "eu_clp", "language": "da",
         "confirmed": True, "known_good": True, "expected_codes": ["H225"]},
        {"file": "clean_osha_en.pdf", "regulation": "us_osha", "language": "en",
         "confirmed": False, "known_good": True, "expected_codes": ["H999"]},
    ]}), encoding="utf-8")
    summary = run()
    assert len(summary.scored) == 1
    assert len(summary.unconfirmed) == 1
    assert summary.code_recall == 1.0      # the bogus H999 is not counted
    assert summary.passed is False
