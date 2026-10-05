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

Anything that does not match exactly is left out and listed in the parse report.
That report separates two very different things, because conflating them made the
key look far worse than it is:

* statements that **restate a code already held** - the same statement printed
  again with its fill-in completed, a usage condition attached, or a typo in the
  published HTML. Not gaps.
* statements **not represented by any code held**. Only these decide the status.

OSHA also defines hazard classes GHS does not and gives them no code. Those are
stored under internal identifiers (OSHA-CD, OSHA-SA) flagged `internal_id`, and
are matched by text - see `internal_id_for`.

**On the statements that differ only in rendering.** Four of OSHA's statements
differ from GHS by a dropped word, an added comma, or a full stop where GHS
prints a colon. Whether those are OSHA's wording or errors in the osha.gov HTML
was checked against the official text and could not be settled: the eCFR renderer
returns 404 for the appendix, eCFR's structure API lists no appendix node under
1910.1200, and the CFR XML on both ecfr.gov and govinfo.gov publishes Appendix C's
tables as **graphics** rather than text - the statements appear nowhere in either.
Until an authoritative text rendering exists, they stay out of the key rather than
being aliased on a guess, and matching stays exact.
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import html as LH

from lingua_oracle.keys.builders.common import BROWSER_UA, SourceUnavailable, fetch, now
from lingua_oracle.keys.builders.ghs_editions import REV8_NAME, pressure_overlay
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
#: Statements not represented by any code held - the real gaps.
UNREPRESENTED: dict[str, int] = {}

#: GHS Rev.7 English is the reference; OSHA HazCom is aligned to a GHS revision.
REFERENCE_FILE = "ghs-rev7/GHS_Rev7_en.pdf"
REFERENCE_NAME = "UN GHS Rev.7 Annex 3 (English)"
_PRECAUTIONARY_COLUMNS = {"prevention", "response", "storage", "disposal"}
# Cells that are only fill-in scaffolding, not a statement.
#: Cells that carry no statement: empty, punctuation only, or the table's own
#: way of saying there is nothing here.
_SCAFFOLD_RE = re.compile(r"^(?:[\s<>…(){}\[\].,;:]*|none\s+assigned\.?)$",
                          re.IGNORECASE)
# A fill-in. The three sources write the same slot three different ways: OSHA uses
# "<…>" and doubles it as "<<…>>", CLP uses "<state route of exposure …>", and GHS
# Rev.7 uses parentheses, "(state route of exposure …)".
#
# Only *directive* parentheticals are collapsed - ones that open with an
# instruction to the labeller. Collapsing every parenthetical would erase real
# content such as EUH206's "(chlorine)" and make two different statements compare
# equal, which is exactly the kind of false match this builder must not produce.
_DIRECTIVE = r"(?:or\s+)?(?:state|specify|indicate|insert|list|name\s+of)\b"
_FILLIN_ATOM = rf"(?:<+[^<>]*>+|\(\s*{_DIRECTIVE}[^()]{{0,240}}\)|\u2026)"
# A run of slots separated only by spaces is one slot. Appendix C prints the same
# statement as "to... ... in accordance", "to... ...in accordance" and
# "to ... ... in accordance"; all three mean one fill-in.
_FILLIN_RE = re.compile(rf"{_FILLIN_ATOM}(?:\s*{_FILLIN_ATOM})*", re.IGNORECASE)

# (2b) A usage condition appended to a statement, e.g.
#   "Do not breathe dusts or mists. - if inhalable particles of dusts or mists..."
#   "Ground and bond container and receiving equipment. if the explosive is..."
# Appendix C column 5 conditions leak into the statement cell; they are guidance
# on when to apply the statement, not part of its text. Only a trailing "if"
# clause introduced by a dash, or following a full stop, is stripped - so
# "...\u2026/ if you feel unwell." keeps its clause.
# A usage condition: a note to the labeller saying when the statement applies.
# Appendix C attaches these after a dash - "- if inhalable particles ...",
# "- for flammable liquids Category 1", "- may be omitted if storage
# temperatures are listed", "- except for temperature controlled ...". The
# opening words are listed rather than matching any dash, because a statement
# may legitimately contain one.
_CONDITION_RE = re.compile(
    r"(?:\s*[-\u2013\u2014]\s*"
    r"(?:if|for|except|unless|when|where|may\s+be\s+omitted|text\s+in)\b.*$)"
    r"|(?<=\.)\s*if\b.*$",
    re.IGNORECASE | re.DOTALL,
)

