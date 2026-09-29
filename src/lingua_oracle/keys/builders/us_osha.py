"""Answer-key builder for US OSHA HazCom, 29 CFR 1910.1200 Appendix C.

Appendix C is organised by hazard class and category, and - verified against both
osha.gov and the eCFR API - it contains **no H/P code numbers at all**. It gives
signal words and statement text, but not the code each statement belongs to.

So this builder takes only what the source actually states:

* **Signal words** are read directly from the "Signal word" column (tier A).
* **Hazard statements** are keyed to a code only where OSHA's own wording is
  identical, after normalisation, to EU CLP's English text for that code. The
  code assignment is then established by the two official texts agreeing, not by
  recall. Statements that do not match any EU CLP text are left out and counted
  in the sanity report, because assigning them a code would mean inventing the
  mapping.

The remainder is filled with `lingua keys import-csv` from a sourced glossary.
"""

from __future__ import annotations

import re

from lxml import html as LH

from lingua_oracle.keys.builders import eu_clp
from lingua_oracle.keys.builders.common import (
    BROWSER_UA,
    SourceUnavailable,
    fetch,
    now,
)
from lingua_oracle.match.normalize import normalize
from lingua_oracle.models import (
    SIGNAL_DANGER,
    SIGNAL_WARNING,
    AnswerKey,
    AnswerKeyEntry,
    Kind,
    Status,
    Tier,
)

REGULATION = "us_osha"
REVISION = "29-CFR-1910.1200-AppC"
SOURCE_URL = "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppC"

# Statements the source states but that could not be keyed to a code; surfaced
# in the sanity report so the gap is visible rather than silently dropped.
UNMAPPED: dict[str, int] = {}

# Cells that are only fill-in scaffolding, not a statement.
_SCAFFOLD_RE = re.compile(r"^[\s<>…(){}\[\].,;:]*$")


def _is_statement(text: str) -> bool:
    if not text or _SCAFFOLD_RE.match(text):
        return False
    stripped = re.sub(r"<[^<>]*>|…|\([^()]*\)", "", text)
    return len(re.findall(r"[A-Za-z]{3,}", stripped)) >= 2


def _match_key(text: str) -> str:
    return normalize(text).casefold().rstrip(".").strip()


def parse_appendix_c(raw: bytes) -> tuple[dict[str, str], set[str]]:
    """Return ({statement_text: signal_word}, {signal words seen})."""
    doc = LH.fromstring(raw)
    statements: dict[str, str] = {}
    signals: set[str] = set()
    for table in doc.xpath("//table"):
        cols: tuple[int, int] | None = None
        for row in table.xpath(".//tr"):
            cells = [" ".join(c.text_content().split()) for c in row.xpath("./td|./th")]
            lower = [c.lower() for c in cells]
            if "hazard statement" in lower and "signal word" in lower:
                cols = (lower.index("signal word"), lower.index("hazard statement"))
                continue
            if cols is None or len(cells) <= max(cols):
                continue
            signal, statement = cells[cols[0]].strip(), cells[cols[1]].strip()
            if signal in ("Danger", "Warning"):
                signals.add(signal)
            if _is_statement(statement):
                statements.setdefault(statement, signal)
    return statements, signals


def build(use_cache: bool = True) -> list[AnswerKey]:
    try:
        raw = fetch(SOURCE_URL, headers={"User-Agent": BROWSER_UA}, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(f"OSHA Appendix C fetch failed: {exc}") from exc

    statements, signals = parse_appendix_c(raw)
    eu_en = eu_clp.build(["en"], use_cache=use_cache, with_signal_words=False)[0]
    by_text = {_match_key(e.text): e for e in eu_en.entries}

    ts = now()
    entries: list[AnswerKeyEntry] = []
    matched = 0
    for statement, signal in statements.items():
        ref = by_text.get(_match_key(statement))
        if ref is None:
            continue
        matched += 1
        entries.append(
            AnswerKeyEntry(
                regulation=REGULATION, revision=REVISION, language="en", code=ref.code,
                kind=Kind.HAZARD if ref.code.startswith("H") else Kind.PRECAUTIONARY,
                text=statement,
                signal_word=signal if signal in ("Danger", "Warning") else None,
                tier=Tier.A, source_url=SOURCE_URL,
                source_ref="29 CFR 1910.1200 App. C; code established by text identity "
                           "with EU CLP Annex III English",
                retrieved_at=ts, status=Status.OK,
            )
        )
    for signal, code in (("Danger", SIGNAL_DANGER), ("Warning", SIGNAL_WARNING)):
        if signal in signals:
            entries.append(
                AnswerKeyEntry(
                    regulation=REGULATION, revision=REVISION, language="en", code=code,
                    kind=Kind.SIGNAL, text=signal, signal_word=signal, tier=Tier.A,
                    source_url=SOURCE_URL,
                    source_ref="29 CFR 1910.1200 App. C, 'Signal word' column",
                    retrieved_at=ts, status=Status.OK,
                )
            )
    entries.sort(key=lambda e: (e.kind, e.code))
    UNMAPPED["us_osha"] = len(statements) - matched
    return [
        AnswerKey(
            regulation=REGULATION, language="en", revision=REVISION,
            status=Status.OK if entries else Status.PENDING_SOURCE,
            source_url=SOURCE_URL, retrieved_at=ts, entries=entries,
        )
    ]
