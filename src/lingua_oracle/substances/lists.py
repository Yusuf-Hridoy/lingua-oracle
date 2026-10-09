"""One list per regulation, and whether that regulation makes it binding.

An ingredient is judged against a published classification. Which publication
depends on the regulation the sheet is written to, and so does what a
difference from it means:

* a binding list - the regulation says a substance in it shall be classified
  as the entry says - makes a missing code a fault in the sheet;
* a reference list is somebody else's law. A difference from it is worth
  knowing and is not a fault, because no regulation obliges the author to
  follow it.

Every line below is cited from the instrument that settles it, and the
citation travels to the report, because "your ingredient is under-classified"
and "the EU classifies this substance differently" are different sentences and
a reader is entitled to know which one they are being shown.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ListUse:
    """The list one regulation is checked against, and on what authority."""

    #: The file under data/, without its extension: "annex_vi" is Table 3.
    name: str
    title: str
    binding: bool
    #: What makes it binding, or what makes it only a reference.
    authority: str
    #: The list's name in a sentence: "HCIS", "GB MCL", "Annex VI" - and
    #: "EU Annex VI (reference)" where it is another jurisdiction's list.
    short: str = ""

    @property
    def status(self) -> str:
        return "binding" if self.binding else "reference only"

    def __str__(self) -> str:
        return f"{self.title} ({self.status})"


ANNEX_VI = "CLP Annex VI Part 3, Table 3"

#: Per regulation. Japan has no entry: no list is on file for it, and none is
#: borrowed.
LISTS: dict[str, ListUse] = {
    "eu_clp": ListUse(
        "annex_vi", ANNEX_VI, True,
        "Regulation (EC) No 1272/2008, Article 4(3): a substance subject to "
        "harmonised classification through an entry in Part 3 of Annex VI "
        '"shall be classified in accordance with that entry".', "Annex VI"),
    "uk_clp": ListUse(
        "gb_mcl", "GB mandatory classification and labelling list", True,
        "Regulation (EC) No 1272/2008 as retained in GB law, Article 4(3): a "
        "substance with an entry in the GB mandatory classification and "
        'labelling list "shall be classified in accordance with that entry" '
        "(data/sources/uk-gb-clp/gb_clp_full.pdf, page 19).", "GB MCL"),
    "au_whs": ListUse(
        "au_hcis", "Safe Work Australia HCIS", False,
        "HCIS publishes these classifications itself and says of them: "
        '"Information on HCIS is for guidance only" and "HCIS is not and '
        'should not be relied on as legal ... advice" '
        "(hcis.safeworkaustralia.gov.au, read 2026-10-07).", "HCIS"),
    "us_osha": ListUse(
        "annex_vi", ANNEX_VI, False,
        "29 CFR 1910.1200 publishes no list of classified substances: "
        "Appendix A gives the criteria and leaves the classification to the "
        "manufacturer. Annex VI is shown as the EU's view of the substance, "
        "which US OSHA does not adopt.", "EU Annex VI (reference)"),
    "ca_whmis": ListUse(
        "annex_vi", ANNEX_VI, False,
        "The Hazardous Products Regulations publish no list of classified "
        "substances; they give the criteria and leave the classification to "
        "the supplier. Annex VI is shown as the EU's view of the substance, "
        "which WHMIS does not adopt.", "EU Annex VI (reference)"),
    "un_ghs": ListUse(
        "annex_vi", ANNEX_VI, False,
        "The GHS is a system of criteria, not a list of classified "
        "substances, and classifies nothing itself. Annex VI is shown as the "
        "EU's view of the substance.", "EU Annex VI (reference)"),
}


def for_regulation(regulation: str) -> ListUse | None:
    """The list to judge an ingredient by, or nothing where there is none."""
    return LISTS.get(regulation)
