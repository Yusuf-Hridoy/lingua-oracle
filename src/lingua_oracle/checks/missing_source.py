"""Why do we hold no official wording for this code?

Three very different situations were all reported as one "not checked":

* **not_on_file** - the regulation may well carry this code; our key for it is
  knowingly incomplete. Our gap, and nothing to say about the document.
* **newer_ghs** - the regulation's source was parsed in full and does not
  contain this code, but a later GHS edition on file does. The sheet is ahead
  of the regulation it claims to follow. That is a finding about the document.
* **unknown** - no edition on file defines it at all. Either a typo or a code
  that does not exist.

Collapsing these lost the only one that was actually about the document.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from enum import StrEnum

from lingua_oracle.keys import ghs_index
from lingua_oracle.match.normalize import normalize

#: How close a candidate must be before it is worth showing at all. Two
#: thresholds because a shared first component is strong evidence on its own:
#: P332+P317 and P332+P313 open with the same statement, so a lower text
#: similarity still identifies the right neighbour, while a bare code has only
#: its wording to go on.
_FAMILY_FLOOR = 0.40
_LONE_FLOOR = 0.55

#: A sub-lettered form of a code: H361D, H360FD, H350i. CLP Annex III lists the
#: statement once, as H361, with the affected-organ options inside it; the
#: letters are a labelling convention layered on top. So the sub-lettered form
#: is a real code that we simply do not hold as its own entry - it is not an
#: invented one, and calling it unknown would fail a correct sheet.
_SUB_LETTERED_RE = re.compile(r"^([HP]\d{3})([A-Za-z]{1,3})$")


def base_code(code: str) -> str:
    """The code without its sub-letters, or "" if it has none."""
    match = _SUB_LETTERED_RE.match(code or "")
    return match.group(1) if match else ""


class Reason(StrEnum):
    NOT_ON_FILE = "not_on_file"
    NEWER_GHS = "newer_ghs"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Missing:
    reason: Reason
    #: For newer_ghs: the oldest edition on file that defines the code.
    edition: str = ""
    #: For newer_ghs: that edition's wording, quoted.
    edition_text: str = ""
    #: The regulation's own closest statement, if one is recognisable. A
    #: suggestion for a human, never a verdict - the code pairing is ours, the
    #: text is the regulation's, quoted verbatim from the key.
    nearest_code: str = ""
    nearest_text: str = ""


def _nearest(code: str, target: str, entries) -> tuple[str, str]:
    """The regulation's statement closest to `target`, or ("", "").

    A combined code is compared only against the regulation's codes sharing its
    first component, when it has any. Without that, "IF SWALLOWED: Get emergency
    medical help immediately." scored highest against a statement about exposure
    rather than about swallowing.
    """
    pool = {c: e for c, e in entries.items() if e.text and not e.internal_id}
    floor = _LONE_FLOOR
    if "+" in code:
        head = code.split("+")[0]
        family = {c: e for c, e in pool.items() if c.split("+")[0] == head}
        if family:
            pool, floor = family, _FAMILY_FLOOR
    want = normalize(target).casefold()
    best_ratio, best = 0.0, ("", "")
    for candidate, entry in pool.items():
        ratio = difflib.SequenceMatcher(
            None, want, normalize(entry.text).casefold()
        ).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, (candidate, entry.text)
    return best if best_ratio >= floor else ("", "")


def classify(code: str, key_status: str, entries) -> Missing:
    """Decide why `code` has no reference text."""
    defining = ghs_index.editions_defining(code)
    if not defining:
        # An incomplete key cannot tell us a code does not exist, only that we
        # do not hold it.
        if key_status != "ok":
            return Missing(Reason.NOT_ON_FILE)
        base = base_code(code)
        if base and (base in entries or ghs_index.known_anywhere(base)):
            return Missing(Reason.NOT_ON_FILE)
        return Missing(Reason.UNKNOWN)

    if key_status != "ok":
        return Missing(Reason.NOT_ON_FILE)

    edition = defining[0]
    text = ghs_index.text_in(code, edition)
    near_code, near_text = _nearest(code, text, entries)
    return Missing(
        reason=Reason.NEWER_GHS, edition=edition, edition_text=text,
        nearest_code=near_code, nearest_text=near_text,
    )
