# Validation findings

Issues found by running the checker against real documents (Phase 1.5).

Real documents are company data. **Nothing in this file names a product, a
customer or a file** — findings are described as patterns, with synthetic
reproductions in `tests/`.

| # | Title | Class | Status |
| --- | --- | --- | --- |
| 1 | Language detection restricted to the regulation's official languages | false_alarm (tool bug) | **fixed** |
| 2 | A negative declaration read as a signal word | false_alarm (tool bug) | **fixed** |
| 3 | `XXXX` in a REACH registration number read as a placeholder | false_alarm (tool bug) | **fixed** |
| 4 | Spacing beside a fill-in or a unit reported as a difference | false_alarm (tool bug) | **fixed** |
| 5 | A fill-in nested in an optional group could not be filled | false_alarm (tool bug) | **fixed** |
| 6 | A closing full stop OSHA's own rendering omits | false_alarm (tool bug) | **fixed** |
| 7 | Capitalisation could pass in silence | false_alarm (tool bug) | **fixed** |
| 8 | A template that matched **any** text at all | tool bug, found in passing | **fixed** |
| 9 | Wrapped table cells gained a space in the keys | extraction_error | **fixed** |

---

## Finding #1 — language detected as English on a Danish document

**Class:** `false_alarm` — the tool is at fault, not the document.
**Found:** a Danish SDS exported against **UN GHS**.
**Severity:** high. Every statement in the document would be compared against the
wrong language's key.

### What happens

`pipeline._prepare` detects the regulation first, then passes that regulation's
`official_languages` to `detect_language` as the candidate set:

```python
candidates = tuple(reg.official_languages) or None
lang, lang_by = detect_language(document.normalized_text, language, candidates)
```

UN GHS's official languages are Arabic, Chinese, English, French, Russian and
Spanish. Danish is not among them, so the restricted detector cannot return it —
and instead of saying so, it returns the best of the six it is allowed. Measured
on the document:

```
unrestricted            -> da   (confidence 1.00, correct)
restricted to un_ghs    -> en   (wrong)
restricted to eu_clp    -> da   (correct — Danish IS official there)
```

The restriction was added to improve accuracy on short text. It does that, but it
silently converts "this language is not in the allowed set" into "this is the
nearest allowed language", which is the worst possible failure for this tool: a
Danish document gets checked against the **English** key, so every hazard and
precautionary statement mismatches and A-02/A-03 fail on all of them. A run full
of confident, wrong failures is worse than no run.

### Why it matters beyond one document

Regulations are routinely used outside their own official language set. A
company may issue a UN GHS sheet in Danish, or an OSHA sheet in Spanish. The
registry's `official_languages` describes the languages the *regulation* is
published in, not the languages a *document* may be written in. Using one as a
constraint on the other conflates two different things.

### Fix (implemented)

1. Detect the language **unrestricted** first. That result is the document's
   language, full stop.
2. If the detected language is not one of the regulation's official languages,
   **keep the detected language** and let the tier system handle the absent key:
   Tier B where the wording can be borrowed on proof, otherwise Tier C, which
   produces *unverified* findings and no wording verdict.
3. Never fall back to another language's key. An unverified finding is honest; a
   confident failure against the wrong language is not.

The regulation's official languages may still be used as a tie-break *between
plausible readings*, never to exclude the detected one.

The official languages survive as a tie-break between readings that are already
close (`_TIE_MARGIN` in `detect/language.py`), never as a filter.

### Reproduction

`tests/fixtures/pattern_language_outside_regulation.pdf` — a Danish sheet issued
against UN GHS, fictional product data, Danish wording taken from EU CLP (which
publishes Danish officially; the point of the fixture is the language, not the
wording). It reports `language == "da"`, no failures, and P280 as unverified —
the rest resolve through tier B.


---

## Finding #2 — "no signal word" read as a signal word

**Class:** `false_alarm` — the tool is at fault. **Status:** fixed.
**Found:** a non-hazardous EU SDS, used as a known-good negative control.

### What happened

The document states, correctly, that it needs no label elements:

> No hazard pictogram, no signal word, no hazard statement(s), no
> precautionary statement(s) required.

A-01 searched for the words "signal word" and captured `(.+)` — the rest of the
line — as the stated value. So a sentence declaring the **absence** of a signal
word was reported as a document claiming a signal word of
`", no hazard statement(s), no precautionary statement(s) required"`, and failed
against the official Danish/English words.

Two mistakes compounded: reading a negation as an assertion, and treating free
text as a value.

### Fix

1. A line matching `_NEGATIVE_RE` — "no signal word", "not classified", "none
   assigned", "not a hazardous substance", and the da/de/fr/es equivalents — is
   skipped. It declares an absence, not a value.
2. The capture stops at the first separator and is rejected if it runs to more
   than two words. A signal word is one word in every language on file.

The check still fails a genuinely wrong signal word; `test_a01_still_catches_a_
wrong_signal_word` pins that, so the fix cannot be blunted into uselessness.

**Reproduction:** `tests/fixtures/pattern_negative_declaration.pdf`, built with
fictional product data by `tests/make_fixtures.py`.


---

## Finding #3 — `XXXX` in a REACH registration number read as a placeholder

**Class:** `false_alarm` — the tool is at fault. **Status:** fixed.
**Found:** the same non-hazardous EU SDS as finding #2.

### What happened

A-06 flags `XXXX` as unfilled placeholder text, which it usually is. But REACH
registration numbers are published in the form

```
01-2119485491-33-XXXX
```

where the trailing four characters are the company-specific suffix and are
printed exactly like that on real sheets. The check read a correctly-formatted
registration number as an unfinished document.

### Fix

