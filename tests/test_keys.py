"""Answer-key schema, store, Tier B borrowing and CSV import."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from lingua_oracle.keys.csv_import import import_csv
from lingua_oracle.keys.store import available_regulations, key_path, load_key, save_key
from lingua_oracle.keys.tierb import resolve
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Kind, Status, Tier
from lingua_oracle.registry import load_registry


def test_registry_has_all_seven_regulations():
    ids = load_registry().ids()
    assert set(ids) == {
        "eu_clp", "uk_clp", "us_osha", "ca_whmis", "un_ghs", "au_whs", "jp_jis"
    }


def test_eu_key_covers_24_languages():
    registry = load_registry()
    assert len(registry.get("eu_clp").official_languages) == 24


def test_answer_key_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        AnswerKeyEntry(
            regulation="eu_clp", revision="r", language="en", code="H225",
            kind=Kind.HAZARD, text="t", nonsense=1,
        )


def test_answer_key_normalises_code():
    entry = AnswerKeyEntry(
        regulation="eu_clp", revision="r", language="en", code=" h225 ",
        kind=Kind.HAZARD, text="  Highly flammable.  ",
    )
    assert entry.code == "H225"
    assert entry.text == "Highly flammable."


def test_every_stored_key_validates():
    for regulation in available_regulations():
        directory = key_path(regulation, "x").parent
        for path in directory.glob("*.json"):
            AnswerKey.model_validate_json(path.read_text(encoding="utf-8"))


def test_eu_da_key_is_populated_and_tier_a():
    key = load_key("eu_clp", "da")
    assert key is not None and key.status is Status.OK
    by_code = key.by_code()
    assert by_code["H225"].text == "Meget brandfarlig væske og damp."
    assert by_code["H225"].tier is Tier.A
    assert by_code["SIGNAL_DANGER"].text == "Fare"
    assert by_code["SIGNAL_WARNING"].text == "Advarsel"


def test_eu_key_carries_source_provenance():
    key = load_key("eu_clp", "en")
    for entry in key.entries[:20]:
        assert entry.source_url and entry.source_ref and entry.retrieved_at


def test_new_euh_codes_are_present():
    by_code = load_key("eu_clp", "en").by_code()
    for code in ("EUH380", "EUH381", "EUH430", "EUH431",
                 "EUH440", "EUH441", "EUH450", "EUH451"):
        assert code in by_code, code


def test_combined_codes_are_present():
    by_code = load_key("eu_clp", "en").by_code()
    assert "P303+P361+P353" in by_code
    assert "H300+H310" in by_code


def test_per_code_signal_words_extracted():
    by_code = load_key("eu_clp", "en").by_code()
    assert by_code["H225"].signal_word == "Danger"
    assert by_code["H319"].signal_word == "Warning"


# (regulation, language) pairs with no usable source on file: the JIS PDF has no
# ToUnicode map so its text cannot be read, and no Arabic/Russian/Chinese GHS
# edition was supplied. Canada is no longer here - the HPR names GHS Rev.7 as its
# source, so WHMIS is built from that.
PENDING_PAIRS = [
    ("jp_jis", "ja"), ("jp_jis", "en"),
    ("un_ghs", "ar"), ("un_ghs", "ru"), ("un_ghs", "zh"),
]


@pytest.mark.parametrize(("regulation", "language"), PENDING_PAIRS)
def test_pending_source_keys_are_empty_not_invented(regulation, language):
    """A source we could not read must never be filled from memory."""
    key = load_key(regulation, language)
    if key is None:
        return
    assert key.status is Status.PENDING_SOURCE
    assert key.entries == []


def test_tier_b_borrows_when_english_matches(tmp_path, monkeypatch):
    """A regulation whose English text equals EU CLP's borrows the translation."""
    monkeypatch.setenv("LINGUA_DATA_DIR", str(tmp_path))
    import lingua_oracle.registry as registry_mod

    registry_mod.load_registry.cache_clear()
    (tmp_path / "answer_keys").mkdir(parents=True)
    (tmp_path / "regulations.yaml").write_text(
        json.dumps({"regulations": {
            "eu_clp": {"display_name": "EU", "revision": "r",
                       "official_languages": ["en", "da"]},
            "uk_clp": {"display_name": "UK", "revision": "r",
                       "official_languages": ["en"]},
        }}), encoding="utf-8")

    def entry(reg, lang, code, text):
        return AnswerKeyEntry(regulation=reg, revision="r", language=lang, code=code,
                              kind=Kind.HAZARD, text=text, tier=Tier.A)

    save_key(AnswerKey(regulation="eu_clp", language="en", revision="r", entries=[
        entry("eu_clp", "en", "H225", "Highly flammable liquid and vapour."),
        entry("eu_clp", "en", "H319", "Causes serious eye irritation."),
    ]))
    save_key(AnswerKey(regulation="eu_clp", language="da", revision="r", entries=[
        entry("eu_clp", "da", "H225", "Meget brandfarlig væske og damp."),
        entry("eu_clp", "da", "H319", "Forårsager alvorlig øjenirritation."),
    ]))
    save_key(AnswerKey(regulation="uk_clp", language="en", revision="r", entries=[
        entry("uk_clp", "en", "H225", "Highly flammable liquid and vapour."),
        entry("uk_clp", "en", "H319", "Causes serious eye damage."),  # differs
    ]))

    resolved = resolve("uk_clp", "da")
    assert "H225" in resolved.borrowed_codes
    assert resolved.entries["H225"].tier is Tier.B
    assert resolved.entries["H225"].text == "Meget brandfarlig væske og damp."
    # Differing English text must NOT borrow; it falls to tier C.
    assert "H319" in resolved.tier_c_codes
    assert "H319" not in resolved.entries
    registry_mod.load_registry.cache_clear()


