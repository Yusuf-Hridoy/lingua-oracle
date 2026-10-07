# EU CLP: adopted changes the consolidation we hold does not carry

Consolidation on file: `02008R1272-20260701` (EUR-Lex: consolidated version of
01/07/2026; created in CELLAR 2026-07-09). It is what the `eu_clp` keys, the
EU mixture rules and `data/annex_vi/table3.json` are built from.

Checked 2026-10-07, read-only, against the Publications Office's CELLAR (the
acts themselves, as XHTML, and their metadata via the SPARQL endpoint).
**Nothing has been applied.** This records what was found, with the evidence,
so the decision of what to do and when is made on it.

---

## 1. The 23rd ATP — Commission Delegated Regulation (EU) 2025/1222

**Not in the 01/07/2026 consolidation.**

| | |
| --- | --- |
| Act | Commission Delegated Regulation (EU) 2025/1222 of 2 April 2025, amending Annex VI (harmonised classification and labelling of certain substances) |
| OJ | published 20.6.2025; ELI `http://data.europa.eu/eli/reg_del/2025/1222/oj` |
| In force | 10.7.2025 |
| Applies | **1 February 2027** — Article 2: *"It shall apply from 1 February 2027. However, suppliers may classify, label and package substances and mixtures in accordance with Regulation (EC) No 1272/2008 as amended by this Regulation from the date of entry into force of this Regulation."* |

Evidence that the consolidation does not contain it:

* Its "Amended by" list ends at **►M37**, Regulation (EU) 2024/2865. No entry
  names 2025/1222, and the string `2025/1222` appears nowhere in the text.
* The Annex of 2025/1222 **inserts 22 entries** into Table 3. None of the 22
  index numbers appears anywhere in the consolidation, nor in
  `data/annex_vi/table3.json`:
  `007-031-00-9 008-004-00-4 015-209-00-2 026-005-00-8 056-006-00-9
  602-111-00-5 602-112-00-0 603-248-00-3 603-249-00-9 604-103-00-7
  607-776-00-5 607-777-00-0 607-778-00-6 607-779-00-1 607-780-00-7
  608-070-00-X 612-300-00-4 612-301-00-X 613-352-00-0 613-353-00-6
  650-059-00-7 650-060-00-2` (ozone, `008-004-00-4`, among them).
* It **replaces 10 entries**. All 10 are present, in their earlier form:
  `015-012-00-1 601-027-00-6 602-025-00-8 607-231-00-1 613-044-00-6
  613-045-00-1 615-008-00-5 616-145-00-3 616-211-00-1 616-212-00-7`.
  Two compared directly:

  | Index No | Table 3 as we hold it (01/07/2026) | As 2025/1222 replaces it |
  | --- | --- | --- |
  | 015-012-00-1 | Flam. Sol. 2, Water-react. 1, Acute Tox. 4 *, Aquatic Acute 1 — H228 H260 H302 H400 | Flam. Sol. 1, Self-heat. 1, Acute Tox. 4* — H228 H251 H302 |
  | 616-211-00-1 | Carc. 2, Aquatic Acute 1, Aquatic Chronic 1 — H351 H400 H410 | Carc. 2, STOT RE 1, Aquatic Acute 1, Aquatic Chronic 1 — H351 H372 (thyroid, liver) H400 H410 |

* It is not in the 01/01/2027 consolidation either (`02008R1272-20270101`,
  created in CELLAR 2026-09-29), which is expected: it applies a month later.
  No 01/02/2027 consolidation exists yet.

What it means here: the ingredient check judges an EU sheet against Table 3 as
of 01/07/2026. A supplier already applying the 23rd ATP early is measured
against the old entries — for 015-012-00-1, a sheet carrying the new H251
would be reported as missing H260 and H400. From 1 February 2027 the table
on file is out of date for these 32 entries.

---

## 2. Regulation (EU) 2025/2439

**Not reflected in the 01/07/2026 consolidation, although that consolidation
was created after 2025/2439 was in force.**

| | |
| --- | --- |
| Act | Regulation (EU) 2025/2439 of the European Parliament and of the Council of 26 November 2025 amending Regulation (EU) 2024/2865 as regards dates of application and transitional provisions |
| OJ | published 3.12.2025; ELI `http://data.europa.eu/eli/reg/2025/2439/oj` |
| In force | 23.12.2025 |
| What it amends | **Regulation (EU) 2024/2865**, Article 2 (its dates) — not the text of 1272/2008 |

What it changes, from its Article 1 against 2024/2865's original Article 2:

| Provisions of 2024/2865 | Originally applied from | Under 2025/2439 |
| --- | --- | --- |
| Art 1(14) — CLP Article 30, updating labels | 1 July 2026 | **1 January 2028** |
| Art 1(26) — CLP Article 48, advertisement | 1 July 2026 | **1 January 2028** |
| Art 1(27) — new CLP Article 48a, distance sales | 1 July 2026 | **1 January 2028** |
| Annex II point (2) | 1 July 2026 | **1 January 2028** |
| Art 1(15)(c), Annex I points (2) and (3) | 1 January 2027 | **1 January 2028** |
| Art 1(1), (9), (24)(b),(d), Annex IV | 1 January 2027 | 1 January 2027 (restated) |

Evidence, comparing the two consolidations CELLAR holds:

| | 01/07/2026 (ours) | 01/01/2027 |
| --- | --- | --- |
| Lists 2025/2439 | no — list ends at ►M37 | yes — *"M38 Amended by: REGULATION (EU) 2025/2439 ... L 2439 1 3.12.2025"* |
| Article 30 | 2024/2865's new text (*"In the event of a change regarding the classification or labelling ... which results in the addition of a new hazard class ..."*) | the earlier text (*"The supplier shall ensure that the label is updated, without undue delay ..."*) |
| Article 48 | 2024/2865's new text (*"... shall indicate, as applicable, the hazard pictograms, signal words, hazard statements and supplemental EUH statements ..."*) | the earlier text (*"... shall mention the hazard classes or hazard categories concerned."*) |
| Article 48a "Distance sales offers" | **present** | absent |

So the 01/07/2026 consolidation prints as applicable three articles that
2025/2439 postponed to 1 January 2028, and the 01/01/2027 consolidation
corrects it. The 01/01/2027 consolidation also adds **►M39**, the *Notice
concerning the harmonised classification of titanium dioxide as Carcinogenic
Category 2 via inhalation* (C/2025/6670, OJ C 10.12.2025), which ours does not
carry either.

What it means here: no builder reads Articles 30, 48 or 48a. The keys come
from Annexes III and IV, the mixture rules from Annex I, the ingredient list
from Annex VI. **Not yet checked:** whether 2024/2865's Annex II point (2) —
one of the postponed provisions — touches any supplemental statement wording
the keys hold. Building the keys from both consolidations and diffing them
would settle it.

---

## How this was found

* Consolidations of 1272/2008 listed through the CELLAR SPARQL endpoint:
  `02008R1272-20250201, -20250901, -20260501, -20260701, -20270101`.
* Each act and both consolidations fetched from
  `http://publications.europa.eu/resource/celex/<CELEX>` with
  `Accept: application/xhtml+xml`, `Accept-Language: eng` — the same request
  the EU CLP builder makes. EUR-Lex's own pages answer plain requests with an
  AWS WAF challenge and were not used.
* Act metadata (entry into force, publication, what each amends) from CELLAR:
  2025/1222 amends 32008R1272; 2025/2439 amends 32024R2865.
