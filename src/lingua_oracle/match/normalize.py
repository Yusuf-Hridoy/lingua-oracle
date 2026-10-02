"""Text normalisation shared by extraction and matching."""

from __future__ import annotations

import re
import unicodedata

# Characters that vary freely between PDF producers and mean the same thing.
_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "«": '"', "»": '"',
}
_DASHES = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "­": "",  # soft hyphen disappears
}
_SPACES = {
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", " ": " ", "\t": " ",
}
_ZERO_WIDTH = {"​": "", "‌": "", "‍": "", "﻿": ""}

_TRANSLATION = str.maketrans({**_QUOTES, **_DASHES, **_SPACES, **_ZERO_WIDTH})

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    """NFC, unified quotes/dashes/spaces, collapsed whitespace, trimmed.

    Punctuation is preserved: callers that want punctuation-insensitive
    comparison use `strip_punctuation` on top of this.
    """
    if not text:
        return ""
    out = unicodedata.normalize("NFC", text)
    out = out.translate(_TRANSLATION)
    out = out.replace("...", "…")
    out = re.sub(r"…+", "…", out)
    out = " ".join(out.split())
    return out.strip()


# An ellipsis marks a mandatory fill-in, so it is content rather than
# punctuation: dropping it would let "Wash thoroughly after handling." pass
# against the template "Wash … thoroughly after handling."
_ELLIPSIS_SENTINEL = "x7fillinx7"


def strip_punctuation(text: str) -> str:
    """Normalised text with punctuation removed, for punctuation-only diffs."""
    guarded = text.replace("…", f" {_ELLIPSIS_SENTINEL} ")
    return " ".join(_PUNCT_RE.sub(" ", guarded).split())


def casefold_key(text: str) -> str:
    """Comparison key ignoring case, for lenient secondary comparisons."""
    return normalize(text).casefold()


def dehyphenate(lines: list[str]) -> str:
    """Join lines, repairing words split by a hyphen at a line end."""
    out: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if (
            i + 1 < len(lines)
            and stripped.endswith("-")
            and len(stripped) > 1
            and stripped[-2].isalpha()
            and lines[i + 1][:1].islower()
        ):
            out.append(stripped[:-1])
        else:
            out.append(stripped + " ")
    return normalize("".join(out))


# Letters that are the same shape in two alphabets. The consolidated CLP text
# has at least one of them typed in the wrong one - Part 2's Greek P261 opens
# with U+0041 LATIN CAPITAL A where the sentence needs U+0391 GREEK CAPITAL
# ALPHA - and a document that types it correctly would otherwise fail against
# the regulator's own slip. The text is never rewritten: this is used to compare
# two renderings, never to produce one.
#
# Only the pairs that are genuinely indistinguishable are here. Greek lower-case
# is left alone apart from omicron: alpha, nu and rho are near-misses, not
# twins, and folding a near-miss would hide a real difference.
_LATIN_TO_GREEK = {
    "A": "Α", "B": "Β", "E": "Ε", "Z": "Ζ", "H": "Η", "I": "Ι", "K": "Κ",
    "M": "Μ", "N": "Ν", "O": "Ο", "P": "Ρ", "T": "Τ", "Y": "Υ", "X": "Χ",
    "o": "ο",
}
_LATIN_TO_CYRILLIC = {
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К", "M": "М",
    "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
}
#: Which fold applies to which language. Both sides of a comparison are folded,
#: so a Latin unit like "kg" or "50 °C" still compares equal to itself.
_HOMOGLYPH_FOLDS = {
    "el": str.maketrans(_LATIN_TO_GREEK),
    "bg": str.maketrans(_LATIN_TO_CYRILLIC),
}


def folds_homoglyphs(language: str | None) -> bool:
    return language in _HOMOGLYPH_FOLDS


def fold_homoglyphs(text: str, language: str | None) -> str:
    """Map Latin letters onto their twins in the language's own alphabet."""
    table = _HOMOGLYPH_FOLDS.get(language or "")
    return text.translate(table) if table else text
