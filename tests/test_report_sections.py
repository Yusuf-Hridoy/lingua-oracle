"""The report by SDS section: where each result goes and what it adds up to.

Built from synthetic 2-propanol sheets (Annex VI 603-117-00-0) and the usual
wording fixtures. The view decides nothing; these tests pin where each verdict
is placed and that the banner, actions and counts come from the same rows.
"""

from __future__ import annotations

from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report import labels, sections
from lingua_oracle.report.render import render_html
from tests.conftest import pdf


def _page(name, regulation=None):
    report = check_pdf(pdf(name), regulation, ingredients=True)
    return report, sections.build(report, "EU CLP", "read from the document")


def test_the_sections_come_in_sds_order():
    _, page = _page("pattern_substance_2_propanol")
    assert [s.number for s in page.sections] == [str(n) for n in range(1, 17)]
    assert [n["label"] for n in page.nav] == [
        "1 · Identification", "2 · Hazards", "3 · Composition", "4 · First aid",
        "5 · Firefighting", "6 · Accidental release", "7 · Handling and storage",
        "8 · Exposure controls", "9 · Physical state", "10 · Stability and reactivity",
        "11 · Toxicology", "12 · Ecology", "13 · Disposal", "14 · Transport",
        "15 · Regulatory", "16 · Other information"]
    assert all(n["href"] and n["status"] == "ok" for n in page.nav)


def test_a_report_without_a_structure_keeps_the_sections_it_reads():
    report, _ = _page("pattern_substance_2_propanol")
    report.structure = None
    page = sections.build(report, "EU CLP", "read from the document")
    assert [s.number for s in page.sections] == ["1", "2", "3", "9", "14", "16"]
    assert "4–8 · not checked" in [n["label"] for n in page.nav]


def test_each_section_shows_its_structure_rows_with_the_texts_wording():
    _, page = _page("pattern_substance_2_propanol")
    seven = next(s for s in page.sections if s.number == "7")
    structure = next(sub for sub in seven.subs if sub.title == "Structure")
    keys = [r.key for r in structure.rows]
    assert keys[:2] == ["Number", "Heading"]
    assert "7.1 Precautions for safe handling" in keys
    assert all(r.status == "ok" for r in structure.rows)
    one = next(s for s in page.sections if s.number == "1")
    document = next(sub for sub in one.subs if sub.title == "Whole document")
    assert {r.key for r in document.rows} == {"A date", "Page numbering"}


def test_a_correct_substance_sheet_is_ready_with_every_item_a_row():
    _, page = _page("pattern_substance_2_propanol")
    assert (page.tone, page.release) == ("ok", labels.READY)
    assert page.stats["must_fix"] == 0 and page.stats["to_check"] == 0
    two = next(s for s in page.sections if s.number == "2")
    keys = [r.key for r in two.rows]
    for item in ("Flam. Liq. 2", "Eye Irrit. 2", "STOT SE 3", "Signal word",
                 "H225", "H319", "H336", "P210", "P233"):
        assert item in keys, item
    # Pictograms are images on this sheet: that row says it could not check them.
    assert all(r.status in ("ok", "plain") or r.key == "Pictograms" for r in two.rows)
    three = next(s for s in page.sections if s.number == "3")
    row = three.table["rows"][0]
    assert (row["cas"], row["share"], row["row"].text) == ("67-63-0", "100 %", "Matches")
    # Every section's structure is judged against the text: 16 of 16.
    assert page.stats["sections"] == 16


def test_a_missing_code_is_one_action_in_the_section_it_is_fixed_in():
    _, page = _page("pattern_substance_missing_h336")
    assert page.release == labels.FIX
    assert page.actions == [
        "Section 2: add STOT SE 3, as CLP Annex VI Part 3, Table 3 gives for "
        "propan-2-ol (603-117-00-0)",
        "Section 2: add H336, which CLP Annex VI Part 3, Table 3 requires for "
        "propan-2-ol (603-117-00-0)"]
    nav = {n["label"]: n["status"] for n in page.nav}
    assert nav["2 · Hazards"] == "fix" and nav["3 · Composition"] == "fix"
    assert nav["16 · Other information"] == "ok"


def test_wrong_wording_carries_both_texts_and_the_action_names_the_section():
    _, page = _page("defect_a02_hazard", "eu_clp")
    row = next(r for s in page.sections for r in s.rows if r.key == "H225")
    assert row.status == "wrong"
    assert '<mark class="diff">' in row.found_html + row.expected_html
    assert page.actions[0].startswith("Section 2: correct H225 to “")


def test_the_counts_are_the_rows():
    _, page = _page("pattern_supplier_ingredients", "eu_clp")
    rows = [r for s in page.sections for r in s.rows]
    assert page.stats["must_fix"] == sum(r.status in ("fix", "wrong") for r in rows)
    assert page.stats["to_check"] == sum(r.status == "check" for r in rows)
    assert page.stats["correct"] == sum(r.status == "ok" for r in rows)


