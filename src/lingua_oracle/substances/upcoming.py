"""Annex VI as an adopted ATP will make it, and from when.

An ATP is adopted, published, and then applies a year or more later. In
between, a supplier may already follow it and is not yet obliged to. So until
the date it applies, a sheet that meets either the table in force or the table
as amended meets Annex VI - and where it meets only the first, the reader is
told what changes and when. From the date on, the amended table is the one
that binds.

Only Annex VI has an upcoming amendment on file; the other lists are not
amended this way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import cache

from lingua_oracle.models import AnnexVIAmendment, AnnexVITable

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def today() -> date:
    """The date a check is made on. One place, so a test can set it."""
    return datetime.now(UTC).date()


def long_date(day: date) -> str:
    """1 February 2027 - the way the act itself writes it."""
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


def compose(table: AnnexVITable, amendment: AnnexVIAmendment) -> AnnexVITable:
    """Table 3 as it reads once the amendment applies.

    Replacements take the place of the entry with the same index number, and
    insertions are added; nothing else moves.
    """
    replaced = {e.index_no: e for e in amendment.replaced}
    entries = [replaced.get(e.index_no, e) for e in table.entries]
    held = {e.index_no for e in entries}
    entries += [e for e in amendment.inserted if e.index_no not in held]
    return AnnexVITable(
        source=f"{table.source} as amended by {amendment.act}",
        note=f"{table.note} Amended by {amendment.title}, which applies from "
             f"{long_date(amendment.applies_from)}.",
        retrieved_at=amendment.retrieved_at,
        entries=sorted(entries, key=lambda e: e.index_no))


@dataclass(frozen=True)
class Upcoming:
    """An adopted amendment to the list, and the list as it will read."""

    title: str
    act: str
    applies_from: date
    table: AnnexVITable
    #: Every CAS number the amendment touches. A substance outside it reads
    #: the same in both tables, and is checked once.
    changed_cas: frozenset[str]

    def binding_on(self, on: date) -> bool:
        return on >= self.applies_from

    @property
    def when(self) -> str:
        return long_date(self.applies_from)

    @property
    def short(self) -> str:
        """The name in brackets - "23rd ATP" - or the title where there is none."""
        if "(" in self.title and self.title.endswith(")"):
            return self.title.rsplit("(", 1)[1][:-1]
        return self.title


def build(table: AnnexVITable, amendment: AnnexVIAmendment) -> Upcoming:
    changed = {cas for entry in (*amendment.inserted, *amendment.replaced)
               for cas in entry.cas_numbers()}
    # A replaced entry's old CAS numbers are touched too, should they differ.
    replaced = {e.index_no for e in amendment.replaced}
    changed |= {cas for entry in table.entries if entry.index_no in replaced
                for cas in entry.cas_numbers()}
    return Upcoming(title=amendment.title, act=amendment.act,
                    applies_from=amendment.applies_from,
                    table=compose(table, amendment),
                    changed_cas=frozenset(changed))


@cache
def for_list(name: str) -> Upcoming | None:
    """The upcoming amendment to one list, or None where none is on file."""
    if name != "annex_vi":
        return None
    from lingua_oracle.keys.builders.annex_vi import load_table, load_upcoming

    table, amendment = load_table(), load_upcoming()
    if table is None or amendment is None:
        return None
    return build(table, amendment)
