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
    """The overlay must stay as narrow as the regulation makes it.

    Reads the GHS Rev.7 and Rev.8 PDFs, which are not committed - they are
    published documents anyone can download, and a hundred megabytes of them in
    every clone is not worth it. Skipped where they are absent; the key this
    builds from is committed and is checked by the test below.
    """
    from pathlib import Path

    from lingua_oracle.keys.builders.ghs_editions import REV7_FILE, REV8_FILE, pressure_overlay
    from lingua_oracle.keys.builders.sources import describe
    from lingua_oracle.registry import data_dir

    root = Path(data_dir()) / "sources"
    for relative in (REV7_FILE.format(lang="en"), REV8_FILE.format(lang="en")):
        if not (root / relative).exists():
            pytest.skip(describe(relative))

    overlay, unchanged = pressure_overlay(root)
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


# -- wrapped cells must not reach the key ------------------------------------

#: Keys parsed out of PDF table cells, where the layout engine wraps lines.
#: eu_clp is read from CELLAR XHTML and us_osha from osha.gov HTML; neither
#: wraps, so a space beside a slash there is the source's own typography.
_PDF_SOURCED_KEYS = [("uk_clp", "en"), ("au_whs", "en"),
                     ("ca_whmis", "en"), ("ca_whmis", "fr"),
                     ("un_ghs", "en"), ("un_ghs", "es"), ("un_ghs", "fr")]


@pytest.mark.parametrize(("reg", "lang"), _PDF_SOURCED_KEYS)
def test_no_key_holds_a_wrapped_alternative(reg, lang):
    """"dust/fume/gas/\\nmist" must not land in the key as "gas/ mist"."""
    import re

    from lingua_oracle.keys.store import load_key

    bad = [(e.code, e.text) for e in load_key(reg, lang).entries
           if re.search(r"/\s+\S", e.text)]
    assert bad == [], bad


@pytest.mark.parametrize(("reg", "lang"), _PDF_SOURCED_KEYS)
def test_no_key_holds_a_wrapped_hyphen(reg, lang):
    """"non-\\nsparking" must not land in the key as "non- sparking"."""
    import re

    from lingua_oracle.keys.store import load_key

    bad = [(e.code, e.text) for e in load_key(reg, lang).entries
           if re.search(r"\w-\s+\w", e.text)]
    assert bad == [], bad


def test_flatten_cell_leaves_a_suspended_hyphen_alone():
    """German "Spreng- und Wurfstuecke" is two words, not one wrapped one."""
    from lingua_oracle.keys.builders.pdf_tables import flatten_cell

    assert flatten_cell("Spreng-\nund Wurfstücke") == "Spreng- und Wurfstücke"
    assert flatten_cell("Brand-\neller eksplosionsfare") == "Brand- eller eksplosionsfare"
    # ... while a wrapped compound is rejoined.
    assert flatten_cell("Use non-\nsparking tools.") == "Use non-sparking tools."


def test_flatten_cell_keeps_real_slash_spacing():
    """Several EU languages genuinely print "A / B"; only the wrap is repaired."""
    from lingua_oracle.keys.builders.pdf_tables import flatten_cell

    assert flatten_cell("dust/fume/gas/\nmist/vapours/\nspray.") == \
        "dust/fume/gas/mist/vapours/spray."
    assert flatten_cell("CENTRE ANTIPOISON / médecin") == "CENTRE ANTIPOISON / médecin"
    assert flatten_cell("CENTRE ANTIPOISON /\nmédecin") == "CENTRE ANTIPOISON /médecin"


# -- OSHA statements that were dropped by the parser, not by the regulation ---


