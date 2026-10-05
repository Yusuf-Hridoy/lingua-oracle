"""Comparing one ingredient's classification with Annex VI Table 3.

Pure and deterministic: given an ingredient and the committed table, the verdict
is a function of the two. No network, no clock, no ordering by chance.

What the comparison can and cannot say:

* A harmonised H code the ingredient does not carry is **under-classified**.
  Annex VI is a floor, so this is a finding whatever else the sheet says.
* A code the ingredient carries that Annex VI does not have is **not** a
  finding. Annex VI covers particular hazards of particular substances; a
  supplier is required to classify for the rest themselves, so extra codes are
  ordinary and are reported as information.
* Where the entry carries "*" - a minimum classification - the category may be
  made stricter but not weaker. Equal or stricter passes.
* Where no entry covers the substance, or where more than one might, nothing is
  checked and the reason is given. Choosing between two harmonised entries for a
  reader would be guessing with the authority of law behind it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from lingua_oracle.keys.builders.annex_vi import base_code
from lingua_oracle.models import AnnexVIEntry, AnnexVITable


class Status(StrEnum):
    FIX = "fix"                  # the sheet is below the harmonised floor
    OK = "ok"                    # everything Annex VI requires is there
    INFO = "info"                # extra codes beyond the harmonised entry
    NOT_CHECKED = "not_checked"  # no reference, or more than one


class Reason(StrEnum):
    NO_ENTRY = "no_harmonised_entry"
    SEVERAL_ENTRIES = "several_harmonised_entries"
    GROUP_ENTRY = "entry_covers_several_substances"
    NO_CAS = "ingredient_has_no_cas"


#: "Acute Tox. 4 *" -> ("Acute Tox.", "4", True). The category of a CLP class is
#: a digit with an optional letter; the asterisk is the minimum-classification
#: mark and belongs to the class, not the category.
_CLASS = re.compile(r"^(?P<name>.*?)\s*(?P<category>\d[A-Fa-f]?)\s*(?P<star>\*)?$")
#: A CAS registry number. The app stores a placeholder - "NOCAS-7a45cd36dcf4" -
#: for substances that have none, and that is a different thing from a CAS the
#: harmonised list happens not to carry.
_CAS_SHAPE = re.compile(r"^\d{2,7}-\d{2}-\d$")


@dataclass(frozen=True)
class HazardClass:
    name: str
    category: str | None
    minimum: bool
    raw: str

    @property
    def rank(self) -> tuple[int, str]:
        """How strict the category is. Lower number, stricter class.

        CLP numbers categories from the most severe down - Acute Tox. 1 is worse
        than Acute Tox. 4 - and sub-categories go 1A, 1B, 1C from worse to less
        bad. Comparing two categories of the *same* class is all this is for.
        """
        if not self.category:
            return (0, "")
        digits = "".join(c for c in self.category if c.isdigit())
        letters = "".join(c for c in self.category if c.isalpha()).upper()
        return (int(digits) if digits else 0, letters)


def parse_class(raw: str) -> HazardClass:
    """"Skin Corr. 1B" -> name "Skin Corr.", category "1B"."""
    text = " ".join(raw.split())
    match = _CLASS.match(text)
    if not match or not match.group("name"):
        return HazardClass(name=text.rstrip("*").strip(), category=None,
                           minimum="*" in text, raw=raw)
    return HazardClass(
        name=match.group("name").strip(),
        category=match.group("category"),
        minimum=bool(match.group("star")),
        raw=raw,
    )


@dataclass
class Finding:
    """One thing to say about one ingredient."""

    status: Status
    code: str | None
    message: str
    required: str = ""
    stated: str = ""


@dataclass
class Verdict:
    """The result for one ingredient."""

    cas: str | None
    status: Status
    findings: list[Finding] = field(default_factory=list)
    entry_index_no: str | None = None
    source_ref: str = ""
    reason: Reason | None = None
    #: Where the app says the substance data came from. Metadata for the
    #: technical block: it is never used to decide anything above.
    data_source: str | None = None

    @property
    def missing_codes(self) -> list[str]:
        return [f.code for f in self.findings
                if f.status is Status.FIX and f.code]


def _normalise(codes: list[str]) -> set[str]:
    return {c.strip().upper().replace(" ", "") for c in codes if c and c.strip()}


def entries_for(cas: str | None, table: AnnexVITable,
                index: dict[str, list[AnnexVIEntry]] | None = None
                ) -> list[AnnexVIEntry]:
    if not cas:
        return []
    lookup = index if index is not None else table.by_cas()
    return lookup.get(cas.strip(), [])


def check_ingredient(cas: str | None, stated_codes: list[str],
                     table: AnnexVITable,
                     index: dict[str, list[AnnexVIEntry]] | None = None,
                     *, data_source: str | None = None) -> Verdict:
    """Compare one ingredient's H codes with its harmonised entry."""
    if not cas or not _CAS_SHAPE.match(cas.strip()):
        return Verdict(cas=cas, status=Status.NOT_CHECKED, reason=Reason.NO_CAS,
                       data_source=data_source,
                       findings=[Finding(
                           Status.NOT_CHECKED, None,
                           "No CAS number, so no harmonised entry can be looked "
                           "up. Annex VI Table 3 is indexed by CAS and EC "
                           "number; a substance with neither cannot be found "
                           "in it.")])

    found = entries_for(cas, table, index)
    if not found:
        return Verdict(cas=cas, status=Status.NOT_CHECKED, reason=Reason.NO_ENTRY,
                       data_source=data_source,
                       findings=[Finding(
                           Status.NOT_CHECKED, None,
                           "No harmonised entry in Annex VI Table 3 for this "
                           "CAS number, so there is no official reference to "
                           "check against.")])
    if len(found) > 1:
        where = ", ".join(e.index_no for e in found)
        return Verdict(cas=cas, status=Status.NOT_CHECKED,
                       reason=Reason.SEVERAL_ENTRIES, data_source=data_source,
                       findings=[Finding(
                           Status.NOT_CHECKED, None,
                           f"This CAS number appears in more than one Annex VI "
                           f"entry ({where}). Which one applies is not "
                           f"something to guess.")])

    entry = found[0]
    if entry.covers_several_substances:
        return Verdict(cas=cas, status=Status.NOT_CHECKED,
                       reason=Reason.GROUP_ENTRY,
                       entry_index_no=entry.index_no,
                       source_ref=entry.source_ref, data_source=data_source,
                       findings=[Finding(
                           Status.NOT_CHECKED, None,
                           f"Annex VI entry {entry.index_no} covers several "
                           f"substances at once, and which classification "
                           f"belongs to this one is not stated.")])

    stated = _normalise(stated_codes)
    stated_bases = {base_code(c) for c in stated}
    required = _normalise(entry.h_codes)

    findings: list[Finding] = []
    for code in sorted(required):
        if code in stated or base_code(code) in stated_bases:
            continue
        findings.append(Finding(
            Status.FIX, code,
            f"Under-classified: Annex VI requires {code}.",
            required=code,
        ))

    extra = sorted(stated - required - {base_code(c) for c in required})
    if extra:
        findings.append(Finding(
            Status.INFO, None,
            "Also classified " + ", ".join(extra)
            + " - Annex VI does not cover these, which is ordinary: a supplier "
              "classifies for the hazards the harmonised entry leaves to them.",
            stated=", ".join(extra),
        ))

    status = Status.FIX if any(f.status is Status.FIX for f in findings) else (
        Status.INFO if extra else Status.OK)
    return Verdict(cas=cas, status=status, findings=findings,
                   entry_index_no=entry.index_no, source_ref=entry.source_ref,
                   data_source=data_source)


