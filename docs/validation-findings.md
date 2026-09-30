# Validation findings

Issues found by running the checker against real documents (Phase 1.5).

Real documents are company data. **Nothing in this file names a product, a
customer or a file** — findings are described as patterns, with synthetic
reproductions in `tests/`.

| # | Title | Class | Status |
| --- | --- | --- | --- |
| 1 | Language detection restricted to the regulation's official languages | false_alarm (tool bug) | open — fix scheduled |
| 2 | A negative declaration read as a signal word | false_alarm (tool bug) | **fixed** |
| 3 | `XXXX` in a REACH registration number read as a placeholder | false_alarm (tool bug) | **fixed** |

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

### Agreed fix (scheduled for step 6, not yet implemented)

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

### Reproduction

To be added in step 6 as a synthetic fixture: a Danish document declaring a
regulation whose official languages exclude Danish, with fictional product data.
The fixture must show the document's language reported as `da`, and its codes
reported as unverified rather than failed.


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
