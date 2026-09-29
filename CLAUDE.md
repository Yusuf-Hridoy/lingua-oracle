# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"   # setup

uv run pytest                                  # full suite (offline, ~2s)
uv run pytest tests/test_checks.py             # one file
uv run pytest -k test_slash_subsets_pass       # one test by name
uv run pytest tests/test_checks.py::test_defect_triggers_its_check -q
uv run ruff check .                            # lint (must be clean)

uv run python tests/make_fixtures.py           # regenerate fixture PDFs
uv run lingua keys build all                   # the ONLY networked command
uv run lingua keys stats
uv run lingua check <pdf> -r eu_clp -l da
uv run lingua serve                            # http://127.0.0.1:8000/
```

`lingua check` exits `1` when there are failures, `0` otherwise.

`ruff format` has **not** been applied to this repo; don't run it, as it reflows
hand-tuned layout in the regex-heavy modules. `ruff check` is the gate.

## Non-negotiable rules

These are product requirements, not style preferences. Breaking them silently
produces a compliance tool that lies.

1. **Never invent, paraphrase, or recall regulatory text.** If a source can't be
   fetched, the key gets `status=pending_source` and stays empty. Every entry
   carries `source_url` + `source_ref` + `retrieved_at`.
2. **No network at check time.** Only `keys/builders/` may fetch. `tests/conftest.py`
   installs a session-wide socket guard that fails any test touching the network.
3. **No AI/LLM calls.** Every verdict is deterministic.
4. **No real customer or product data.** Fixtures are synthetic and generated from
   the answer keys. `data/sources/` is gitignored as a drop folder for ad-hoc PDFs.

## Architecture

### The package is `lingua_oracle`, not `lingua`

The `lingua-py` language detector owns the top-level `lingua` import name, so the
package had to be renamed. The CLI command is still `lingua`. Inside
`detect/language.py`, `from lingua import ...` refers to the **detector**, not
this package.

### Pipeline

`pipeline.py` is the single entry point (`check_pdf` / `compare_pdfs`) and the
best file to read first:

```
PDF → extract/ → detect/ (regulation, language, sections, codes)
    → keys/tierb.resolve() → CheckContext → checks/ → Report → report/
