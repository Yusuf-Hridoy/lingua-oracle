# Lingua Oracle

An internal QA tool that reads an SDS or label PDF and checks every signal word
and hazard/precautionary phrase against the **official wording** for its
regulation and language. It produces a pass/fail report showing expected vs found
text with character-level diffs.

Phase 1 is deterministic: **no AI or LLM calls**, and **no network access at
check time**. Only the answer-key builder reaches the internet.

---

## Setup

```bash
cd lingua-oracle
uv venv --python 3.12
uv pip install -e ".[dev]"
```

Build the answer keys once (this is the only networked step):

```bash
uv run lingua keys build all
uv run lingua keys stats
```

Generate the synthetic test PDFs and run the suite:

```bash
uv run python tests/make_fixtures.py
uv run pytest
uv run ruff check .
```

---

## Running a check

```bash
# one document — regulation and language are detected unless you name them
uv run lingua check data/sources/somefile.pdf
uv run lingua check tests/fixtures/clean_eu_da.pdf --regulation eu_clp --language da

# a folder of documents (drop-folder mode)
uv run lingua check-folder ~/inbox

# two documents, adds check B-11 (same code set in both)
uv run lingua compare sheet_en.pdf sheet_da.pdf
```

Each run writes `reports/<id>.json` and a self-contained `reports/<id>.html`, and
prints the path. **Exit code is `1` when there are failures, `0` otherwise**, so it
drops straight into a pipeline. Detection never guesses: if the regulation cannot
be determined the run stops and asks you to pass `--regulation`.

A finding is `fail`, `warn`, `info`, or *unverified* — the last means there was no
reference text to judge against (tier C), never a pass or a failure.

## All commands

```bash
lingua check <pdf> [--regulation eu_clp] [--language da] [--out DIR]
lingua check-folder <dir>              # drop-folder mode
lingua compare <pdf_a> <pdf_b>         # adds check B-11
lingua keys build <regulation|all> [--languages da,de] [--no-cache]
lingua keys import-csv <file> --regulation jp_jis --language ja --tier C
lingua keys stats [--json]
lingua serve [--host 127.0.0.1] [--port 8000]
```

`lingua check` exits `0` when there are no failures and `1` when there are, so it
drops straight into a pipeline.

### Web

`lingua serve`, then open <http://127.0.0.1:8000/>.

| Route | Purpose |
| --- | --- |
| `GET /` | Upload page: drop a PDF, optional regulation and language |
| `POST /check` | multipart PDF → Report JSON |
| `POST /check/html` | same, redirects to the HTML report |
| `POST /compare` | two PDFs → Report with B-11 |
| `GET /reports/{id}` | HTML report |
| `GET /reports/{id}.json` | JSON report |

Reports are files under `reports/`. There is no database.

---

## The 15 checks

| ID | Check | Severity |
| --- | --- | --- |
| A-01 | Signal word exact for the language | fail |
| A-02 | H-statement text matches key (incl. combined H codes) | fail |
| A-03 | P-statement text matches key (incl. combined P codes) | fail |
| A-04 | Supplemental statements (EUH/AUH) match key | fail |
| A-05 | English left behind in a non-English document | fail |
| A-06 | Leftover placeholders (`{0}`, unfilled `<…>`, `TBD`) | fail |
| A-07 | Broken characters (U+FFFD, mojibake, missing glyphs) | fail |
| B-08 | Every H-code in Section 3 has full text in Section 16 | fail |
| B-09 | Section 2 and label show the same signal word and statements | fail |
| B-10 | Signal word fits the codes | fail |
| B-11 | Translated copy has the same code set (compare mode) | fail |
| C-12 | Phrases valid for the chosen regulation (EUH on OSHA, AUH on EU) | fail |
| C-13 | Wording matches the current revision | warn |
| C-14 | Required languages present (WHMIS: en + fr) | fail |
| C-02 | Same code gives the same text everywhere in the document | warn |

---

## Tiers