def test_nothing_but_technical_details_is_collapsed():
    body = render_html(check_pdf(pdf("pattern_supplier_ingredients"), "eu_clp",
                                 ingredients=True))
    assert body.count("<details") == 1
    assert "<summary>Technical details</summary>" in body
    assert 'id="s7"' in body                       # every section shown, open


def test_a_mixture_whose_ranges_reach_100_says_nothing_is_undisclosed():
    _, page = _page("pattern_glycol_coolant_gb")
    two = next(s for s in page.sections if s.number == "2")
    basis = next(r.text for r in two.rows if r.key == "Mixture")
    assert "upper ends total 124.5 %, so nothing is undisclosed" in basis
    assert "at both ends of every range" in basis
    assert "of the mixture" not in basis


def test_acute_toxicity_is_a_row_of_2_1_with_its_arithmetic():
    body = render_html(check_pdf(pdf("pattern_glycol_coolant_gb"), ingredients=True))
    two = body[body.index('id="s2"'):body.index('id="s3"')]
    assert 'data-class="Acute toxicity, oral"' in two
    assert "ATEmix = 1250 mg/kg" in two and "ATEmix = 800 mg/kg" in two
    assert "Category 4" in two


def _card(body, family):
    start = body.index(f'data-class="{family}"')
    return body[start:body.index('<div class="srow', start + 1)]


def test_a_differing_section_two_shows_the_question_and_no_basis_box():
    body = render_html(check_pdf(pdf("pattern_glycol_coolant_gb"), ingredients=True))
    card = _card(body, "Target organ toxicity, repeated exposure")
    assert 'class="pill check"' in card
    assert "Section 2 states STOT RE 2; calculated from the ingredients" in card
    assert "confirm which principle and which reference mixture" in card
    assert 'class="justify"' not in card


def test_the_sheets_own_basis_is_quoted_next_to_the_verdict(tmp_path):
    from tests.make_fixtures import _glycol_coolant

    line = "Classification based on test data on the mixture."
    path = _glycol_coolant(tmp_path / "coolant.pdf",
                           section_two=[("STOT RE 2", "H373")], extra_s2=[line])
    body = render_html(check_pdf(str(path), "uk_clp", ingredients=True))
    card = _card(body, "Acute toxicity, oral")
    assert 'class="pill check"' in card and 'class="pill fix"' not in card
    assert "What the sheet gives as its basis" in card
    assert f"<q>{line}</q>" in card


def test_label_elements_and_the_flash_point_are_rows_where_they_belong():
    _, page = _page("pattern_substance_2_propanol")
    by_number = {s.number: s for s in page.sections}
    two = next(sub for sub in by_number["2"].subs if sub.title == "Label elements")
    assert ("Signal word", "ok") in [(r.key, r.status) for r in two.rows]
    nine = next(sub for sub in by_number["9"].subs if sub.title == "Flash point")
    assert [r.status for r in nine.rows] == ["ok"]
    assert "Table 2.6.1" in nine.rows[0].source


def test_a_mixture_card_says_when_its_class_comes_from_section_11(tmp_path):
    from tests.make_fixtures import _glycol_coolant

    path = _glycol_coolant(tmp_path / "c11.pdf", section_eleven=[
        "Acute toxicity of the mixture: LD50 oral, rat: 1500 mg/kg"])
    body = render_html(check_pdf(str(path), "uk_clp", ingredients=True))
    card = _card(body, "Acute toxicity, oral")
    assert "Section 11&rsquo;s data on the mixture" in card or "Section 11’s data on the mixture" in card
    assert "used instead of the additivity calculation" in card


def test_section_14_shows_the_transport_class_and_required_field_rows(tmp_path):
    from tests.make_fixtures import structured_sheet

    path = structured_sheet(tmp_path / "t.pdf", regulation="uk_clp", language="en", bodies={
        "2": ["H225", "Highly flammable liquid and vapour"],
        "3": ["Synthetic component A  CAS 000-00-0  30-60%"],
        "9": ["State :", "liquid", "Flash point :", "Not specified"],
        "14": ["UN ID Number:", "1001", "Shipping Name:", "Not applicable",
               "Class or Division:", "Not applicable"]})
    report = check_pdf(str(path), "uk_clp", "en")
    page = sections.build(report, "GB CLP", "flag")
    fourteen = next(s for s in page.sections if s.number == "14")
    subs = {sub.title: sub.rows for sub in fourteen.subs}
    [cls] = subs["Transport class against the product"]
    assert cls.status == "fix" and cls.action.startswith("give a UN entry whose class fits")
    fields = subs["Required transport fields"]
    assert {r.status for r in fields} == {"fix"} and len(fields) == 2
    assert fields[0].action.startswith("give the shipping name, class and packing group")
