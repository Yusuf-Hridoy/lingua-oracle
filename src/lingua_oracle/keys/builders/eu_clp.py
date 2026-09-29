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
import re

from lxml import html as LH

from lingua_oracle.keys.builders.common import (
    SourceUnavailable,
    fetch,
    normalise_code,
    now,
    strip_markers,
)
from lingua_oracle.models import (
    SIGNAL_DANGER,
    SIGNAL_WARNING,
    AnswerKey,
    AnswerKeyEntry,
    Kind,
    Status,
    Tier,
)

REGULATION = "eu_clp"
CELEX = "02008R1272-20260701"
BASE_URL = f"http://publications.europa.eu/resource/celex/{CELEX}"

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


def _doc(lang_iso3: str, *, use_cache: bool = True):
    try:
        raw = fetch(
            BASE_URL,
            headers={"Accept": "application/xhtml+xml", "Accept-Language": lang_iso3},
            use_cache=use_cache,
        )
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(f"CELLAR fetch failed for {lang_iso3}: {exc}") from exc
    if len(raw) < 100_000:
        raise SourceUnavailable(f"CELLAR returned {len(raw)} bytes for {lang_iso3}")
    return LH.fromstring(raw)


def _row_cells(row) -> list[str]:
    return [" ".join(c.text_content().split()) for c in row.xpath("./td|./th")]


def _kind_for(code: str) -> Kind:
    if code.startswith("EUH"):
        return Kind.SUPPLEMENTAL
    if code.startswith("H"):
        return Kind.HAZARD
    return Kind.PRECAUTIONARY


def _expand_code(raw_code: str) -> list[str]:
    """'EUH 201/ 201A' covers two codes that share one text."""
    code = normalise_code(raw_code)
    if "/" not in code:
        return [code]
    head, *rest = [p.strip() for p in code.split("/")]
    prefix = re.match(r"^([A-Z]+)", head)
    out = [head]
    for r in rest:
        out.append(r if re.match(r"^[A-Z]", r) else f"{prefix.group(1) if prefix else ''}{r}")
    return [normalise_code(c) for c in out if c]


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
            text = strip_markers(cells[2])
            if not lang or not text:
                continue
            for code in codes:
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


def extract_signal_words(doc, positions) -> dict[str, str]:
    """Read translated signal words from the aligned cell positions.

    Returns {'Danger': text, 'Warning': text} only for words whose aligned cells
    agree unanimously; a disagreement means the documents are not parallel and the
    word is dropped rather than guessed.
    """
    tables = doc.xpath("//table")
    votes: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for ti, ri, ci, en_val in positions:
        if ti >= len(tables):
            continue
        rows = tables[ti].xpath(".//tr")
        if ri >= len(rows):
            continue
        cells = _row_cells(rows[ri])
        if ci >= len(cells):
            continue
        val = strip_markers(cells[ci])
        if val:
            votes[en_val][val] += 1
    result = {}
    for en_val, counter in votes.items():
        if not counter:
            continue
        (best, n), = counter.most_common(1)
        if n == sum(counter.values()):  # unanimous
            result[en_val] = best
    return result


def build(languages: list[str] | None = None, *, use_cache: bool = True,
          with_signal_words: bool = True) -> list[AnswerKey]:
    """Build EU CLP answer keys. Returns one AnswerKey per language."""
    wanted = languages or list(LANGS)
    en_doc = _doc("eng", use_cache=use_cache)
    per_lang = parse_statements(en_doc)
    positions = signal_word_positions(en_doc)
    ts = now()

    keys: list[AnswerKey] = []
    for lang in wanted:
        iso3 = LANGS.get(lang)
        if iso3 is None:
            continue
        entries = list(per_lang.get(lang, []))
        if with_signal_words:
            doc = en_doc if lang == "en" else _doc(iso3, use_cache=use_cache)
            words = extract_signal_words(doc, positions)
            for en_val, code in (("Danger", SIGNAL_DANGER), ("Warning", SIGNAL_WARNING)):
                text = words.get(en_val)
                if not text:
                    continue
                entries.append(
                    AnswerKeyEntry(
                        regulation=REGULATION, revision=CELEX, language=lang, code=code,
                        kind=Kind.SIGNAL, text=text,
                        signal_word="Danger" if en_val == "Danger" else "Warning",
                        tier=Tier.A, source_url=BASE_URL,
                        source_ref="Annex I label element tables (aligned 'Signal Word' rows)",
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
