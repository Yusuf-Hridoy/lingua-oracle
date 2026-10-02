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
from dataclasses import dataclass, replace
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
from lingua_oracle.keys.builders.defects import defects
from lingua_oracle.keys.builders.eu_acts import (
    Decision,
    act_rank,
    act_rendering,
    amending_acts,
    annex_iv_scope,
    decide,
    markers_by_code,
    markers_used,
)
from lingua_oracle.keys.builders.signal_words import leading_word
from lingua_oracle.keys.errata import load_errata
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


def _differing_by_code(
    part_one: dict[str, dict[str, str]], part_two: dict[str, dict[str, str]]
) -> dict[str, list[str]]:
    """{code: [language, ...]} wherever the two Parts disagree over a statement."""
    out: dict[str, list[str]] = {}
    for lang in sorted(set(part_one) & set(part_two)):
        for code, text in part_one[lang].items():
            other = part_two[lang].get(code)
            if other and not _same_statement(text, other):
                out.setdefault(code, []).append(lang)
    return out


def act_scope(acts: dict[str, dict[str, str]], markers: set[str], *,
              use_cache: bool = True) -> dict[str, dict[str, dict[str, str]]]:
    """Read the Annex IV section of every act that governs a statement here.

    Only the acts that actually produced a block of Annex IV are fetched - five
    of the thirty-seven in the consolidation's front matter have ever touched
    it. Which five is read off the markers, so a later amendment pulls its own
    act in without anyone editing a list.
    """
    scope: dict[str, dict[str, dict[str, str]]] = {}
    for marker in sorted(markers):
        if act_rank(marker) in (None, 0):
            continue  # the base act amends nothing; a corrigendum is not an act
        celex = acts.get(marker, {}).get("celex")
        if not celex:
            continue
        try:
            scope[marker] = annex_iv_scope(celex, use_cache=use_cache)
        except Exception:  # noqa: BLE001 - an unreadable act decides nothing
            continue
    return scope


def decisions_for(language: str, part_one_marks: dict[str, str],
                  part_two_marks: dict[str, str],
                  scope: dict[str, dict[str, dict[str, str]]],
                  ) -> dict[str, Decision]:
    """Which Part is in force, for every precautionary code in both Parts."""
    codes = {c for c in set(part_one_marks) & set(part_two_marks)
             if c.startswith("P")}
    return {
        code: decide(code, language, part_one_marks.get(code),
                     part_two_marks.get(code), scope)
        for code in sorted(codes)
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


@dataclass(frozen=True)
class Chosen:
    """The text in force for one code in one language, and how it got there."""

    code: str
    language: str
    decision: Decision
    text: str
    superseded: str
    defects: tuple[str, ...]
    #: "ok" when the text may be used, "errata" when a reviewed correction
    #: covers its defect, "not_on_file" when it may not be used at all.
    status: str
    #: True when the amending act prints the defect too, so there is nothing to
    #: correct it from; None when the act was not consulted.
    act_confirms_defect: bool | None = None


def choose(code: str, language: str, decision: Decision,
           part_one_text: str | None, part_two_text: str | None,
           *, erratum_for: str | None = None) -> Chosen:
    """Apply one decision to the two renderings, and check what it chose.

    The Part the acts point at is taken whole - never blended with the other.
    If the chosen rendering carries a visible defect, it is not used silently:
    either a reviewed erratum covers it, or the code is withheld in that
    language. Repairing it here would mean writing regulatory text ourselves.
    """
    wanted = part_one_text if decision.from_part_one else part_two_text
    other = part_two_text if decision.from_part_one else part_one_text
    if not wanted:
        # The language's own act could not be read, so the rendering the acts
        # point at is not available here; what is left is the superseded one.
        return Chosen(code, language, decision, other or "", other or "", (),
                      "not_on_file" if decision.from_part_one else "ok")
    found = tuple(defects(wanted, other))
    if erratum_for is not None and erratum_for == wanted:
        # A reviewed correction covers this exact text; resolve() applies it.
        status = "errata"
    elif found:
        status = "not_on_file"
    else:
        status = "ok"
    return Chosen(code, language, decision, wanted, other or "", found, status)


def write_act_audit(acts: dict[str, dict[str, str]],
                    scope: dict[str, dict[str, dict[str, str]]]) -> Path:
    """Record what each amending act does to Annex IV, read from the act."""
    target = data_dir() / "audits" / "eu_clp_amending_acts.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "source": CELEX,
                "note": ("Annex IV amendments, read from each act's own ANNEX IV. "
                         "Only acts that have amended Annex IV appear here."),
                "acts": {
                    marker: {
                        **acts.get(marker, {}),
                        "annex_iv": {part: dict(sorted(codes.items()))
                                     for part, codes in sorted(parts.items())},
                    }
                    for marker, parts in sorted(
                        scope.items(), key=lambda kv: act_rank(kv[0]) or 0)
                },
            },
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    return target


