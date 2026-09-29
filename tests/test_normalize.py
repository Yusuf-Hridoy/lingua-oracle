"""Unit tests for the text normalizer."""

from __future__ import annotations

import pytest

from lingua_oracle.match.normalize import (
    casefold_key,
    dehyphenate,
    normalize,
    strip_punctuation,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Highly   flammable  ", "Highly flammable"),
        ("quotes ‘a’ and “b”", "quotes 'a' and \"b\""),
        ("dash – and — and −", "dash - and - and -"),
        ("soft­hyphen", "softhyphen"),
        ("non breaking space", "non breaking space"),
        ("zero​width", "zerowidth"),
        ("dots... and …", "dots… and …"),
        ("", ""),
    ],
)
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_normalize_is_idempotent():
    text = "  Causes “serious” eye damage – really…  "
    assert normalize(normalize(text)) == normalize(text)


def test_strip_punctuation_keeps_words():
    assert strip_punctuation(normalize("Danger! Causes damage.")) == "Danger Causes damage"


def test_strip_punctuation_keeps_ellipsis_as_content():
    """An unfilled fill-in must not vanish into 'punctuation-only'."""
    with_fill = strip_punctuation(normalize("Wash … thoroughly after handling."))
    without = strip_punctuation(normalize("Wash thoroughly after handling."))
    assert with_fill != without


def test_casefold_key():
    assert casefold_key("HIGHLY Flammable") == casefold_key("highly flammable")


def test_dehyphenate_rejoins_split_words():
    assert dehyphenate(["Highly flamma-", "ble liquid and", "vapour."]) == (
        "Highly flammable liquid and vapour."
    )


def test_dehyphenate_keeps_real_hyphens():
    assert "explosion-proof" in dehyphenate(["Use explosion-proof", "Equipment."])
