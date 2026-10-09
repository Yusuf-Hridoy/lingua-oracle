# Reference classifications (PubChem)

`lingua keys pubchem <CAS...>` or `lingua keys pubchem --from <pdfs>` writes
one file per CAS number here: PubChem's GHS classifications for it, as read
from PUG-View's "GHS Classification" heading - every entry, in PubChem's
order, with its source and, for ECHA's aggregate, how many notifications
give each code.

PubChem (ECHA C&L notifications) — reference, not legally binding. The
binding lists (Annex VI, the GB MCL) are kept elsewhere and always marked as
binding.

The files are local and not tracked: the CAS numbers in them are the
ingredients of the documents checked. The check reads them and never fetches.
