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

from lingua_oracle.match.normalize import (
    fold_homoglyphs,
    folds_homoglyphs,
    normalize,
    strip_punctuation,
)

# A fill-in: an ellipsis, an <instruction>, or a (parenthetical instruction).
# The sources write the same slot three ways - EU CLP uses angle brackets, the
# GHS Annex 3 tables use parentheses, and both use the ellipsis - so a matcher
# that knew only angle brackets treated "(state all organs affected, if known)"
# as literal text the document had to reproduce word for word.
#
# Only *directive* parentheticals count, ones opening with an instruction to the
# author. Treating every parenthetical as a slot would erase real content such
# as EUH206's "(chlorine)" and let two different statements compare equal.
#
# Adjacent fill-ins separated only by spaces are treated as one slot, so that
# "<or state all organs affected> <state route of exposure>" reports a single
# readable value instead of an arbitrary split across the two.
_DIRECTIVE = r"(?:or\s+)?(?:state|specify|indicate|insert|list|name\s+of)\b"
_FILLIN_ATOM = rf"(?:<[^<>]*>|\(\s*{_DIRECTIVE}[^()]{{0,240}}\)|…)"
_FILLIN_RE = re.compile(rf"{_FILLIN_ATOM}(?:\s*{_FILLIN_ATOM})*", re.IGNORECASE)

# Some slots are conditional by the source's own words: "<or state all organs
# affected, if known>", "<state route of exposure if it is conclusively proven
# that no other routes of exposure cause the hazard>". An author who does not
# know the organs, or cannot prove the route, is meant to leave them out - so
# requiring them failed correct sheets. These two phrasings are the only
# conditional forms in any key on file.
_CONDITIONAL_SLOT_RE = re.compile(
    r"\bif\s+known\b|\bif\s+it\s+is\s+conclusively\s+proven\b", re.IGNORECASE
)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s")
# Two places where PDF producers move a space and nothing is meant by it:
# beside a fill-in ellipsis ("Use… to" / "Use … to"), and between a number and
# the symbol that qualifies it ("50°C" / "50 °C", "50%" / "50 %").
#
# This is deliberately NOT a general "ignore all whitespace" rule. French
# typography puts a space before ':' ';' '!' '?', and the user ruled that
# document-vs-key matching stays exact there - a licence granted for comparing
# editions of a source, never for judging a document. Widening this to every
# space would silently revoke that decision, and
# test_edition_proof_spacing_licence_is_not_used_by_the_matcher pins it.
_FILLIN_SPACE_RE = re.compile(r"\s*…\s*")
_UNIT_SPACE_RE = re.compile(r"(?<=\d)\s+(?=[^\w\s])")


def _spacing_key(text: str) -> str:
    """Text with only the two non-significant spacings collapsed."""
    return _UNIT_SPACE_RE.sub("", _FILLIN_SPACE_RE.sub("…", text))
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
        # Allow whitespace between the literal and the value. A template may
        # abut the two ("[and…]", "Use…") while the document that fills it in
        # naturally writes a space ("and other specified body parts").
        group = rf"\s*(?P<fill_{next(_GROUP_SEQ)}>[^\s].*?)"
        if _CONDITIONAL_SLOT_RE.search(m.group(0)):
            group = f"(?:{group})?"
        parts.append(group)
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


def _compile_variants(template: str, *, ignore_case: bool = True) -> list[re.Pattern[str]]:
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

    # A statement ending in an open option - ".../hearing protection/…" - has no
    # full stop, because the author is meant to continue it. One who takes a
    # subset and stops writes the sentence out: "…/face protection." Without
    # this, the only reading that matched was the one where the open option
    # swallowed "face protection." as if it were filled in, so a correct subset
    # came back as an unfinished blank.
    closing = r"[.!?]?" if tpl.rstrip().endswith("…") else ""

    compiled: list[re.Pattern[str]] = []
    seen: set[str] = set()
    for v in variants:
        if v in seen:
            continue
        seen.add(v)
        flags = re.IGNORECASE if ignore_case else 0
        try:
            pattern = re.compile(
                r"^\s*" + _optional_brackets(v) + closing + r"\s*$", flags
            )
        except re.error:
            continue
        if pattern.match(_CATCHALL_PROBE):
            # This reading reduced to "anything at all". It happens when the
            # leading literal is cut away AND the chosen subset of alternatives
            # is nothing but a fill-in, leaving a bare `.*?` between anchors -
            # e.g. "IF ON SKIN: Wash with plenty of water/…" once compiled that
            # way matched every sentence ever written, so A-03 could not fail a
            # wrong statement for any code whose text ends in "/…".
            # A variant that matches the probe carries no literal to check
            # against and can only ever produce false passes.
            continue
        compiled.append(pattern)
    return compiled


# Text sharing no word with any official statement. A compiled variant that
# matches it is a catch-all, not a reading of the template.
_CATCHALL_PROBE = "zzq unrelated probe text zzq"

