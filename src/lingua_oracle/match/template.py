"""Matching document phrases against official template text.

Official GHS/CLP texts are not fixed strings. They carry three kinds of choice:

* **slash alternatives** - ``Wear protective gloves/protective clothing/eye
  protection/face protection.`` A document may keep any non-empty subset, in the
  official order, joined by ``/`` or ``,``.
* **fill-ins** - ``…`` or ``<state route of exposure>``. Any non-empty text is
  acceptable; the filled value is reported as ``info`` for human review.
* **optional groups** - ``[electrical/ventilating/lighting/…]``. The bracketed
  part may be dropped, and the brackets themselves may or may not be printed.

Where a slash run begins is genuinely ambiguous in the source text: in
``Get medical advice/attention.`` the alternatives are *advice* and *attention*,
but in ``Wear protective gloves/protective clothing`` the first alternative is
the two-word *protective gloves*. Rather than guess one split, every candidate
split is compiled and the phrase passes if **any** of them matches. A false
failure on correct official wording is far more damaging to this tool's
credibility than mild leniency.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations

from lingua_oracle.match.normalize import normalize, strip_punctuation

# A fill-in: an ellipsis, or an <instruction> the author must replace.
# Adjacent fill-ins separated only by spaces are treated as one slot, so that
# "<or state all organs affected> <state route of exposure>" reports a single
# readable value instead of an arbitrary split across the two.
_FILLIN_RE = re.compile(r"(?:<[^<>]*>|…)(?:\s*(?:<[^<>]*>|…))*")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s")
_MAX_ALTS = 8  # official texts never exceed this; caps subset enumeration


class MatchKind(StrEnum):
    EXACT = "exact"
    TEMPLATE = "template"
    PUNCTUATION = "punctuation"
    CASE = "case"
    MISMATCH = "mismatch"


@dataclass
class MatchResult:
    matched: bool
    kind: MatchKind
    fillins: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def is_clean(self) -> bool:
        return self.matched and self.kind in (MatchKind.EXACT, MatchKind.TEMPLATE)


def has_template_syntax(text: str) -> bool:
    return bool(_FILLIN_RE.search(text)) or "/" in text or "[" in text


# --------------------------------------------------------------------------
# Compiling a template into regexes
# --------------------------------------------------------------------------


# Group names must be unique within a single compiled pattern, and `_lit` is
# called many times while building one. A process-wide counter keeps them apart.
_GROUP_SEQ = itertools.count()


def _lit(text: str) -> str:
    """Escape literal text, letting whitespace float and fill-ins match anything."""
    parts = []
    pos = 0
    for m in _FILLIN_RE.finditer(text):
        parts.append(_escape_ws(text[pos : m.start()]))
        parts.append(rf"(?P<fill_{next(_GROUP_SEQ)}>[^\s].*?)")
        pos = m.end()
    parts.append(_escape_ws(text[pos:]))
    return "".join(parts)


def _escape_ws(text: str) -> str:
    """Escape text, treating runs of whitespace as flexible."""
    chunks = text.split()
    if not chunks:
        return r"\s*" if text else ""
    body = r"\s+".join(re.escape(c) for c in chunks)
    lead = r"\s*" if text[:1].isspace() else ""
    trail = r"\s*" if text[-1:].isspace() else ""
    return f"{lead}{body}{trail}"


def _ordered_subsets(items: list[str]) -> list[tuple[str, ...]]:
    """Every non-empty subset of `items`, preserving the official order."""
    out: list[tuple[str, ...]] = []
    n = min(len(items), _MAX_ALTS)
    idx = range(n)
    for size in range(n, 0, -1):
        for combo in combinations(idx, size):
            out.append(tuple(items[i] for i in combo))
    return out


def _alt_group_pattern(alts: list[str]) -> str:
    """Regex matching any non-empty ordered subset joined by '/' or ','."""
    sep = r"\s*(?:/|,|\band\b|\bor\b)\s*"
    branches = []
    for combo in _ordered_subsets(alts):
        branches.append(sep.join(_lit(a.strip()) for a in combo))
    # Longest (most alternatives) first so the fullest match wins.
    return "(?:" + "|".join(branches) + ")"


@dataclass
class _Run:
    """A maximal `a/b/c` run inside the template."""

    start: int
    end: int
    atoms: list[str]


def _find_runs(text: str) -> list[_Run]:
    runs: list[_Run] = []
    for m in re.finditer(r"[^/\n]+(?:/[^/\n]+)+", text):
        seg = m.group(0)
        runs.append(_Run(m.start(), m.end(), seg.split("/")))
    return runs


def _split_candidates_first(atom: str) -> list[tuple[str, str]]:
    """Ways to cut leading literal from the first alternative, longest literal first."""
    words = atom.split(" ")
    out: list[tuple[str, str]] = []
    # try taking 1..len words as the alternative (i.e. cut point from the right)
    for take in range(1, len(words) + 1):
        literal = " ".join(words[: len(words) - take])
        alt = " ".join(words[len(words) - take :])
        if not alt.strip():
            continue
        out.append((literal + (" " if literal else ""), alt))
    return out


def _split_candidates_last(atom: str) -> list[tuple[str, str]]:
    """Ways to cut a trailing literal off the last alternative."""
    out: list[tuple[str, str]] = []
    # Cut at the first sentence end, if any (e.g. '…. Protect from moisture.').
    parts = _SENTENCE_END_RE.split(atom, maxsplit=1)
    if len(parts) == 2:
        out.append((parts[0], " " + parts[1]))
    # Cut trailing sentence punctuation.
    m = re.match(r"^(.*?)([\s.;:!?]*)$", atom, re.DOTALL)
    if m and m.group(1).strip():
        out.append((m.group(1), m.group(2)))
    out.append((atom, ""))
    seen, uniq = set(), []
    for a, b in out:
        if (a, b) not in seen:
            seen.add((a, b))
            uniq.append((a, b))
    return uniq


def _optional_brackets(pattern_text: str) -> str:
    """Turn `[...]` groups into optional, bracket-tolerant regions."""
    return pattern_text


def _compile_variants(template: str) -> list[re.Pattern[str]]:
    """Compile every plausible reading of a template into an anchored regex."""
    tpl = normalize(template)
    variants: list[str] = []

    # Handle optional [ ... ] groups by also trying the version with them removed
    # and the version with brackets stripped but content kept.
    bodies = {tpl}
    if "[" in tpl and "]" in tpl:
        bodies.add(re.sub(r"\s*\[[^\[\]]*\]\s*", " ", tpl))
        bodies.add(tpl.replace("[", "").replace("]", ""))

    for body in bodies:
        runs = _find_runs(body)
        if not runs:
            variants.append(_lit(body))
            continue
        run = runs[0]  # official texts contain at most one slash run per phrase
        prefix_text = body[: run.start]
        suffix_text = body[run.end :]
        atoms = run.atoms
        first_opts = _split_candidates_first(atoms[0])
        last_opts = _split_candidates_last(atoms[-1]) if len(atoms) > 1 else [(atoms[-1], "")]
        for lead, first_alt in first_opts:
            for last_alt, trail in last_opts:
                alts = [first_alt, *atoms[1:-1], last_alt] if len(atoms) > 1 else [first_alt]
                alts = [a for a in alts if a.strip()]
                if not alts:
                    continue
                pattern = (
                    _lit(prefix_text + lead)
                    + _alt_group_pattern(alts)
                    + _lit(trail + suffix_text)
                )
                variants.append(pattern)

    compiled: list[re.Pattern[str]] = []
    seen: set[str] = set()
    for v in variants:
        if v in seen:
            continue
        seen.add(v)
        try:
            compiled.append(re.compile(r"^\s*" + _optional_brackets(v) + r"\s*$", re.IGNORECASE))
        except re.error:
            continue
    return compiled


_CACHE: dict[str, list[re.Pattern[str]]] = {}


def compile_template(template: str) -> list[re.Pattern[str]]:
    if template not in _CACHE:
        _CACHE[template] = _compile_variants(template)
    return _CACHE[template]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def match(found: str, template: str) -> MatchResult:
    """Compare a phrase from a document against official template text."""
    f = normalize(found)
    t = normalize(template)
    if not f:
        return MatchResult(False, MatchKind.MISMATCH, message="empty text in document")

    if f == t:
        return MatchResult(True, MatchKind.EXACT)
    if f.casefold() == t.casefold():
        return MatchResult(True, MatchKind.CASE, message="differs only in letter case")

    for pattern in compile_template(t):
        m = pattern.match(f)
        if m:
            fillins = [v for k, v in (m.groupdict() or {}).items()
                       if k.startswith("fill_") and v and v.strip()]
            return MatchResult(True, MatchKind.TEMPLATE, fillins=fillins)

    if strip_punctuation(f) == strip_punctuation(t):
        return MatchResult(True, MatchKind.PUNCTUATION, message="differs only in punctuation")
    if strip_punctuation(f).casefold() == strip_punctuation(t).casefold():
        return MatchResult(True, MatchKind.PUNCTUATION,
                           message="differs only in punctuation and letter case")

    return MatchResult(False, MatchKind.MISMATCH, message="text does not match official wording")