def write_part_audit(chosen: dict[str, dict[str, Chosen]],
                     acts: dict[str, dict[str, str]]) -> Path:
    """Record, per code and per language, which Part is in force and why."""
    # Not under answer_keys/: everything there is loaded as a key.
    target = data_dir() / "audits" / "eu_clp_annex_iv.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    record: dict[str, dict] = {}
    for code in sorted(chosen):
        per_language = chosen[code]
        if not per_language:
            continue
        sample = next(iter(per_language.values())).decision
        record[code] = {
            "part": sample.part,
            "act": sample.act,
            "act_title": acts.get(sample.act, {}).get("title", ""),
            "note": sample.note,
            "corroborated": sample.corroborated,
            "languages": {
                lang: {
                    "part": c.decision.part,
                    "act": c.decision.act,
                    "status": c.status,
                    "text": c.text,
                    "superseded": c.superseded,
                    "defects": list(c.defects),
                    "act_confirms_defect": c.act_confirms_defect,
                }
                for lang, c in sorted(per_language.items())
            },
        }
    target.write_text(
        json.dumps(
            {
                "source": CELEX,
                "note": ("Which Part of Annex IV holds the text in force, per code "
                         "and per language. Decided by the latest amending act to "
                         "touch each Part, corroborated by the consolidation's own "
                         "markers. Only codes whose two Parts differ are listed."),
                "decisions": record,
            },
            ensure_ascii=False, indent=1,
        ),
        encoding="utf-8",
    )
    return target


def _cell(text: str | None) -> str:
    """A table cell: no pipes, no line breaks, nothing silently truncated."""
    if not text:
        return "_(not in this Part)_"
    return text.replace("|", "\\|").replace("\n", " ").strip()


def write_part_comparison(part_one: dict[str, dict[str, str]],
                          part_two: dict[str, dict[str, str]],
                          chosen: dict[str, dict[str, Chosen]],
                          acts: dict[str, dict[str, str]]) -> Path:
    """List every disagreement between Annex IV Parts 1 and 2, with its verdict.

    One row per code per language, because the decision is made per code per
    language: the acts amend both at once, but only the languages whose own act
    could be read have markers to corroborate, and a defect is a property of one
    rendering in one language.
    """
    differing = _differing_by_code(part_one, part_two)
    languages = sorted(set(part_one) & set(part_two))
    rows = []
    for code in sorted(chosen, key=lambda c: (-len(differing.get(c, ())), c)):
        count = len(differing.get(code, ()))
        for lang, c in sorted(chosen[code].items()):
            verdict = {"ok": c.decision.part, "errata": "errata",
                       "not_on_file": "not_on_file"}[c.status]
            note = "; ".join(c.defects) if c.defects else c.decision.note
            if c.act_confirms_defect:
                note += " - and the act prints it that way too"
            rows.append(
                f"| {code} | {lang} | {count}/{len(languages)} "
                f"| {_cell(part_one.get(lang, {}).get(code))} "
                f"| {_cell(part_two.get(lang, {}).get(code))} "
                f"| {verdict} | {c.decision.act} | {_cell(note)} |"
            )
    titles = []
    for marker in sorted({c.decision.act for per in chosen.values()
                          for c in per.values()}, key=lambda m: (len(m), m)):
        act = acts.get(marker, {})
        oj = act.get("oj", "").strip()
        titles.append(f"`{marker}` = {act.get('title', '')}"
                      + (f" (OJ {oj})" if oj else ""))
    lines_out = [
        "# EU CLP Annex IV: where Part 1 and Part 2 disagree",
        "",
        f"Source: `{CELEX}`  ",
        f"Languages compared: {len(languages)} ({', '.join(languages)})  ",
        f"Codes where the two Parts disagree in at least one language: "
        f"{len(differing)}  ",
        f"Rows below (one per code per language): {len(rows)}",
        "",
        "CLP states each statement twice: Part 1 beside the hazard class it is",
        "selected for, Part 2 in every language. Several amending acts rewrote",
        "one Part and not the other, so which rendering is the law has to be",
        "decided per code: the latest act to touch each Part wins, read from the",
        "acts themselves and corroborated by the consolidation's own markers.",
        "Where the two sources disagree, or both Parts come from the same act,",
        "Part 2 stands and the reason is given.",
        "",
        "**in force** is what the key holds: `Part 1` or `Part 2` where the text",
        "is used as the act prints it, `errata` where a reviewed correction in",
        "`data/errata/` repairs a defect in it, and `not_on_file` where the text",
        "in force carries a defect that cannot be corrected from the act, so the",
        "code is withheld in that language rather than used.",
        "",
        "**act** is the act that decided it:",
        "",
        *[f"* {t}" for t in titles],
        "",
        "| Code | Lang | Differs in | Part 1 | Part 2 | In force | Act | Why |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        *rows,
    ]
    target = data_dir() / "audits" / "eu_clp_part1_vs_part2.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
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