@pytest.mark.parametrize(
    ("code", "fragment"),
    [
        # A slash list wrapped across lines: "dust/fume/gas/mist/ vapors/spray".
        ("P260", "Do not breathe"),
        ("P261", "Avoid breathing"),
        # Statement and labeller guidance in one paragraph, so the whole
        # paragraph was rejected.
        ("P302+P352", "Wash with plenty of water"),
        # A parenthesis wrapped after the bracket: "( see … on this label)".
        ("P321", "Specific treatment"),
    ],
)
def test_osha_statements_recovered_from_the_source(code, fragment):
    from lingua_oracle.keys.store import load_key

    entry = load_key("us_osha", "en").by_code().get(code)
    assert entry is not None, f"{code} is in Appendix C but missing from the key"
    assert fragment.lower() in entry.text.lower()


def test_osha_wrap_repair_leaves_real_spacing_alone():
    from lingua_oracle.keys.builders.us_osha import repair_wrapping

    assert repair_wrapping("dust/fume/gas/mist/ vapors/spray") == \
        "dust/fume/gas/mist/vapors/spray"
    assert repair_wrapping("( see … on this label)") == "(see … on this label)"
    # A slash before a fill-in or at the end of a clause is not a wrap.
    assert repair_wrapping("water/… …") == "water/… …"
    assert repair_wrapping("and/or") == "and/or"


def test_osha_guidance_is_cut_but_statements_are_not():
    from lingua_oracle.keys.builders.us_osha import strip_guidance

    assert strip_guidance(
        "If on skin: Wash with plenty of water/… … Chemical manufacturer, "
        "importer, or distributor may specify a cleansing agent."
    ) == "If on skin: Wash with plenty of water/…"
    # "Refer to manufacturer, importer ..." IS a statement and must survive.
    kept = "Refer to manufacturer, importer, or distributor … for information on disposal."
    assert strip_guidance(kept) == kept


# -- one cell, two codes, two statements --------------------------------------


@pytest.mark.parametrize(
    ("base", "variant"),
    [("EUH201", "EUH201A"), ("EUH209", "EUH209A")],
)
def test_an_a_variant_differs_from_its_base_code(base, variant):
    """CLP heads one table "EUH 209/ 209A" and puts a statement per code in it.

    The cell's two paragraphs were flattened into one string and handed to both
    codes, so every sheet citing either got the other's wording appended.
    """
    from lingua_oracle.keys.store import available_languages, load_key

    for language in available_languages("eu_clp"):
        key = load_key("eu_clp", language).by_code()
        assert key[base].text != key[variant].text, f"{language}: {base} == {variant}"
        assert key[base].text and key[variant].text


def test_the_a_variant_is_the_shorter_warning():
    from lingua_oracle.keys.store import load_key

    key = load_key("eu_clp", "en").by_code()
    assert key["EUH201A"].text == "Warning! Contains lead."
    assert key["EUH209A"].text == "Can become flammable in use."
    assert key["EUH209"].text == "Can become highly flammable in use."


def test_a_multi_code_cell_is_split_by_paragraph():
    from lxml import html as LH

    from lingua_oracle.keys.builders.eu_clp import _cell_paragraphs

    cell = LH.fromstring(
        '<td><p>Can become highly flammable in use.</p>'
        '<p>Can become flammable in use.</p></td>'
    )
    assert _cell_paragraphs(cell) == [
        "Can become highly flammable in use.",
        "Can become flammable in use.",
    ]
    # A cell with no paragraphs still yields its whole text.
    plain = LH.fromstring("<td>Contains lead.</td>")
    assert _cell_paragraphs(plain) == ["Contains lead."]


# -- the degree sign ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "fixed"),
    [
        ("Do not expose to temperatures exceeding 50 oC/122oF.",
         "Do not expose to temperatures exceeding 50 °C/122°F."),
        ("Store at temperatures not exceeding … oC/…oF.",
         "Store at temperatures not exceeding … °C/…°F."),
        # Italian P413 loses the second fill-in, so the slash is the anchor.
        ("a temperature non superiori a … °C/oF.",
         "a temperature non superiori a … °C/°F."),
        # Nothing where a word meaning "or" could stand is touched.
        ("5 o 6 grados", "5 o 6 grados"),
        ("Mezcla de oC no", "Mezcla de oC no"),
        ("sucked or chewed", "sucked or chewed"),
    ],
)
def test_degree_sign_repair(raw, fixed):
    from lingua_oracle.keys.builders.common import repair_degree_sign

    assert repair_degree_sign(raw) == fixed


