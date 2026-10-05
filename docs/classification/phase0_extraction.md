# Classification check, Flow A — Phase 0: extraction discovery

**Status: discovery only.** No classification logic was written, no existing
behaviour was changed, and nothing in `src/` was touched. This document records
what Sections 2 and 3 actually look like across the documents we hold, and
proposes the data model the later phases would fill.

The eventual goal of the module is to recalculate a mixture's classification
from Section 3 under the CLP mixture rules and compare it with the
classification Section 2 states. Phase 0 asks a narrower question: **can the
inputs be read off these PDFs at all, and in what shapes?**

No product or customer names appear below. Documents are named by file only, and
every worked example uses placeholders (`<name>`, `CAS 000-00-0`) in place of
real identifiers. The shapes are the point, not the substances.

---

## 1. How this was measured

A read-only probe opened each PDF with `pdfplumber`, located the Section 2, 3
and 4 headings, and pulled out everything between them — both as positioned text
lines and as detected tables, bounded by the headings' own coordinates rather
than by page. It reused the repo's existing vocabulary rather than inventing
one: `data/hazard_classes/eu_clp.json` (the Annex VI Table 1.1 class list the
key builder already commits) for hazard classes, and `detect.codes.CODE_RE` for
H/EUH/P codes.

The probe lives in the session scratchpad, not the repo, because a half-formed
extractor committed next to this document would be read as the module. Its
patterns are reproduced in Appendix A so the measurement can be repeated, and it
can be committed under `docs/classification/` on request.

## 2. The corpus

Thirteen documents: six under `data/validation/app/` and seven under
`data/validation/third_party/`. Both directories are gitignored; nothing from
them is reproduced here.

| | documents |
| --- | --- |
| Section 2 heading found | 11 of 13 |
| Section 3 heading found | 12 of 13 |
| Section 3 composition readable | 9 clean, 2 messy, 2 not found |
| Per-ingredient classification present | **2 of 13** |
| **Section 3 with more than one ingredient** | **0 of 13** |

That last row is the finding that matters most, and it is addressed in §4.

## 3. Per document

"Kind" is what the sheet calls itself (`3.1 Substances` / `3.2 Mixtures`);
"unstated" means it uses neither heading.

| File | Source | Kind | Section 3 | Ingredients | Per-ingredient classification |
| --- | --- | --- | --- | --- | --- |
| `au_whs_en_38710.pdf` | app | unstated | clean table | 1 (60 %) | none |
| `eu_clp_en_4250.pdf` | app | unstated | clean table | 1 (100 %) | none |
| `uk_clp_en_38584.pdf` | app | unstated | clean table | 1 (60 %) | none |
| `un_ghs_en_57867.pdf` | app | unstated | clean table | 1 (100 %) | none |
| `un_ghs_en_58007.pdf` | app | unstated | clean table | 1 (100 %) | none |
| `us_osha_en_58677.pdf` | app | unstated | clean table | 1 (90 %) | none |
| `50-85-1 (1).pdf` | third party | unstated | clean table | 1 (≤ 100 %) | none |
| `s20.pdf` | third party | **mixture** | clean table | 1 (≥ 90 – ≤ 100 % w/w) | **class + category + H code** |
| `v1104.pdf` | third party | substance | clean table | 1 (≥ 90 – ≤ 100 % w/w) | none (empty M-factor/SCL/ATE column) |
| `50-85-1.pdf` | third party | substance | messy layout | 1 (≤ 100 %) | **class + category, split over 3 lines** |
| `50-85-1 (2).pdf` | third party | substance | messy layout | identifiers only | none |
| `1111040001.pdf` | third party | unstated | not found | — | — |
| `50-85-1 (3).pdf` | third party | unstated | not found | — | — |

Two documents cannot be read at all, for reasons worth separating:

* `1111040001.pdf` — Section 3 says, in full, *"Refer to component SDS"*. It is a
  kit of separately-supplied components. There is no composition to extract, and
  no amount of parser work will produce one. **Flow A is not applicable**, and
  the module should say exactly that rather than report an empty Section 3.
* `50-85-1 (3).pdf` — every character is drawn twice (`SSEECCTTIIOONN 11`), a
  producer artefact the repo already recognises elsewhere (A-07, broken
  characters). No heading, code or identifier can be matched. The module should
  refuse rather than guess, and reuse A-07's detection to say why.

**Single-substance sheets.** Three declare themselves substances
(`50-85-1.pdf`, `50-85-1 (2).pdf`, `v1104.pdf`) and should be marked as such:
the mixture rules do not apply, and a comparison between Section 2 and Section 3
reduces to "does the stated classification match the substance's own". Nine more
are effectively single-ingredient without saying so.

