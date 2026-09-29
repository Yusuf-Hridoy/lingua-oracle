"""Regulation, language and section detection."""

from __future__ import annotations

import pytest

from lingua_oracle.detect.language import detect_language, looks_untranslated
from lingua_oracle.detect.regulation import RegulationUndetermined, detect_regulation
from lingua_oracle.detect.sections import LABEL, detect_sections
from lingua_oracle.extract import extract
from tests.conftest import pdf


def test_flag_always_wins():
    result = detect_regulation("nothing relevant here", flag="us_osha")
    assert result.regulation == "us_osha"
    assert result.detected_by == "flag"


def test_detects_eu_clp_from_text():
    result = detect_regulation("Prepared under Regulation (EC) No 1272/2008.")
    assert result.regulation == "eu_clp"
    assert result.detected_by == "auto"


def test_detects_osha_from_text():
    assert detect_regulation("See 29 CFR 1910.1200 for details.").regulation == "us_osha"


def test_never_guesses_silently():
    """No signal must produce an error naming the choices, not a guess."""
    with pytest.raises(RegulationUndetermined) as excinfo:
        detect_regulation("A document about nothing in particular.")
    assert "eu_clp" in str(excinfo.value)


def test_unknown_regulation_flag_is_rejected():
    with pytest.raises(KeyError, match="Unknown regulation"):
        detect_regulation("text", flag="atlantis")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Meget brandfarlig væske og damp. Holdes væk fra varme og gnister.", "da"),
        ("Hochentzündliche Flüssigkeit und Dampf. Von Hitze fernhalten.", "de"),
        ("Highly flammable liquid and vapour. Keep away from heat.", "en"),
        ("Liquide et vapeurs très inflammables. Tenir à l'écart de la chaleur.", "fr"),
    ],
)
def test_language_detection(text, expected):
    assert detect_language(text)[0] == expected


def test_language_flag_wins():
    assert detect_language("Highly flammable liquid.", flag="da") == ("da", "flag")


def test_looks_untranslated():
    assert looks_untranslated("Causes serious eye irritation and damage.", "da")
    assert not looks_untranslated("Forårsager alvorlig øjenirritation overalt.", "da")
    assert not looks_untranslated("Causes serious eye irritation.", "en")
    assert not looks_untranslated("Short", "da")  # too short to judge


def test_sections_detected_in_danish():
    document = extract(pdf("clean_eu_da"))
    names = {span.name for span in detect_sections(document, "da")}
    assert {"2", "3", "16"} <= names


def test_sections_detected_in_english():
    document = extract(pdf("clean_eu_en"))
    names = {span.name for span in detect_sections(document, "en")}
    assert {"2", "3", "16"} <= names


def test_label_block_is_detected():
    document = extract(pdf("defect_b09_label"))
    names = {span.name for span in detect_sections(document, "da")}
    assert LABEL in names