A match is skipped when it sits inside a REACH registration number, recognised by
its shape: `\d{2}-\d{10}-\d{2}-(XXXX|\d{4})`. The exemption is deliberately tied
to that whole shape rather than to the token `XXXX`, so a bare "Supplier: XXXX"
is still flagged — `test_only_the_reach_shape_is_exempt` pins both directions,
including a near-miss (`Batch 12-345-XXXX`) that must still be caught.

**Reproduction:** `tests/fixtures/pattern_reach_registration.pdf`, fictional data.


---

## Finding #4 — spacing beside a fill-in or a unit

**Class:** `false_alarm`. **Status:** fixed.

Sheets write `Use … to extinguish` where the key has `Use…`, and `50 °C` where
the key has `50°C`. Neither is something a regulation legislates.

Only those two shapes are collapsed, **not whitespace generally**. French
typography puts a space before `:` `;` `!` `?`, and the licence to ignore that
was granted for comparing *editions of a source*, never for judging a document.
The first attempt used a blanket rule and broke
`test_edition_proof_spacing_licence_is_not_used_by_the_matcher`, which is
exactly what that test is for.

A clean pass here still reports an ellipsis the author never filled, so
tolerating the spacing cannot swallow an unfinished statement.

**Reproduction:** `tests/fixtures/pattern_spacing_variant.pdf`.

---

## Finding #5 — a fill-in nested in an optional group

**Class:** `false_alarm`. **Status:** fixed.

`P264+P265` is `Wash hands [and…] thoroughly after handling.` — a fill-in inside
an optional group. The compiled pattern required the value to start immediately
after `and`, so an author who kept the group and wrote `and other specified body
parts` failed, while *dropping* the group passed. The fill-in group now tolerates
leading whitespace; it still requires a non-empty value.

**Reproduction:** `tests/fixtures/pattern_optional_fillin.pdf`.

---

## Finding #6 — a closing full stop OSHA's own rendering omits

**Class:** `false_alarm`. **Status:** fixed.

The official CFR publishes Appendix C as graphics; the osha.gov HTML is the only
text rendering, and it prints the statements with no closing full stop. A sheet
that writes the sentence normally was failing A-03 on the period alone.

The licence is a **registry flag**, not a rule in the matcher, so it applies to
`us_osha` and nothing else — a test pins that the set stays `{us_osha}`. It runs
one way: dropping a terminator the official text *has* is still reported.

**Reproduction:** `tests/fixtures/pattern_osha_terminator.pdf`.

---

## Finding #7 — capitalisation could pass in silence

**Class:** `false_alarm`. **Status:** fixed.

Authoring tools that substitute values mid-sentence emit `Take off Immediately`
and `Rinse SKIN`. The words are the official words, so this was never a wording
*failure* — but the compiled template patterns were case-insensitive and returned
a **clean** match, so a capitalisation difference could disappear entirely.

Templates are now tried case-sensitively first; the case-insensitive pass is kept
only so the difference can be reported. Never a fail, never silent. A-01 is
unchanged and stays case-sensitive — the signal word is a prescribed token.

**Reproduction:** `tests/fixtures/pattern_capitalisation.pdf`.

---

## Finding #8 — a template that matched any text at all

**Class:** tool bug. **Status:** fixed. **Severity: the worst one here.**

Found while working on finding #7, and it predates Phase 1.5. The template for
`P302+P352` compiled a variant that matched **every sentence ever written**:

```
IF ON SKIN: Wash with plenty of water/…   matched   "Completely unrelated sentence here."
```

The matcher compiles every plausible reading of a template and passes if any
matches — deliberately permissive. One of those readings cut the leading literal
away *and* picked a subset of alternatives that was nothing but the fill-in,
leaving a bare wildcard between the anchors. For any code whose official text
ends in a slash followed by a fill-in, **A-03 could not fail a wrong statement**.

Rather than reason about which splits can degenerate, each compiled variant is
now tried against text sharing no word with any statement; one that matches
carries no literal to check against and is discarded. Every official text in
`eu_clp`, `un_ghs` and `us_osha` is asserted to still match itself.

**Residual, not fixed, needs a decision:** the matcher is still lenient enough
that `IF ON SKIN: Rinse with plenty of beer` passes against that template — the
reading "everything after the colon is the fill-in alternative" survives.
Tightening it means rejecting subsets that are *only* a fill-in, which would also
reject the legitimate `IF ON SKIN: Wash with plenty of soap`. That trade-off is a
judgement call and has been left open rather than decided unilaterally.

---

## Finding #9 — wrapped table cells gained a space in the keys

**Class:** `extraction_error`. **Status:** fixed.

A cell that breaks straight after a slash is a wrapped list of alternatives, not
a spaced one. Turning each break into a space put

```
Avoid breathing dust/fume/gas/ mist/vapours/ spray.
```

in the `uk_clp` key, which then failed against every document that writes the
list normally. Twelve `uk_clp` entries were affected, and the same artifact was
in `au_whs`, `ca_whmis` and `un_ghs`. A compound wrapped across lines is rejoined
the same way, keeping the hyphen (`Use non- sparking tools.`).

The hyphen rule needed a guard: a **suspended** hyphen — `Spreng- und
Wurfstücke`, `Brand- eller eksplosionsfare` — has a real space after it, and the
first attempt closed those up. What follows a suspended hyphen is a conjunction,
so the join is skipped when the next line starts with one. That list is the whole
guard, and a suspended hyphen followed by a non-conjunction and falling exactly
on a line end would still be joined wrongly.

Only PDF-sourced keys go through this. `eu_clp` comes from CELLAR XHTML and
`us_osha` from osha.gov HTML; neither wraps, so a space beside a slash there is
the source's own typography and is left alone.