## 4. What is missing — and what it means for Flow A

Three things block Flow A on this corpus, in descending order of seriousness.

**(a) No multi-ingredient sheet exists here.** Every readable Section 3 lists
exactly one ingredient. Flow A is a mixture calculation — summation for health
classes, M-factors for aquatic, additivity for acute toxicity — and none of it
can be exercised, let alone validated, against a one-row table. Before Phase 1
is worth building, the corpus needs genuine multi-ingredient mixtures.

**(b) The app documents carry no per-ingredient classification.** All six have
the same five columns:

```
CHEMICAL NAME | CAS NO. | EC NO. | INDEX NO. | CONCENTRATION (%)
```

There is no classification column, and no classification anywhere else in
Section 3. Flow A needs each ingredient's own hazard classes to recalculate
anything, so on these sheets it would have to supply them from elsewhere —
Annex VI Table 3 by CAS or EC number, which the repo does not hold. That is a
data-sourcing decision, not a parsing one, and it should be taken before Phase 1
rather than discovered inside it.

**(c) The declared ingredients do not add up to 100 %.** Three app documents
declare a single ingredient at 60 %, 60 % and 90 %. The remainder is
undisclosed, which is lawful and ordinary. Any recalculation has to treat the
undeclared balance explicitly — as unknown, never as absent — or it will under-
classify every sheet that withholds a formulation. A result computed from 60 %
of a mixture is not a classification; at most it is a lower bound.

## 5. Every shape Section 3 takes

### 5.1 Table headers seen

```
CHEMICAL NAME | CAS NO. | EC NO. | INDEX NO. | CONCENTRATION (%)
Component     | CAS No  | Weight %
Chemical name | CAS-No. / EC-No. / Index-No. / Registration number | Classification | Concentration (% w/w)
Chemical name | CAS-No. EC-No. | Concentration (% w/w) | M-Factor, SCL, ATE
Component     | Classification | Concentration            (header row renders empty)
```

Five layouts across nine readable documents. Notable consequences:

* **Identifiers stacked in one column.** `s20.pdf` puts CAS-No., EC-No.,
  Index-No. and the REACH registration number in a single column, one under the
  other, with the ingredient's name spanning all four rows. A row-wise reading
  returns four rows of which three have no name.
* **A column header wrapped mid-word.** `Concentratio` / `n (% w/w)` — the unit
  belongs to a header that is itself split across two lines.
* **The unit lives in the header, not the cell.** Every app document's cell says
  `100`, `60`, `90`; the `%` is in `CONCENTRATION (%)`. A cell parser that
  requires a unit returns nothing on six of thirteen documents.
* **A header row that extracts as empty cells.** `50-85-1.pdf` has a visible
  Component/Classification/Concentration header that `extract_tables` returns as
  `['', 'Component', '', '', 'Classification', '', '', 'Concentration', '']`.

### 5.2 Concentration shapes seen

| Shape | Example as printed | Note |
| --- | --- | --- |
| Bare number, unit in header | `100`, `60`, `90` | six documents |
| Single bound, no space | `<=100` | one document |
| Single bound with unit | `<= 100 %` | one document |
| Two-sided bound | `>= 90 - <= 100` | two documents |

Of the shapes named in the Phase 0 brief, `5-10%`, `≥ 10 – < 20` and `<1%` do
**not** appear anywhere in this corpus. They are common in multi-ingredient
sheets, and this corpus has none, so the parser should still expect them — but
they are untested here and should be marked as such.

### 5.3 Classification shapes seen

* **Short code with category, semicolon-separated, split across lines** —
  `50-85-1.pdf` prints:

  ```
  Acute Tox. 4; Skin Irrit. 2;       <= 100 %
  Eye Irrit. 2A; STOT SE 3;
  H302, H315, H319, H335
  ```

  The classification runs over two lines, the concentration sits on the first of
  them, and the H codes come on a third line in a different separator style
  (comma, not semicolon). The trailing `;` on line 2 is the only hint that the
  list continues.
* **Short code plus H code on one line** — `Asp. Tox. 1; H304` (`s20.pdf`).
* **Column present but empty** — `v1104.pdf` has an `M-Factor, SCL, ATE` column
  carrying nothing. Three distinct data types share one column, so when it is
  populated it will need splitting by keyword, and an empty one must not be read
  as "no M-factor applies".
* **Cross-reference instead of text** — "For the full text of the H-Statements
  mentioned in this Section, see Section 16." The H codes in Section 3 are codes
  only; their wording is elsewhere.

### 5.4 Other shapes that will break a naive parser

