"""A statement stops where a legend starts, even one broken at the line end.

"... exposure. Abbrevi-" at the end of a line, with "ations and acronyms:" on
the next page, was taken into H373 - and then reported as H373 written two
ways in one sheet. Synthetic sheet; the statement texts come from the key.
"""

from __future__ import annotations

import pytest

from lingua_oracle.extract.rejoin import cut_at_new_item
from lingua_oracle.pipeline import check_pdf
from tests.make_fixtures import HEADINGS, PRODUCT, SUPPLIER, TOP, Sheet, texts


@pytest.mark.parametrize(("text", "kept"), [
    ("through prolonged or repeated exposure. Abbrevi-", "through prolonged or repeated exposure."),
    ("exposure. Glos-", "exposure."),
    ("exposure. Abkür-", "exposure."),
    # An ordinary word broken at the line end is the statement's own.
    ("IF SWALLOWED: Rinse mouth. Do NOT induce vomit-", "IF SWALLOWED: Rinse mouth. Do NOT induce vomit-"),
    ("Wear protective gloves. Wear protec-", "Wear protective gloves. Wear protec-"),
])
def test_only_a_legend_fragment_is_cut(text, kept):
    assert cut_at_new_item(text) == kept


def _sheet(path):
    head = HEADINGS["en"]
    official = texts("eu_clp", "en", ["H373", "P260"])
    sheet = Sheet(path)
    sheet.line(PRODUCT, bold=True, size=12)
    sheet.line(SUPPLIER)
    sheet.line("Prepared according to Regulation (EC) No 1272/2008.", size=8)
    sheet.blank()
    sheet.line(head["2"], bold=True, size=11)
    sheet.line("Signal word: Warning")
    sheet.line(f"H373 {official['H373']}")
    sheet.line(f"P260 {official['P260']}")
    sheet.blank()
    sheet.line(head["3"], bold=True, size=11)
    sheet.line("Synthetic component A  CAS 000-00-0  30-60%")
    sheet.blank()
    sheet.line(head["16"], bold=True, size=11)
    sheet.line(f"H373 {official['H373']} Abbrevi-")
    sheet.canvas.showPage()
    sheet.y = TOP
    sheet.line("ations and acronyms: ACGIH = American Conference of Governmental "
               "Industrial Hygienists")
    sheet.save()
    return path


def test_the_legend_is_not_taken_into_h373(tmp_path):
    report = check_pdf(str(_sheet(tmp_path / "legend.pdf")), "eu_clp", "en")
    verdict = next(v for v in report.statements if v.code == "H373")
    assert verdict.status == "correct", (verdict.found, verdict.why)
    assert "Abbrevi" not in verdict.found


def test_the_same_code_is_not_reported_as_written_two_ways(tmp_path):
    report = check_pdf(str(_sheet(tmp_path / "legend.pdf")), "eu_clp", "en")
    assert not [f for f in report.findings if f.check_id == "C-02" and f.code == "H373"]
