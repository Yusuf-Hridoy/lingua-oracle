"""C-23 on synthetic sheets: Section 14's transport class against the
product's own state and flash point, by the UN Model Regulations'
definitions (2.2.1.1 gases, 2.3.1.2 flammable liquids), quoted from
data/lists/un_dangerous_goods.json. Every sheet is invented."""

from __future__ import annotations

from lingua_oracle.pipeline import check_pdf
from tests.make_fixtures import structured_sheet

_ACETYLENE = ["UN ID Number:", "1001", "Shipping Name:", "ACETYLENE, DISSOLVED",
              "Class or Division:", "2.1"]
_FLAM_LIQ = ["Flammable liquids Category 2", "Signal word: Danger", "H225"]


def _rows(tmp_path, regulation="au_whs", *, two=_FLAM_LIQ, nine=(), fourteen=_ACETYLENE):
    bodies = {"2": list(two), "3": ["Synthetic component A  CAS 000-00-0  30-60%"],
              "9": list(nine) or ["Physical state: Liquid", "Flash point: 10 °C",
                                  "Initial boiling point: 80 °C"],
              "14": list(fourteen)}
    path = structured_sheet(tmp_path / "t.pdf", regulation=regulation, language="en",
                            bodies=bodies)
    report = check_pdf(str(path), regulation, "en")
    return [r for r in report.consistency if r.check == "C-23"], report


def test_a_flammable_liquid_shipped_as_a_class_2_gas_is_a_fault(tmp_path):
    rows, report = _rows(tmp_path)
    assert [(r.key, r.status) for r in rows] == [("UN1001 class 2.1", "fix")]
    row = rows[0]
    assert row.quote.startswith("2.2.1.1 A gas is a substance which")
    assert "2.3.1.2 Flammable liquids are liquids" in row.quote
    assert row.citation.endswith("2.2.1.1 and 2.3.1.2") and "Rev.24" in row.citation
    assert "within Class 3's limit (60 °C closed-cup)" in row.text
    assert any(f.check_id == "C-23" and f.severity.value == "fail" for f in report.findings)


def test_the_class_comes_from_the_list_where_the_sheet_prints_only_a_number(tmp_path):
    rows, _ = _rows(tmp_path, fourteen=["UN number: UN1001"])
    assert [(r.key, r.status) for r in rows] == [("UN1001 class 2.1", "fix")]


def test_a_gas_shipped_as_class_3_is_a_fault(tmp_path):
    rows, _ = _rows(tmp_path, two=["Not classified."], nine=["Physical state: Gas"],
                    fourteen=["UN number: UN1090", "UN proper shipping name: Acetone",
                              "Transport hazard class(es): 3", "Packing group: II"])
    assert [(r.key, r.status) for r in rows] == [("UN1090 class 3", "fix")]


def test_a_flammable_liquid_in_class_3_fits(tmp_path):
    rows, _ = _rows(tmp_path, fourteen=["UN number: UN1993", "UN proper shipping name: "
                                        "Flammable liquid, n.o.s. (synthetic solvent)",
                                        "Transport hazard class(es): 3", "Packing group: II"])
    assert [(r.key, r.status) for r in rows] == [("UN1993 class 3", "ok")]


def test_without_a_flash_point_the_stated_categorys_criterion_decides(tmp_path):
    # As the app's AU sheet prints it: no flash point, H225 in Section 2, liquid.
    rows, _ = _rows(tmp_path, two=["H225", "Highly flammable liquid and vapour"],
                    nine=["State :", "liquid", "Flash point :", "Not specified"])
    assert [(r.key, r.status) for r in rows] == [("UN1001 class 2.1", "fix")]
    assert "Flam. Liq. 2 is “Flash point < 23 °C" in rows[0].text
    assert "Table 2.6.1" in rows[0].text


def test_without_a_flash_point_or_a_category_there_is_nothing_to_decide(tmp_path):
    rows, _ = _rows(tmp_path, two=["Not classified."], nine=["Physical state: Liquid",
                                                            "Flash point: Not available"])
    assert rows == []


def test_the_open_cup_limit_is_the_texts_own(tmp_path):
    open_cup, _ = _rows(tmp_path, two=["Not classified."],
                        nine=["Physical state: Liquid", "Flash point: 63 °C (open cup)"])
    assert [r.status for r in open_cup] == ["fix"] and "65.6 °C open-cup" in open_cup[0].text
    (tmp_path / "closed").mkdir()
    closed, _ = _rows(tmp_path / "closed", two=["Not classified."],
                      nine=["Physical state: Liquid", "Flash point: 63 °C (closed cup)"])
    assert closed == []


def test_an_aerosol_is_left_alone(tmp_path):
    rows, _ = _rows(tmp_path, two=["Aerosol 1", "Signal word: Danger", "H222"],
                    nine=["Physical state: Liquid", "Flash point: -20 °C"],
                    fourteen=["UN number: UN1950", "UN proper shipping name: Aerosols",
                              "Transport hazard class(es): 2.1"])
    assert rows == []
