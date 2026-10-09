"""The H-code verdict as the page shows it: one row per code with its own
word, Wrong weighed by whether its data binds, the inputs labelled, and the
likely causes in the technical details only."""

from __future__ import annotations

from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report import labels, sections
from lingua_oracle.report.render import render_html
from tests.make_fixtures import structured_sheet, texts
from tests.test_reference import on_file  # noqa: F401 - the recorded PubChem records


def _page(tmp_path, regulation, codes, three, bare=()):
    official = texts(regulation, "en", codes)
    path = structured_sheet(tmp_path / "p.pdf", regulation=regulation, language="en", bodies={
        "2": [*(f"{c} {official[c]}" for c in codes), *bare], "3": list(three)})
    report = check_pdf(str(path), regulation, "en", ingredients=True)
    return report, sections.build(report, "X", "flag")


def _subs(page, title):
    two = next(s for s in page.sections if s.number == "2")
    return next(sub for sub in two.subs if sub.title == title)


def test_each_code_has_its_verdict_word(tmp_path, on_file):  # noqa: F811
    report, page = _page(tmp_path, "eu_clp", ["H225", "H304", "H315", "H336", "H373"],
                         ["Synthetic solvent  CAS 108-88-3  100%"], bare=["H361d"])
    rows = {r.key: r for r in _subs(page, "2.1 H-code verdict").rows}
    assert (rows["H315"].verdict, rows["H315"].status) == ("Confirmed", "ok")
    assert (rows["H225"].verdict, rows["H225"].status) == ("Can't confirm", "na")
    assert "With ExactSDS's own input" in rows["H361d"].note
    html = render_html(report)
    assert "2.1 H-code verdict" in html
    assert "Can&#39;t confirm" in html or "Can't confirm" in html


def test_wrong_on_reference_data_is_one_to_check_and_on_a_binding_list_a_fault(
        tmp_path, on_file):  # noqa: F811
    _, us = _page(tmp_path, "us_osha", ["H225", "H319"], ["Synthetic solvent  CAS 67-64-1  90%"])
    row = next(r for r in _subs(us, "2.1 H-code verdict").rows if r.key == "H336")
    assert (row.status, row.verdict) == ("check", "Wrong (reference data)")
    assert row.action.startswith("add H336 to Section 2")
    (tmp_path / "eu").mkdir()
    _, eu = _page(tmp_path / "eu", "eu_clp", ["H225", "H304", "H336", "H373"],
                  ["Synthetic solvent  CAS 108-88-3  100%"], bare=["H361d"])
    row = next(r for r in _subs(eu, "2.1 H-code verdict").rows if r.key == "H315")
    assert (row.status, row.verdict) == ("fix", "Wrong")


def test_the_inputs_are_labelled_and_the_binding_list_marked_binding(tmp_path, on_file):  # noqa: F811
    _, page = _page(tmp_path, "eu_clp", ["H225"], ["Synthetic solvent  CAS 108-88-3  100%"])
    note = _subs(page, "2.1 Inputs per ingredient").rows[0].note
    assert "B - best available" in note and "(binding)" in note
    assert "PubChem, first listed classification" in note and "not legally binding" in note


def test_likely_causes_are_in_the_technical_details_only(tmp_path, on_file):  # noqa: F811
    report, page = _page(tmp_path, "eu_clp", ["H225", "H304", "H315", "H336", "H373"],
                         ["Synthetic solvent  CAS 108-88-3  100%"], bare=["H361d"])
    caveats = labels._caveats(report, page)
    assert any(c.startswith("Likely cause (not part of any verdict)") and "letter suffix" in c
               for c in caveats)
    shown = " ".join(r.text + r.note for s in page.sections for r in s.rows)
    assert "letter suffix" not in shown