* **Formula and molecular weight interleaved with identifiers**, with subscripts
  on their own line: `Formula: C H O` / `8 8 3`.
* **Synonyms listed before the composition block**, each on its own line, so the
  first line after the heading is not the ingredient.
* **REACH registration numbers split across a page break**: `NN-NNNNNNNNNN-` /
  `NN-XXXX`.
* **Vendor footers inside the section range** — page numbers, a corporate
  footer, a product code — which sit between the heading and the data.
* **No footnote markers were seen** in this corpus (`[1]`, `*`, `¹`). Expect
  them; do not assume this corpus proves their absence.

## 6. Section 2 shapes

Two renderings, and they share no vocabulary.

**(a) H code plus a bare category** — all six app documents:

```
H225 Category 2
H319 Category 2A
H336 Category 3
H361D
EUH018 Supplemental
```

The hazard **class is never named**. The class has to be derived from the H
code (H225 → Flam. Liq.), and the category is a separate token beside it.
Supplemental statements carry the word `Supplemental` where a category would be,
and some codes (`H361D`) carry neither.

**(b) GHS long form with the statement attached** — `s20.pdf`, `v1104.pdf`:

```
Aspiration hazard, Category 1 H304: May be fatal if swallowed and enters
airways.
```

Class name in full, category spelled out, H code and its full text on the same
line, wrapping onto the next. Mapping `Aspiration hazard` → `Asp. Tox.` needs a
long-form-to-short-code table the repo does not yet hold.

Both renderings also carry `PBT` and `vPvB` assessments in Section 2, which are
not hazard classes and must not be read as such.

## 7. Extraction pitfalls found while measuring

These cost real time during Phase 0 and are recorded so Phase 1 does not pay
them again.

1. **A CAS number and a concentration range are the same shape.** A CAS number
   `NN-NN-N` matches a `\d+-\d+` range pattern, and an EC number `NNN-NNN-N`
   matches it twice. Every
   identifier must be masked out of the text before concentrations are looked
   for, or every document reports its CAS numbers as percentages.
2. **Page-level table association is too coarse.** Sections 2 and 3 routinely
   share a page, and picking "the table on Section 3's page" returned Section
   2's statement table on four of six app documents. Tables must be bounded by
   the headings' coordinates.
3. **Other tables share the composition table's columns.** `50-85-1 (1).pdf` has
   three further Component/CAS tables — IARC/NTP/ACGIH listings, TSCA flags —
   with the same opening columns. Selecting by header words alone picks the
   wrong one.
4. **Hazard class stems match ordinary prose.** `Aerosol` is an Annex VI class
   stem and also an everyday word; it matched inside Section 2 narrative on two
   documents. A class token should only be accepted with a category beside it,
   or in a known classification context.
5. **Heading wording varies more than expected**: `Hazards identification`,
   `Hazard identification`, `Hazard(s) identification`, with and without the
   word `SECTION`, numbered `2.` or `2:`. One variant cost a whole document's
   Section 2.

## 8. Proposed data model

Two extraction results, one per section, each carrying its own provenance and
its own list of reasons it may not be usable. Nothing is inferred at extraction
time: a field that is not printed is `None`, never a default.