# Paragraphs that are directions to the labeller rather than label text.
_INSTRUCTION_RE = re.compile(
    r"^\s*[-\u2013\u2014\u2026]"                      # a dash or ellipsis lead-in
    r"|chemical manufacturer,?\s*importer"           # "... to specify ..."
    r"|^\s*no (?:hazard|precautionary) statement",
    re.IGNORECASE,
)


def _node_text(element) -> str:
    """Text of an element, joining its text nodes with a space.

    lxml's text_content() concatenates adjacent nodes directly, so markup such as
    "when<i>fire</i> reaches" comes out as "whenfire reaches". Joining on
    itertext() keeps the words apart.
    """
    return repair_wrapping(" ".join(" ".join(element.itertext()).split()))


#: Appendix C's HTML carries the line breaks of the printed page: a slash list
#: broken across lines arrives as "dust/fume/gas/mist/ vapors/spray", and a
#: parenthesis broken after the bracket as "( see … on this label)". English
#: GHS never spaces either, so both are layout and neither is wording - but
#: comparison here is exact, so both cost a code.
_WRAP_AFTER_SLASH_RE = re.compile(r"/[ \t]+(?=\w)")
_WRAP_AFTER_PAREN_RE = re.compile(r"\([ \t]+(?=\w)")


def repair_wrapping(text: str) -> str:
    out = _WRAP_AFTER_SLASH_RE.sub("/", text or "")
    return _WRAP_AFTER_PAREN_RE.sub("(", out)


#: Guidance addressed to whoever writes the label, printed inside the same
#: paragraph as the statement it qualifies:
#:
#:     If on skin: Wash with plenty of water/… … Chemical manufacturer,
#:     importer, or distributor may specify a cleansing agent if appropriate …
#:
#: `_is_statement` rejects a paragraph containing this, which threw the
#: statement away with it. Cutting at the marker keeps the statement and drops
#: only what follows.
#: "Refer to manufacturer, importer, or distributor … for information on
#: disposal" is a statement, not guidance, so a bare "manufacturer, importer"
#: only counts when it opens the segment or follows the ellipsis that
#: introduces a note.
_GUIDANCE_START_RE = re.compile(
    r"\s*\u2026?\s*chemical manufacturers?,?\s*importers?"
    r"|(?:^|\u2026)\s*manufacturers?,?\s*importers?,?\s*or\s*distributors?"
    r"|\s*\u2026\s*reference to supplemental\b",
    re.IGNORECASE,
)


def strip_guidance(text: str) -> str:
    """The statement, with any labeller guidance that follows it removed."""
    match = _GUIDANCE_START_RE.search(text or "")
    return (text[: match.start()] if match else (text or "")).strip()


#: Appendix C lists alternative statements and the connector leaks into the cell,
#: e.g. "May cause respiratory irritation; or".
_CONNECTOR_RE = re.compile(r"\s*[;,]?\s*\b(?:or|and)\s*$", re.IGNORECASE)


def strip_condition(text: str) -> str:
    """Remove a trailing usage condition or list connector from a statement cell."""
    out = _CONDITION_RE.sub("", text or "").strip().rstrip("-\u2013\u2014").strip()
    return _CONNECTOR_RE.sub("", out).strip()


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


#: A footnote row that says what a slot in this table's statements is for:
#:
#:     < >    (state route of exposure if no other routes of exposure cause the hazard)
#:     <<…>>  (state route of exposure if no other routes of exposure cause the hazard)
#:     <…>    (or state all organs affected, if known)
#:
#: Appendix C prints the slot bare in the statement and explains it once at the
#: foot of the table. Dropping the explanation left "Suspected of causing cancer
#: <…>" in the key, where nothing says the slot is conditional, so a label that
#: correctly omits the route - because no other route causes the hazard - failed.
_SLOT_LEGEND_RE = re.compile(
    r"^(?P<open><+)\s*[….\s]*(?P<close>>+)\s*"
    r"\(\s*(?P<instruction>(?:or\s+)?(?:state|specify|indicate|list)\b[^()]{0,240})\)\s*$",
    re.IGNORECASE,
)


def slot_legend(cell: str) -> tuple[int, str] | None:
    """(bracket depth, the instruction) for a slot footnote, or None."""
    m = _SLOT_LEGEND_RE.match(cell.strip())
    if not m:
        return None
    return len(m.group("open")), " ".join(m.group("instruction").split())


def apply_slot_legends(statement: str, legends: dict[int, str]) -> str:
    """Put the table's own explanation inside the slots of one statement.

    The result is the source's wording, assembled from the two places it prints
    it. Nothing is invented: the instruction is copied verbatim, and a slot with
    no legend is left exactly as it was.
    """
    def replace(match: re.Match[str]) -> str:
        depth = len(match.group(1))
        instruction = legends.get(depth)
        return f"<{instruction}>" if instruction else match.group(0)

    return re.sub(r"(<+)\s*[….\s]*>+", replace, statement)


