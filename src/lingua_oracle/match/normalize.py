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
