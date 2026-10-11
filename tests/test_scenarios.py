"""One synthetic fixture per scenario in data/scenarios.yaml - invented
products, real list entries - each asserting the expected verdict; and a
test that fails if any scenario has none."""

from __future__ import annotations

import pytest

from lingua_oracle.pipeline import check_pdf
from lingua_oracle.reference import scenarios
from tests.conftest import pdf
from tests.make_fixtures import Sheet, structured_sheet
from tests.test_reference import on_file  # noqa: F401 - recorded PubChem records

CASES: dict = {}


def scenario(name):
    def register(test):
        CASES[name] = test
        return test
    return register


def _check(tmp_path, regulation, *, two=(), three=(), nine=None, language="en", name="s.pdf"):
    bodies = {"2": list(two) or ["Not classified."], "3": list(three)}
    if nine is not None:
        bodies["9"] = list(nine)
    path = structured_sheet(tmp_path / name, regulation=regulation, language=language,
                            bodies=bodies)
    return check_pdf(str(path), regulation, language, ingredients=True)


def _rows(report):
    return {row["code"]: row for row in report.hcodes.rows}


def test_every_scenario_has_a_fixture():
    ids = {s["id"] for s in scenarios.load()}
    assert ids and not ids - set(CASES), sorted(ids - set(CASES))
    assert all(s["status"] in ("supported", "partial", "not_supported") for s in scenarios.load())
    assert all(s.get("reason") for s in scenarios.load() if s["status"] != "supported")


# -- product types -------------------------------------------------------------------

@scenario("substance_on_list")
def _(tmp_path):
    report = check_pdf(pdf("pattern_substance_2_propanol"), "eu_clp", "en", ingredients=True)
    assert report.composition == "substance" and report.substance.state == "checked"
    assert "substance_on_list" in scenarios.hit(report)
    assert _rows(report)["H319"]["status"] == "confirmed"


@scenario("substance_not_on_list")
def _(tmp_path):
    report = _check(tmp_path, "us_osha", two=["H319", "H336"], three=["Synthetic solvent  CAS 67-64-1"])
    item = report.hcodes.ingredients[0]
    assert item["b"]["source"].startswith("PubChem (ECHA C&L notifications) — reference")
    row = _rows(report)["H319"]
    assert row["status"] == "confirmed" and not row["binding"]


@scenario("substance_no_cas")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H315"],
                    three=["Synthetic hydrocarbon  EC 203-625-9  100%"])
    item = report.hcodes.ingredients[0]
    assert item["cas"] == "108-88-3" and item["identified"] == "by EC 203-625-9"
    assert "substance_no_cas" in scenarios.hit(report)


@scenario("mixture_exact_percent")
def _(tmp_path):
    report = _check(tmp_path, "us_osha", two=["H319", "H336"],
                    three=["Synthetic solvent  CAS 67-64-1  90%"])
    assert _rows(report)["H319"]["status"] == "confirmed"
    assert "mixture_exact_percent" in scenarios.hit(report)


@scenario("mixture_ranges")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H315"],
                    three=["Synthetic aromatic  CAS 108-88-3  5 - 15 %"])
    row = _rows(report)["H315"]
    assert row["status"] == "cant" and "end" in row["reason"]
    assert "mixture_ranges" in scenarios.hit(report)


@scenario("mixture_withheld")
def _(tmp_path):
    report = _check(tmp_path, "us_osha", two=["H319"],
                    three=["Synthetic solvent  CAS 67-64-1  60%",
                           "Trade secret ingredient  30 - 40 %"])
    assert any("withheld as a trade secret" in a for a in report.hcodes.assumptions)
    assert "mixture_withheld" in scenarios.hit(report)


@scenario("mixture_no_percent")
def _(tmp_path):
    report = _check(tmp_path, "us_osha", two=["H319"],
                    three=["Synthetic solvent  CAS 67-64-1", "Synthetic aromatic  CAS 108-88-3"])
    assert any("partial check" in a for a in report.hcodes.assumptions)
    assert _rows(report)["H319"]["status"] == "cant"