```python
class Bound(StrEnum):
    AT_MOST = "<="      # "<= 100 %"
    LESS_THAN = "<"
    AT_LEAST = ">="
    MORE_THAN = ">"
    EXACTLY = "="

class Unit(StrEnum):
    PERCENT_WW = "% w/w"
    PERCENT_VV = "% v/v"
    PERCENT = "%"        # unqualified - the sheet did not say which
    PPM = "ppm"
    G_PER_L = "g/l"
    MG_PER_KG = "mg/kg"

class Concentration(BaseModel):
    """A single value or a range, as printed. Never normalised on the way in."""
    low: Decimal | None            # ">= 90 - <= 100" -> low 90, high 100
    high: Decimal | None
    low_bound: Bound | None
    high_bound: Bound | None
    unit: Unit | None              # None when the unit was in the column header
    unit_from_header: bool = False
    raw: str                       # exactly what the cell said

class ClassificationEntry(BaseModel):
    """One hazard class + category, however the sheet wrote it."""
    hazard_class: str | None       # "Acute Tox." - Annex VI short form
    category: str | None           # "4", "1B", "2A"
    h_codes: list[str] = []
    raw: str
    #: How it was written, because each form needs a different repair later:
    #: short_code      "Acute Tox. 4"
    #: long_form       "Aspiration hazard, Category 1"
    #: code_and_category  "H225 Category 2" - no class named
    #: code_only       "H361D"
    #: supplemental    "EUH018 Supplemental"
    form: Literal["short_code", "long_form", "code_and_category",
                  "code_only", "supplemental"]

class SpecificLimit(BaseModel):
    """An SCL, M-factor or ATE given against one ingredient."""
    kind: Literal["scl", "m_factor", "ate"]
    hazard_class: str | None
    category: str | None
    value: Decimal | None
    unit: Unit | None
    route: str | None              # ATE only: oral / dermal / inhalation
    raw: str

class Ingredient(BaseModel):
    name: str | None
    cas: str | None
    ec: str | None
    index: str | None
    reach: str | None
    concentration: Concentration | None
    classification: list[ClassificationEntry] = []
    limits: list[SpecificLimit] = []
    footnotes: list[str] = []
    #: Where this came from, so a finding can point at the page.
    page: int | None = None
    raw_cells: list[str] = []

class Composition(BaseModel):
    """Section 3."""
    kind: Literal["substance", "mixture", "unstated"]
    ingredients: list[Ingredient] = []
    layout: Literal["table", "lines", "absent"]
    #: True when the sheet points elsewhere ("Refer to component SDS").
    delegated: bool = False
    declared_total: Decimal | None = None   # sum of the single-valued ones
    issues: list[ExtractionIssue] = []

class StatedClassification(BaseModel):
    """Section 2."""
    entries: list[ClassificationEntry] = []
    layout: Literal["lines", "table", "absent"]
    issues: list[ExtractionIssue] = []

class ExtractionIssue(BaseModel):
    """A reason the extraction is incomplete, in words a reader can act on."""
    code: Literal["section_not_found", "no_composition", "delegated",
                  "unreadable_text", "class_without_category",
                  "concentration_unparsed", "ingredient_without_concentration",
                  "undeclared_balance", "single_ingredient"]
    message: str
    page: int | None = None
```

Three design points worth arguing now rather than later:

* **`raw` on every value.** Every example in §5 is a case where the printed form
  carries information the parsed form loses — a trailing `;` meaning "continues
  on the next line", a unit that was in the header. Keeping the raw string costs
  nothing and makes a wrong parse visible in the report instead of invisible in
  a number.
* **`form` on every classification entry.** The six app documents name no
  hazard class at all. Recording *how* a classification was written is what lets
  a later phase decide whether it can be used, repaired from the H code, or has
  to be refused.
* **`issues` rather than exceptions.** Two of thirteen documents cannot be read
  and both have a specific, reportable reason. "Flow A does not apply to this
  sheet, because its Section 3 refers to component sheets" is a useful result;
  a stack trace is not.

## 9. What Phase 1 needs before it starts

1. **Multi-ingredient sheets.** Nothing in this corpus exercises a mixture
   calculation. Without them Phase 1 would be written against one-row tables and
   validated against nothing.
2. **A decision on ingredient classification.** Six of thirteen documents give
   none. Either Flow A is scoped to sheets that publish it (two documents here),
   or the repo takes on Annex VI Table 3 as a committed data source, with the
   same provenance rules as the answer keys.
3. **A decision on the undeclared balance.** 60 % declared means 40 % unknown.
   The rule for that has to be stated before any arithmetic is written.
4. **A long-form to short-code table**, if Section 2's GHS long form is to be
   compared with Annex VI short codes. It belongs in `data/`, built from a
   source, not typed from memory.

---

## Appendix A — how to repeat the measurement

The probe used `pdfplumber` directly (the repo's `extract` package exposes lines
but not tables), grouped words into lines by rounding `top` to 3-point bands, and
found sections with:

```python
HEAD2 = r"(?:section\s*)?2[.:)\s]{0,3}\s*hazard[s(]{0,3}s?[)]?\s+identification"
HEAD3 = r"(?:section\s*)?3[.:)\s]{0,3}\s*composition"
HEAD4 = r"(?:section\s*)?4[.:)\s]{0,3}\s*first[- ]aid"
```

Identifiers were masked before concentrations were matched:

```python
IDENTIFIER_RE = (r"\b\d{2}-\d{10}-\d{2}(?:-\w{4})?\b"   # REACH
                 r"|\b\d{3}-\d{3}-\d{2}-\d\b"           # Index
                 r"|\b\d{2,7}-\d{2}-\d\b"               # CAS
                 r"|\b\d{3}-\d{3}-\d\b")                # EC
```

Hazard classes came from `data/hazard_classes/eu_clp.json`, H/EUH/P codes from
`lingua_oracle.detect.codes.CODE_RE`, and tables from `page.find_tables()`
filtered to those whose bounding box falls between the Section 3 and Section 4
headings.
