# Canada WHMIS — design note for a class/category → code mapping

**Status:** design only. Nothing here is implemented, and no entry has been
written to the WHMIS key.

## The problem

The Hazardous Products Regulations (SOR/2015-17) are fetchable and parse cleanly,
but they are shaped differently from every other source this tool reads. A scan of
the full 165-page bilingual text finds **zero** H or P codes. The HPR does not
codify statements; it states them positionally, in Schedule tables keyed by

    hazard class → category (or subcategory) → the statement to display

in English and French side by side. Every other regulation this tool supports
(EU CLP Annex III/IV, UN GHS Annex 3, GB CLP, GHS Rev.7) publishes a table whose
first column *is* the code, which is why one parser serves all of them.

So the missing thing is not the text — the HPR has it, in both official
languages — but the code each statement belongs to.

## Why the OSHA trick does not transfer

US OSHA has the same "no codes" shape, and there the code is established by
comparing OSHA's English against EU CLP's English: identical wording means the
same statement. That works because both are English.

It does not transfer to WHMIS for the French half. WHMIS French is a Canadian
translation and is not expected to be identical to EU CLP's French, so text
identity cannot establish the code. Matching French-to-French across two
jurisdictions would be guessing, which is exactly what this tool must not do.

## Proposed mapping

Three stages, strongest first. Each stage records *how* a code was established, so
a reviewer can weigh it.

### 1. English by text identity (reuses existing machinery)

Run the WHMIS English statements through the same comparison ladder
`keys/builders/us_osha.py` already uses — identical, identical once fill-ins are
collapsed, then near-identical at a high similarity floor — against EU CLP
English. This should key most of the English side, because WHMIS English and GHS
English are close.

Output: `{code: english_statement}`.

### 2. French by position, not by text

This is the part that needs the HPR's own structure. Within one Schedule row the
English and French cells are the *same statement* in two languages. So once stage
1 has keyed the English cell of a row, the French cell of that same row inherits
the code — positionally, with no text comparison at all.

This requires the parser to keep row identity across the bilingual layout, which
the current `harvest` does not (it flattens to `{code: text}`). A
`harvest_bilingual_rows` returning `[(en_cell, fr_cell, class, category)]` would
be the addition.

Confidence here is as good as stage 1's, because the French code is inherited
rather than inferred.

### 3. Class/category cross-check (verification, not a source)

The HPR row also gives hazard class and category. EU CLP Annex I and UN GHS
Annex 1 both state which statement belongs to which class/category. Comparing
them catches stage-1 mistakes: if the HPR places a statement under
"Flammable liquids, category 2" and the code assigned in stage 1 belongs to
category 3 in CLP, the mapping is wrong and should be rejected, not stored.

Use this only to *reject*, never to assign — deriving a code from a class alone
would be inference.

## What must not be done

- Do not translate. Neither direction, not even for a cross-check.
- Do not match WHMIS French against EU CLP French to establish a code.
- Do not fall back to "the statement that looks closest" without a similarity
  floor and a recorded score.
- Anything left unkeyed stays out of the key and goes in `_parse_issues.txt`.

## Expected outcome

Stage 1 should key the bulk of the English side; stage 2 gives French for free
wherever stage 1 succeeded; stage 3 removes the mistakes. The result would be
`status: partial` with `status_reason: counts_not_reconciled`, matching how OSHA
is handled — not `ok`, because coverage would be incomplete and the HPR's own
revision cycle differs from CLP's.

Until this exists, `lingua keys import-csv` is the supported way to populate
WHMIS from a sourced company glossary.