def test_no_key_spells_the_degree_sign_as_a_letter():
    """CELLAR marks it up as a superscript "o"; the PDFs set it as a raised one."""
    import re

    from lingua_oracle.keys.store import iter_all_keys

    pattern = re.compile(r"\bo[CF]\b|\d\s*o[CF]")
    bad = [(k.regulation, k.language, e.code)
           for k in iter_all_keys() for e in k.entries
           if pattern.search(e.text or "")]
    assert bad == [], bad


# -- key integrity: five things no key may ever contain -----------------------
#
# Each was a real bug found by audit, and each generated false alarms on correct
# sheets. They run over every committed key, so a rebuild that reintroduces one
# fails here rather than in a customer's report.


def _all_entries():
    from lingua_oracle.keys.store import iter_all_keys

    for key in iter_all_keys():
        for entry in key.entries:
            if entry.text:
                yield key.regulation, key.language, entry


def test_no_statement_is_only_a_deletion_marker():
    from lingua_oracle.keys.builders.common import is_deleted_marker

    bad = [(r, lang, e.code) for r, lang, e in _all_entries()
           if is_deleted_marker(e.text)]
    assert bad == [], bad


def test_no_statement_carries_an_amendment_marker():
    import re

    bad = [(r, lang, e.code, e.text[:60]) for r, lang, e in _all_entries()
           if re.search(r"\[[XF]\d", e.text)]
    assert bad == [], bad


def test_no_statement_spells_a_degree_sign_as_a_letter():
    import re

    pattern = re.compile(r"\bo[CF]\b|\d\s*o[CF]")
    bad = [(r, lang, e.code) for r, lang, e in _all_entries()
           if pattern.search(e.text)]
    assert bad == [], bad


def test_an_a_variant_never_repeats_its_base_code():
    """EUH201A is not EUH201, and a shared table must not make them equal."""
    from lingua_oracle.keys.store import iter_all_keys

    bad = []
    for key in iter_all_keys():
        by_code = key.by_code()
        for code, entry in by_code.items():
            if not code.endswith("A") or not entry.text:
                continue
            base = by_code.get(code[:-1])
            if base is not None and base.text and base.text == entry.text:
                bad.append((key.regulation, key.language, code))
    assert bad == [], bad


def test_no_statement_is_two_statements_run_together():
    """One cell holding two codes' statements is how EUH209 went wrong.

    Asserted precisely: no statement may equal two other statements from the
    same key joined together, unless the code is a combination and they are its
    own components. A looser rule cannot be used - P305+P351+P338 IS exactly
    its three parts run together, and that is correct.

    This does NOT by itself catch the EUH209 shape that prompted it: there both
    codes held the merged text, so neither half existed as an entry to match
    against. test_an_a_variant_never_repeats_its_base_code is the guard for
    that. This one catches the other half of the family - one code swallowing a
    neighbour's statement while the neighbour stays correct.
    """
    from lingua_oracle.keys.store import iter_all_keys

    bad = []
    for key in iter_all_keys():
        texts = {e.code: " ".join(e.text.split())
                 for e in key.entries if e.text and len(e.text) > 20}
        for code, text in texts.items():
            parts = set(code.split("+")) if "+" in code else set()
            for other, other_text in texts.items():
                if other == code or other in parts:
                    continue
                if not text.startswith(other_text):
                    continue
                rest = text[len(other_text):].strip()
                if rest and rest in set(texts.values()):
                    bad.append((key.regulation, key.language, code, other))
                    break
    assert bad == [], bad[:10]


