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


def test_pending_source_keys_are_empty_not_invented():
    """A source we could not fetch must never be filled from memory."""
    for regulation in ("uk_clp", "un_ghs", "au_whs", "ca_whmis", "jp_jis"):
        for language in load_registry().get(regulation).official_languages:
            key = load_key(regulation, language)
            if key is None:
                continue
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
