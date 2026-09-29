# Canada WHMIS — how the key is built

**Status: implemented.** This note previously proposed a three-stage mapping from
HPR hazard class/category to GHS codes. That design was unnecessary, and the
reason is worth recording.

## What the earlier design got wrong

The starting observation was right: the Hazardous Products Regulations
(SOR/2015-17) contain **zero** H or P codes, and state statements positionally by
hazard class and category. From that it looked as though a class/category →
statement → code mapping had to be invented, with the French half inherited
positionally from bilingual HPR rows because WHMIS French could not safely be
matched against EU CLP French.

What that missed is that the HPR says where its statements come from:

> **"GHS** means the United Nations document entitled *Globally Harmonized System
> of Classification and Labelling of Chemicals (GHS), Seventh Revised Edition."*

WHMIS statements therefore *are* GHS Rev.7 statements. The codes were never
missing — they are in GHS Rev.7 Annex 3, a code-keyed table, in every UN language
including French.

## What is actually done

* **English** from `data/sources/ghs-rev7/GHS_Rev7_en.pdf`, Annex 3.
* **French** from `data/sources/ghs-rev7/GHS_Rev7_fr.pdf`, Annex 3.

Each language is read from its own edition. Nothing is translated, nothing is
text-matched across languages, and no code is inferred from a position: the code
is the one in the table the statement sits in. Tier A, with `source_ref` recording
both the GHS row and the HPR definition that makes Rev.7 the right edition.

Signal words come from the Rev.7 Annex 1 label-element tables — English directly,
French by aligning tables on their H codes, which are identical across editions.

## The two gaps, and why they are gaps

**Chemicals under pressure.** For this class the HPR points not at Rev.7 but at
Annex 3 of the **Eighth** revised edition, which is not on file. The affected
codes are left out entirely, with `status_reason: needs_ghs_rev8_annex3`. Which
codes those are is read from the hazard-class column of a GHS edition that names
them, not from recall — they do not exist in Rev.7 at all, which is precisely why
the HPR had to reach forward to Rev.8.

The HPR also states, in both languages, an additional statement for this class:
*"Chemical under pressure: May explode if heated / Produit chimique sous pression :
peut exploser sous l'effet de la chaleur"*. It is **not** recorded, because the
HPR gives it no code and assigning one would be inference. It is quoted in
`_parse_issues.txt` so it is not lost.

To close this gap, supply GHS Rev.8 Annex 3 (English and French) under
`data/sources/` and extend `GHS7_FILES` in the builder.

**Canada-only classes** — biohazardous infectious materials, and the physical and
health hazards "not otherwise classified". The HPR defines these and sets
classification criteria for them, but states no statement text, so there is
nothing to record. They are listed in `_parse_issues.txt`.

## What must still not be done

- Do not translate, in either direction.
- Do not match WHMIS French against another regulation's French to establish a code.
- Do not fill the chemicals-under-pressure codes from Rev.7 or Rev.11; the HPR
  names Rev.8 specifically, and the wording differs between revisions.
