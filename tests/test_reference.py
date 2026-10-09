"""PubChem as reference data, inputs A and B, and the H-code verdict - on
recorded PubChem responses for public substances (tests/fixtures/pubchem)
and invented sheets. Nothing here reaches the network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingua_oracle.keys.builders import pubchem
from lingua_oracle.pipeline import check_pdf
from lingua_oracle.reference import inputs
from tests.make_fixtures import structured_sheet, texts

RECORDED = Path(__file__).parent / "fixtures" / "pubchem"


def _record(cas: str) -> dict:
    held = json.loads((RECORDED / f"{cas}.json").read_text(encoding="utf-8"))
    return pubchem.parse(held["view"], cas=cas, cid=held["cid"],
                         url=pubchem.VIEW_URL.format(cid=held["cid"]))


@pytest.fixture
def on_file(tmp_path, monkeypatch):
    """PubChem records for the recorded substances, in a folder of their own."""
    folder = tmp_path / "reference_classifications"
    folder.mkdir()
    for path in RECORDED.glob("*.json"):
        cas = path.stem
        (folder / f"{cas}.json").write_text(json.dumps({**_record(cas), "retrieved": "2026-10-09"}))
    (folder / "999-99-9.json").write_text(json.dumps(
        {"cas": "999-99-9", "cid": None, "source_url": "", "label": pubchem.LABEL,
         "status": "not_found", "entries": [], "retrieved": "2026-10-09"}))
    monkeypatch.setattr(pubchem, "folder", lambda: folder)
    return folder


# -- the record ----------------------------------------------------------------------

def test_every_classification_is_kept_with_its_source_and_notifier_shares():
    record = _record("108-88-3")
    assert record["status"] == "ok" and record["label"].endswith("not legally binding")
    first = record["entries"][0]
    assert first["source"].startswith("Regulation (EC) No 1272/2008")
    assert "H361d" in [c["code"] for c in first["codes"]]
    echa = next(e for e in record["entries"] if e["reports"])
    assert echa["reports"] > 1000 and echa["notifications"]
    assert {c["code"]: c["percent"] for c in echa["codes"]}["H412"] < 50


def test_the_most_commonly_notified_classification_is_the_biggest_block_by_majority():
    codes, about = inputs.majority(_record("108-88-3"))
    assert "H412" not in codes and "H373" in codes             # 16.5 % of reports: not a majority
    water, about = inputs.majority(_record("7732-18-5"))
    assert water == [] and about["reports"] > 1000           # "Not Classified" by most


# -- input A -------------------------------------------------------------------------

def test_input_a_is_the_apps_stored_codes_when_the_app_holds_the_product(on_file):
    a = inputs.input_a("67-64-1", ["H225", "H319", "H335"])
    assert a.codes == ["H225", "H319", "H335"] and a.source == inputs.APP_LABEL


def test_input_a_reproduces_the_apps_pubchem_selection(on_file):
    a = inputs.input_a("108-88-3", None)
    # The first entry, plain H codes: H361d is dropped as the app's reading drops it.
    assert a.codes == ["H225", "H304", "H315", "H336", "H373"] and a.reproducible
    assert a.detail["first_source"].startswith("Regulation (EC) No 1272/2008")


def test_more_than_five_codes_is_not_reproducible_and_keeps_the_fallback(on_file):
    a = inputs.input_a("71-43-2", None)
    assert a.codes is None and not a.reproducible
    assert a.why == "not reproducible: the app uses an AI selection"
    assert a.fallback == ["H225", "H304", "H315", "H319", "H340"]


def test_no_record_and_unknown_cas_are_said(on_file):
    assert inputs.input_a("1-23-4", None).why.startswith("no PubChem record on file")
    assert inputs.input_a("999-99-9", None).codes == []


# -- input B -------------------------------------------------------------------------

def test_input_b_is_the_binding_list_first(on_file):
    b = inputs.input_b("108-88-3", "eu_clp")
    assert b.binding and "H361d" in b.codes and "(binding)" in b.source


def test_input_b_falls_back_to_the_most_commonly_notified(on_file):
    b = inputs.input_b("67-64-1", "us_osha")
    assert not b.binding and b.codes == ["H225", "H319", "H336"]
    assert b.source.startswith(pubchem.LABEL)


def test_likely_causes_name_the_apps_known_gaps(on_file):
    a = inputs.input_a("108-88-3", None)
    b = inputs.input_b("108-88-3", "eu_clp")
    notes = inputs.likely_causes("108-88-3", a, b)
    assert any("does not capture codes with a letter suffix" in n for n in notes)


# -- the verdict -----------------------------------------------------------------------

def _sheet(tmp_path, regulation, two_codes, three, *, extra_two=(), name="h.pdf", words=(),
           bare=()):
    """Section 2: each code with its official text from the key; `bare`
    codes printed alone, where the key holds no text for them."""
    official = texts(regulation, "en", list(two_codes)) if two_codes else {}
    two = [*extra_two, *words, *(f"{c} {official[c]}" for c in two_codes), *bare]
    path = structured_sheet(tmp_path / name, regulation=regulation, language="en",
                            bodies={"2": two or ["Not classified."], "3": list(three)})
    return check_pdf(str(path), regulation, "en", ingredients=True).hcodes


def _rows(hcodes):
    return {r["code"]: r for r in hcodes.rows}


def test_codes_the_ingredients_give_are_confirmed_and_a_physical_one_cannot_be(tmp_path, on_file):
    h = _sheet(tmp_path, "eu_clp", ["H225", "H304", "H315", "H336", "H373"],
               ["Synthetic solvent  CAS 108-88-3  100%"], bare=["H361d"])
    rows = _rows(h)
    for code in ("H315", "H336", "H361d", "H373"):
        assert rows[code]["status"] == "confirmed", code
    assert rows["H225"]["status"] == "cant" and "physical hazard" in rows["H225"]["reason"]
    assert rows["H361d"]["binding"]


def test_a_and_b_differing_are_both_said_and_point_at_the_data(tmp_path, on_file):
    h = _sheet(tmp_path, "eu_clp", ["H225", "H304", "H315", "H336", "H373"],
               ["Synthetic solvent  CAS 108-88-3  100%"], bare=["H361d"])
    row = _rows(h)["H361d"]
    assert row["a"]["status"] == "cant" and row["b"]["status"] == "confirmed"
    assert row["differs"].startswith("With ExactSDS's own input: Can't confirm")
    assert "With the binding/most common data: Confirmed" in row["differs"]
    assert any("likely a data issue" in x for x in row["likely"])
    assert any("letter suffix" in n for n in h.notes)


def test_a_hazard_the_ingredients_give_and_section_2_lacks_is_wrong(tmp_path, on_file):
    h = _sheet(tmp_path, "us_osha", ["H225", "H319"], ["Synthetic solvent  CAS 67-64-1  90%"])
    row = _rows(h)["H336"]
    assert row["status"] == "wrong" and not row["printed"] and "lacks it" in row["reason"]


def test_a_class_stated_in_words_is_judged_like_its_code(tmp_path, on_file):
    h = _sheet(tmp_path, "us_osha", [], ["Synthetic solvent  CAS 67-64-1  90%"],
               words=["Serious eye damage/eye irritation Category 2A", "Signal word: Warning"])
    row = _rows(h)["H319"]
    assert row["status"] == "confirmed" and "Category 2A" in row["stated_as"]


def test_one_ingredient_without_a_share_is_the_substance_at_100(tmp_path, on_file):
    h = _sheet(tmp_path, "us_osha", ["H225", "H319", "H336"], ["Synthetic solvent  CAS 67-64-1"])
    assert any("100 %" in a for a in h.assumptions)
    assert _rows(h)["H319"]["status"] == "confirmed"


def test_several_ingredients_without_shares_are_checked_in_part(tmp_path, on_file):
    h = _sheet(tmp_path, "us_osha", ["H319", "H351"],
               ["Synthetic solvent  CAS 67-64-1", "Synthetic aromatic  CAS 108-88-3"])
    rows = _rows(h)
    assert rows["H351"]["status"] == "check" and "no listed ingredient" in rows["H351"]["reason"]
    assert rows["H319"]["status"] == "cant" and "fully confirmed" in rows["H319"]["reason"]
    assert any("partial check" in a for a in h.assumptions)


def test_bridging_cannot_be_confirmed_without_the_reference_mixture(tmp_path, on_file):
    h = _sheet(tmp_path, "us_osha", ["H319"], ["Synthetic solvent  CAS 67-64-1  90%"],
               extra_two=["Classified by bridging principles from a tested mixture."])
    assert _rows(h)["H319"]["status"] == "cant"
    assert "needs the reference mixture" in _rows(h)["H319"]["reason"]


def test_an_input_a_that_is_not_reproducible_gives_no_verdict_and_shows_the_fallback(
        tmp_path, on_file):
    h = _sheet(tmp_path, "eu_clp", ["H225", "H350"], ["Synthetic aromatic  CAS 71-43-2  50%"])
    assert h.runs["A"]["available"] is False and "AI selection" in h.runs["A"]["why"]
    assert h.runs["A5"]["label"] == "first 5 codes (the app's own fallback)"
    assert all(not r["a"]["status"] for r in h.rows)
    assert any("a5" in r for r in h.rows)


def test_no_hazard_printed_and_none_given_says_so(tmp_path, on_file):
    h = _sheet(tmp_path, "us_osha", [], ["Water  CAS 7732-18-5  99%"])
    assert h.rows == [] and "give none" in h.message


def test_a_record_keeps_the_date_it_was_read_while_pubchem_says_the_same(tmp_path, monkeypatch):
    monkeypatch.setattr(pubchem, "folder", lambda: tmp_path)
    monkeypatch.setattr(pubchem, "fetch", lambda cas, use_cache=True: _record("67-64-1"))
    pubchem.write("67-64-1", today="2026-10-01")
    pubchem.write("67-64-1", today="2026-10-09")
    held = pubchem.load("67-64-1")
    assert held["retrieved"] == "2026-10-01" and held["source_url"].startswith("https://pubchem")


def test_a_product_chosen_later_is_judged_from_the_sheets_kept_context(tmp_path, on_file):
    from lingua_oracle.reference import verdict

    h = _sheet(tmp_path, "us_osha", ["H225", "H319"], ["Synthetic solvent  CAS 67-64-1  90%"])
    again = verdict.rebuild(h, "us_osha", [{"cas": "67-64-1", "name": "", "concentration": "90"}],
                            app_codes={"67-64-1": ["H225", "H319", "H335"]})
    rows = _rows(again)
    assert again.printed == h.printed and rows["H319"]["status"] == "confirmed"
    assert rows["H335"]["a"]["status"] == "wrong" and rows["H335"]["status"] == "confirmed"