@scenario("mixture_in_mixture")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H317"],
                    three=["Synthetic solvent  CAS 67-64-1  50%", "Fragrance mixture  H317  5%",
                           "Flavour blend  2%"])
    by_name = {i["cas"]: i for i in report.hcodes.ingredients}
    given = next(i for k, i in by_name.items() if k.startswith("Fragrance"))
    assert given["a"]["codes"] == ["H317"] and "(a mixture)" in given["a"]["source"]
    missing = next(i for k, i in by_name.items() if k.startswith("Flavour"))
    assert missing["a"]["codes"] is None and "does not give" in missing["a"]["why"]
    assert _rows(report)["H317"]["status"] == "confirmed"


@scenario("aerosol")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", three=["Synthetic solvent  CAS 67-64-1  50%"],
                    nine=["Physical state: Aerosol"])
    row = _rows(report)["H222 / H223 / H229"]
    assert row["status"] == "wrong" and "2.3.2.1" in row["reason"]
    (tmp_path / "p").mkdir()
    printed = _check(tmp_path / "p", "eu_clp", two=["H222", "H229"],
                     three=["Synthetic solvent  CAS 67-64-1  50%"], nine=["Physical state: Aerosol"])
    assert _rows(printed)["H222"]["status"] == "cant"


@scenario("gas_mixture")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H220"],
                    three=["Synthetic gas A  CAS 74-98-6  60%", "Synthetic gas B  CAS 106-97-8  40%"],
                    nine=["Physical state: Gas"])
    row = _rows(report)["H220"]
    assert row["status"] == "cant" and "method not on file" in row["reason"]
    assert "ISO 10156" in row["reason"]


@scenario("solid_powder")
def _(tmp_path):
    report = _check(tmp_path, "us_osha", two=["H319"], three=["Synthetic salt  CAS 7732-18-5  99%"],
                    nine=["Physical state: Solid", "Form: Powder"])
    assert report.physical_state == "solid" and "solid_powder" in scenarios.hit(report)


@scenario("not_classified")
def _(tmp_path):
    report = _check(tmp_path, "us_osha", three=["Water  CAS 7732-18-5  99%"])
    assert report.hcodes.rows == [] and "give none" in report.hcodes.message
    assert "not_classified" in scenarios.hit(report)


# -- special rules ---------------------------------------------------------------------

@scenario("euh208")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", three=["Synthetic terpene  CAS 5989-27-5  0.5%",
                                               "Water  CAS 7732-18-5  99.5%"])
    row = _rows(report)["EUH208"]
    assert row["status"] == "wrong" and "Table 3.4.6" in row["reason"]
    assert "Sub-category 1B" in row["reason"]


@scenario("euh210")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", three=["Synthetic aromatic  CAS 108-88-3  0.5%",
                                               "Water  CAS 7732-18-5  99.5%"])
    row = _rows(report)["EUH210"]
    assert row["status"] == "wrong" and "Annex II, 2.10" in row["reason"]


@scenario("euh066")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H319", "EUH066"],
                    three=["Synthetic solvent  CAS 67-64-1  90%"])
    row = _rows(report)["EUH066"]
    assert row["status"] == "cant" and "Annex II, 1.2.4" in row["reason"]


@scenario("euh071")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H319", "EUH071"],
                    three=["Synthetic solvent  CAS 67-64-1  90%"])
    assert _rows(report)["EUH071"]["status"] == "check"


@scenario("euh401")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H319", "EUH401"],
                    three=["Synthetic solvent  CAS 67-64-1  90%"])
    row = _rows(report)["EUH401"]
    assert row["status"] == "cant" and "plant protection" in row["reason"]


@scenario("aspiration_h304")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H315"],
                    three=["Synthetic aromatic  CAS 108-88-3  50%", "Water  CAS 7732-18-5  50%"],
                    nine=["Physical state: Liquid", "Kinematic viscosity: 0.6 mm²/s at 40 °C"])
    row = _rows(report)["H304"]
    assert row["status"] == "wrong" and "3.10.3.3.1.2" in row["reason"]
    (tmp_path / "v").mkdir()
    unknown = _check(tmp_path / "v", "eu_clp", two=["H304", "H315"],
                     three=["Synthetic aromatic  CAS 108-88-3  50%", "Water  CAS 7732-18-5  50%"],
                     nine=["Physical state: Liquid", "Viscosity: 0.55 mPa·s"])
    row = _rows(unknown)["H304"]
    assert row["status"] == "cant" and "dynamic" in row["reason"]


