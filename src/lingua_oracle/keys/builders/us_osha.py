"""Answer-key builder for US OSHA HazCom, 29 CFR 1910.1200 Appendix C.

Appendix C is organised by hazard class and category, and - verified against
osha.gov, the eCFR API and the local copy - it contains **no H or P code numbers
at all**. It gives the statement text and the signal word, but never says which
code a statement belongs to.

So codes are not recalled; they are established by comparing OSHA's own wording
with EU CLP's English text for each code, in three stages of decreasing strength:

1. **identical** after normalisation and case folding;
2. **identical once fill-ins are collapsed** - OSHA prints "May cause cancer <…>"
   where EU CLP prints the full "<state route of exposure …>" instruction, so the
   fixed part of the statement is what is compared;
3. **near-identical**, a similarity of at least 0.97, which absorbs US spelling
   ("vapor", "poison center") and sentence case.

Anything weaker is left out and listed in the parse report, together with every
EU CLP code that OSHA has no statement for. Those are *not* assumed to be gaps:
OSHA adopted an earlier GHS revision, so some absences are real differences.

The key is therefore marked `partial`: the statements it holds are OSHA's own,
but the set is smaller than EU CLP's and the counts are not reconciled.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from lxml import html as LH

from lingua_oracle.keys.builders.common import BROWSER_UA, SourceUnavailable, fetch, now
from lingua_oracle.keys.builders.pdf_tables import ParseIssues
from lingua_oracle.keys.store import load_key
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

SIMILARITY_FLOOR = 0.97
_PRECAUTIONARY_COLUMNS = {"prevention", "response", "storage", "disposal"}
# Cells that are only fill-in scaffolding, not a statement.
_SCAFFOLD_RE = re.compile(r"^[\s<>…(){}\[\].,;:]*$")
# A fill-in, whether OSHA's bare "<…>" or CLP's full "<state route of exposure …>".
# OSHA also doubles the brackets, "<<…>>", so one or more of each side is allowed.
_FILLIN_RE = re.compile(r"(?:<+[^<>]*>+|\([^()]{0,90}\)|…)+")

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
    return normalize(text).casefold().rstrip(".").strip()


def _core_key(text: str) -> str:
    """Comparison key with fill-ins collapsed, so only the fixed wording counts."""
    collapsed = _FILLIN_RE.sub(" ﹤﹥ ", normalize(text).casefold())
    return " ".join(collapsed.replace(".", " ").split())


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


def _resolve_code(text: str, candidates: list[tuple[str, str, str]]) -> tuple[str | None, float, str]:
    """Best code for `text`. Returns (code, score, how)."""
    exact, core = _match_key(text), _core_key(text)
    for code, ckey, _core in candidates:
        if exact == ckey:
            return code, 1.0, "identical"
    for code, _ckey, ccore in candidates:
        if core and core == ccore:
            return code, 1.0, "identical once fill-ins collapsed"
    ranked = sorted(
        ((difflib.SequenceMatcher(None, exact, ckey).ratio(), code)
         for code, ckey, _c in candidates),
        reverse=True,
    )
    if ranked and ranked[0][0] >= SIMILARITY_FLOOR:
        return ranked[0][1], ranked[0][0], f"near-identical (similarity {ranked[0][0]:.2f})"
    return None, (ranked[0][0] if ranked else 0.0), "no match"


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
    eu = load_key("eu_clp", "en")
    if eu is None:
        raise SourceUnavailable("EU CLP English key is required to key OSHA statements")

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
            (e.code, _match_key(e.text), _core_key(e.text))
            for e in eu.entries
            if e.code.startswith(prefix) and not e.code.startswith("EUH")
        ]
        for text in items:
            code, score, how = _resolve_code(text, candidates)
            if code is None:
                unmapped.append(f"{prefix}: {text[:70]} (best {score:.2f})")
                continue
            if code in entries:
                continue
            entries[code] = AnswerKeyEntry(
                regulation=REGULATION, revision=REVISION, language="en", code=code,
                kind=kind, text=text,
                signal_word=hazard.get(text) if hazard.get(text) in ("Danger", "Warning") else None,
                tier=Tier.A, source_url=SOURCE_URL,
                source_ref=f"29 CFR 1910.1200 App. C; code established by wording {how} "
                           f"to EU CLP Annex III/IV English",
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

    eu_h = {e.code for e in eu.entries if e.code.startswith("H") and not e.code.startswith("EUH")}
    eu_p = {e.code for e in eu.entries if e.code.startswith("P")}
    absent = sorted((eu_h - set(entries)) | (eu_p - set(entries)))

    issues.rows_used = len(entries)
    issues.notes.append(
        f"statements read from the source: {len(hazard)} hazard, "
        f"{len(precautionary)} precautionary"
    )
    issues.notes.append(f"codes established: {h_count} H, {p_count} P, "
                        f"{len(signals)} signal word(s)")
    if unmapped:
        issues.notes.append(
            f"statements with no confident code ({len(unmapped)}); Appendix C states "
            "no codes, so these are left out rather than guessed:"
        )
        issues.notes.extend(f"    {u}" for u in unmapped[:40])
        if len(unmapped) > 40:
            issues.notes.append(f"    … and {len(unmapped) - 40} more")
    if absent:
        issues.notes.append(
            f"EU CLP codes with no OSHA statement ({len(absent)}). These are NOT "
            "assumed to be gaps: OSHA adopted an earlier GHS revision, so some are "
            "genuine differences and some are parse misses. Needs review:"
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