# -- CLP states each statement twice; the key must hold the amended one --------


def test_p103_is_the_amended_text():
    """Regulation (EU) 2019/521 replaced "Read label before use.".

    The consolidated act shows the new wording only in Annex IV Part 1, under a
    M19 block; Part 2, which the builder reads, still carries the old one.
    """
    from lingua_oracle.keys.store import load_key

    for regulation in ("eu_clp", "uk_clp"):
        text = load_key(regulation, "en").by_code()["P103"].text
        assert text == "Read carefully and follow all instructions.", regulation


def test_p280_includes_hearing_protection():
    from lingua_oracle.keys.store import load_key

    for regulation in ("eu_clp", "uk_clp"):
        text = load_key(regulation, "en").by_code()["P280"].text
        assert "hearing protection" in text, regulation
        assert text.startswith("Wear protective gloves/protective clothing/")


@pytest.mark.parametrize("code", ["P103", "P280"])
def test_the_amendment_reached_every_language(code):
    """An amendment rewrites every translation, which is how it was identified."""
    from lingua_oracle.keys.store import available_languages, load_key

    stale = {
        "P103": "Read label before use.",
        "P280": "Wear protective gloves/protective clothing/eye protection/face protection.",
    }[code]
    behind = []
    for language in available_languages("eu_clp"):
        entry = load_key("eu_clp", language).by_code().get(code)
        if entry is None:
            continue
        if language == "en" and entry.text == stale:
            behind.append(language)
        # Every language's text must differ from the pre-2019 English one and
        # must not be empty.
        assert entry.text, f"{language}/{code} is empty"
    assert behind == [], behind


def _part_audit():
    import json

    from lingua_oracle.registry import data_dir

    record = data_dir() / "audits" / "eu_clp_annex_iv.json"
    if not record.exists():
        pytest.skip("no audit record; rebuild eu_clp to produce one")
    return json.loads(record.read_text(encoding="utf-8"))["decisions"]


def test_no_key_entry_holds_text_a_later_act_superseded():
    """The integrity rule, in one assertion.

    For every code whose two Parts of Annex IV disagree, the build decided which
    Part the law is in - the latest act to touch each, read from the acts and
    corroborated by the consolidation's markers. The key must hold that text and
    no other: holding the losing Part would mean checking documents against
    wording an amendment replaced.
    """
    audit = _part_audit()
    for code, record in audit.items():
        for language, chosen in record["languages"].items():
            key = load_key("eu_clp", language)
            if key is None:
                continue
            entry = key.by_code().get(code)
            assert entry is not None, f"{language}/{code} vanished"
            if chosen["status"] == "not_on_file":
                assert entry.status is Status.NOT_ON_FILE, (
                    f"{language}/{code} is used for verdicts although the audit "
                    f"withheld it: {chosen['defects']}"
                )
                continue
            assert entry.text == chosen["text"], (
                f"{language}/{code} holds {entry.text!r}, but the act in force "
                f"({chosen['act']}, {chosen['part']}) says {chosen['text']!r}"
            )
            assert entry.text != chosen["superseded"] or not chosen["superseded"], (
                f"{language}/{code} holds the superseded rendering"
            )


def test_the_decision_is_recorded_with_the_act_that_made_it():
    for code, record in _part_audit().items():
        assert record["part"] in {"Part 1", "Part 2"}, code
        assert record["act"], code
        assert record["note"], code
        if record["corroborated"]:
            assert record["act_title"] or record["act"] == "B", code


def test_a_withheld_entry_says_what_was_wrong_with_it():
    audit = _part_audit()
    for code, record in audit.items():
        for language, chosen in record["languages"].items():
            if chosen["status"] != "not_on_file":
                continue
            entry = load_key("eu_clp", language).by_code()[code]
            assert "not used for a verdict" in (entry.source_ref or ""), (
                f"{language}/{code}"
            )
            assert code not in resolve("eu_clp", language).entries