@scenario("extreme_ph")
def _(tmp_path):
    report = _check(tmp_path, "us_osha", two=["H319"], three=["Synthetic solvent  CAS 67-64-1  90%"],
                    nine=["Physical state: Liquid", "pH: 13"])
    row = _rows(report)["H314"]
    assert row["status"] == "check" and "A.2.3.1.3" in row["reason"]


@scenario("annex_vi_limits")
def _(tmp_path):
    # MBIT: Skin Sens. 1A, the entry's own limit C ≥ 0,0015 % - at 0.01 % the
    # mixture is a sensitiser only by it (the generic 1A limit is 0,1 %).
    report = _check(tmp_path, "eu_clp", two=["H317"],
                    three=["Synthetic preservative  CAS 2527-66-4  0.01%",
                           "Water  CAS 7732-18-5  99.99%"])
    assert _rows(report)["H317"]["status"] == "confirmed"


@scenario("annex_vi_notes")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H304"],
                    three=["Synthetic naphtha  CAS 8006-61-9  50%", "Water  CAS 7732-18-5  50%"])
    rows = _rows(report)
    noted = [r for r in rows.values() if "Note P" in r["reason"]]
    assert noted and all(r["status"] == "cant" for r in noted)


@scenario("cmr_edges")
def _(tmp_path):
    at = _check(tmp_path, "eu_clp", three=["Synthetic aromatic  CAS 71-43-2  0.1%",
                                           "Water  CAS 7732-18-5  99.9%"])
    assert _rows(at)["H350"]["status"] == "wrong"
    (tmp_path / "b").mkdir()
    below = _check(tmp_path / "b", "eu_clp", three=["Synthetic aromatic  CAS 71-43-2  0.05%",
                                                    "Water  CAS 7732-18-5  99.95%"])
    assert "H350" not in _rows(below)


@scenario("acute_routes")
def _(tmp_path):
    report = _check(tmp_path, "eu_clp", two=["H301"],
                    three=["Synthetic salt  CAS 7681-49-4  60%", "Water  CAS 7732-18-5  40%"])
    row = _rows(report)["H301"]
    assert "does not calculate" not in row["reason"]


# -- document situations ---------------------------------------------------------------

@scenario("bilingual_canadian")
def _(tmp_path):
    report = _check(tmp_path, "ca_whmis", three=["Synthetic solvent  CAS 67-64-1  90%"],
                    language="en+fr")
    assert report.language == "en+fr" and "bilingual_canadian" in scenarios.hit(report)


@scenario("label_only")
def _(tmp_path):
    report = check_pdf(pdf("pattern_label_only"), "eu_clp", "en")
    assert "label_only" in scenarios.hit(report)


@scenario("several_products")
def _(tmp_path):
    sheet = Sheet(tmp_path / "two.pdf")
    for product in ("First synthetic product", "Second synthetic product"):
        sheet.line("SECTION 1: Identification of the substance/mixture", bold=True, size=11)
        sheet.line(f"Product name: {product}")
        sheet.line("SECTION 2: Hazards identification", bold=True, size=11)
        sheet.line("Not classified.")
    sheet.save()
    report = check_pdf(str(tmp_path / "two.pdf"), "eu_clp", "en")
    assert report.products == 2 and any("2 safety data sheets" in n for n in report.notes)


@scenario("scanned")
def _(tmp_path):
    import pymupdf

    picture = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), 0)
    picture.clear_with(200)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(50, 50, 300, 300), pixmap=picture)
    doc.save(tmp_path / "scan.pdf")
    report = check_pdf(str(tmp_path / "scan.pdf"))
    assert report.unreadable.startswith("This PDF has no readable text (scanned) — not checked")
    assert report.findings == [] and scenarios.hit(report) == ["scanned"]


@scenario("eu_languages")
def _(tmp_path):
    report = check_pdf(pdf("clean_eu_da"), "eu_clp", "da")
    assert report.statements and "eu_languages" in scenarios.hit(report)


# Last, so every scenario above is registered when the cases are collected.
@pytest.mark.parametrize("name", sorted(CASES))
def test_scenario(name, tmp_path, on_file):  # noqa: F811
    CASES[name](tmp_path)


def test_a_rule_the_text_decides_alone_binds_whatever_the_data(tmp_path, on_file):  # noqa: F811
    report = _check(tmp_path, "au_whs", three=["Synthetic solvent  CAS 67-64-1  50%"],
                    nine=["Physical state: Aerosol"])
    assert _rows(report)["H222 / H223 / H229"]["binding"]


