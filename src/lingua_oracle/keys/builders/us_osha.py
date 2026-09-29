"""Answer-key builder for US OSHA HazCom, 29 CFR 1910.1200 Appendix C.

Appendix C is organised by hazard class and category, and - verified against
osha.gov, the eCFR API and the local copy - it contains **no H or P code numbers
at all**. It gives the statement text and the signal word, but never says which
code a statement belongs to.

So codes are not recalled; they are established by comparing OSHA's own wording
against a reference table, and the reference is **UN GHS Rev.7 English**, not
EU CLP. OSHA's HazCom is aligned to a GHS revision, so GHS is the text it should
agree with; EU CLP adds its own drafting and its own later revisions, which made
it the wrong yardstick.

The comparison is **exact**, in two stages, with no fuzzy fallback:

1. **identical** after normalisation, case folding and US/UK spelling folding
   (`keys/builders/spelling.py` - an explicit reviewed table, not a blanket rule);
2. **identical once fill-ins are collapsed** - OSHA prints "May cause cancer <<…>>"
   where GHS prints the full "<state route of exposure …>" instruction, so only
   the fixed part of the statement is compared.

The previous 0.97-similarity stage is gone. A similarity score cannot tell a
spelling difference from a substantive one, so it risked attaching a code to
wording that does not actually say the same thing.

Anything that does not match exactly is left out and listed in the parse report,
together with every GHS code OSHA has no statement for. Those are *not* assumed
to be gaps: OSHA adopted an earlier GHS revision, so some absences are real.

The key is therefore marked `partial`: the statements it holds are OSHA's own,
but the set is smaller than EU CLP's and the counts are not reconciled.
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import html as LH

from lingua_oracle.keys.builders.common import BROWSER_UA, SourceUnavailable, fetch, now
from lingua_oracle.keys.builders.pdf_tables import (
    ParseIssues,
    annex_page_range,
    harvest,
)
from lingua_oracle.keys.builders.spelling import fold
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
from lingua_oracle.registry import data_dir

REGULATION = "us_osha"
REVISION = "29-CFR-1910.1200-AppC"
SOURCE_URL = "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppC"
DEFAULT_FILE = "us-osha/appendix_c.html"

# Statements the source states but that could not be keyed to a code.
UNMAPPED: dict[str, int] = {}

#: GHS Rev.7 English is the reference; OSHA HazCom is aligned to a GHS revision.
REFERENCE_FILE = "ghs-rev7/GHS_Rev7_en.pdf"
REFERENCE_NAME = "UN GHS Rev.7 Annex 3 (English)"
_PRECAUTIONARY_COLUMNS = {"prevention", "response", "storage", "disposal"}
# Cells that are only fill-in scaffolding, not a statement.
_SCAFFOLD_RE = re.compile(r"^[\s<>…(){}\[\].,;:]*$")
# A fill-in. The three sources write the same slot three different ways: OSHA uses
# "<…>" and doubles it as "<<…>>", CLP uses "<state route of exposure …>", and GHS
# Rev.7 uses parentheses, "(state route of exposure …)".
#
# Only *directive* parentheticals are collapsed - ones that open with an
# instruction to the labeller. Collapsing every parenthetical would erase real
# content such as EUH206's "(chlorine)" and make two different statements compare
# equal, which is exactly the kind of false match this builder must not produce.
_DIRECTIVE = r"(?:or\s+)?(?:state|specify|indicate|insert|list|name\s+of)\b"
_FILLIN_RE = re.compile(
    rf"(?:<+[^<>]*>+|\(\s*{_DIRECTIVE}[^()]{{0,240}}\)|…)+",
    re.IGNORECASE,
)

# Paragraphs that are directions to the labeller rather than label text.
_INSTRUCTION_RE = re.compile(
    r"^\s*[-\u2013\u2014\u2026]"                      # a dash or ellipsis lead-in
    r"|chemical manufacturer,?\s*importer"           # "... to specify ..."
    r"|^\s*no (?:hazard|precautionary) statement",
    re.IGNORECASE,
)


def _is_statement(text: str) -> bool:
    if not text or _SCAFFOLD_RE.match(text):
        return False
    if _INSTRUCTION_RE.search(text):
        return False
    stripped = _FILLIN_RE.sub("", text)
    return len(re.findall(r"[A-Za-z]{3,}", stripped)) >= 2


def _match_key(text: str) -> str:
    return fold(normalize(text).casefold()).rstrip(".").strip()


_SLOT = "\ufe64\ufe65"


def _core_key(text: str) -> str:
    """Comparison key with fill-ins collapsed, so only the fixed wording counts.

    Runs of adjacent slots collapse to one. The sources differ purely in layout
    here - OSHA writes "<…> <<…>>" with a space, GHS Rev.7 writes
    "(state specific effect if known)(state route of exposure …)" with none - so
    counting the slots would fail a match on formatting alone.
    """
    collapsed = _FILLIN_RE.sub(f" {_SLOT} ", fold(normalize(text).casefold()))
    words = collapsed.replace(".", " ").split()
    out: list[str] = []
    for word in words:
        if word == _SLOT and out and out[-1] == _SLOT:
            continue
        out.append(word)
    return " ".join(out)


def parse_appendix_c(raw: bytes) -> tuple[dict[str, str], set[str], set[str]]:
    """Return ({hazard statement: signal word}, {precautionary statements}, signals).

    Hazard statements come from tables carrying a "Hazard statement" column beside
    a "Signal word" column. Precautionary statements live in the C.4 tables under
    Prevention / Response / Storage / Disposal, one per paragraph; paragraphs that
    open with an ellipsis are instructions to the manufacturer, not statements.
    """
    doc = LH.fromstring(raw)
    hazard: dict[str, str] = {}
    precautionary: set[str] = set()
    signals: set[str] = set()

    for table in doc.xpath("//table"):
        hazard_cols: tuple[int, int] | None = None
        prec_cols: list[int] | None = None
        for row in table.xpath(".//tr"):
            cells = row.xpath("./td|./th")
            values = [" ".join(c.text_content().split()) for c in cells]
            lower = [v.lower() for v in values]

            if "hazard statement" in lower and "signal word" in lower:
                hazard_cols = (lower.index("signal word"), lower.index("hazard statement"))
                prec_cols = None
                continue
            if len([v for v in lower if v in _PRECAUTIONARY_COLUMNS]) >= 2:
                prec_cols = [i for i, v in enumerate(lower) if v in _PRECAUTIONARY_COLUMNS]
                hazard_cols = None
                continue

            if hazard_cols and len(values) > max(hazard_cols):
                signal = values[hazard_cols[0]].strip()
                statement = values[hazard_cols[1]].strip()
                if signal in ("Danger", "Warning"):
                    signals.add(signal)
                if _is_statement(statement):
                    hazard.setdefault(statement, signal)
            elif prec_cols:
                for index in prec_cols:
                    if index >= len(cells):
                        continue
                    paragraphs = cells[index].xpath(".//p")
                    chunks = (
                        [" ".join(p.text_content().split()) for p in paragraphs]
                        if paragraphs
                        else [values[index]]
                    )
                    for chunk in chunks:
                        text = chunk.strip()
                        if _is_statement(text):
                            precautionary.add(text)
    return hazard, precautionary, signals


def _resolve_code(
    text: str, candidates: list[tuple[str, str, str]]
) -> tuple[str | None, str]:
    """The code whose reference wording is exactly this statement, or None."""
    exact, core = _match_key(text), _core_key(text)
    for code, ckey, _ccore in candidates:
        if exact == ckey:
            return code, "identical"
    for code, _ckey, ccore in candidates:
        if core and core == ccore:
            return code, "identical once fill-ins collapsed"
    return None, "no exact match"


def build(use_cache: bool = True, *, from_file: str | None = None,
          sources_root: Path | None = None) -> tuple[list[AnswerKey], list[ParseIssues]]:
    root = Path(sources_root) if sources_root else (data_dir() / "sources")
    local = Path(from_file) if from_file else root / DEFAULT_FILE
    if local.exists():
        raw = local.read_bytes()
        origin = local.name
    else:
        try:
            raw = fetch(SOURCE_URL, headers={"User-Agent": BROWSER_UA}, use_cache=use_cache)
            origin = SOURCE_URL
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailable(f"OSHA Appendix C fetch failed: {exc}") from exc

    hazard, precautionary, signals = parse_appendix_c(raw)

    reference_path = root / REFERENCE_FILE
    if not reference_path.exists():
        raise SourceUnavailable(
            f"{REFERENCE_NAME} is required to key OSHA statements: {reference_path}"
        )
    first, last = annex_page_range(str(reference_path))
    reference, ref_issues = harvest(str(reference_path), first_page=first, last_page=last)
    reference = {c: t for c, t in reference.items() if c[:1] in "HP"}

    issues = ParseIssues(source=f"{REGULATION}/en ({origin})")
    issues.rows_seen = len(hazard) + len(precautionary)
    ts = now()
    entries: dict[str, AnswerKeyEntry] = {}
    unmapped: list[str] = []

    for prefix, items, kind in (
        ("H", sorted(hazard), Kind.HAZARD),
        ("P", sorted(precautionary), Kind.PRECAUTIONARY),
    ):
        candidates = [
            (code, _match_key(ref_text), _core_key(ref_text))
            for code, ref_text in reference.items()
            if code.startswith(prefix)
        ]
        for text in items:
            code, how = _resolve_code(text, candidates)
            if code is None:
                unmapped.append(f"{prefix}: {text[:70]}")
                continue
            if code in entries:
                continue
            entries[code] = AnswerKeyEntry(
                regulation=REGULATION, revision=REVISION, language="en", code=code,
                kind=kind, text=text,
                signal_word=hazard.get(text) if hazard.get(text) in ("Danger", "Warning") else None,
                tier=Tier.A, source_url=SOURCE_URL,
                source_ref=f"29 CFR 1910.1200 App. C; code established by wording {how} "
                           f"to {REFERENCE_NAME}",
                retrieved_at=ts, status=Status.OK,
            )

    for signal, code in (("Danger", SIGNAL_DANGER), ("Warning", SIGNAL_WARNING)):
        if signal in signals:
            entries[code] = AnswerKeyEntry(
                regulation=REGULATION, revision=REVISION, language="en", code=code,
                kind=Kind.SIGNAL, text=signal, signal_word=signal, tier=Tier.A,
                source_url=SOURCE_URL,
                source_ref="29 CFR 1910.1200 App. C, 'Signal word' column",
                retrieved_at=ts, status=Status.OK,
            )

    h_count = sum(1 for c in entries if c.startswith("H"))
    p_count = sum(1 for c in entries if c.startswith("P"))
    UNMAPPED[REGULATION] = len(unmapped)

    absent = sorted(set(reference) - set(entries))

    issues.rows_used = len(entries)
    issues.tables_seen += ref_issues.tables_seen
    issues.notes.append(f"reference table: {REFERENCE_NAME} ({len(reference)} codes)")
    issues.notes.append(
        f"statements read from the source: {len(hazard)} hazard, "
        f"{len(precautionary)} precautionary"
    )
    issues.notes.append(f"codes established: {h_count} H, {p_count} P, "
                        f"{len(signals)} signal word(s)")
    if unmapped:
        issues.notes.append(
            f"statements with no exact match ({len(unmapped)}); Appendix C states no "
            "codes, and matching is exact after spelling and fill-in folding, so "
            "these are left out rather than guessed:"
        )
        issues.notes.extend(f"    {u}" for u in unmapped[:40])
        if len(unmapped) > 40:
            issues.notes.append(f"    … and {len(unmapped) - 40} more")
    if absent:
        issues.notes.append(
            f"GHS Rev.7 codes with no OSHA statement ({len(absent)}). These are NOT "
            "assumed to be gaps: OSHA's adoption is partial, so some are genuine "
            "differences and some are parse misses. Needs review:"
        )
        issues.notes.append("    " + ", ".join(absent))
    issues.notes.append(
        "status=partial: the statements are OSHA's own, but the code set is smaller "
        "than EU CLP's and the counts are not reconciled."
    )

    key = AnswerKey(
        regulation=REGULATION, language="en", revision=REVISION,
        status=Status.PARTIAL if entries else Status.PENDING_SOURCE,
        status_reason="counts_not_reconciled" if entries else "source_unreadable",
        source_url=SOURCE_URL, retrieved_at=ts,
        entries=sorted(entries.values(), key=lambda e: (e.kind, e.code)),
    )
    return [key], [issues]