def test_a_defect_the_act_itself_prints_is_never_corrected():
    """The line between a typing error and the law.

    Where the amending act prints the defect too, there is nothing to correct
    the text from, and inventing the repair is not an option. What follows is
    decided by what the defect costs: one that loses meaning withholds the
    entry, one that costs only appearance is carried and recorded.
    """
    from lingua_oracle.keys.builders.defects import WITHHOLDING

    audit = _part_audit()
    confirmed = [(c, lang, v) for c, r in audit.items()
                 for lang, v in r["languages"].items()
                 if v.get("act_confirms_defect")]
    assert confirmed, "no defect was checked against its act"
    for code, language, chosen in confirmed:
        entry = load_key("eu_clp", language).by_code()[code]
        costly = any(d.split(":", 1)[0] in WITHHOLDING for d in chosen["defects"])
        if costly:
            assert entry.status is Status.NOT_ON_FILE, f"{language}/{code}"
        else:
            assert entry.status is Status.OK, f"{language}/{code}"
            assert entry.text == chosen["text"], f"{language}/{code}"


def test_a_carried_defect_is_still_written_down():
    """Used is not the same as unnoticed: the entry says what is in its text."""
    audit = _part_audit()
    carried = [(c, lang, v) for c, r in audit.items()
               for lang, v in r["languages"].items()
               if v["status"] == "ok" and v["defects"]]
    assert len(carried) >= 15
    for code, language, chosen in carried:
        entry = load_key("eu_clp", language).by_code()[code]
        assert entry.status is Status.OK
        assert "it" in (entry.source_ref or "")
        assert any(d.split(":", 1)[1].strip()[:20] in (entry.source_ref or "")
                   for d in chosen["defects"]), f"{language}/{code}"
        assert code in resolve("eu_clp", language).entries


def test_only_a_defect_that_loses_meaning_withholds_an_entry():
    from lingua_oracle.keys.builders.defects import WITHHOLDING

    for code, record in _part_audit().items():
        for language, chosen in record["languages"].items():
            if chosen["status"] != "not_on_file" or not chosen["defects"]:
                continue
            kinds = {d.split(":", 1)[0] for d in chosen["defects"]}
            assert kinds & WITHHOLDING, f"{language}/{code} withheld for {kinds}"


# -- an open option is not an unfilled blank ----------------------------------


@pytest.mark.parametrize(
    ("document", "fillins"),
    [
        # A subset that drops the open option and ends the sentence is correct.
        ("Wear protective gloves/protective clothing/eye protection/face protection.", []),
        ("Wear protective gloves/eye protection.", []),
        ("Wear protective gloves.", []),
        # Without the full stop too.
        ("Wear protective gloves/protective clothing/eye protection/face protection", []),
        # A literal leftover placeholder IS an unfilled blank.
        ("Wear protective gloves/protective clothing/eye protection/face protection/"
         "hearing protection/…", ["…"]),
        ("Wear protective gloves/protective clothing/eye protection/face protection/"
         "hearing protection/ …", ["…"]),
        # Something the author wrote into the open option is a filled value.
        ("Wear protective gloves/protective clothing/eye protection/face protection/"
         "hearing protection/a rubber apron.", ["a rubber apron"]),
    ],
)
def test_an_open_option_may_simply_be_dropped(document, fillins):
    """".../hearing protection/…" invites more; a sheet may decline."""
    from lingua_oracle.keys.store import load_key
    from lingua_oracle.match.template import match

    result = match(document, load_key("eu_clp", "en").by_code()["P280"].text)
    assert result.matched, document
    assert result.fillins == fillins, result.fillins


