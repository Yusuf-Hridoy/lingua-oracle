# Validation findings

Issues found by running the checker against real documents (Phase 1.5).

Real documents are company data. **Nothing in this file names a product, a
customer or a file** — findings are described as patterns, with synthetic
reproductions in `tests/`.

| # | Title | Class | Status |
| --- | --- | --- | --- |
| 1 | Language detection restricted to the regulation's official languages | false_alarm (tool bug) | open — fix scheduled |

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