```

- **`extract/`** — `Extractor` protocol with PyMuPDF (default, **AGPL**) and
  pdfplumber backends; swap via `LINGUA_PDF_BACKEND`.
- **`detect/`** — regulation (flag always wins; ties/no-signal raise
  `RegulationUndetermined` rather than guess), language, sections 2/3/16, codes.
- **`match/`** — normalizer + template matcher.
- **`checks/`** — 15 checks, one concern per module.
- **`report/`** — JSON + a single self-contained HTML file.

### Tiers are the core concept

Every verdict carries the provenance of the text it was judged against:

| Tier | Meaning |
|---|---|
| A | Official text for this regulation and language |
| B | Borrowed: the regulation's **English** text is byte-identical (after normalisation) to EU CLP's English for that code, so EU CLP's official translation stands in |
| C | No reference text — **no wording verdict at all**; only C-02 runs, findings are `unverified` |

A tier C code must **never** be reported as a failure. An empty answer key
produces "unverified", never a false accusation. `keys/tierb.resolve()` performs
the A→B→C resolution and returns the `Borrowed` object the checks read from.

### Answer keys are data, built separately

`data/answer_keys/{regulation}/{lang}.json`, built by `keys/builders/*.py` and
committed. Check time only reads them.

Current coverage: EU CLP 24 languages (5,757), UN GHS Rev.11 en/fr/es (737),
UK GB CLP en (236), Australia en (236), US OSHA en (33). Canada, Japan and
UN GHS ar/ru/zh are `pending_source`.

Sources that cannot be fetched programmatically live in
`data/sources/<regulation>/` and are parsed with `lingua keys build <reg>
--from-file`. `keys/builders/pdf_tables.py` holds the shared parsers: rows are
matched on the **code pattern in column 0**, not header text, so one parser
serves English, French and Spanish. Four table shapes are handled - plain
code/statement, CLP multilingual (`[code, "Language", class]` then a row per
language), inline (`"AUH001 - Explosive when dry"`), and quoted prose in GB CLP's
Annex II. Table detection costs ~0.5s a page, so results are cached under
`LINGUA_CACHE_DIR` keyed on file size and mtime.

Every build writes `data/answer_keys/<reg>/_parse_issues.txt` recording pages
scanned, rows used, codes with an empty statement, and codes seen twice with
conflicting text. **Read it after any builder change** - it is how a silent
parsing regression becomes visible.

Two source facts that drive the design and are easy to re-discover the hard way:

- **EU CLP** comes from the EU Publications Office **CELLAR** endpoint
  (`publications.europa.eu/resource/celex/...`) with `Accept: application/xhtml+xml`
  and `Accept-Language: <iso639-3>`. EUR-Lex's own HTML is behind an AWS WAF
  challenge. Annex III/IV render each code as a table containing **all 24
  languages**, so one fetch yields every translation.
- **OSHA Appendix C contains no H/P code numbers at all** (verified against
  osha.gov and the eCFR API). Statements are keyed to a code only where OSHA's
  wording is identical to EU CLP's English; the rest are counted in
  `us_osha.UNMAPPED`, never guessed.
- **Canada's HPR contains no code-keyed statements** - zero H/P codes in the full
  text - so `ca_whmis` stays pending by evidence, not by omission.
- **The Japanese PDF cannot be read at all**: its font carries no ToUnicode CMap,
  so neither PyMuPDF nor pdfplumber can recover characters. Do not "fix" this with
  a decoding heuristic; only OCR would work, and it needs the user's approval.
- **GB CLP is retained law**: EU codes added after retention (EUH380/381/430/431/
  440/441/450/451) are legitimately absent from `uk_clp`, not missing.

Signal-word **text** never goes in `regulations.yaml` — it lives in the keys under
the pseudo-codes `SIGNAL_DANGER` / `SIGNAL_WARNING`. Per-code signal words (for
B-10) are extracted from CLP Annex I, where the "Signal Word" and "Hazard
Statement" rows are column-aligned.

### Adding a check

Create `checks/xx_name.py`, decorate with `@register(CHECK_ID, TITLE)`, and add it
to the import list in `checks/__init__.py` — importing that package is what
registers everything. Checks receive only `CheckContext` (`checks/base.py`), which
exposes `entry(code)`, `tier_for(code)`, `hits_in(section)`, `section_for(hit)`.

### Template matcher (`match/template.py`)

Official texts encode choices: slash alternatives, `…` / `<...>` fill-ins, and
`[...]` optional groups. Where a slash run *begins* is genuinely ambiguous in the
source (`Get medical advice/attention.` means advice-or-attention, but `Wear
protective gloves/...` has a two-word first alternative). The matcher therefore
**compiles every plausible split and passes if any matches** — deliberately
permissive, because a false failure on correct official wording is far more
damaging than mild leniency. `tests/test_template_matcher.py` asserts every
official EU text matches itself across five languages; keep that guard.

## Gotchas that have already caused bugs

- **lingua-py's `Language` enum fails `is` comparison** (pyo3-backed). Use `==`.
- **Language confidence is relative, not absolute** — a correct English SDS
  sentence scores ~0.6. Compare English *against the document's language* with a
  margin (`looks_untranslated`); don't use an absolute threshold.
- **`rejoin_lines` must not glue a heading onto the text below it** — that breaks
  section detection and the signal word at once. `starts_new_block` /
  `is_continuation` in `extract/rejoin.py` are shared with `detect/codes.py`;
  changing one affects phrase extraction too.
- **"ends with a full stop" is not a valid phrase terminator** — OSHA texts have
  no trailing period, so phrase continuation ran into the next heading.
- **Mandated-bilingual regulations** (WHMIS = en + fr) legitimately repeat a code
  in two languages. A-05 and C-02 special-case `required_languages`.
- **`strip_punctuation` must preserve `…`** or an unfilled fill-in passes as
  "punctuation-only difference".
- **FastAPI route order**: `/reports/{id}.json` must be declared *before*
  `/reports/{id}`, or Starlette swallows the suffix.
- **Generic phrases are not detection signals** — "Globally Harmonized System"
  appears in nearly every SDS's abbreviations glossary. `detect_patterns` must
  match the document's *governing* statement.
- Fixtures pull official text from the answer keys; **never hardcode regulatory
  wording into `tests/make_fixtures.py`**.

## Environment overrides

`LINGUA_DATA_DIR`, `LINGUA_REPORTS_DIR`, `LINGUA_CACHE_DIR`, `LINGUA_PDF_BACKEND`.
Tests use `LINGUA_DATA_DIR` with `load_registry.cache_clear()` to isolate key
fixtures — the registry is `lru_cache`d.

## Git

Work on `main`; the remote is `Yusuf-Hridoy/lingua-oracle` (private) and `main` is
its default branch. Commit one module at a time.