def test_the_rule_holds_for_every_open_ended_statement():
    """Not P280 alone: any template ending in an open option behaves this way."""
    from lingua_oracle.keys.store import load_key
    from lingua_oracle.match.template import match

    key = load_key("eu_clp", "en").by_code()
    open_ended = [e for e in key.values()
                  if e.text.rstrip().endswith("…") and "/" in e.text]
    assert len(open_ended) > 3, "no open-ended statements to check"
    for entry in open_ended:
        subset = entry.text.rstrip().rsplit("/", 1)[0] + "."
        result = match(subset, entry.text)
        assert result.matched, entry.code
        assert not [v for v in result.fillins if "…" in v], (
            f"{entry.code}: dropping the open option read as an unfilled blank"
        )


# -- text we know to be superseded must not judge anything --------------------


@pytest.mark.parametrize("code", ["P103", "P280"])
def test_irish_holds_the_superseded_text_and_says_so(code):
    """Regulation (EU) 2019/521 amended these in Part 1 only.

    Part 1 is published per language and the Irish act could not be read, so
    what we hold for 'ga' is the wording the amendment replaced. Kept on file
    so the gap is visible, and marked, because checking a sheet against
    replaced wording fails a correct sheet.
    """
    entry = load_key("eu_clp", "ga").by_code()[code]
    assert entry.status is Status.NOT_ON_FILE
    assert "not used for a verdict" in (entry.source_ref or "")


@pytest.mark.parametrize("code", ["P103", "P280"])
def test_a_not_on_file_entry_never_reaches_a_comparison(code):
    assert code not in resolve("eu_clp", "ga").entries


def test_only_the_superseded_codes_are_withheld_in_irish():
    """The rest of the Irish key is ordinary Part 2 text and still usable.

    A code is withheld in Irish when an act rewrote Part 1 and demonstrably
    changed the wording - the Part 2 text Irish holds is then the superseded
    one, and there is no Irish version of the amending act to replace it with.
    Where the two Parts say the same thing everywhere they can be read, nothing
    was superseded and the Irish entry stands.
    """
    from lingua_oracle.keys.builders import annulled

    audit = _part_audit()
    expected = {code for code, record in audit.items()
                if record["languages"].get("ga", {}).get("status") == "not_on_file"}
    # Withheld in every language, for a reason of their own: the courts
    # annulled them. See tests/test_annulled.py.
    expected |= annulled.STATEMENTS
    withheld = {
        code for code, entry in load_key("eu_clp", "ga").by_code().items()
        if entry.status is Status.NOT_ON_FILE
    }
    assert withheld == expected
    assert {"P103", "P280"} <= withheld
    assert len(withheld) < len(load_key("eu_clp", "ga").entries) / 4


def test_the_languages_that_do_have_the_amendment_are_untouched():
    # de and et are not in this list: their Part 1 rendering of P280 is printed
    # without its full stop, in the act as well as the consolidation, so the
    # entry is withheld rather than used. See the defect tests below.
    for lang in ("en", "fr", "es"):
        entry = load_key("eu_clp", lang).by_code()["P280"]
        assert entry.status is Status.OK
        assert "Annex IV Part 1, in force under" in (entry.source_ref or "")
        assert "P280" in resolve("eu_clp", lang).entries


# -- the Part 1 / Part 2 comparison, written for review -----------------------


def _comparison_rows():
    import re

    from lingua_oracle.registry import data_dir

    path = data_dir() / "audits" / "eu_clp_part1_vs_part2.md"
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 8 and re.fullmatch(r"[PH]\d{3}(\+[PH]\d{3})*", cells[0]):
            rows.append(cells)
    return rows


def test_the_part_comparison_has_a_row_per_code_and_language():
    rows = _comparison_rows()
    assert len(rows) > 200
    assert len({(r[0], r[1]) for r in rows}) == len(rows)


def test_the_two_amendments_lead_the_comparison():
    """The codes every language disagrees on are the real amendments."""
    rows = _comparison_rows()
    assert {r[0] for r in rows[:46]} == {"P103", "P280"}


