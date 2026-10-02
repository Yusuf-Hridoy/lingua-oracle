"""Visible defects in an official rendering of a statement.

Choosing the text in force decides *which* of the act's two renderings to hold.
It does not promise that rendering is clean. The consolidation is typed by
people, and the Part that happens to be in force sometimes carries a slip the
other Part does not: a degree sign that never made it in, a blank the author of
the row dropped, a sentence left without its full stop, a Latin ``A`` at the
start of a Greek sentence.

What follows from one depends on what it costs. A defect that loses *meaning* -
a blank with nowhere to put the value, a temperature with no scale - makes the
entry unusable: it is withheld, because a correct sheet would be judged against
a sentence that no longer says what it must, and guessing the repair in code
would be inventing regulatory text. A defect that costs only *appearance* - a
sentence that stops without its full stop, a letter typed in the wrong alphabet
- is carried, because the comparison already handles it: a full stop a document
adds or drops is reported as something to check, never as wrong wording, and
homoglyphs fold in the Greek and Bulgarian comparisons.

Either way the defect is recorded, so the audit shows what is in the text.

Each check is deliberately narrow and says what it saw, so a human reviewing
``data/audits/eu_clp_part1_vs_part2.md`` can decide which it is.
"""

from __future__ import annotations

import re
import unicodedata

#: Latin tokens that belong in a sentence written in any script: units, symbols
#: and the regulation's own code letters.
_UNIT_WORDS = {
    "kg", "g", "mg", "l", "ml", "lb", "lbs", "m", "cm", "mm", "km", "kpa", "pa",
    "c", "f", "k", "ph", "un", "ec", "eu", "cas", "ce", "pbt", "vpvb", "x",
}
_UNIT_TOKEN = re.compile(r"[\d…]\s*(?:°\s*)?[CF]\b|\b(?:kg|lbs?|°C|°F)\b")
_FILL = "…"


def _script(ch: str) -> str | None:
    if not ch.isalpha():
        return None
    name = unicodedata.name(ch, "")
    return name.split()[0] if name else None


def _words(text: str) -> list[str]:
    return text.replace(_FILL, f" {_FILL} ").split()


def _aligned(text: str) -> list[str]:
    """Words with surrounding punctuation removed, so a dropped blank shows up.

    "naudoti." and "naudoti" are the same word; without this the full stop that
    moved when the blank was dropped would read as a different sentence.
    """
    out = []
    for word in _words(text):
        bare = word.strip(".,;:!?'\u2019\u201c\u201d()[]/\u2014\u2013-")
        if bare:
            out.append(bare)
    return out


#: Defect kinds that make an entry unusable. The rest are recorded and carried:
#: the comparison handles them without judging a correct sheet wrongly.
WITHHOLDING = frozenset({"blank", "degree sign", "dropped words"})


def wrong_script(text: str) -> str | None:
    """A letter from another alphabet inside the sentence.

    Part 2's Greek P261 opens with U+0041 LATIN CAPITAL A where the sentence
    needs U+0391 GREEK CAPITAL ALPHA. It reads identically and compares as a
    different string, so every correct Greek sheet would fail on it.
    """
    counts: dict[str, int] = {}
    for ch in text:
        script = _script(ch)
        if script:
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return None
    main = max(counts, key=lambda s: counts[s])
    if main not in {"GREEK", "CYRILLIC"} or "LATIN" not in counts:
        return None
    stray = []
    for token in re.split(r"[\s/()\[\],;:.]+", text):
        letters = [c for c in token if c.isalpha()]
        if not letters or not any(_script(c) == "LATIN" for c in letters):
            continue
        bare = "".join(c for c in token if c.isalpha()).casefold()
        if bare in _UNIT_WORDS:
            continue
        stray.append(token)
    if not stray:
        return None
    first = stray[0]
    bad = next(c for c in first if _script(c) == "LATIN")
    return (f"a {main.lower()} sentence containing the latin character "
            f"{bad!r} (U+{ord(bad):04X}) in {first!r}")


def missing_degree_sign(text: str) -> str | None:
    """One temperature unit has its degree sign and the other does not."""
    units = re.findall(r"(?:^|[\s/…\d])(°?)\s*([CF])\b", text)
    if len(units) < 2:
        return None
    if any(d for d, _ in units) and any(not d for d, _ in units):
        return "a temperature unit without its degree sign"
    return None


def missing_terminator(text: str, other: str | None) -> str | None:
    """A sentence left without the full stop the other Part gives it.

    A statement that ends in an open option - ".../hearing protection/…" - has
    no full stop by design: the author is meant to continue it. Only a sentence
    that simply stops counts.
    """
    if not other or not other.rstrip().endswith((".", "!", "?")):
        return None
    stripped = text.rstrip()
    if stripped.endswith((".", "!", "?", _FILL, "...", ":")):
        return None
    tail = stripped[-1] if stripped else ""
    return (f"the sentence ends {tail!r} where the other Part ends it with a "
            "full stop")


def missing_blank(text: str, other: str | None) -> str | None:
    """Fewer fill-ins than the same sentence has in the other Part."""
    if not other:
        return None
    here, there = text.count(_FILL), other.count(_FILL)
    if here >= there:
        return None
    if [w for w in _aligned(text) if w != _FILL] != [
            w for w in _aligned(other) if w != _FILL]:
        return None  # the wording differs too; not a dropped blank
    return (f"{there - here} fill-in(s) fewer than the same sentence has in the "
            "other Part")


def dropped_words(text: str, other: str | None) -> str | None:
    """Words missing from an otherwise identical sentence, around a unit.

    Only reported when what is missing carries a unit or a blank - "/… lbs"
    dropped from a mass, say. A shorter sentence is not a defect in itself: an
    amendment is allowed to shorten one.
    """
    if not other:
        return None
    here, there = _aligned(text), _aligned(other)
    if here == there or len(here) >= len(there):
        return None
    i, missing = 0, []
    for word in there:
        if i < len(here) and here[i] == word:
            i += 1
        else:
            missing.append(word)
    if i != len(here) or not missing:
        return None  # not a subsequence: the wording differs, not a drop
    gap = " ".join(missing)
    if _FILL not in gap and not _UNIT_TOKEN.search(gap):
        return None
    return f"missing {gap!r}, which the same sentence carries in the other Part"


def defects(text: str, other: str | None = None) -> list[tuple[str, str]]:
    """Every visible defect in `text`, as (kind, what was seen).

    `other` is the rendering in the other Part, used as evidence of what the
    sentence carries when it is whole.
    """
    blank = missing_blank(text, other)
    found = [
        ("wrong script", wrong_script(text)),
        ("degree sign", missing_degree_sign(text)),
        ("terminator", missing_terminator(text, other)),
        ("blank", blank),
        # A dropped blank is already named; saying it twice helps nobody.
        ("dropped words", None if blank else dropped_words(text, other)),
    ]
    return [(kind, message) for kind, message in found if message]


def withholding(found: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The defects that make an entry unusable, out of everything seen."""
    return [(kind, message) for kind, message in found if kind in WITHHOLDING]