Every verdict carries the provenance of the text it was judged against.

| Tier | Meaning |
| --- | --- |
| **A** | Official text for this regulation and language. |
| **B** | Borrowed: the regulation's *English* text is identical to EU CLP's English for that code, so EU CLP's official translation is used. |
| **C** | No official source. **No wording verdict is produced.** Only C-02 consistency runs, and findings are marked *unverified* rather than pass or fail. |

A tier C code is never reported as a failure. This matters: an empty answer key
produces "unverified", never a false accusation.

---

## Coverage

Every entry is **tier A** — official text for that regulation and language, with
`source_url`, `source_ref` and `retrieved_at` on each one. Nothing is filled from
memory; where a source could not be read, the key stays empty.

| Regulation | Languages | Entries | Status | Tier | Source |
| --- | --- | --- | --- | --- | --- |
| EU CLP | 24 (bg cs da de el en es et fi fr ga hr hu it lt lv mt nl pl pt ro sk sl sv) | 240 each | `ok` | A | EU Publications Office **CELLAR**, consolidated 1272/2008 |
| UN GHS Rev.11 | en, es, fr | 248 each | `ok` | A | `un-ghs/GHS_Rev11_{en,es,fr}.pdf`, Annex 3 |
| UN GHS Rev.11 | ar, ru, zh | 0 | `pending_source` / `no_source_edition` | — | no edition on file |
| UK GB CLP | en | 238 | `ok` | A | `uk-gb-clp/gb_clp_full.pdf`, Annex III + IV + Annex II prose |
| Australia WHS | en | 238 | `ok` | A | `ghs-rev7/GHS_Rev7_en.pdf` (H/P) + `australia/swa_classification_guidance.pdf` (AUH) |
| Canada WHMIS | en | 229 | `ok` | A | `ghs-rev7/GHS_Rev7_en.pdf` + `ghs-rev8/GHS_Rev8_en.pdf` for chemicals under pressure |
| Canada WHMIS | fr | 226 | `partial` / `needs_ghs_rev8_french` | A | `ghs-rev7/GHS_Rev7_fr.pdf`; no French Rev.8 on file |
| US OSHA HazCom | en | 126 | `partial` / `unrepresented_statements_remain` | A | `us-osha/appendix_c.html`, keyed against GHS Rev.7 + Rev.8 |
| Japan JIS | ja, en | 0 | `pending_source` / `wrong_source` | — | file on record is UN GHS Rev.9 Japanese, not JIS |