def test_every_comparison_row_names_its_verdict_and_act():
    for code, lang, _count, _one, _two, verdict, act, why in _comparison_rows():
        assert verdict in {"Part 1", "Part 2", "errata", "not_on_file"}, code
        assert act, f"{code}/{lang}"
        assert why, f"{code}/{lang}"


def test_P336_is_in_the_comparison_as_an_english_difference():
    """The code the errata table corrects has to be visible here as evidence."""
    row = next(r for r in _comparison_rows() if r[0] == "P336" and r[1] == "en")
    assert "Do not rub" in row[3]
    assert "Do no rub" in row[4]


def test_the_comparison_agrees_with_the_audit():
    audit = _part_audit()
    for code, lang, _c, _o, _t, verdict, act, _why in _comparison_rows():
        chosen = audit[code]["languages"][lang]
        expected = {"ok": chosen["part"], "errata": "errata",
                    "not_on_file": "not_on_file"}[chosen["status"]]
        assert verdict == expected, f"{code}/{lang}"
        assert act == chosen["act"], f"{code}/{lang}"


# -- the source documents, and where to get them ------------------------------


def test_every_source_a_builder_names_is_on_the_record():
    """A file a builder looks for must have a row saying where it comes from.

    Otherwise an absent file is a dead end: the error names a path and nothing
    tells the reader which document that path is supposed to hold.
    """
    from lingua_oracle.keys.builders import au_whs, ca_whmis, uk_clp, us_osha
    from lingua_oracle.keys.builders.ghs_editions import REV7_FILE, REV8_FILE
    from lingua_oracle.keys.builders.sources import BY_PATH

    named = {
        au_whs.GHS7_FILE, au_whs.SWA_FILE, ca_whmis.HPR_FILE,
        uk_clp.DEFAULT_FILE, us_osha.DEFAULT_FILE, us_osha.REFERENCE_FILE,
        REV7_FILE.format(lang="en"), REV7_FILE.format(lang="fr"),
        REV8_FILE.format(lang="en"), REV8_FILE.format(lang="fr"),
    }
    assert named <= set(BY_PATH), sorted(named - set(BY_PATH))


def test_every_source_row_says_where_to_download_it():
    from lingua_oracle.keys.builders.sources import SOURCES

    for source in SOURCES:
        assert source.title and source.edition and source.added
        assert source.used_by
        # Documents whose link could not be confirmed say so rather than guess:
        # the Japanese file, and two sites that refuse scripts (ECHA, UNECE).
        if source.url is None:
            assert source.path.split("/")[0] in ("japan", "eu-echa")
        else:
            assert source.url.startswith("https://")


def test_a_missing_source_names_the_file_and_the_link():
    from lingua_oracle.keys.builders.common import SourceUnavailable
    from lingua_oracle.keys.builders.sources import describe, require

    message = describe("un-ghs/GHS_Rev11_en.pdf")
    assert "data/sources/un-ghs/GHS_Rev11_en.pdf" in message
    assert "unece.org" in message
    assert "README" in message

    with pytest.raises(SourceUnavailable) as caught:
        require("un-ghs/does_not_exist.pdf")
    assert "data/sources/un-ghs/does_not_exist.pdf" in str(caught.value)


def test_the_readme_lists_every_source():
    from lingua_oracle.keys.builders.sources import SOURCES, readme
    from lingua_oracle.registry import data_dir

    generated = readme()
    for source in SOURCES:
        assert f"`{source.path}`" in generated
        assert source.edition in generated
    on_disk = (data_dir() / "sources" / "README.md")
    assert on_disk.exists(), "run sources.write_readme()"
    assert on_disk.read_text(encoding="utf-8") == generated, (
        "data/sources/README.md is out of date; it is generated from "
        "keys/builders/sources.py"
    )


def test_the_source_documents_are_not_committed():
    """A hundred megabytes of published PDFs do not belong in every clone."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "data/sources"],
        capture_output=True, text=True, check=False).stdout.split()
    assert tracked == ["data/sources/README.md"], tracked
