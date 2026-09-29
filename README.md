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
| UN GHS Rev.11 | 3 (en, fr, es) | 737 | ok (tier A); ar/ru/zh `pending_source` |
| UK GB CLP | 1 (en) | 236 | ok (tier A) |
| Australia WHS | 1 (en) | 236 | ok (tier A) |
| US OSHA HazCom | 1 (en) | 111 | **partial** (tier A) — see below |
| Canada WHMIS | — | 0 | `pending_source` / `needs_class_category_mapping` |
| Japan JIS | — | 0 | `pending_source` / `wrong_source` |

**No key is ever filled from memory.** Where a source could not be read, the key
is empty and marked `pending_source`, with a machine-readable `status_reason` and
the full explanation in `data/answer_keys/{regulation}/_parse_issues.txt`. Fill
those with `lingua keys import-csv`.

| `status` | Meaning |
| --- | --- |
| `ok` | Built from its official source and believed complete |
| `partial` | Built from its official source, but the code set is knowingly incomplete (`status_reason` says why) |
| `pending_source` | Nothing could be derived; the key is empty |

Rebuilds are deterministic: an entry keeps its stored `retrieved_at` when its
code, text and `source_ref` are unchanged, so re-running `lingua keys build`
against unchanged sources leaves the working tree clean and any diff is real.

### Sources

Official texts that could not be fetched programmatically are kept under
`data/sources/<regulation>/` and parsed with `--from-file`:

| Regulation | Source | How it is read |
| --- | --- | --- |
| EU CLP | EU Publications Office **CELLAR** (network) | Annex III/IV multilingual tables — one fetch yields all 24 languages |
| UN GHS | `un-ghs/GHS_Rev11_{en,fr,es}.pdf` | Annex 3 code/statement tables |
| UK GB CLP | `uk-gb-clp/gb_clp_full.pdf` | Annex III multilingual (EN row) + Annex IV tables + Annex II prose |
| Australia | `ghs-rev7/GHS_Rev7_en.pdf` + `australia/swa_classification_guidance.pdf` | GHS Rev.7 for H/P; SWA guidance for AUH |
| US OSHA | `us-osha/appendix_c.html` | Signal words directly; statements by text identity with EU CLP |
| Canada | `ca-whmis/hpr_bilingual.pdf` | scanned, yields nothing — see below |
| Japan | `japan/GHS_Rev9_ja_annex2-3.pdf` | unreadable — see below |

Rows are located by the **code pattern in column 0**, not by header text, so one
parser works across English, French and Spanish. Every build writes a
`_parse_issues.txt` next to the keys recording pages scanned, rows used, codes
with an empty statement, and codes seen twice with conflicting text.

### Why OSHA is partial

29 CFR 1910.1200 Appendix C contains **no H or P code numbers at all** — verified
against osha.gov, the eCFR API and the local copy. It gives signal words and
statement text organised by hazard class, but never says which code a statement
belongs to.

So codes are established by comparing OSHA's own wording against EU CLP's English,
in three stages of decreasing strength: identical; identical once fill-ins are
collapsed (OSHA prints `May cause cancer <<…>>` where CLP prints the full
`<state route of exposure …>` instruction); then near-identical at 0.97
similarity, which absorbs US spelling such as "vapor" and "poison center".

That yields **53 H and 56 P codes** plus both signal words. Statements with no
confident code are listed in `_parse_issues.txt` rather than guessed, as are the
96 EU CLP codes OSHA has no statement for — those are **not** assumed to be gaps,
since OSHA adopted an earlier GHS revision and some absences are genuine
differences. The key is `partial` until those counts are reconciled.

### Why Canada is pending

The Hazardous Products Regulations (SOR/2015-17) state statements by **hazard
class and category**, never against a code: a scan of the full 165-page bilingual
text finds **zero** H or P codes. So WHMIS is not blocked on a missing source but
on a missing mapping — `status_reason: needs_class_category_mapping`. The proposed
design is written up in `data/answer_keys/ca_whmis/_design_note.md` (design only,
nothing implemented).

### Why Japan is pending

Two separate reasons, hence `status_reason: wrong_source`. First, the file on
record is the Japanese edition of **UN GHS Rev.9, not JIS Z 7252/7253** — a
different document at a different revision — so nothing may be taken from it for a
JIS key, and nothing is. Second, it is unreadable anyway:
`GHS_Rev9_ja_annex2-3.pdf` does not yield readable Japanese. PyMuPDF returns
mojibake (0.6% Japanese characters, `㝃ᒓ᭩` where `附属書` is meant) and pdfplumber
returns `(cid:NNNN)` placeholders only. The cause is in the file: its Japanese
font (`MS-Mincho-90ms-RKSJ-H`) carries **no ToUnicode CMap**, so the PDF contains
no glyph-to-character mapping to recover. No amount of text extraction can fix
that; OCR would be required, and has not been run.

## Adding a regulation## Adding a regulation

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

* **Canada and Japan have no answer key**, for the reasons above, as do Arabic,
  Russian and Chinese UN GHS (no edition on file). Documents under those report
  *unverified*, never pass or fail on wording.
* **OSHA covers 31 codes**, for the reason above.
* **The UK key has 19 codes whose English text appears twice with different
  wording** in the retained text, most likely an original and an amended version.
  The first reading is kept and every conflict is listed in
  `data/answer_keys/uk_clp/_parse_issues.txt` for a human to settle.
* **EUH211 and EUH212 are absent from the UK key** — they are not in Annex III's
  tables nor stated as quoted prose in Annex II of the copy on file.
* **UN GHS French is missing P317** (the source cell is empty) and reports one
  conflicting reading for P332.
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