`status` is `ok` (built and believed complete), `partial` (built but knowingly
incomplete — `status_reason` and the key's `notes` say what is missing) or
`pending_source` (empty). `lingua keys stats` prints this live.

### How the sources are read

Sources that cannot be fetched programmatically live under
`data/sources/<regulation>/`. `keys/builders/pdf_tables.py` matches rows on the
**code pattern in column 0** rather than header text, so one parser serves
English, French and Spanish. Four table shapes are handled: plain code/statement,
the CLP multilingual table, inline (`AUH001 - Explosive when dry`), and quoted
prose in GB CLP's Annex II.

Which regulation reads which edition is decided by the regulation's own words —
the HPR states *"GHS means … Seventh Revised Edition"*, and points chemicals under
pressure at the Eighth. The Rev.8 overlay is therefore exactly three codes
(H282/H283/H284); the class's other codes are identical in Rev.7 and stay there.

Every build writes `data/answer_keys/<reg>/_parse_issues.txt` recording pages
scanned, rows used, and what could not be used — and **rebuilds are
deterministic**: running `lingua keys build all` twice leaves the tree clean, so
any diff is a real change.

## Known limitations

* **Japan is `wrong_source`.** The file on record is the Japanese edition of UN
  GHS Rev.9, not JIS Z 7252/7253 — a different document at a different revision —
  so nothing is taken from it. It is unreadable regardless: its Japanese font
  carries no ToUnicode CMap, so no extractor can recover characters. JIS itself is
  a paid standard and is not scraped. Fill via `lingua keys import-csv`.
* **UN GHS ar/ru/zh are `no_source_edition`.** No Arabic, Russian or Chinese
  edition is on file. Their text is not derivable from the editions that are.
* **Canada French lacks chemicals under pressure.** The HPR points that class at
  GHS Rev.8 and no French Rev.8 is on file, so H282/H283/H284 are absent rather
  than filled from Rev.7, another revision, or the English text.
* **OSHA holds 126 entries and four statements remain out.** Appendix C states no
  codes at all, so codes are established by exact wording against GHS Rev.7 (plus
  Rev.8 for chemicals under pressure). Four statements differ from GHS only in
  rendering — a dropped word, an added comma, a full stop where GHS prints a
  colon. Whether those are OSHA's wording or errors in the osha.gov HTML could not
  be verified: the official CFR publishes Appendix C's tables as **graphics**, not
  text, on both ecfr.gov and govinfo.gov. They are left out rather than aliased on
  a guess, and matching stays exact.
* **OSHA internal identifiers.** OSHA defines hazard classes GHS does not and
  gives them no code. Their statements are stored under `OSHA-CD` (combustible
  dust) and `OSHA-SA` (simple asphyxiant), flagged `internal_id: true`. **These
  are not regulatory codes.** They never appear as codes on a document and are
  matched by text. Do not put them on a label or an SDS.
* **Tier B is implemented but currently borrows little**, since most regulations
  now have their own tier A text.
* **The slash-alternative matcher is deliberately permissive** where the official
  text is ambiguous about where a slash run begins; a false failure on correct
  wording was judged the worse error.
* **No OCR, no classification correctness, no pictograms, no layout checks.**
* PyMuPDF is **AGPL**. It is the default backend but sits behind an interface; set
  `LINGUA_PDF_BACKEND=pdfplumber` to avoid it.

## Adding a regulation

1. Add an entry to `data/regulations.yaml`: `display_name`, `revision`,
   `official_languages`, `required_languages`, `allowed_prefixes`,
   `supplemental_prefixes`, `detect_patterns`.
2. Add a builder module under `src/lingua_oracle/keys/builders/` exposing
   `build() -> list[AnswerKey]`, and wire it into `keys_build` in `cli.py`.
   If the source cannot be fetched, add it to `pending.PENDING` with the reason
   instead — never fill it from memory.
3. Run `lingua keys build <id>` and check the sanity report it prints (counts per
   kind plus ten random entries for spot-check).

Signal-word *text* never goes in `regulations.yaml`. It lives in the answer keys
under the pseudo-codes `SIGNAL_DANGER` / `SIGNAL_WARNING`.

## Adding a language

1. Add the BCP-47 tag to the regulation's `official_languages`.
2. Add `data/headings/<tag>.yaml` with `section_word`, `sections` (2, 3, 16) and
   `label_markers`. Without it the tool falls back to `en` patterns plus
   numbered-heading detection.
3. Add the tag to `_TAGS` in `src/lingua_oracle/detect/language.py` so lingua-py
   can detect it.
4. Rebuild the key for that language.

---

## Notes

* The package is `lingua_oracle`, not `lingua`, because the `lingua-py` language
  detector already owns the top-level `lingua` import name. The CLI command is
  still `lingua`.
* `uv run ruff check .` is clean. `ruff format` has not been applied, to keep
  hand-tuned line layout in the regex-heavy modules.
* Environment overrides: `LINGUA_DATA_DIR`, `LINGUA_REPORTS_DIR`,
  `LINGUA_CACHE_DIR`, `LINGUA_PDF_BACKEND`.
* No real customer or product data is in this repo. Every fixture is synthetic;
  the only real text is the regulatory wording, pulled from the answer keys.
* `data/sources/` is gitignored. Drop real SDS PDFs there to check them ad hoc
  (`lingua check data/sources/x.pdf`) without any risk of committing them.
