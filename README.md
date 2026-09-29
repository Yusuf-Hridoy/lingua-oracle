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

## Commands

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

## Answer-key coverage as built

`lingua keys stats` on this build:

| Regulation | Languages | Entries | Status |
| --- | --- | --- | --- |
| EU CLP | 24 | 5 757 | ok (tier A) |
| US OSHA HazCom | 1 (en) | 33 | ok (tier A), partial — see below |
| UK GB CLP | — | 0 | `pending_source` |
| Canada WHMIS | — | 0 | `pending_source` |
| UN GHS | — | 0 | `pending_source` |
| Australia WHS | — | 0 | `pending_source` |
| Japan JIS | — | 0 | `pending_source` |

**No key is ever filled from memory.** Where a source could not be fetched, the
key is empty and marked `pending_source`, with the reason recorded in
`src/lingua_oracle/keys/builders/pending.py`. Fill them with
`lingua keys import-csv` from a sourced glossary.

### Sources actually used

* **EU CLP** — the EU Publications Office **CELLAR** endpoint,
  `http://publications.europa.eu/resource/celex/02008R1272-20260701`, requested
  with `Accept: application/xhtml+xml` and `Accept-Language: <iso639-3>`.
  EUR-Lex's own HTML views sit behind an AWS WAF challenge; CELLAR is the
  sanctioned machine-readable route. Annex III and IV render each code as a
  table containing all 24 languages, so one fetch yields every translation,
  including EUH380/381/430/431/440/441/450/451 and all combined codes.
* **US OSHA** — `https://www.osha.gov/.../1910.1200AppC`.

### Why OSHA is partial

29 CFR 1910.1200 Appendix C contains **no H or P code numbers at all** — verified
against both osha.gov and the eCFR API. It gives signal words and statement text
organised by hazard class, but not the code each statement belongs to.

So the builder takes only what the source states: signal words directly, and
hazard statements keyed to a code **only where OSHA's own wording is identical,
after normalisation, to EU CLP's English text for that code**. That maps 31 of
78 statements. The remaining 40 are counted and reported rather than guessed,
because assigning them a code would mean inventing the mapping.

---

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

## Known limitations

* **Four regulations have no answer key.** UK GB CLP (legislation.gov.uk serves
  every view, including `data.xml` and `data.akn`, behind an AWS WAF JavaScript
  challenge), UN GHS (unece.org returns 403 to programmatic clients), Australia
  (safeworkaustralia.gov.au does not answer programmatic requests), and Canada
  WHMIS (the HPR full text is reachable but contains no code-keyed statements).
  Japan is `pending_source` by design, as JIS is a paid standard. Until these are
  imported, documents under those regulations report *unverified*, not pass.
* **Tier B currently borrows nothing**, because it needs a regulation's English
  key to compare against EU CLP's, and the regulations that would benefit have no
  key yet. The logic is implemented and unit-tested; it activates as soon as an
  English key is imported.
* **OSHA covers 31 codes**, for the reason above.
* **C-13 finds nothing** until an older revision is archived at
  `data/answer_keys/{regulation}@{revision}/{lang}.json`. Only one revision is
  currently built.
* **B-10 needs per-code signal words.** These are extracted from CLP Annex I for
  EU (68 codes) and from Appendix C for OSHA. For a regulation with neither, the
  check abstains rather than guessing.
* **Greek and Irish signal words are incomplete.** The Greek consolidated text
  genuinely splits between two words for *Warning*, so neither is recorded; there
  is no Irish language version of the consolidated act. Both are left absent by
  design — A-01 reports them as unverified.
* **The slash-alternative parser is deliberately permissive.** Where the official
  text is ambiguous about where a slash run begins (`Get medical
  advice/attention.`), every plausible split is compiled and the phrase passes if
  any matches. This can accept an unusual-but-plausible subset. A false failure
  on correct official wording was judged the worse error.
* **Per-phrase language detection is unreliable under ~25 characters**, so A-05
  skips short phrases.
* **Scanned/image-only PDFs are not handled.** There is no OCR.
* **No classification correctness.** The tool checks wording, not whether the
  classification itself is right. Pictograms and layout are out of scope.
* PyMuPDF is **AGPL**. It is the default backend but sits behind an interface;
  set `LINGUA_PDF_BACKEND=pdfplumber` to avoid it entirely.

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
