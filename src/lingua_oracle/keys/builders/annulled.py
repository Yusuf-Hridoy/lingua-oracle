"""What the courts have annulled that the consolidation we build from still prints.

A consolidation is a reading aid; a court judgment is the law. The General
Court annulled Delegated Regulation (EU) 2020/217 as regards titanium dioxide
on 23 November 2022 (Joined Cases T-279/20, T-283/20, T-288/20), the Court of
Justice dismissed the appeals on 1 August 2025 (Joined Cases C-71/23 P,
C-82/23 P), and Commission notice C/2025/6670 records the consequence: the
Table 3 row for index number 022-006-00-2 is annulled, and so are Annexes I and
II of 2020/217 and Notes W and 10 of its Annex III. Annex II is where the two
statements for mixtures containing titanium dioxide, EUH211 and EUH212, came
from.

The consolidation of 01/07/2026 still prints all three. The next one, of
01/01/2027, lists the notice as M39 and prints none of them. Until the keys are
built from a consolidation that leaves them out, this is where they are left
out - and it is narrow on purpose, like the errata table:

* it names each item, and applies to nothing else;
* it stops applying from the consolidation that already leaves them out, so it
  never outlives the problem it corrects;
* it carries the citation, which goes onto every entry it touches.
"""

from __future__ import annotations

NOTICE = ("Commission notice C/2025/6670 (OJ C, 10.12.2025): the General "
          "Court's judgment of 23 November 2022 in Joined Cases T-279/20, "
          "T-283/20 and T-288/20, upheld by the Court of Justice on 1 August "
          "2025 in Joined Cases C-71/23 P and C-82/23 P, annulled Delegated "
          "Regulation (EU) 2020/217 as regards titanium dioxide")
NOTICE_URL = "http://data.europa.eu/eli/C/2025/6670/oj"

#: Annex II, section 2.13, mixtures containing titanium dioxide.
STATEMENTS = frozenset({"EUH211", "EUH212"})
#: Titanium dioxide in powder form, Carc. 2 by inhalation.
ANNEX_VI_ENTRIES = frozenset({"022-006-00-2"})

#: The first consolidation that prints none of them. From there on there is
#: nothing to leave out, and this module does nothing.
FIRST_WITHOUT = "02008R1272-20270101"


def applies_to(celex: str) -> bool:
    """True while the consolidation `celex` predates the one that drops them.

    CELEX numbers of consolidations of one act sort by their date.
    """
    return celex < FIRST_WITHOUT


def why() -> str:
    return f"annulled - {NOTICE} ({NOTICE_URL})"
