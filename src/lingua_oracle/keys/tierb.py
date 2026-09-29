"""Tier B borrowing: reusing EU CLP translations for another regulation.

When checking regulation R in language L and R has no official text in L, a code
may still be checkable. If R's **English** text for that code is identical, after
normalisation, to EU CLP's English text for the same code, then the two
regulations demonstrably use the same statement, and EU CLP's official L-text can
stand in. Such an entry is marked tier B.

Where the English texts differ, or R has no English text for the code, nothing is
borrowed and the code falls to tier C: no reference text, so no wording verdict.
"""

from __future__ import annotations

from dataclasses import dataclass

from lingua_oracle.keys.store import load_key
from lingua_oracle.match.normalize import normalize
from lingua_oracle.models import AnswerKey, AnswerKeyEntry, Tier

EU = "eu_clp"


def _key(text: str) -> str:
    return normalize(text).casefold().rstrip(".").strip()


@dataclass
class Borrowed:
    entries: dict[str, AnswerKeyEntry]
    borrowed_codes: set[str]
    tier_c_codes: set[str]


def resolve(regulation: str, language: str) -> Borrowed:
    """Best available reference entries for `regulation` x `language`.

    Tier A entries win. Codes with no tier A entry are borrowed from EU CLP where
    the English texts agree; anything left is tier C.
    """
    own = load_key(regulation, language)
    entries: dict[str, AnswerKeyEntry] = dict(own.by_code()) if own else {}
    borrowed: set[str] = set()
    tier_c: set[str] = set()

    if regulation == EU:
        return Borrowed(entries=entries, borrowed_codes=borrowed, tier_c_codes=tier_c)

    own_en = load_key(regulation, "en")
    eu_en = load_key(EU, "en")
    eu_l = load_key(EU, language)
    if not own_en or not eu_en or not eu_l:
        return Borrowed(entries=entries, borrowed_codes=borrowed, tier_c_codes=tier_c)

    own_en_by_code = own_en.by_code()
    eu_en_by_code = eu_en.by_code()
    eu_l_by_code = eu_l.by_code()

    for code, own_entry in own_en_by_code.items():
        if code in entries:
            continue
        eu_entry_en = eu_en_by_code.get(code)
        eu_entry_l = eu_l_by_code.get(code)
        if eu_entry_en is None or eu_entry_l is None:
            tier_c.add(code)
            continue
        if _key(own_entry.text) != _key(eu_entry_en.text):
            tier_c.add(code)
            continue
        entries[code] = eu_entry_l.model_copy(
            update={
                "regulation": regulation,
                "tier": Tier.B,
                "source_ref": (
                    f"borrowed from EU CLP {language} "
                    f"(English texts identical); {eu_entry_l.source_ref or ''}"
                ).strip(),
            }
        )
        borrowed.add(code)

    return Borrowed(entries=entries, borrowed_codes=borrowed, tier_c_codes=tier_c)


def reference_key(regulation: str, language: str) -> AnswerKey:
    """Flatten `resolve` into an AnswerKey for reporting and stats."""
    resolved = resolve(regulation, language)
    base = load_key(regulation, language)
    return AnswerKey(
        regulation=regulation,
        language=language,
        revision=base.revision if base else "",
        status=base.status if base else "pending_source",
        source_url=base.source_url if base else None,
        retrieved_at=base.retrieved_at if base else None,
        entries=sorted(resolved.entries.values(), key=lambda e: (e.kind, e.code)),
    )
