"""US/UK spelling variants, applied when comparing statements across sources.

OSHA writes American English; the UN GHS text this tool compares against writes
British English. The difference is orthographic, not substantive - "vapor" and
"vapour" are the same word - so folding it is not a judgement about meaning.

The table is deliberately explicit and short rather than a general -our/-or or
-ize/-ise rule: a blanket rule would also rewrite words where the two spellings
are not equivalent, and would be impossible to review. Every pair below is a
plain orthographic variant of one word. Add to it only after checking the pair
actually occurs in the sources.

Folding runs on whole words only, so it cannot corrupt a substring of an
unrelated word.
"""

from __future__ import annotations

import re

#: US spelling -> UK spelling. One direction only; both sides are folded to UK.
VARIANTS: dict[str, str] = {
    "vapor": "vapour",
    "vapors": "vapours",
    "center": "centre",
    "centers": "centres",
    "color": "colour",
    "colors": "colours",
    "colored": "coloured",
    "odor": "odour",
    "odors": "odours",
    "fiber": "fibre",
    "fibers": "fibres",
    "liter": "litre",
    "liters": "litres",
    "meter": "metre",
    "meters": "metres",
    "sulfur": "sulphur",
    "aluminum": "aluminium",
    "gray": "grey",
    "jewelry": "jewellery",
    "pressurized": "pressurised",
    "categorized": "categorised",
    "sensitized": "sensitised",
    "utilized": "utilised",
    "vaporize": "vapourise",
    "smolder": "smoulder",
    "smoldering": "smouldering",
    "practice": "practise",
}

_WORD_RE = re.compile(r"[A-Za-z]+")


def fold(text: str) -> str:
    """Rewrite US spellings to their UK equivalents, whole words only."""
    return _WORD_RE.sub(lambda m: VARIANTS.get(m.group(0).lower(), m.group(0)), text)
