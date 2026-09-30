# Terms the report shows that a non-developer may not understand

Collected from what the page actually renders, not from memory: the labels in
`report.html.j2` and `index.html.j2`, the 15 check titles, and every distinct
message shape produced across the fixture set.

**Status: applied.** The vocabulary now lives in `src/lingua_oracle/report/labels.py`,
which the template renders from and the browser tests assert against, so the two
cannot drift. The tables below are kept as the record of what was changed and why.

Two items went further than proposed: check titles were rewritten beyond the
`key` → `official wording` swap, and the report notes lost their tier language
too. One was not done: `/compare` still answers with JSON rather than landing on
a report.

Ordered by how likely it is to stop a reviewer, worst first.

## 1. Words that mean something other than their everyday meaning

| Shown now | Where | Why it misleads | Suggested label |
| --- | --- | --- | --- |
| `Tier` · `A` `B` `C` | Column + legend | Reads like a quality grade of the *document*. It is the provenance of the text we compared against. | **Source of official text** — `A` → `Official`, `B` → `Borrowed (EU CLP)`, `C` → `None on file` |
| `UNVERIFIED` | Tile + badge | Sounds like the document failed a verification. It means we had nothing to check against. | **Not checked** (tile: *Could not check*) |
| `Coverage` `100.0%` | Tile | Coverage of what? Reads like "the document is 100% compliant". | **Codes we could check** |
| `Codes found` | Tile | Ambiguous between "codes in the document" and "problems found". | **Codes in document** |
| `Detected by` `flag` / `auto` | Header | "flag" is a command-line word. Users see it when they *chose* the regulation. | **Regulation set by** → `You chose it` / `Read from the document` |
| `key` (in 3 check titles) | Check titles | "key" means the answer key. Reads as encryption or a database key. | **official wording** |
| `Fill-in` / `Filled in` / `Not filled in` | Messages | Jargon for the `…` slot in an official phrase. | **Blank to complete** — "You completed this blank with '…'" / "This blank was never completed" |
| `Extraction backend: pymupdf.` | Notes | Internal detail; means nothing to a reviewer. | Drop it, or **How we read the PDF** |

## 2. Codes and identifiers shown without explanation

| Shown now | Why it misleads | Suggested label |
| --- | --- | --- |
| `A-01` … `C-14` | Our internal check numbers. Easily mistaken for regulatory references like H225 or P210 — the very things on the page next to them. | Lead with the title and demote the id: **"Signal word exact for the language"** *(check A‑01)* |
| `SIGNAL` in the Code column | Not a regulatory code; our placeholder for the signal word. | **Signal word** |
| `OSHA-CD`, `OSHA-SA` | Internal ids for OSHA hazard classes with no GHS code. Already flagged in the data, but the page does not say so. | Show as **"OSHA class (no GHS code)"** |
| `EUH` / `AUH` "family" | "family" is ours. | **EU-only statements** / **Australia-only statements** |
| `Section` `2` `3` `16` | Fine for SDS authors, opaque to anyone else. | Keep the number, add the name: **2 — Hazards identification** |

## 3. Severity words

| Shown now | Why it misleads | Suggested label |
| --- | --- | --- |
| `FAIL` | Reads as "this document is rejected". It means one statement does not match. | **Wrong wording** |
| `WARN` | Says nothing about what to do. | **Check this** |
| `INFO` | Looks ignorable; it is where fill-ins needing human judgement appear. | **Needs a person** |

Severity is also the one place where colour alone carries meaning — red, amber,
blue. Worth a shape or icon for colour-blind reviewers.

## 4. Column headers and phrasing

| Shown now | Suggested |
| --- | --- |
| `Expected` / `Found` | **Official wording** / **Your document** |
| `Report ID` | **Reference** (say it is for quoting back to us) |
| `Generated` | **Checked on** |
| `No reference text for P319 in UN GHS 'en' (tier C): wording not verified.` | **"We have no official UN GHS (en) wording for P319 on file, so we could not check it."** |
| `H336 is in this document but missing from da.` | **"H336 is in this document but not in the Danish one."** (use the language name) |
| `Compare (returns JSON)` (upload page) | Users should not be shown a raw JSON page at all — **Compare** should land on a report like the single-document flow does. |

## 5. One thing the page did not say at all — now fixed

A reviewer could not tell **what to do next**. Every finding stated a difference;
none said whether the document could ship. There is now a verdict banner at the
top of every report, in one of three states:

- **Wording problems found — fix before release** (any failure)
- **Looks correct — some items need a person to check** (warnings or info only)
- **All checked wording matches the official text** (clean)

Every one of them carries *What this does not tell you* underneath: codes with no
official wording on file, wording borrowed from EU CLP, coverage below 100%, and
the standing limit that this checks wording and not classification. A green
headline can never stand alone and overclaim.