#: Filled by the last build: {code: {language: Chosen}} for every code whose two
#: Parts disagree. Written into the parse report so the choice is on the record.
IN_FORCE: dict[str, dict[str, Chosen]] = {}


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
    # Markers are read from the same documents: which act produced each block is
    # a property of the language's own consolidation, so it is read per language
    # rather than assumed from English.
    part_one_marks: dict[str, dict[str, str]] = {}
    part_two_marks: dict[str, dict[str, str]] = {}
    for lang in wanted:
        iso3 = LANGS.get(lang)
        if iso3 is None:
            continue
        try:
            doc = en_doc if lang == "en" else _doc(iso3, use_cache=use_cache)
        except SourceUnavailable:
            continue  # the language's own act is unavailable; Part 2 stands
        part_one[lang] = part_one_statements(doc)
        part_one_marks[lang], part_two_marks[lang] = markers_by_code(doc)

    acts = amending_acts(en_doc)
    markers = set()
    for lang in part_one_marks:
        both = set(part_one_marks[lang]) & set(part_two_marks[lang])
        markers |= markers_used(part_one_marks[lang], part_two_marks[lang], both)
    scope = act_scope(acts, markers, use_cache=use_cache)
    write_act_audit(acts, scope)

    # The acts amend every language at once, so a language whose own act could
    # not be read still has a decision - English's - and the question for it is
    # only whether the text that decision points at exists here.
    reference = decisions_for("en", part_one_marks.get("en", {}),
                              part_two_marks.get("en", {}), scope)
    differing = _differing_by_code(part_one, part_two)
    chosen: dict[str, dict[str, Chosen]] = {}
    for code, langs in differing.items():
        for lang in langs:
            decision = (decisions_for(lang, part_one_marks.get(lang, {}),
                                      part_two_marks.get(lang, {}), scope).get(code)
                        if lang in part_one_marks else reference.get(code))
            if decision is None:
                continue
            chosen.setdefault(code, {})[lang] = choose(
                code, lang, decision,
                part_one.get(lang, {}).get(code),
                part_two.get(lang, {}).get(code),
                erratum_for=next((e.wrong for e in load_errata(REGULATION)
                                  if e.code == code and e.language == lang), None),
            )
    # A language with no document of its own loses only the codes whose Parts
    # are known to disagree: there the Part 2 text it holds may be the
    # superseded one and nothing here can tell. Where every readable language
    # shows the two Parts saying the same thing, nothing is superseded and the
    # text stands.
    for code, decision in reference.items():
        if not decision.from_part_one or code not in differing:
            continue
        for lang in wanted:
            if lang in part_one_marks or lang not in LANGS:
                continue
            chosen.setdefault(code, {}).setdefault(lang, choose(
                code, lang, decision, None, part_two.get(lang, {}).get(code)))
    # A defective rendering is checked against the act that produced it. If the
    # act prints the same thing, the defect is the law's own and there is
    # nothing to correct it from; the code is withheld in that language.
    celex = {m: info.get("celex", "") for m, info in acts.items()}
    for code, per_language in chosen.items():
        for lang, pick in list(per_language.items()):
            if not pick.defects or not celex.get(pick.decision.act):
                continue
            iso3 = LANGS.get(lang)
            if iso3 is None:
                continue
            try:
                printed = act_rendering(celex[pick.decision.act], iso3, lang, code,
                                        pick.decision.part, use_cache=use_cache)
            except Exception:  # noqa: BLE001 - an unreadable act proves nothing
                printed = None
            if printed is not None:
                per_language[lang] = replace(
                    pick, act_confirms_defect=printed.strip() == pick.text.strip())
    IN_FORCE.clear()
    IN_FORCE.update(chosen)
    if chosen:
        write_part_audit(chosen, acts)
    if len(part_one) >= 20:
        write_part_comparison(part_one, part_two, chosen, acts)

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
        # The text in force, per code. Taken whole from the Part the acts point
        # at, never blended; withheld where that rendering is defective or is
        # not available in this language.
        updated = []
        for entry in entries:
            pick = chosen.get(entry.code, {}).get(lang)
            if pick is None:
                updated.append(entry)
                continue
            act = acts.get(pick.decision.act, {}).get("title", pick.decision.act)
            where = f"Annex IV {pick.decision.part}, in force under {act}"
            if pick.status == "not_on_file":
                why = ("; ".join(pick.defects) if pick.defects else
                       f"the {pick.decision.part} text is not available in "
                       f"'{lang}'")
                if pick.act_confirms_defect:
                    why += " - the act prints it that way too, so it cannot be "\
                           "corrected from the act"
                updated.append(entry.model_copy(update={
                    "status": Status.NOT_ON_FILE,
                    "text": pick.text or entry.text,
                    "source_ref": f"{entry.source_ref}; {where}, but {why} "
                                  "- not used for a verdict",
                }))
            elif pick.text and pick.text != entry.text:
                updated.append(entry.model_copy(update={
                    "text": pick.text,
                    "source_ref": f"{entry.source_ref}; {where}",
                }))
            else:
                updated.append(entry)
        entries = updated
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