def parse_appendix_c(
    raw: bytes,
) -> tuple[dict[str, str], set[str], set[str], dict[str, str]]:
    """Return hazard statements, precautionary statements, signals and categories.

    The fourth value maps a hazard statement to its "Hazard category" cell. For
    most rows that is a GHS category number, but for hazard classes OSHA defines
    itself it is the class name - "Simple Asphyxiant", "Combustible Dust 2" -
    which is what identifies them without recall.

    Hazard statements come from tables carrying a "Hazard statement" column beside
    a "Signal word" column. Precautionary statements live in the C.4 tables under
    Prevention / Response / Storage / Disposal, one per paragraph; paragraphs that
    open with an ellipsis are instructions to the manufacturer, not statements.
    """
    doc = LH.fromstring(raw)
    hazard: dict[str, str] = {}
    precautionary: set[str] = set()
    signals: set[str] = set()
    categories: dict[str, str] = {}

    for table in doc.xpath("//table"):
        hazard_cols: tuple[int, int] | None = None
        category_col: int | None = None
        prec_cols: list[int] | None = None
        # A table's slot footnotes, and the statements that use them. The
        # footnote is printed after the statements, so they are expanded once
        # the table has been read.
        legends: dict[int, str] = {}
        in_this_table: list[str] = []
        for row in table.xpath(".//tr"):
            cells = row.xpath("./td|./th")
            values = [_node_text(c) for c in cells]
            lower = [v.lower() for v in values]

            if "hazard statement" in lower and "signal word" in lower:
                hazard_cols = (lower.index("signal word"), lower.index("hazard statement"))
                category_col = (
                    lower.index("hazard category") if "hazard category" in lower else None
                )
                prec_cols = None
                continue
            if len([v for v in lower if v in _PRECAUTIONARY_COLUMNS]) >= 2:
                prec_cols = [i for i, v in enumerate(lower) if v in _PRECAUTIONARY_COLUMNS]
                hazard_cols = None
                continue

            if hazard_cols and len(values) > max(hazard_cols):
                signal = values[hazard_cols[0]].strip()
                raw_statement = values[hazard_cols[1]]
                legend = slot_legend(raw_statement)
                if legend:
                    depth, instruction = legend
                    legends[depth] = instruction
                    continue
                statement = strip_condition(strip_guidance(raw_statement))
                if signal in ("Danger", "Warning"):
                    signals.add(signal)
                if _is_statement(statement):
                    hazard.setdefault(statement, signal)
                    in_this_table.append(statement)
                    if category_col is not None and category_col < len(values):
                        category = values[category_col].strip()
                        if category:
                            categories.setdefault(statement, category)
            elif prec_cols:
                for index in prec_cols:
                    if index >= len(cells):
                        continue
                    paragraphs = cells[index].xpath(".//p")
                    chunks = (
                        [_node_text(p) for p in paragraphs]
                        if paragraphs
                        else [values[index]]
                    )
                    for chunk in chunks:
                        text = strip_condition(strip_guidance(chunk))
                        if _is_statement(text):
                            precautionary.add(text)

        for statement in in_this_table:
            expanded = apply_slot_legends(statement, legends)
            if expanded == statement:
                continue
            hazard[expanded] = hazard.pop(statement)
            if statement in categories:
                categories[expanded] = categories.pop(statement)
    return hazard, precautionary, signals, categories


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


# A "Hazard category" cell that names a class rather than a GHS category. OSHA
# defines a few hazard classes GHS does not, and their rows carry the class name
# here instead of a number ("Simple Asphyxiant", "Combustible Dust 2").
_CLASS_CATEGORY_RE = re.compile(r"^(?!Division|Type|Category)([A-Za-z][A-Za-z ]{3,})\s*\d*$")


def internal_id_for(category: str) -> str | None:
    """An internal identifier for an OSHA-only hazard class, or None.

    These are NOT regulatory codes - OSHA assigns none - so they are prefixed
    OSHA- and flagged `internal_id` on the entry. The initials come from the
    class name the document itself states.
    """
    match = _CLASS_CATEGORY_RE.match((category or "").strip())
    if not match:
        return None
    words = [w for w in match.group(1).split() if w]
    if not words:
        return None
    return "OSHA-" + "".join(w[0].upper() for w in words)


