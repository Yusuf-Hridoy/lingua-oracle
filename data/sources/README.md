# Official source documents

The regulations the answer keys are built from. **These files are not
committed**: they are large published documents - a hundred megabytes
of them - that anyone can download from the publisher, and carrying
every edition in every clone forever is not worth it.

Download what you need and put it at the path below. Builders that
cannot find their file say which file and where it comes from; only
`eu_clp` and the OSHA fallback reach the network on their own.

This file is generated from `keys/builders/sources.py`. Edit that.

| Path | Document | Edition | Downloaded from | Added | Read by |
| --- | --- | --- | --- | --- | --- |
| `un-ghs/GHS_Rev11_en.pdf` | UN GHS (Purple Book), English | Rev.11 (2025) | [link](https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025) | 2026-09-29 | un_ghs |
| `un-ghs/GHS_Rev11_fr.pdf` | UN GHS (Purple Book), French | Rev.11 (2025) | [link](https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025) | 2026-09-29 | un_ghs |
| `un-ghs/GHS_Rev11_es.pdf` | UN GHS (Purple Book), Spanish | Rev.11 (2025) | [link](https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025) | 2026-09-29 | un_ghs |
| `ghs-rev7/GHS_Rev7_en.pdf` | UN GHS (Purple Book), English | Rev.7 (2017) | [link](https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev7-2017) | 2026-09-29 | au_whs, ca_whmis, us_osha, ghs_index |
| `ghs-rev7/GHS_Rev7_fr.pdf` | UN GHS (Purple Book), French | Rev.7 (2017) | [link](https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev7-2017) | 2026-09-29 | ca_whmis, ghs_index |
| `ghs-rev8/GHS_Rev8_en.pdf` | UN GHS (Purple Book), English | Rev.8 (2019) | [link](https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev8-2019) | 2026-09-30 | ca_whmis, ghs_index |
| `ghs-rev8/GHS_Rev8_fr.pdf` | UN GHS (Purple Book), French | Rev.8 (2019) | [link](https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev8-2019) | 2026-09-30 | ca_whmis, ghs_index |
| `uk-gb-clp/gb_clp_full.pdf` | GB CLP - Regulation (EC) No 1272/2008 as retained | consolidated, as published by legislation.gov.uk | [link](https://www.legislation.gov.uk/eur/2008/1272/contents) | 2026-09-29 | uk_clp |
| `uk-gb-clp/gb_mcl_list.xlsx` | GB mandatory classification and labelling list (GB MCL List) | eighth version; file last modified 2026-05-19 | [link](https://www.hse.gov.uk/chemical-classification/classification/mcl-list.htm) | 2026-10-07 | nothing yet |
| `ca-whmis/hpr_bilingual.pdf` | Hazardous Products Regulations (SOR/2015-17), bilingual | consolidated, current to 2026-09-21, last amended 2022-12-15 | [link](https://laws-lois.justice.gc.ca/eng/regulations/SOR-2015-17/) | 2026-09-29 | ca_whmis |
| `australia/swa_classification_guidance.pdf` | Safe Work Australia - GHS classification and labelling guidance | as published | [link](https://www.safeworkaustralia.gov.au/doc/ghs-classification-and-labelling-chemicals) | 2026-09-29 | au_whs |
| `australia/hcis_hazard_classification_export_2026-10-07.xlsx` | Safe Work Australia HCIS, hazard classification data export | 7 062 chemicals, exported 2026-10-07 | [link](https://hcis.safeworkaustralia.gov.au/search/?filter=all) | 2026-10-07 | nothing yet |
| `us-osha/appendix_c.html` | OSHA 29 CFR 1910.1200 Appendix C | as published | [link](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppC) | 2026-09-29 | us_osha (falls back to the network if absent) |
| `us-osha/appendix_a.html` | OSHA 29 CFR 1910.1200 Appendix A | as published | [link](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppA) | 2026-10-06 | us_osha mixture rules (falls back to the network if absent) |
| `japan/GHS_Rev9_ja_annex2-3.pdf` | UN GHS (Purple Book), Japanese - NOT JIS | Rev.9 (2021) | _not recorded_ | 2026-09-29 | nothing: see builders/pending.py |

## Notes

* `japan/GHS_Rev9_ja_annex2-3.pdf` is **not** JIS Z 7252/7253. It is the
  Japanese edition of UN GHS Rev.9, a different document, and nothing is
  taken from it for the `jp_jis` key. Its text cannot be read in any
  case: the PDF carries no ToUnicode map for its Japanese font.
* `us-osha/appendix_c.html` is a convenience copy. The OSHA builder
  fetches the page itself when the file is absent.
* "Added" is the date the file was first committed to this repository,
  which is the closest record we have of when it was downloaded.
