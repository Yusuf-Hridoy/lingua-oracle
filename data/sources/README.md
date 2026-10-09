# Official source documents

The regulations the answer keys are built from. **These files are not
committed**: they are large published documents - a hundred megabytes
of them - that anyone can download from the publisher, and carrying
every edition in every clone forever is not worth it.

Download what you need and put it at the path below. Builders that
cannot find their file say which file and where it comes from; only
`eu_clp`, REACH Annex II and the OSHA fallbacks reach the network on
their own.

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
| `australia/model_whs_regulations_2025-12-05.pdf` | Model Work Health and Safety Regulations | as at 5 December 2025 | [link](https://www.safeworkaustralia.gov.au/sites/default/files/2025-12/model-whs-regulations-5_december_2025.pdf) | 2026-10-08 | section16 |
| `australia/hcis_hazard_classification_export_2026-10-07.xlsx` | Safe Work Australia HCIS, hazard classification data export | 7 062 chemicals, exported 2026-10-07 | [link](https://hcis.safeworkaustralia.gov.au/search/?filter=all) | 2026-10-07 | nothing yet |
| `us-osha/appendix_c.html` | OSHA 29 CFR 1910.1200 Appendix C | as published | [link](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppC) | 2026-09-29 | us_osha (falls back to the network if absent) |
| `us-osha/appendix_a.html` | OSHA 29 CFR 1910.1200 Appendix A | as published | [link](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppA) | 2026-10-06 | us_osha mixture rules (falls back to the network if absent) |
| `us-osha/appendix_d.html` | OSHA 29 CFR 1910.1200 Appendix D | as published | [link](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppD) | 2026-10-08 | section16 (falls back to the network if absent) |
| `uk-gb-reach/gb_reach_annex_ii.pdf` | GB REACH - Regulation (EC) No 1907/2006 as retained, Annex II | legislation.gov.uk PDF, document generated 2026-10-08 | [link](https://www.legislation.gov.uk/eur/2006/1907/annex/II) | 2026-10-08 | section16 (download by hand: the site answers scripts with a WAF challenge) |
| `eu-echa/candidate_list_export_2026-10-09.xlsx` | ECHA Candidate List of substances of very high concern for authorisation | export of 09-Oct-2026 09:20:07; 507 entries, latest inclusion 04-Feb-2026 | _not recorded_ | 2026-10-09 | lists (svhc_candidate) |
| `un-model-regulations/model_regulations_vol1.pdf` | UN Recommendations on the Transport of Dangerous Goods, Model Regulations, Vol. I | Rev.24 (2025), ST/SG/AC.10/1/Rev.24, published 15 Sep 2025 | [link](https://unece.org/transport/dangerous-goods/un-model-regulations-rev-24) | 2026-10-09 | lists (un_dangerous_goods) - downloaded by hand: unece.org answers scripts with a Cloudflare challenge |
| `japan/GHS_Rev9_ja_annex2-3.pdf` | UN GHS (Purple Book), Japanese - NOT JIS | Rev.9 (2021) | _not recorded_ | 2026-09-29 | nothing: see builders/pending.py |

## Notes

* `japan/GHS_Rev9_ja_annex2-3.pdf` is **not** JIS Z 7252/7253. It is the
  Japanese edition of UN GHS Rev.9, a different document, and nothing is
  taken from it for the `jp_jis` key. Its text cannot be read in any
  case: the PDF carries no ToUnicode map for its Japanese font.
* `us-osha/appendix_c.html` is a convenience copy. The OSHA builder
  fetches the page itself when the file is absent.
* 49 CFR 172.101 (the DOT Hazardous Materials Table) and 49 CFR 173.120
  (flammable liquid) are read from eCFR's versioner API at a pinned date.
* The ECHA Candidate List export records no download link: the site
  answers a script with 403, so no link could be confirmed.
* The UN Model Regulations (Rev.24, Vol. I) were downloaded by hand from
  the page linked: unece.org answers a script with a Cloudflare challenge.
* 29 CFR 1910.1200 itself - (g)(2), the SDS headings and their order -
  is read from eCFR's versioner API at a pinned date, and is not a file
  here.
* EU REACH Annex II (what Section 16 must say) is read from the
  Publications Office like EU CLP, and is not a file here. GB REACH
  Annex II has to be downloaded by hand: legislation.gov.uk answers a
  script with a WAF challenge.
* "Added" is the date the file was first committed to this repository,
  which is the closest record we have of when it was downloaded.