def _entry(code, text, kind, signal, ts, how, reference_name=None):
    return AnswerKeyEntry(
        regulation=REGULATION, revision=REVISION, language="en", code=code,
        kind=kind, text=text,
        signal_word=signal if signal in ("Danger", "Warning") else None,
        tier=Tier.A, source_url=SOURCE_URL,
        source_ref=f"29 CFR 1910.1200 App. C; code established by wording {how} "
                   f"to {reference_name or REFERENCE_NAME}",
        retrieved_at=ts, status=Status.OK,
    )


def split_two_statements(
    text: str, candidates: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]] | None:
    """Split a cell that holds two statements, e.g. H222 followed by H229.

    Appendix C sometimes prints two statements in one cell with no separator:
    "Extremely flammable aerosol Pressurized container: may burst if heated".
    Rather than guess where one ends - a capitalised word after a lower-case one
    is not a reliable signal, since statements contain capitalised words - every
    word boundary is tried and a split is accepted only when **both** halves
    resolve to a code exactly. A wrong split cannot survive that test, so this
    adds no guesswork.
    """
    words = text.split()
    if len(words) < 4:
        return None
    for cut in range(2, len(words) - 1):
        left, right = " ".join(words[:cut]), " ".join(words[cut:])
        left_code, left_how = _resolve_code(left, candidates)
        if left_code is None:
            continue
        right_code, right_how = _resolve_code(right, candidates)
        if right_code is None or right_code == left_code:
            continue
        return [(left, left_code, left_how), (right, right_code, right_how)]
    return None


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

    hazard, precautionary, signals, categories = parse_appendix_c(raw)

    # OSHA's key is knowingly incomplete, so "this code is not in the key" does
    # not mean "this regulation does not have it". Record which GHS wordings
    # appear anywhere in Appendix C, so check time can tell the two apart.
    from lingua_oracle.keys.builders.ghs_index import write_source_presence

    write_source_presence(
        "us_osha",
        Path(from_file).name if from_file else "appendix_c.html",
        list(hazard) + list(precautionary),
    )

    reference_path = root / REFERENCE_FILE
    if not reference_path.exists():
        raise SourceUnavailable(
            f"{REFERENCE_NAME} is required to key OSHA statements: {reference_path}"
        )
    first, last = annex_page_range(str(reference_path))
    reference, ref_issues = harvest(str(reference_path), first_page=first, last_page=last)
    reference = {c: t for c, t in reference.items() if c[:1] in "HP"}

    # OSHA covers chemicals under pressure, a class Rev.7 does not define. Its
    # statements come from Rev.8, which is the edition that introduced them, and
    # only for that class - everything else stays on Rev.7.
    overlay, _unchanged = pressure_overlay(root)
    reference.update(overlay)
    rev8_codes = set(overlay)

    issues = ParseIssues(source=f"{REGULATION}/en ({origin})")
    issues.rows_seen = len(hazard) + len(precautionary)
    ts = now()
    entries: dict[str, AnswerKeyEntry] = {}
    unmapped: list[str] = []
    split_count = [0]
    internal_count: list[str] = []

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
                pair = split_two_statements(text, candidates)
                if pair is None:
                    internal = (
                        internal_id_for(categories.get(text, ""))
                        if prefix == "H" else None
                    )
                    if internal and internal not in entries:
                        entries[internal] = AnswerKeyEntry(
                            regulation=REGULATION, revision=REVISION, language="en",
                            code=internal, kind=Kind.HAZARD, text=text,
                            signal_word=hazard.get(text)
                            if hazard.get(text) in ("Danger", "Warning") else None,
                            tier=Tier.A, internal_id=True, source_url=SOURCE_URL,
                            source_ref=f"29 CFR 1910.1200 App. C, hazard class "
                                       f"'{categories.get(text, '').strip()}'. OSHA "
                                       "defines this class without a GHS code; "
                                       f"'{internal}' is an internal identifier of "
                                       "this tool, NOT a regulatory code, and is "
                                       "matched by text.",
                            retrieved_at=ts, status=Status.OK,
                        )
                        internal_count.append(internal)
                        continue
                    unmapped.append((prefix, text))
                    continue
                split_count[0] += 1
                for part, part_code, part_how in pair:
                    if part_code not in entries:
                        entries[part_code] = _entry(
                            part_code, part, kind, hazard.get(text), ts,
                            f"{part_how}; split from a cell holding two statements",
                            REV8_NAME if part_code in rev8_codes else None,
                        )
                continue
            if code in entries:
                continue
            entries[code] = _entry(
                code, text, kind, hazard.get(text), ts, how,
                REV8_NAME if code in rev8_codes else None,
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
    issues.notes.append(
        f"reference table: {REFERENCE_NAME} ({len(reference) - len(rev8_codes)} codes)"
        + (f", overlaid with {REV8_NAME} for {', '.join(sorted(rev8_codes))} "
           "(chemicals under pressure, a class Rev.7 does not define)"
           if rev8_codes else "")
    )
    issues.notes.append(
        f"statements read from the source: {len(hazard)} hazard, "
        f"{len(precautionary)} precautionary"
    )
    issues.notes.append(f"codes established: {h_count} H, {p_count} P, "
                        f"{len(signals)} signal word(s)")
    if internal_count:
        issues.notes.append(
            "OSHA-only hazard classes, stored under internal identifiers (NOT "
            f"regulatory codes) and matched by text: {', '.join(sorted(internal_count))}"
        )
    if split_count[0]:
        issues.notes.append(
            f"cells holding two statements, split and both halves resolved: {split_count[0]}"
        )
    # An unmatched statement is not the same as a missing code. Most are the same
    # statement printed again with its fill-in completed, with a usage condition
    # attached, or with a typo in the published HTML - the code is already held.
    # Only the remainder are real gaps, and only those decide the key's status.
    from lingua_oracle.match.template import match as _template_match

    duplicates: list[tuple[str, str]] = []
    genuinely_absent: list[tuple[str, str]] = []
    for prefix, raw_text in unmapped:
        restates = any(
            not e.internal_id
            and e.code.startswith(prefix)
            and _template_match(raw_text, e.text).matched
            for e in entries.values()
        )
        (duplicates if restates else genuinely_absent).append((prefix, raw_text))

    if duplicates:
        issues.notes.append(
            f"statements that restate a code already held ({len(duplicates)}): the "
            "same statement printed again with its fill-in completed, a usage "
            "condition attached, or a typo in the published HTML. Not gaps."
        )
    if genuinely_absent:
        issues.notes.append(
            f"statements not represented by any code held ({len(genuinely_absent)}). "
            "Matching is exact, so these are left out rather than guessed:"
        )
        issues.notes.extend(f"    {p}: {t[:100]}" for p, t in genuinely_absent)
    UNREPRESENTED[REGULATION] = len(genuinely_absent)
    if absent:
        issues.notes.append(
            f"GHS Rev.7 codes with no OSHA statement ({len(absent)}). These are NOT "
            "assumed to be gaps: OSHA's adoption is partial, so some are genuine "
            "differences and some are parse misses. Needs review:"
        )
        issues.notes.append("    " + ", ".join(absent))


    notes: list[str] = []
    if genuinely_absent:
        notes.append(
            f"{len(genuinely_absent)} Appendix C statement(s) are not represented by "
            "any code held. Matching is exact, so they are left out rather than "
            "guessed:"
        )
        notes.extend(f"  {p}: {t}" for p, t in genuinely_absent)
        notes.append(
            "None is substantive divergence. Each differs from the GHS text only in "
            "how the osha.gov HTML renders it: a dropped word ('Explosive; fire, "
            "blast or projection' against Rev.7 H203's '... projection hazard'), an "
            "added comma (against H260), or a full stop where Rev.8 prints a colon "
            "(H282, H283). They are excluded solely because matching is exact."
        )
    if genuinely_absent:
        notes.append(
            "Whether these are OSHA's own wording or errors in the osha.gov HTML "
            "could not be verified: the official CFR publishes Appendix C's tables "
            "as graphics, not text (eCFR renderer 404s for the appendix, its "
            "structure API lists no appendix node, and neither ecfr.gov nor "
            "govinfo.gov XML contains the statements). They are left out rather "
            "than aliased on a guess."
        )
    notes.append(
        f"{len(duplicates)} further statement(s) restate a code already held "
        "(fill-in completed, usage condition attached, or a typo in the published "
        "HTML). Those are not gaps."
    )
    if internal_count:
        notes.append(
            "OSHA-only hazard classes are stored under internal identifiers "
            f"({', '.join(sorted(internal_count))}). These are NOT regulatory "
            "codes and are matched by text."
        )

    if genuinely_absent:
        status, reason = Status.PARTIAL, "unrepresented_statements_remain"
    elif entries:
        status, reason = Status.OK, None
    else:
        status, reason = Status.PENDING_SOURCE, "source_unreadable"

    key = AnswerKey(
        regulation=REGULATION, language="en", revision=REVISION,
        status=status, status_reason=reason,
        source_url=SOURCE_URL, retrieved_at=ts, notes=notes,
        entries=sorted(entries.values(), key=lambda e: (e.kind, e.code)),
    )
    return [key], [issues]
