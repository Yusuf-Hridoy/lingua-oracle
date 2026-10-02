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


# -- third-party sheets name their regulation in their own words ---------------

MARKER_SHEETS = {
    # EU CLP
    "eu_clp_1272": ("eu_clp", "Classified according to Regulation (EC) No 1272/2008."),
    "eu_clp_spaced": ("eu_clp", "in accordance with 1272 / 2008 as amended"),
    "eu_reach": ("eu_clp", "Safety data sheet according to Regulation (EC) No 1907/2006"),
    "eu_878": ("eu_clp", "Prepared under Commission Regulation (EU) 2020/878"),
    "eu_clp_named": ("eu_clp", "Classification under the CLP Regulation and REACH."),
    "eu_by_euh": ("eu_clp", "Supplemental: EUH066 Repeated exposure may cause dryness."),
    # US OSHA
    "osha_cfr": ("us_osha", "This chemical is hazardous under 29 CFR 1910.1200."),
    "osha_cfr_spaced": ("us_osha", "see 29CFR1910.1200 Appendix C for details"),
    "osha_hcs": ("us_osha", "Classified under HCS 2012."),
    "osha_hazcom": ("us_osha", "Prepared to HazCom 2012 requirements."),
    "osha_standard": ("us_osha", "Meets the Hazard Communication Standard."),
    # Canada WHMIS
    "ca_whmis": ("ca_whmis", "WHMIS 2015 classification shown below."),
    "ca_hpr": ("ca_whmis", "Classified under the Hazardous Products Regulations."),
    "ca_sor": ("ca_whmis", "Hazardous Products Regulations SOR/2015-17 apply."),
    "ca_bilingual": ("ca_whmis",
                     "SECTION 2: Hazards identification. Hazard statements. "
                     "RUBRIQUE 2: Identification des dangers. Mentions de danger. "
                     "WHMIS"),
    # UK GB CLP
    "uk_gbclp": ("uk_clp", "Classified under GB CLP."),
    "uk_reach": ("uk_clp", "Registered under UK REACH; Great Britain."),
    "uk_retained": ("uk_clp", "Classified under retained Regulation 1272/2008 for GB."),
    # Australia
    "au_swa": ("au_whs", "Prepared per Safe Work Australia guidance."),
    "au_whs_regs": ("au_whs", "Classified under the WHS Regulations."),
    "au_code": ("au_whs", "See the Model Code of Practice for labelling."),
    "au_by_auh": ("au_whs", "AUH001 Explosive when dry. Work Health and Safety."),
    # UN GHS
    "un_rev": ("un_ghs", "Classified to GHS Rev. 11."),
    "un_long": ("un_ghs", "United Nations Globally Harmonized System of classification."),
    "un_bare": ("un_ghs", "Classified according to GHS."),
}


@pytest.mark.parametrize(("name", "expected", "text"),
                         [(n, r, t) for n, (r, t) in MARKER_SHEETS.items()])
def test_a_marker_identifies_its_regulation(name, expected, text):
    from lingua_oracle.detect.regulation import detect_regulation

    result = detect_regulation(text)
    assert result.regulation == expected, (name, result.scores)
    assert result.evidence.get(expected), name


def test_bare_ghs_loses_to_anything_more_specific():
    """Every sheet mentions GHS; it names the UN text only on its own."""
    from lingua_oracle.detect.regulation import detect_regulation

    assert detect_regulation("Classified according to GHS.").regulation == "un_ghs"
    mixed = detect_regulation(
        "Classified according to GHS and Regulation (EC) No 1272/2008."
    )
    assert mixed.regulation == "eu_clp"
    assert "GHS" not in mixed.evidence.get("un_ghs", [])


def test_euh_codes_only_support_uk_with_a_gb_marker():
    from lingua_oracle.detect.regulation import _content_evidence

    plain = _content_evidence("EUH066 Repeated exposure may cause skin dryness.")
    assert "eu_clp" in plain and "uk_clp" not in plain
    gb = _content_evidence("GB CLP applies. EUH066 Repeated exposure.")
    assert "uk_clp" in gb


@pytest.mark.parametrize(
    "text",
    [
        "Classified under (EC) No 1272/2008 and 29 CFR 1910.1200.",
        "WHMIS 2015 classification. Safe Work Australia.",
        "This sheet mentions no regulation at all, only a product name.",
    ],
)
def test_an_ambiguous_sheet_asks_instead_of_guessing(text):
    from lingua_oracle.detect.regulation import (
        RegulationUndetermined,
        detect_regulation,
    )

    with pytest.raises(RegulationUndetermined):
        detect_regulation(text)


def test_the_reason_is_recorded_for_the_report():
    from lingua_oracle.detect.regulation import detect_regulation

    result = detect_regulation(
        "Prepared under 29 CFR 1910.1200, the Hazard Communication Standard."
    )
    assert result.regulation == "us_osha"
    assert "29 CFR 1910.1200" in result.evidence["us_osha"]
    assert "Hazard Communication Standard" in result.evidence["us_osha"]


def test_the_report_says_why_the_regulation_was_chosen():
    from lingua_oracle.pipeline import check_pdf

    report = check_pdf(pdf("clean_osha_en"))
    assert report.regulation == "us_osha"
    reasons = [n for n in report.notes if n.startswith("Regulation read from")]
    assert reasons, report.notes
    assert "29 CFR 1910.1200" in reasons[0]


@pytest.mark.parametrize(
    "text",
    [
        # Spellings found on real third-party sheets: no ".1200", and "OSHA
        # HCS" rather than "HCS 2012".
        "GHS Classification in accordance with 29 CFR 1910 (OSHA HCS)",
        "Classification in accordance with 29CFR1910.1200",
        "per 29 CFR 1910 . 1200",
    ],
)
def test_third_party_spellings_of_the_osha_standard(text):
    from lingua_oracle.detect.regulation import detect_regulation

    assert detect_regulation(text).regulation == "us_osha"


def test_one_named_instrument_outweighs_an_inferred_code():
    """An EU code on an OSHA sheet is a finding, not a second candidate."""
    from lingua_oracle.detect.regulation import detect_regulation

    result = detect_regulation(
        "Prepared under 29 CFR 1910.1200 (Hazard Communication). "
        "EUH066 Repeated exposure may cause skin dryness or cracking."
    )
    assert result.regulation == "us_osha"
    assert result.scores["eu_clp"] > 0, "the EU evidence is still recorded"


def test_two_named_instruments_still_ask():
    from lingua_oracle.detect.regulation import (
        RegulationUndetermined,
        detect_regulation,
    )

    with pytest.raises(RegulationUndetermined):
        detect_regulation(
            "Classified under (EC) No 1272/2008 and under 29 CFR 1910.1200."
        )