def test_csv_import_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUA_DATA_DIR", str(tmp_path))
    import lingua_oracle.registry as registry_mod

    registry_mod.load_registry.cache_clear()
    (tmp_path / "regulations.yaml").write_text(
        json.dumps({"regulations": {"jp_jis": {
            "display_name": "JP", "revision": "r", "official_languages": ["ja"]}}}),
        encoding="utf-8")
    csv_file = tmp_path / "glossary.csv"
    csv_file.write_text(
        "code,text,kind\nH225,引火性液体,hazard\nP210,火気厳禁,precautionary\n",
        encoding="utf-8")

    key = import_csv(csv_file, "jp_jis", "ja", Tier.C)
    assert len(key.entries) == 2
    assert key.by_code()["H225"].tier is Tier.C
    assert key.by_code()["H225"].kind is Kind.HAZARD
    assert load_key("jp_jis", "ja") is not None
    registry_mod.load_registry.cache_clear()


def test_csv_import_rejects_missing_columns(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGUA_DATA_DIR", str(tmp_path))
    import lingua_oracle.registry as registry_mod

    registry_mod.load_registry.cache_clear()
    (tmp_path / "regulations.yaml").write_text(
        json.dumps({"regulations": {"jp_jis": {
            "display_name": "JP", "revision": "r", "official_languages": ["ja"]}}}),
        encoding="utf-8")
    bad = tmp_path / "bad.csv"
    bad.write_text("code\nH225\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required column"):
        import_csv(bad, "jp_jis", "ja", Tier.C)
    registry_mod.load_registry.cache_clear()


# -- keys built from the local official sources ----------------------------


@pytest.mark.parametrize(
    ("regulation", "language", "must_have"),
    [
        ("un_ghs", "en", ["H225", "P280", "P305+P351+P338"]),
        ("un_ghs", "fr", ["H225", "P280"]),
        ("un_ghs", "es", ["H225", "P280"]),
        ("uk_clp", "en", ["H225", "EUH066", "P280"]),
        ("au_whs", "en", ["H225", "AUH044", "AUH066"]),
        ("us_osha", "en", ["SIGNAL_DANGER", "SIGNAL_WARNING"]),
    ],
)
def test_built_keys_are_populated(regulation, language, must_have):
    key = load_key(regulation, language)
    assert key is not None, f"{regulation}/{language} missing"
    # OSHA is deliberately `partial`: Appendix C states no codes, so its key
    # holds fewer than EU CLP and the counts are not reconciled.
    assert key.status in (Status.OK, Status.PARTIAL)
    by_code = key.by_code()
    for code in must_have:
        assert code in by_code, f"{regulation}/{language} has no {code}"
        assert by_code[code].text.strip()


def test_built_keys_carry_provenance():
    """Every entry must be traceable to a source; nothing filled from memory."""
    for regulation in ("un_ghs", "uk_clp", "au_whs"):
        key = load_key(regulation, "en")
        assert key is not None and key.entries
        for entry in key.entries:
            assert entry.source_url, f"{regulation} {entry.code} has no source_url"
            assert entry.source_ref, f"{regulation} {entry.code} has no source_ref"
            assert entry.retrieved_at is not None


def test_australia_has_auh_and_uk_has_euh_but_not_swapped():
    """C-12 depends on these families belonging to the right regulation."""
    au = load_key("au_whs", "en").by_code()
    uk = load_key("uk_clp", "en").by_code()
    assert any(c.startswith("AUH") for c in au)
    assert not any(c.startswith("EUH") for c in au)
    assert any(c.startswith("EUH") for c in uk)
    assert not any(c.startswith("AUH") for c in uk)


def test_gb_clp_lacks_post_retention_eu_codes():
    """GB CLP is retained law: EU codes added after retention must be absent."""
    uk = load_key("uk_clp", "en").by_code()
    for code in ("EUH380", "EUH381", "EUH430", "EUH450"):
        assert code not in uk, f"{code} postdates GB retention and should not be present"


def test_japan_stays_pending_source():
    """The JIS PDF does not yield valid Japanese, so nothing may be recorded."""
    for language in ("ja", "en"):
        key = load_key("jp_jis", language)
        if key is None:
            continue
        assert key.status is Status.PENDING_SOURCE
        assert key.entries == []


def test_tier_b_activates_against_the_real_keys():
    """With UN GHS English on file, EU CLP translations become borrowable.

    Tier B was dormant while only EU CLP had a key; this is the end-to-end check
    that it now does real work, and that borrowed entries are marked tier B.
    """
    from lingua_oracle.keys.tierb import resolve

    resolved = resolve("un_ghs", "de")
    assert len(resolved.borrowed_codes) > 50
    for code in list(resolved.borrowed_codes)[:20]:
        entry = resolved.entries[code]
        assert entry.tier is Tier.B
        assert entry.regulation == "un_ghs"
        assert "borrowed from EU CLP" in (entry.source_ref or "")


def test_tier_b_does_not_borrow_for_eu_itself():
    from lingua_oracle.keys.tierb import resolve

    resolved = resolve("eu_clp", "da")
    assert resolved.borrowed_codes == set()
    assert all(e.tier is Tier.A for e in resolved.entries.values())


# -- US OSHA -----------------------------------------------------------------


@pytest.mark.parametrize("code", ["H225", "H350", "H360", "H372", "P210", "P280"])
def test_osha_key_has_required_codes(code):
    """Appendix C states no codes, so these are only present if the mapping works."""
    key = load_key("us_osha", "en")
    assert key is not None
    by_code = key.by_code()
    assert code in by_code, f"OSHA key is missing {code}"
    assert by_code[code].text.strip()
    assert by_code[code].source_ref and "1910.1200" in by_code[code].source_ref


def test_osha_key_has_both_families_and_is_marked_partial():
    key = load_key("us_osha", "en")
    codes = set(key.by_code())
    h = {c for c in codes if c.startswith("H")}
    p = {c for c in codes if c.startswith("P")}
    assert len(h) >= 40, f"expected OSHA hazard codes, got {len(h)}"
    assert len(p) >= 40, f"expected OSHA precautionary codes, got {len(p)}"
    assert key.status is Status.PARTIAL
    assert key.status_reason == "unrepresented_statements_remain"
    # the caveat must be stated on the key, not only in the parse report
    assert any("not represented by any code held" in n for n in key.notes)


def test_osha_carries_no_euh_codes():
    """EUH belongs to EU/UK CLP; C-12 depends on it being absent here."""
    assert not any(c.startswith("EUH") for c in load_key("us_osha", "en").by_code())


def test_osha_parse_issues_lists_codes_absent_from_osha():
    from lingua_oracle.keys.store import keys_root

    report = (keys_root() / "us_osha" / "_parse_issues.txt").read_text(encoding="utf-8")
    assert "GHS Rev.7 codes with no OSHA statement" in report
    assert "NOT" in report and "assumed to be gaps" in report


def test_japan_reason_is_wrong_source_not_just_pending():
    """The file on record is UN GHS Rev.9 Japanese, not JIS; nothing may be taken."""
    for language in ("ja", "en"):
        key = load_key("jp_jis", language)
        if key is None:
            continue
        assert key.status is Status.PENDING_SOURCE
        assert key.status_reason == "wrong_source"
        assert key.entries == []


def test_whmis_design_note_records_the_implemented_build():
    from lingua_oracle.keys.store import keys_root

    note = keys_root() / "ca_whmis" / "_design_note.md"
    assert note.exists(), "the WHMIS design note is referenced by the status reason"
    body = note.read_text(encoding="utf-8")
    assert "Seventh Revised Edition" in body
    assert "needs_ghs_rev8_annex3" in body


def test_stats_reports_partial_rather_than_inferring_ok():
    """A populated-but-incomplete key must not be reported as `ok`."""
    import json

    from typer.testing import CliRunner

    from lingua_oracle.cli import app

    result = CliRunner().invoke(app, ["keys", "stats", "--json"])
    assert result.exit_code == 0
    rows = {r["regulation"]: r for r in json.loads(result.output)}
    assert rows["us_osha"]["status"] == "partial"
    assert rows["us_osha"]["status_reasons"] == ["unrepresented_statements_remain"]
    assert rows["jp_jis"]["status_reasons"] == ["wrong_source"]
    assert rows["ca_whmis"]["status_reasons"] == []      # both languages are ok now


# -- signal words ------------------------------------------------------------


def _ok_keys():
    from lingua_oracle.keys.store import iter_all_keys

    return [k for k in iter_all_keys() if k.status is Status.OK and k.entries]


def test_every_ok_key_has_both_signal_words():
    """A key claiming `ok` must be able to answer check A-01 in both directions."""
    missing = []
    for key in _ok_keys():
        by_code = key.by_code()
        for code in ("SIGNAL_DANGER", "SIGNAL_WARNING"):
            if code not in by_code or not by_code[code].text.strip():
                missing.append(f"{key.regulation}/{key.language}:{code}")
    assert not missing, f"ok keys without signal words: {missing}"


def test_signal_words_are_tier_a_with_provenance():
    for key in _ok_keys():
        for code in ("SIGNAL_DANGER", "SIGNAL_WARNING"):
            entry = key.by_code().get(code)
            if entry is None:
                continue
            assert entry.tier is Tier.A
            assert entry.kind is Kind.SIGNAL
            assert entry.source_url and entry.source_ref


def test_greek_and_irish_signal_words_resolved():
    """Both needed a documented fallback; pin the results so they cannot regress."""
    greek = load_key("eu_clp", "el").by_code()
    assert greek["SIGNAL_WARNING"].text == "Προσοχή"
    assert "EUH206" in greek["SIGNAL_WARNING"].source_ref
    irish = load_key("eu_clp", "ga").by_code()
    assert irish["SIGNAL_DANGER"].text and irish["SIGNAL_WARNING"].text
    assert "32008R1272" in irish["SIGNAL_DANGER"].source_ref


# -- Canada WHMIS ------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "fr"])
def test_whmis_is_built_from_ghs_rev7(language):
    """The HPR defines GHS as the Seventh Revised Edition, so that is the source."""
    key = load_key("ca_whmis", language)
    assert key is not None and key.entries, f"ca_whmis/{language} is empty"
    by_code = key.by_code()
    for code in ("H225", "P210", "P280"):
        assert code in by_code, f"ca_whmis/{language} missing {code}"
    sample = by_code["H225"]
    assert sample.tier is Tier.A
    assert "Rev.7" in sample.source_ref
    assert "Seventh Revised Edition" in sample.source_ref


def test_whmis_languages_differ_and_are_not_translated():
    """English and French come from their own editions, not from each other."""
    en = load_key("ca_whmis", "en").by_code()
    fr = load_key("ca_whmis", "fr").by_code()
    assert en["H225"].text != fr["H225"].text
    assert set(en) & set(fr), "the two editions should share codes"


PRESSURE_CODES = ("H282", "H283", "H284")


def test_whmis_english_takes_chemicals_under_pressure_from_rev8():
    """The HPR sends that class to Rev.8, and the English edition is on file."""
    key = load_key("ca_whmis", "en")
    by_code = key.by_code()
    for code in PRESSURE_CODES:
        assert code in by_code, f"{code} should come from GHS Rev.8"
        assert "Rev.8" in by_code[code].source_ref
        assert by_code[code].tier is Tier.A
    # everything else must still come from Rev.7
    assert "Rev.7" in by_code["H225"].source_ref
    assert key.status is Status.OK
    assert key.status_reason is None



def test_whmis_parse_report_names_the_overlay():
    from lingua_oracle.keys.store import keys_root

    report = (keys_root() / "ca_whmis" / "_parse_issues.txt").read_text(encoding="utf-8")
    assert "Rev.8" in report
    assert "Canada-only classes" in report


# -- combined-code repair (UN GHS French) ------------------------------------


def test_french_combined_code_repaired():
    """P332+P317's code cell is truncated by table extraction; the page text repairs it."""
    fr = load_key("un_ghs", "fr").by_code()
    for code in ("P332+P317", "P333+P317", "P337+P317"):
        assert code in fr, f"un_ghs/fr is missing {code}"
    # the standalone codes must survive alongside the combined ones
    assert "P332" in fr and "P317" in fr
    assert fr["P332"].text != fr["P332+P317"].text


def test_combined_code_repair_is_scoped_to_the_page():
    """A page that defines the bare code standalone must not be rewritten."""
    from lingua_oracle.keys.builders.pdf_tables import combined_codes_on_page

    assert combined_codes_on_page("P332 + P317 Demander une aide.") == {"P332": "P332+P317"}
    assert combined_codes_on_page("P331 Ne PAS faire vomir. P332 En cas d'irritation :") == {}


# -- GHS edition overlay ------------------------------------------------------


def test_rev8_overlay_is_exactly_the_codes_rev7_lacks():
    """The overlay must stay as narrow as the regulation makes it."""
    from pathlib import Path

    from lingua_oracle.keys.builders.ghs_editions import pressure_overlay
    from lingua_oracle.registry import data_dir

    overlay, unchanged = pressure_overlay(Path(data_dir()) / "sources")
    assert set(overlay) == {"H282", "H283", "H284"}
    # the class's other codes are identical in Rev.7 and must not be overlaid
    assert set(unchanged) == {"P376", "P378", "P370+P378", "P410+P403"}
    assert not set(overlay) & set(unchanged)


def test_osha_uses_rev8_only_for_the_pressure_class():
    key = load_key("us_osha", "en")
    by_code = key.by_code()
    if "H284" in by_code:
        assert "Rev.8" in by_code["H284"].source_ref
    # everything else must still cite Rev.7
    assert "Rev.7" in by_code["H225"].source_ref
    assert "Rev.8" not in by_code["H225"].source_ref


def test_osha_notes_record_the_unverifiable_rendering_cases():
    key = load_key("us_osha", "en")
    assert key.status is Status.PARTIAL
    assert any("graphics" in n for n in key.notes), "the eCFR finding must be recorded"


def test_whmis_english_and_french_have_the_same_code_set():
    """Both languages are read from the same editions, so the codes must agree.

    Only the text may differ between them. Any divergence at all now means one
    edition was parsed less completely than the other.
    """
    en = set(load_key("ca_whmis", "en").by_code())
    fr = set(load_key("ca_whmis", "fr").by_code())
    assert en == fr, {"only_en": sorted(en - fr), "only_fr": sorted(fr - en)}


def test_damaged_cell_recovered_only_with_an_edition_proof():
    """P302+P335+P334's Rev.7 English cell is unreadable; Rev.8 supplies the text.

    The recovery is licensed by the French edition showing the statement unchanged
    between Rev.7 and Rev.8, and the entry must say so.
    """
    entry = load_key("ca_whmis", "en").by_code()["P302+P335+P334"]
    assert entry.tier is Tier.A
    assert "Rev.8" in entry.source_ref
    assert "unchanged between Rev.7 and Rev.8" in entry.source_ref
    assert "document-vs-key matching stays exact" in entry.source_ref


def test_edition_proof_spacing_licence_is_not_used_by_the_matcher():
    """The French-spacing licence is for comparing editions, never for checking.

    A document that differs from the key by a space before a colon must still be
    reported, so the matcher must not treat the two as identical.
    """
    from lingua_oracle.match.template import MatchKind, match

    result = match("EN CAS DE CONTACT AVEC LA PEAU: Rincer.",
                   "EN CAS DE CONTACT AVEC LA PEAU : Rincer.")
    assert result.kind is not MatchKind.EXACT


def test_whmis_both_languages_are_ok_and_carry_the_rev8_overlay():
    for language in ("en", "fr"):
        key = load_key("ca_whmis", language)
        assert key.status is Status.OK
        assert key.status_reason is None
        by_code = key.by_code()
        for code in ("H282", "H283", "H284"):
            assert code in by_code, f"{language} is missing {code}"
            assert "Rev.8" in by_code[code].source_ref
            assert by_code[code].tier is Tier.A
    # and the two languages really are different text, not a copy
    assert load_key("ca_whmis", "en").by_code()["H284"].text != (
        load_key("ca_whmis", "fr").by_code()["H284"].text
    )
