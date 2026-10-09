"""C-24 on synthetic sheets: a UN number in Section 14 with the fields each
regulation's own text requires (data/section14). Every sheet is invented."""

from __future__ import annotations

import pytest

from lingua_oracle.consistency import transport_fields
from lingua_oracle.keys.builders import section14
from lingua_oracle.pipeline import check_pdf
from tests.make_fixtures import structured_sheet

_EMPTY = ["UN ID Number:", "1090", "Shipping Name:", "Not applicable", "Packaging Group:",
          "Not applicable", "Class or Division:", "Not applicable"]
_FULL = ["UN number: UN1090", "UN proper shipping name: Acetone",
         "Transport hazard class(es): 3", "Packing group: II"]


def _rows(tmp_path, regulation, fourteen):
    path = structured_sheet(tmp_path / "t.pdf", regulation=regulation, language="en",
                            bodies={"2": ["Not classified."],
                                    "3": ["Synthetic component A  CAS 000-00-0  30-60%"],
                                    "14": list(fourteen)})
    report = check_pdf(str(path), regulation, "en")
    return [r for r in report.consistency if r.check == "C-24"], report


@pytest.mark.parametrize("regulation", ["eu_clp", "uk_clp"])
def test_reach_a_number_without_name_class_or_packing_group_is_a_fault(tmp_path, regulation):
    rows, report = _rows(tmp_path, regulation, _EMPTY)
    by_key = {r.key: r for r in rows}
    assert {k: r.status for k, r in by_key.items()} == {
        "Transport UN1090 proper shipping name": "fix",
        "Transport UN1090 transport hazard class": "fix",
        "Transport UN1090 packing group": "fix"}
    assert by_key["Transport UN1090 packing group"].citation.endswith("Annex II, 14.4")
    assert "shall be provided" in by_key["Transport UN1090 transport hazard class"].quote
    assert by_key["Transport UN1090 packing group"].expected == "II"
    assert sum(f.check_id == "C-24" for f in report.findings) == 3


def test_no_packing_group_is_asked_where_the_list_entry_has_none(tmp_path):
    rows, _ = _rows(tmp_path, "uk_clp", ["UN ID Number:", "1045", "Shipping Name:",
                                         "Not applicable", "Class or Division:", "Not applicable"])
    assert sorted(r.key for r in rows) == ["Transport UN1045 proper shipping name",
                                           "Transport UN1045 transport hazard class"]


def test_every_field_given_is_ok(tmp_path):
    rows, _ = _rows(tmp_path, "eu_clp", _FULL)
    assert [(r.key, r.status) for r in rows] == [("Transport UN1090", "ok")]


def test_eu_a_name_given_in_one_mode_need_not_be_repeated(tmp_path):
    rows, _ = _rows(tmp_path, "eu_clp", ["ADR"] + _FULL + [
        "IMDG", "UN number: UN1090", "Transport hazard class(es): 3", "Packing group: II"])
    assert [(r.key, r.status) for r in rows] == [("ADR UN1090", "ok"), ("IMDG UN1090", "ok")]


def test_the_name_need_not_be_given_where_it_is_the_product_identifier():
    rows = transport_fields.run(["UN number: UN1090", "Transport hazard class(es): 3",
                                 "Packing group: II"], "eu_clp", "Acetone")
    assert [(r.key, r.status) for r in rows] == [("Transport UN1090", "ok")]


def test_ghs_recommends_so_a_missing_field_is_one_to_check(tmp_path):
    rows, _ = _rows(tmp_path, "un_ghs", ["UN number: UN1090", "UN proper shipping name: Acetone",
                                         "Packing group: II"])
    assert [(r.key, r.status) for r in rows] == [
        ("Transport UN1090 transport hazard class", "check")]
    assert rows[0].citation.endswith("A4.3.14.3")


@pytest.mark.parametrize("regulation, cited", [
    ("au_whs", "Schedule 7, clause 1(2)(n)"), ("ca_whmis", "section 4(2)"),
    ("us_osha", "Appendix D, introduction")])
def test_where_the_text_requires_no_field_there_is_a_note(tmp_path, regulation, cited):
    rows, report = _rows(tmp_path, regulation, _EMPTY)
    assert [(r.key, r.status) for r in rows] == [("Required fields", "na")]
    assert rows[0].citation.endswith(cited) and rows[0].quote
    assert not [f for f in report.findings if f.check_id == "C-24"]


def test_the_section_14_rules_are_quoted_from_each_text():
    for regulation in ("eu_clp", "uk_clp"):
        held = section14.load(regulation)
        assert held["binding"] is True
        for field, sub in (("number", "14.1"), ("name", "14.2"), ("class", "14.3"),
                           ("group", "14.4")):
            assert held["fields"][field]["citation"].endswith(f"Annex II, {sub}")
            assert "shall be provided" in held["fields"][field]["quote"]
    assert "unless it was used as the product identifier in subsection 1.1" in \
        section14.load("uk_clp")["fields"]["name"]["quote"]
    assert section14.load("eu_clp")["name_once"]["quote"].startswith("If the UN number")
    ghs = section14.load("un_ghs")
    assert ghs["binding"] is False and ghs["fields"]["group"]["quote"].startswith("Provide")
    assert "may be omitted" in section14.load("ca_whmis")["note"]["quote"]
    assert "not mandatory" in section14.load("us_osha")["note"]["quote"]
    assert "(n) Section 14: Transport information;" in section14.load("au_whs")["note"]["quote"]