_CACHE: dict[tuple[str, bool], list[re.Pattern[str]]] = {}


def compile_template(template: str, *, ignore_case: bool = True) -> list[re.Pattern[str]]:
    key = (template, ignore_case)
    if key not in _CACHE:
        _CACHE[key] = _compile_variants(template, ignore_case=ignore_case)
    return _CACHE[key]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


_TERMINATORS = (".", "!", "?")


def match(found: str, template: str, *, optional_terminator: bool = False,
          language: str | None = None) -> MatchResult:
    """Compare a phrase from a document against official template text.

    `optional_terminator` is for a regulation whose own rendering prints the
    statements without a closing full stop (us_osha - see the note in
    data/regulations.yaml). It lets the document end the sentence normally and
    report nothing at all. It never works the other way round: a document that
    DROPS a terminator the official text has is still a difference, and no
    other punctuation moves.

    `language` enables the homoglyph fold for the alphabets that share letter
    shapes with Latin. It is a second attempt, made only when the plain
    comparison has already failed, so a document is never judged against
    anything but its own text.
    """
    f = normalize(found)
    t = normalize(template)
    if not f:
        return MatchResult(False, MatchKind.MISMATCH, message="empty text in document")
    result = _compare(f, t, optional_terminator=optional_terminator)
    if result.matched or not folds_homoglyphs(language):
        return result
    folded_f, folded_t = (fold_homoglyphs(f, language), fold_homoglyphs(t, language))
    if (folded_f, folded_t) == (f, t):
        return result
    return _compare(folded_f, folded_t, optional_terminator=optional_terminator)


def _compare(f: str, t: str, *, optional_terminator: bool) -> MatchResult:
    if optional_terminator and not t.endswith(_TERMINATORS) and f.endswith(_TERMINATORS):
        f = f[:-1].rstrip()

    if f == t:
        # Word for word the official text - placeholder and all. A sheet that
        # ships the blank still in it is not finished, and matching exactly is
        # exactly how that happens: the comparison never reaches the fill-in.
        unfilled = ["…"] if "…" in f and _FILLIN_RE.search(t) else []
        return MatchResult(True, MatchKind.EXACT, fillins=unfilled)
    if _spacing_key(f) == _spacing_key(t):
        # Spacing only. If the template has a fill-in, the document reproduced
        # it verbatim rather than filling it, so report the value for review -
        # a clean pass here must not silently swallow an unfilled slot.
        unfilled = ["…"] if "…" in f and _FILLIN_RE.search(t) else []
        return MatchResult(True, MatchKind.EXACT, fillins=unfilled)
    if f.casefold() == t.casefold():
        return MatchResult(True, MatchKind.CASE, message="differs only in capitalisation")

    def _fillins(m: re.Match[str]) -> list[str]:
        return [v for k, v in (m.groupdict() or {}).items()
                if k.startswith("fill_") and v and v.strip()]

    # Case-sensitive first. The permissive pass below exists so a capitalisation
    # difference is REPORTED rather than passed over: matching the template
    # case-insensitively and returning a clean result would make "Rinse SKIN"
    # indistinguishable from "Rinse skin", which is the one outcome that must
    # not happen - never a fail, never silent.
    for pattern in compile_template(t, ignore_case=False):
        m = pattern.match(f)
        if m:
            return MatchResult(True, MatchKind.TEMPLATE, fillins=_fillins(m))
    for pattern in compile_template(t):
        m = pattern.match(f)
        if m:
            return MatchResult(True, MatchKind.CASE, fillins=_fillins(m),
                               message="differs only in capitalisation")

    # The official text of several statements stops without a full stop - the
    # consolidation prints "…/Gehörschutz/… tragen" that way, and so does the
    # act. An author who writes the sentence out ends it normally, and the only
    # difference is that full stop. It is reported, never failed: the subset the
    # author chose is correct, so this goes through the template again with the
    # terminator set aside rather than falling through to a mismatch.
    if not t.endswith(_TERMINATORS) and f.endswith(_TERMINATORS):
        trimmed = f[:-1].rstrip()
        for patterns, message in (
            (compile_template(t, ignore_case=False), "differs only in punctuation"),
            (compile_template(t), "differs only in punctuation and letter case"),
        ):
            for pattern in patterns:
                m = pattern.match(trimmed)
                if m:
                    return MatchResult(True, MatchKind.PUNCTUATION,
                                       fillins=_fillins(m), message=message)

    if strip_punctuation(f) == strip_punctuation(t):
        return MatchResult(True, MatchKind.PUNCTUATION, message="differs only in punctuation")
    if strip_punctuation(f).casefold() == strip_punctuation(t).casefold():
        return MatchResult(True, MatchKind.PUNCTUATION,
                           message="differs only in punctuation and letter case")

    return MatchResult(False, MatchKind.MISMATCH, message="text does not match official wording")
