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


def _is_supplemental(code: str) -> bool:
    """True for a prefix some regulation defines outside GHS, e.g. EUH, AUH.

    The GHS index knows nothing about these, so without this they read as
    invented codes. EUH066 on an OSHA sheet is a real statement in the wrong
    place, which is C-12's finding to make, not a typo.
    """
    from lingua_oracle.registry import load_registry

    prefixes = {
        prefix
        for regulation in load_registry().regulations.values()
        for prefix in regulation.supplemental_prefixes
    }
    return any(code.startswith(prefix) for prefix in prefixes if prefix)


class Reason(StrEnum):
    NOT_ON_FILE = "not_on_file"
    NEWER_GHS = "newer_ghs"
    #: The regulation does not carry this code, but the GHS edition it aligns
    #: to always has - OSHA's HazCom leaves out environmental hazards and
    #: Category 5 acute toxicity, for instance. The wording can still be
    #: checked, against GHS, and saying so is more use than "not checked".
    OUTSIDE_SCOPE = "outside_scope"
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


def _is_complete_statement(text: str) -> bool:
    """False for a fragment that only introduces a statement.

    A regulation publishes P301 as "IF SWALLOWED:" - the opening of a combined
    statement, not something anyone can put on a label on its own. Offering it
    as the nearest equivalent to P301+P317 tells a reader to use a colon.
    """
    stripped = (text or "").strip()
    if not stripped or stripped.endswith(":"):
        return False
    # Something has to follow the lead-in.
    after = stripped.split(":", 1)[-1] if ":" in stripped else stripped
    return len(after.split()) >= 2


def _nearest(code: str, target: str, entries) -> tuple[str, str]:
    """The regulation's closest *complete* statement, or ("", "").

    A combined code is compared only against the regulation's other combined
    codes sharing its first component. Without the shared component, "IF
    SWALLOWED: Get emergency medical help immediately." scored highest against a
    statement about exposure rather than about swallowing; without "combined",
    the winner was the bare P301, "IF SWALLOWED:", which is not a statement a
    label can carry.
    """
    pool = {c: e for c, e in entries.items()
            if e.text and not e.internal_id and _is_complete_statement(e.text)}
    floor = _LONE_FLOOR
    if "+" in code:
        head = code.split("+")[0]
        family = {c: e for c, e in pool.items()
                  if "+" in c and c.split("+")[0] == head}
        if not family:
            return "", ""
        pool, floor = family, _FAMILY_FLOOR
    else:
        pool = {c: e for c, e in pool.items() if "+" not in c}
    want = normalize(target).casefold()
    best_ratio, best = 0.0, ("", "")
    for candidate, entry in pool.items():
        ratio = difflib.SequenceMatcher(
            None, want, normalize(entry.text).casefold()
        ).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, (candidate, entry.text)
    return best if best_ratio >= floor else ("", "")


def classify(code: str, key_status: str, entries, regulation: str = "") -> Missing:
    """Decide why `code` has no reference text.

    The hard case is a regulation whose key is knowingly incomplete. Membership
    of the key cannot settle anything there - "not in our key" is equally
    consistent with "the regulation has it and we missed it" and with "the
    regulation does not have it at all". So where the regulation's own source
    text has been searched (`keys/builders/ghs_index.write_source_presence`),
    that search decides instead: wording found in the source means our gap,
    wording found nowhere in it means the sheet is ahead of the regulation.

    Without such a search an incomplete key can only own the gap, which is the
    honest answer when we do not know.
    """
    defining = ghs_index.editions_defining(code)

    if regulation and ghs_index.source_searched(regulation):
        if ghs_index.wording_in_source(regulation, code):
            return Missing(Reason.NOT_ON_FILE)
        can_judge = True
    else:
        can_judge = key_status == "ok"

    if not defining:
        if not can_judge:
            return Missing(Reason.NOT_ON_FILE)
        base = base_code(code)
        if base and (base in entries or ghs_index.known_anywhere(base)):
            return Missing(Reason.NOT_ON_FILE)
        if _is_supplemental(code):
            return Missing(Reason.NOT_ON_FILE)
        return Missing(Reason.UNKNOWN)

    if not can_judge:
        return Missing(Reason.NOT_ON_FILE)

    edition = defining[0]
    text = ghs_index.text_in(code, edition)
    near_code, near_text = _nearest(code, text, entries)
    # A statement the oldest edition on file already carried is not "newer
    # wording"; the regulation has simply never covered it. Labelling that as a
    # later revision would be wrong, but it is still checkable against GHS.
    reason = (Reason.OUTSIDE_SCOPE if ghs_index.oldest_edition_defines(code)
              else Reason.NEWER_GHS)
    return Missing(
        reason=reason, edition=edition, edition_text=text,
        nearest_code=near_code, nearest_text=near_text,
    )
