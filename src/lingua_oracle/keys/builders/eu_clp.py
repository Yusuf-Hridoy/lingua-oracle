"""Answer-key builder for EU CLP, Regulation (EC) No 1272/2008 (consolidated).

Source: the EU Publications Office CELLAR endpoint, which serves the official
consolidated act as XHTML with content negotiation. EUR-Lex's own HTML views sit
behind a WAF challenge; CELLAR is the sanctioned machine-readable route.

Two passes:

1. Statements. Annexes III and IV render each code as a table whose header row is
   ``[code, "Language", <hazard class>]`` followed by one row per official
   language. A single fetch therefore yields all 24 languages.
2. Signal words. These are not in a multilingual table; they appear in the
   Annex I label-element tables as rows starting "Signal Word". Language versions
   of the act are structurally parallel (same table and row count), so the
   translated signal word is read from the *same cell position* as the English
   "Danger"/"Warning". A value is only accepted when the aligned cells agree.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from lxml import html as LH

from lingua_oracle.keys.builders.common import (
    SourceUnavailable,
    fetch,
    normalise_code,
    now,
    repair_degree_sign,
    strip_markers,
)
from lingua_oracle.keys.builders.signal_words import leading_word
from lingua_oracle.match.normalize import normalize, strip_punctuation
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

# Languages whose act text was unavailable, so signal words could not be read.
MISSING_SIGNAL_WORDS: set[str] = set()

REGULATION = "eu_clp"
CELEX = "02008R1272-20260701"
BASE_URL = f"http://publications.europa.eu/resource/celex/{CELEX}"
# The consolidated act has no Irish version (CELLAR returns 404), but the
# original 2008 act does, and signal words have not changed since. Irish signal
# words are read from there and the fallback is recorded in source_ref.
ORIGINAL_CELEX = "32008R1272"
ORIGINAL_URL = f"http://publications.europa.eu/resource/celex/{ORIGINAL_CELEX}"
# Supplemental statements that open with the signal word for Warning. Used only
# to break a tie where the act contradicts itself; the rule is validated first
# against languages whose Annex I vote is unambiguous.
WARNING_LEAD_CODES = ("EUH206", "EUH207", "EUH201A")

# CELLAR wants ISO-639-3 in Accept-Language; keys are the BCP-47 tags we store.
LANGS: dict[str, str] = {
    "bg": "bul", "cs": "ces", "da": "dan", "de": "deu", "el": "ell", "en": "eng",
    "es": "spa", "et": "est", "fi": "fin", "fr": "fra", "ga": "gle", "hr": "hrv",
    "hu": "hun", "it": "ita", "lt": "lit", "lv": "lav", "mt": "mlt", "nl": "nld",
    "pl": "pol", "pt": "por", "ro": "ron", "sk": "slk", "sl": "slv", "sv": "swe",
}
# Column label used inside the multilingual tables -> our BCP-47 tag.
COL_TO_BCP47 = {v.upper(): k for k, v in
                {"bg": "BG", "cs": "CS", "da": "DA", "de": "DE", "el": "EL", "en": "EN",
                 "es": "ES", "et": "ET", "fi": "FI", "fr": "FR", "ga": "GA", "hr": "HR",
                 "hu": "HU", "it": "IT", "lt": "LT", "lv": "LV", "mt": "MT", "nl": "NL",
                 "pl": "PL", "pt": "PT", "ro": "RO", "sk": "SK", "sl": "SL",
                 "sv": "SV"}.items()}


def _doc(lang_iso3: str, *, use_cache: bool = True, url: str = BASE_URL):
    try:
        raw = fetch(
            url,
            headers={"Accept": "application/xhtml+xml", "Accept-Language": lang_iso3},
            use_cache=use_cache,
        )
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(f"CELLAR fetch failed for {lang_iso3}: {exc}") from exc
    if len(raw) < 100_000:
        raise SourceUnavailable(f"CELLAR returned {len(raw)} bytes for {lang_iso3}")
    return LH.fromstring(raw)


def _row_cells(row) -> list[str]:
    return [repair_degree_sign(" ".join(c.text_content().split()))
            for c in row.xpath("./td|./th")]


def _kind_for(code: str) -> Kind:
    if code.startswith("EUH"):
        return Kind.SUPPLEMENTAL
    if code.startswith("H"):
        return Kind.HAZARD
    return Kind.PRECAUTIONARY


def _cell_paragraphs(cell) -> list[str]:
    """The cell's paragraphs, in order, as separate strings.

    A header naming two codes - "EUH 209/ 209A" - has a cell holding two
    statements, one per code, as two <p> elements. text_content() flattens
    them into one string, which is how both codes came to hold
    "Can become highly flammable in use. Can become flammable in use."
    """
    out = [repair_degree_sign(" ".join(p.text_content().split()))
           for p in cell.xpath("./p")]
    out = [t for t in out if t]
    return out or [repair_degree_sign(" ".join(cell.text_content().split()))]


def _expand_code(raw_code: str) -> list[str]:
    """'EUH 201/ 201A' names two codes, each with its own statement."""
    code = normalise_code(raw_code)
    if "/" not in code:
        return [code]
    head, *rest = [p.strip() for p in code.split("/")]
    prefix = re.match(r"^([A-Z]+)", head)
    out = [head]
    for r in rest:
        out.append(r if re.match(r"^[A-Z]", r) else f"{prefix.group(1) if prefix else ''}{r}")
    return [normalise_code(c) for c in out if c]


#: A footnote marker attached to a class code, e.g. "Press. Gas (*1)".
_CLASS_FOOTNOTE_RE = re.compile(r"\s*\(\*?\d+\)\s*$")


def hazard_class_codes(doc) -> list[str]:
    """CLP's hazard class and category codes, from Annex VI Table 1.1.

    "Skin Irrit. 2", "Aquatic Chronic 3", "Flam. Liq. 2" - what a sheet puts in
    the classification column beside the H code. Read from the source rather
    than typed out, because a list from memory is exactly the thing this
    project does not allow.

    Some cells name several categories at once - "Resp. Sens. 1, 1A, 1B" - and
    are expanded into one code each.
    """
    out: list[str] = []
    for table in doc.xpath("//table"):
        rows = table.xpath(".//tr")
        if not rows:
            continue
        head = _row_cells(rows[0])
        if len(head) != 2 or "hazard class and category code" not in head[1].lower():
            continue
        for row in rows[1:]:
            cells = row.xpath("./td|./th")
            if len(cells) != 2:
                continue
            for raw in _cell_paragraphs(cells[1]):
                text = _CLASS_FOOTNOTE_RE.sub("", strip_markers(raw)).strip()
                if not text:
                    continue
                head_part, _, tail = text.partition(",")
                out.append(head_part.strip())
                if tail:
                    # "Resp. Sens. 1, 1A, 1B": the stem is everything before
                    # the final category token of the first entry.
                    stem = head_part.rsplit(" ", 1)[0].strip()
                    for extra in tail.split(","):
                        extra = extra.strip()
                        if extra:
                            out.append(f"{stem} {extra}")
        break
    return sorted({c for c in out if c})


_CODE_CELL = re.compile(r"^(EUH|AUH|P|H)\s?\d{3}[A-Za-z]?$")


def part_one_statements(doc) -> dict[str, str]:
    """{code: text} from Annex IV Part 1, the tables that select statements.

    CLP states each statement twice: Part 1 lists it beside the hazard class it
    is selected for, and Part 2 gives it in all 24 languages. They are normally
    identical, and where they are not, Part 1 has sometimes had an amendment
    Part 2 did not - Regulation (EU) 2019/521 rewrote P103 and P280, and in this
    consolidation only Part 1 shows it, under a ▼M19 block.

    Part 1 tables carry five columns and name the code in each row; Part 2
    tables carry three and name the code in the header.
    """
    out: dict[str, str] = {}
    for table in doc.xpath("//table"):
        rows = table.xpath(".//tr")
        if len(rows) < 2:
            continue
        head = _row_cells(rows[0])
        if len(head) < 3 or _CODE_CELL.match(head[0].strip().replace(" ", "")):
            continue
        for row in rows[1:]:
            cells = _row_cells(row)
            if len(cells) < 2:
                continue
            code = normalise_code(cells[0])
            if _CODE_CELL.match(code) and cells[1].strip():
                out.setdefault(code, strip_markers(cells[1]))
    return out


def _same_statement(a: str, b: str) -> bool:
    """True when two renderings differ only in punctuation, spacing or case."""
    key = lambda t: strip_punctuation(normalize(t)).casefold()  # noqa: E731
    return key(a) == key(b)


#: How much of the language set has to show the same disagreement before Part 1
#: is taken as an amendment. A real amendment rewrites every translation; a
#: rendering difference in one or two languages is Part 1 abbreviating a row.
_AMENDMENT_SHARE = 0.8


def amended_in_part_one(
    part_one: dict[str, dict[str, str]], part_two: dict[str, dict[str, str]]
) -> dict[str, list[str]]:
    """Codes whose Part 1 text supersedes Part 2, with the languages agreeing."""
    languages = sorted(set(part_one) & set(part_two))
    if len(languages) < 20:
        return {}  # not a full build; nothing to compare across
    disagreeing: dict[str, list[str]] = {}
    for lang in languages:
        for code, text in part_one[lang].items():
            other = part_two[lang].get(code)
            if other and not _same_statement(text, other):
                disagreeing.setdefault(code, []).append(lang)
    return {
        code: langs for code, langs in disagreeing.items()
        if len(langs) >= _AMENDMENT_SHARE * len(languages)
    }


def parse_statements(doc) -> dict[str, list[AnswerKeyEntry]]:
    """Return {bcp47: [entry, ...]} for every multilingual code table."""
    per_lang: dict[str, list[AnswerKeyEntry]] = collections.defaultdict(list)
    ts = now()
    seen: set[tuple[str, str]] = set()
    for table in doc.xpath("//table"):
        rows = table.xpath(".//tr")
        if not rows:
            continue
        head = _row_cells(rows[0])
        if len(head) != 3 or head[1].strip() != "Language":
            continue
        codes = _expand_code(head[0])
        if not codes or not re.match(r"^(H|P|EUH)\d", codes[0]):
            continue
        source_ref = strip_markers(head[2]) or None
        for row in rows[1:]:
            cells = _row_cells(row)
            if len(cells) != 3:
                continue  # amendment-marker row
            lang = COL_TO_BCP47.get(cells[1].strip().upper())
            # One paragraph per code when the counts line up; otherwise the
            # whole cell for each, which is the old behaviour and is recorded
            # as an issue rather than silently assumed.
            paragraphs = _cell_paragraphs(row.xpath("./td|./th")[2])
            if len(codes) > 1 and len(paragraphs) == len(codes):
                texts = [strip_markers(t) for t in paragraphs]
            else:
                # Counts do not line up: fall back to the whole cell for each
                # code. test_an_a_variant_differs_from_its_base_code fails if
                # that ever produces two codes with identical text again.
                texts = [strip_markers(cells[2])] * len(codes)
            if not lang or not any(texts):
                continue
            for code, text in zip(codes, texts, strict=True):
                if not text:
                    continue
                if (lang, code) in seen:
                    continue
                seen.add((lang, code))
                per_lang[lang].append(
                    AnswerKeyEntry(
                        regulation=REGULATION, revision=CELEX, language=lang, code=code,
                        kind=_kind_for(code), text=text, tier=Tier.A,
                        source_url=BASE_URL,
                        source_ref=f"Annex III/IV table for {code}"
                        + (f" ({source_ref})" if source_ref else ""),
                        retrieved_at=ts, status=Status.OK,
                    )
                )
    return per_lang


def signal_word_positions(en_doc) -> list[tuple[int, int, int, str]]:
    """Cells in the English act holding a literal 'Danger'/'Warning' signal word."""
    out = []
    for ti, table in enumerate(en_doc.xpath("//table")):
        for ri, row in enumerate(table.xpath(".//tr")):
            cells = _row_cells(row)
            if not cells or cells[0].strip().lower() != "signal word":
                continue
            for ci, val in enumerate(cells[1:], start=1):
                v = strip_markers(val)
                if v in ("Danger", "Warning"):
                    out.append((ti, ri, ci, v))
    return out


def extract_signal_words(doc, positions, en_tables=None) -> dict[str, str]:
    """Read translated signal words from the aligned cell positions.

    Language versions are *mostly* structurally parallel, not perfectly so, and a
    misaligned row contributes nonsense. Two filters keep that out:

    1. A position only counts when the target row has the same cell count as the
       English row it is aligned to.
    2. Votes are grouped by the target row's own label cell. Genuine signal-word
       rows all share one label (``Signalwort``, ``Signalord``, ...), so the
       largest label group is the real one and stray rows fall away.

    A word is returned only on a two-thirds supermajority within that group. Greek,
    for one, splits genuinely between two words in the consolidated text; there the
    right answer is to return nothing and let the check report the code as
    unverified, rather than to pick one.
    """
    tables = doc.xpath("//table")
    by_label: dict[str, dict[str, collections.Counter]] = collections.defaultdict(
        lambda: collections.defaultdict(collections.Counter)
    )
    for ti, ri, ci, en_val in positions:
        if ti >= len(tables):
            continue
        rows = tables[ti].xpath(".//tr")
        if ri >= len(rows):
            continue
        cells = _row_cells(rows[ri])
        if en_tables is not None:
            en_rows = en_tables[ti].xpath(".//tr")
            if ri >= len(en_rows) or len(cells) != len(_row_cells(en_rows[ri])):
                continue
        if ci >= len(cells):
            continue
        value = strip_markers(cells[ci])
        if value:
            by_label[strip_markers(cells[0])][en_val][value] += 1

    if not by_label:
        return {}
    label = max(
        by_label,
        key=lambda lb: sum(sum(c.values()) for c in by_label[lb].values()),
    )
    result: dict[str, str] = {}
    for en_val, counter in by_label[label].items():
        total = sum(counter.values())
        (best, votes), = counter.most_common(1)
        if total >= 2 and votes * 3 >= total * 2:
            result[en_val] = best
    return result


def hazard_signal_words(en_doc) -> dict[str, str]:
    """Map each hazard code to the signal word CLP Annex I assigns it.

    The Annex I label-element tables are column-aligned: a "Signal Word" row and
    a "Hazard Statement" row share one column per hazard category, so the signal
    word for a code is the cell directly above it. A code that appears under both
    Danger and Warning in different categories is recorded as "Either".
    """
    seen: dict[str, set[str]] = collections.defaultdict(set)
    for table in en_doc.xpath("//table"):
        rows = [_row_cells(r) for r in table.xpath(".//tr")]
        signal_row = next(
            (r for r in rows if r and r[0].strip().lower() == "signal word"), None
        )
        statement_rows = [
            r for r in rows if r and "hazard statement" in r[0].strip().lower()
        ]
        if signal_row is None or not statement_rows:
            continue
        for statement_row in statement_rows:
            for col in range(1, min(len(signal_row), len(statement_row))):
                word = strip_markers(signal_row[col])
                if word not in ("Danger", "Warning"):
                    continue
                for m in re.finditer(r"\b(?:EUH|H)\s?\d{3}[A-Za-z]?\b",
                                     statement_row[col]):
                    seen[normalise_code(m.group(0))].add(word)
    return {
        code: (words.pop() if len(words) == 1 else "Either")
        for code, words in ((c, set(w)) for c, w in seen.items())
    }



def _signal_words_for(lang, iso3, en_doc, positions, en_tables, entries, *, use_cache=True):
    """Signal words for one language, with two documented fallbacks.

    1. The Annex I vote on the consolidated act (the normal path).
    2. Where a word is contested - Greek uses two different words across the
       consolidated text - it is taken from the opening word of a supplemental
       statement that begins with it, e.g. EUH206 "Warning! ...". That rule is
       only applied to the contested word, and it agrees with the Annex I vote in
       every language where the vote is unambiguous.
    3. Where the consolidated act has no version in that language at all - Irish -
       the original 2008 act is used instead, and the source_ref says so.
    """
    note = ""
    try:
        doc = en_doc if lang == "en" else _doc(iso3, use_cache=use_cache)
        words = extract_signal_words(doc, positions, en_tables)
    except SourceUnavailable:
        words = {}

    if not words:
        try:
            original_en = _doc("eng", use_cache=use_cache, url=ORIGINAL_URL)
            original = _doc(iso3, use_cache=use_cache, url=ORIGINAL_URL)
        except SourceUnavailable:
            return {}, note
        words = extract_signal_words(
            original, signal_word_positions(original_en), original_en.xpath("//table")
        )
        if words:
            note = (
                f"; taken from the original act {ORIGINAL_CELEX}, which unlike the "
                "consolidated version exists in this language"
            )

    if "Warning" not in words:
        by_code = {e.code: e.text for e in entries}
        for code in WARNING_LEAD_CODES:
            lead = leading_word(by_code.get(code, ""))
            if lead:
                words["Warning"] = lead
                note += (
                    f"; Warning resolved from {code}, which opens with the signal "
                    "word, because the Annex I tables disagree in this language"
                )
                break
    return words, note


def write_part_audit(amended: dict[str, list[str]],
                     part_one: dict[str, dict[str, str]]) -> Path:
    """Record which codes Part 1 superseded, and with what.

    The audit that found P103 and P280 becomes a permanent test: the key has to
    keep holding the text this build chose, in every language it chose it for.
    """
    # Not under answer_keys/: everything there is loaded as a key.
    target = data_dir() / "audits" / "eu_clp_annex_iv.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "source": CELEX,
                "note": "Annex IV Part 1 text used where Part 2 was not amended",
                "amended": {c: sorted(langs) for c, langs in sorted(amended.items())},
                "text": {
                    code: {lang: part_one[lang][code]
                           for lang in sorted(langs) if code in part_one.get(lang, {})}
                    for code, langs in sorted(amended.items())
                },
            },
            ensure_ascii=False, indent=1, sort_keys=False,
        ),
        encoding="utf-8",
    )
    return target


def write_hazard_classes(doc) -> Path:
    """Commit the class list so check time needs no network and no parse."""
    target = data_dir() / "hazard_classes" / "eu_clp.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"source": CELEX, "codes": hazard_class_codes(doc)},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return target


#: Filled by the last build: {code: [languages where Part 1 superseded Part 2]}.
#: Written into the parse report so the choice is on the record.
AMENDED_IN_PART_ONE: dict[str, list[str]] = {}


def build(languages: list[str] | None = None, *, use_cache: bool = True,
          with_signal_words: bool = True) -> list[AnswerKey]:
    """Build EU CLP answer keys. Returns one AnswerKey per language."""
    wanted = languages or list(LANGS)
    en_doc = _doc("eng", use_cache=use_cache)
    # A sheet's classification column holds these, not statements; check time
    # needs the list and must not parse the act to get it.
    write_hazard_classes(en_doc)
    per_lang = parse_statements(en_doc)
    code_signals = hazard_signal_words(en_doc)
    positions = signal_word_positions(en_doc)
    en_tables = en_doc.xpath("//table")
    ts = now()

    # Each language's own act, read for Part 1. Fetched once here rather than
    # inside the loop below, because deciding whether a difference is an
    # amendment needs every language at once.
    part_one: dict[str, dict[str, str]] = {}
    part_two: dict[str, dict[str, str]] = {
        lang: {e.code: e.text for e in entries if e.text}
        for lang, entries in per_lang.items()
    }
    for lang in wanted:
        iso3 = LANGS.get(lang)
        if iso3 is None:
            continue
        try:
            doc = en_doc if lang == "en" else _doc(iso3, use_cache=use_cache)
        except SourceUnavailable:
            continue  # the language's own act is unavailable; Part 2 stands
        part_one[lang] = part_one_statements(doc)

    amended = amended_in_part_one(part_one, part_two)
    AMENDED_IN_PART_ONE.clear()
    AMENDED_IN_PART_ONE.update(amended)
    if amended:
        write_part_audit(amended, part_one)

    keys: list[AnswerKey] = []
    for lang in wanted:
        iso3 = LANGS.get(lang)
        if iso3 is None:
            continue
        entries = [
            e.model_copy(update={"signal_word": code_signals[e.code]})
            if e.code in code_signals
            else e
            for e in per_lang.get(lang, [])
        ]
        # Where Part 1 carries an amendment Part 2 never received, Part 1 is
        # the text in force. Chosen per code, never blended within a statement.
        newer = part_one.get(lang, {})
        entries = [
            e.model_copy(update={
                "text": newer[e.code],
                "source_ref": f"{e.source_ref}; Part 1 text, amended after Part 2",
            })
            if e.code in amended and newer.get(e.code) else e
            for e in entries
        ]
        if with_signal_words:
            words, note = _signal_words_for(lang, iso3, en_doc, positions, en_tables,
                                            entries, use_cache=use_cache)
            for en_val, code in (("Danger", SIGNAL_DANGER), ("Warning", SIGNAL_WARNING)):
                text = words.get(en_val)
                if not text:
                    MISSING_SIGNAL_WORDS.add(f"{lang}/{en_val}")
                    continue
                entries.append(
                    AnswerKeyEntry(
                        regulation=REGULATION, revision=CELEX, language=lang, code=code,
                        kind=Kind.SIGNAL, text=text,
                        signal_word="Danger" if en_val == "Danger" else "Warning",
                        tier=Tier.A, source_url=BASE_URL,
                        source_ref="Annex I label element tables "
                                   "(aligned 'Signal Word' rows)" + note,
                        retrieved_at=ts, status=Status.OK,
                    )
                )
        entries.sort(key=lambda e: (e.kind, e.code))
        keys.append(
            AnswerKey(
                regulation=REGULATION, language=lang, revision=CELEX,
                status=Status.OK if entries else Status.PENDING_SOURCE,
                source_url=BASE_URL, retrieved_at=ts, entries=entries,
            )
        )
    return keys