def test_euh210_on_a_classified_mixture_is_outside_2_10(tmp_path, on_file):  # noqa: F811
    report = _check(tmp_path, "eu_clp", two=["H319", "EUH210"],
                    three=["Synthetic solvent  CAS 67-64-1  90%"])
    row = _rows(report)["EUH210"]
    assert row["status"] == "cant" and "not classified as hazardous" in row["reason"]


def test_without_a_composition_the_text_alone_still_judges(tmp_path, on_file):  # noqa: F811
    report = _check(tmp_path, "eu_clp", three=["Synthetic ingredient  10%"],
                    nine=["Physical state: Aerosol", "pH: 1"])
    rows = _rows(report)
    assert rows["H222 / H223 / H229"]["status"] == "wrong" and rows["H314"]["status"] == "check"
    assert "only what Section 9" in report.hcodes.message


# -- specific limits inside the skin and eye summations ---------------------------------

import pytest as _pytest  # noqa: E402


@_pytest.mark.parametrize("share, skin, eye", [
    ("0.5", "Skin Irrit. 2", "Eye Irrit. 2"),      # Skin Irrit. 2 / Eye Irrit. 2: 0,5 % ≤ C < 2 %
    ("2", "Skin Corr. 1B", None),                   # Skin Corr. 1B: 2 % ≤ C < 5 %
    ("3", "Skin Corr. 1B", "Eye Dam. 1"),           # eye: no specific limit, generic 3 %
    ("5", "Skin Corr. 1A", "Eye Dam. 1"),           # Skin Corr. 1A: C ≥ 5 %
])
def test_sodium_hydroxide_by_its_annex_vi_limits(share, skin, eye):
    from decimal import Decimal

    from lingua_oracle.mixture.calculate import calculate
    from lingua_oracle.mixture.limits import parse
    from lingua_oracle.mixture.model import from_annex_vi
    from lingua_oracle.substances.load import load_list

    entry = load_list("annex_vi").by_cas()["1310-73-2"][0]
    ingredient = from_annex_vi("1310-73-2", "sodium hydroxide", Decimal(share), Decimal(share),
                               entry, parse(entry.limits))
    results, _ = calculate([ingredient], [], "eu_clp")
    found = {r.family: r for r in results}
    assert found["Skin"].calculated_class == skin
    assert any("3.2.3.3.6" in a and "1.1.2.3" in a for a in found["Skin"].assumptions)
    if eye is None:
        assert "Eye" not in found
    else:
        assert found["Eye"].calculated_class == eye


def test_a_specific_limit_beside_an_ingredient_summed_generically(tmp_path, on_file):  # noqa: F811
    # 0,5 % sodium hydroxide is Skin Irrit. 2 by its own limit; 8 % of a
    # generic Skin Irrit. 2 ingredient (toluene) is not enough alone (10 %) -
    # and the sodium hydroxide does not join that sum.
    report = _check(tmp_path, "eu_clp", two=["H315"],
                    three=["Synthetic alkali  CAS 1310-73-2  0.5%",
                           "Synthetic aromatic  CAS 108-88-3  8%", "Water  CAS 7732-18-5  91.5%"])
    row = _rows(report)["H315"]
    assert row["status"] == "confirmed" and "3.2.3.3.6" in row["reason"]
    assert "Annex VI, Part 1, 1.1.2.3" in row["reason"]


def test_a_range_spanning_a_specific_limit_cannot_be_decided(tmp_path, on_file):  # noqa: F811
    report = _check(tmp_path, "eu_clp", two=["H314"],
                    three=["Synthetic alkali  CAS 1310-73-2  1 - 3 %", "Water  CAS 7732-18-5  97%"])
    row = _rows(report)["H314"]
    assert row["status"] == "cant" and "end" in row["reason"]


def test_without_its_specific_limit_the_generic_summation_would_pass_it(tmp_path, on_file):  # noqa: F811
    report = _check(tmp_path, "eu_clp", two=["H315"],
                    three=["Synthetic alkali  CAS 1310-73-2  3%", "Water  CAS 7732-18-5  97%"])
    row = _rows(report)["H315"]
    assert row["status"] == "wrong" and "Skin Corr. 1B" in row["reason"]