def compare_categories(stated: str, harmonised: str) -> str:
    """"stricter", "equal", "weaker" or "incomparable" for two class strings.

    Only meaningful for two categories of the same hazard class, which is what a
    minimum classification is about: Annex VI's "Acute Tox. 4 *" may be made
    "Acute Tox. 3", never "Acute Tox. 4" downgraded further.
    """
    a, b = parse_class(stated), parse_class(harmonised)
    if a.name.casefold() != b.name.casefold() or not a.category or not b.category:
        return "incomparable"
    if a.rank == b.rank:
        return "equal"
    return "stricter" if a.rank < b.rank else "weaker"


def check_minimum_classification(stated_classes: list[str],
                                 entry: AnnexVIEntry) -> list[Finding]:
    """Findings for the "*" entries: equal or stricter passes, weaker does not."""
    findings: list[Finding] = []
    for raw in entry.hazard_classes:
        harmonised = parse_class(raw)
        if not harmonised.minimum or not harmonised.category:
            continue
        same = [c for c in stated_classes
                if parse_class(c).name.casefold() == harmonised.name.casefold()]
        if not same:
            continue  # the missing-code check already covers an absent class
        best = min(same, key=lambda c: parse_class(c).rank)
        verdict = compare_categories(best, raw)
        if verdict == "weaker":
            findings.append(Finding(
                Status.FIX, None,
                f"Weaker than the minimum classification: Annex VI gives "
                f"{harmonised.raw.strip()}, the sheet says {best}.",
                required=harmonised.raw.strip(), stated=best,
            ))
    return findings


def check_product(ingredients: list[dict], table: AnnexVITable,
                  index: dict[str, list[AnnexVIEntry]] | None = None
                  ) -> list[Verdict]:
    """Check every ingredient of one product.

    `ingredients` are plain dicts so this stays independent of where they came
    from - the app, a PDF, or a test.
    """
    lookup = index if index is not None else table.by_cas()
    out = []
    for row in ingredients:
        codes = row.get("h_codes") or []
        if isinstance(codes, str):
            codes = [c.strip() for c in codes.split(",") if c.strip()]
        verdict = check_ingredient(row.get("cas"), codes, table, lookup,
                                   data_source=row.get("data_source"))
        if verdict.entry_index_no and row.get("hazard_classes"):
            entry = next(e for e in entries_for(row.get("cas"), table, lookup)
                         if e.index_no == verdict.entry_index_no)
            extra = check_minimum_classification(row["hazard_classes"], entry)
            if extra:
                verdict.findings += extra
                verdict.status = Status.FIX
        out.append(verdict)
    return out
