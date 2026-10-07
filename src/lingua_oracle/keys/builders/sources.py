"""The official source documents a builder reads, and where each came from.

These are large published PDFs - a hundred megabytes of them - and they are no
longer committed. Every clone would otherwise carry every edition ever used,
forever, for files anyone can download from the publisher.

This table is the record of what is expected: the path a builder looks for, the
page it was downloaded from, which edition it is, when it was put in, and what
reads it. `data/sources/README.md` is generated from it, and a builder that
cannot find its file raises an error naming the file and the link, rather than
an empty key or a stack trace.

A URL here is the page the document was taken from, as recorded by the builder
that used it. Where no URL was recorded, this says so - an invented link is
worse than an admitted gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lingua_oracle.keys.builders.common import SourceUnavailable
from lingua_oracle.registry import data_dir


@dataclass(frozen=True)
class Source:
    path: str
    title: str
    edition: str
    url: str | None
    added: str
    used_by: str
    #: How a report names this document: which document and which version, in
    #: the words a reader would look it up by. Says only what the file itself
    #: or its download page shows; where neither gives a version, the date it
    #: was put on file stands in, and says that is what it is.
    version: str = ""

    @property
    def where(self) -> Path:
        return data_dir() / "sources" / self.path


SOURCES: tuple[Source, ...] = (
    Source("un-ghs/GHS_Rev11_en.pdf",
           "UN GHS (Purple Book), English", "Rev.11 (2025)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025",
           "2026-09-29", "un_ghs",
           version="UN GHS Rev.11 (2025), English edition"),
    Source("un-ghs/GHS_Rev11_fr.pdf",
           "UN GHS (Purple Book), French", "Rev.11 (2025)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025",
           "2026-09-29", "un_ghs",
           version="UN GHS Rev.11 (2025), French edition"),
    Source("un-ghs/GHS_Rev11_es.pdf",
           "UN GHS (Purple Book), Spanish", "Rev.11 (2025)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025",
           "2026-09-29", "un_ghs",
           version="UN GHS Rev.11 (2025), Spanish edition"),
    Source("ghs-rev7/GHS_Rev7_en.pdf",
           "UN GHS (Purple Book), English", "Rev.7 (2017)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev7-2017",
           "2026-09-29", "au_whs, ca_whmis, us_osha, ghs_index",
           version="UN GHS Rev.7 (2017), English edition"),
    Source("ghs-rev7/GHS_Rev7_fr.pdf",
           "UN GHS (Purple Book), French", "Rev.7 (2017)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev7-2017",
           "2026-09-29", "ca_whmis, ghs_index",
           version="UN GHS Rev.7 (2017), French edition"),
    Source("ghs-rev8/GHS_Rev8_en.pdf",
           "UN GHS (Purple Book), English", "Rev.8 (2019)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev8-2019",
           "2026-09-30", "ca_whmis, ghs_index",
           version="UN GHS Rev.8 (2019), English edition"),
    Source("ghs-rev8/GHS_Rev8_fr.pdf",
           "UN GHS (Purple Book), French", "Rev.8 (2019)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev8-2019",
           "2026-09-30", "ca_whmis, ghs_index",
           version="UN GHS Rev.8 (2019), French edition"),
    Source("uk-gb-clp/gb_clp_full.pdf",
           "GB CLP - Regulation (EC) No 1272/2008 as retained",
           "consolidated, as published by legislation.gov.uk",
           "https://www.legislation.gov.uk/eur/2008/1272/contents",
           "2026-09-29", "uk_clp",
           version="GB CLP (Regulation (EC) No 1272/2008 as retained), "
                   "legislation.gov.uk consolidated text, on file since 2026-09-29"),
    Source("uk-gb-clp/gb_mcl_list.xlsx",
           "GB mandatory classification and labelling list (GB MCL List)",
           "eighth version; file last modified 2026-05-19",
           "https://www.hse.gov.uk/chemical-classification/classification/mcl-list.htm",
           "2026-10-07", "nothing yet",
           version="GB MCL list, 8th version (file last modified 2026-05-19)"),
    Source("ca-whmis/hpr_bilingual.pdf",
           "Hazardous Products Regulations (SOR/2015-17), bilingual",
           "consolidated, current to 2026-09-21, last amended 2022-12-15",
           "https://laws-lois.justice.gc.ca/eng/regulations/SOR-2015-17/",
           "2026-09-29", "ca_whmis",
           version="Hazardous Products Regulations (SOR/2015-17), "
                   "current to 2026-09-21, last amended 2022-12-15"),
    Source("australia/swa_classification_guidance.pdf",
           "Safe Work Australia - GHS classification and labelling guidance",
           "as published",
           "https://www.safeworkaustralia.gov.au/doc/ghs-classification-and-labelling-chemicals",
           "2026-09-29", "au_whs",
           version="Safe Work Australia GHS classification and labelling "
                   "guidance (AUH statements), on file since 2026-09-29"),
    Source("australia/hcis_hazard_classification_export_2026-10-07.xlsx",
           "Safe Work Australia HCIS, hazard classification data export",
           "7 062 chemicals, exported 2026-10-07",
           "https://hcis.safeworkaustralia.gov.au/search/?filter=all",
           "2026-10-07", "nothing yet",
           version="Safe Work Australia HCIS export 2026-10-07 (7 062 chemicals)"),
    Source("us-osha/appendix_c.html",
           "OSHA 29 CFR 1910.1200 Appendix C", "as published",
           "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppC",
           "2026-09-29", "us_osha (falls back to the network if absent)",
           version="OSHA 29 CFR 1910.1200 Appendix C (osha.gov), "
                   "on file since 2026-09-29"),
    Source("us-osha/appendix_a.html",
           "OSHA 29 CFR 1910.1200 Appendix A", "as published",
           "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppA",
           "2026-10-06", "us_osha mixture rules (falls back to the network if absent)",
           version="OSHA 29 CFR 1910.1200 Appendix A (osha.gov), "
                   "on file since 2026-10-06"),
    Source("japan/GHS_Rev9_ja_annex2-3.pdf",
           "UN GHS (Purple Book), Japanese - NOT JIS", "Rev.9 (2021)",
           None,
           "2026-09-29", "nothing: see builders/pending.py",
           version="UN GHS Rev.9 (2021), Japanese edition - not JIS"),
)

BY_PATH = {source.path: source for source in SOURCES}


# -- which versions a report used ----------------------------------------------

_CONSOLIDATION = re.compile(r"\b0?2008R1272-(\d{4})(\d{2})(\d{2})\b")


def eu_clp_version(revision: str) -> str:
    """EU CLP named by its consolidated version, as EUR-Lex dates it.

    EU CLP is not a file here - it is read from the Publications Office - so
    its version is the CELEX number of the consolidation the key was built
    from, `02008R1272-20260701`, printed as the date EUR-Lex shows for it.
    """
    match = _CONSOLIDATION.search(revision or "")
    if match is None:
        return f"EU CLP, Regulation (EC) No 1272/2008, {revision}"
    year, month, day = match.groups()
    return ("EU CLP, Regulation (EC) No 1272/2008, consolidated version of "
            f"{day}/{month}/{year}")


def _version(path: str) -> str:
    return BY_PATH[path].version


def _wording(regulation: str, language: str, revision: str) -> list[str]:
    """What a regulation's statements were read from, in this language."""
    rev7 = BY_PATH["ghs-rev7/GHS_Rev7_en.pdf"].edition
    rev8 = BY_PATH["ghs-rev8/GHS_Rev8_en.pdf"].edition
    match regulation:
        case "eu_clp":
            return [eu_clp_version(revision)]
        case "uk_clp":
            return [_version("uk-gb-clp/gb_clp_full.pdf")]
        case "au_whs":
            return [_version("ghs-rev7/GHS_Rev7_en.pdf"),
                    _version("australia/swa_classification_guidance.pdf")]
        case "ca_whmis":
            # The HPR names the edition; the text is the edition's own.
            return [f"UN GHS {rev7}, English and French editions, as "
                    f"incorporated by the {_version('ca-whmis/hpr_bilingual.pdf')}",
                    f"UN GHS {rev8}, for chemicals under pressure, as the HPR "
                    "directs"]
        case "us_osha":
            return [_version("us-osha/appendix_c.html")]
        case "un_ghs":
            path = f"un-ghs/GHS_Rev11_{language.split('-')[0]}.pdf"
            if path in BY_PATH:
                return [_version(path)]
    return []


#: The source file behind each published list that is not Annex VI. Annex VI is
#: part of EU CLP and carries the consolidation it was read from.
_LIST_SOURCES = {
    "gb_mcl": "uk-gb-clp/gb_mcl_list.xlsx",
    "au_hcis": "australia/hcis_hazard_classification_export_2026-10-07.xlsx",
}


#: Where the mixture rules came from a file on this list, that file names
#: the version. The others name their edition in the rule table already.
_MIXTURE_SOURCES = {
    "us_osha": "us-osha/appendix_a.html",
    "uk_clp": "uk-gb-clp/gb_clp_full.pdf",
}


def list_version(name: str, annex_vi_source: str = "") -> str:
    """One published substance list, named by its version."""
    if name == "annex_vi":
        return ("CLP Annex VI Part 3, Table 3, from the "
                + eu_clp_version(annex_vi_source))
    path = _LIST_SOURCES.get(name)
    return _version(path) if path else name


def upcoming_version(upcoming) -> str:
    """An adopted amendment to Annex VI, named with the date it applies."""
    return (f"{upcoming.title}, amending Annex VI Table 3 from "
            f"{upcoming.applies_from:%d/%m/%Y}, read from the act "
            f"(CELEX {upcoming.act})")


def used(regulation: str, language: str, revision: str, *,
         ingredient_list: str = "", annex_vi_source: str = "",
         mixture_document: str = "", upcoming=None) -> list[str]:
    """Every source a report was judged against, each with its version.

    Only what this report actually used: the ingredient list and the mixture
    rules appear when those halves ran, and not otherwise.
    """
    lines = [f"Wording: {line}"
             for line in _wording(regulation, language, revision)]
    if not lines:
        lines.append("Wording: no official text on file for this regulation "
                     "and language")
    if regulation == "us_osha":
        # Appendix C prints no codes; they were matched against the GHS.
        lines.append("Statement codes: matched against UN GHS "
                     f"{BY_PATH['ghs-rev7/GHS_Rev7_en.pdf'].edition} and "
                     f"{BY_PATH['ghs-rev8/GHS_Rev8_en.pdf'].edition}, "
                     "English editions")
    if ingredient_list:
        lines.append("Ingredients: "
                     + list_version(ingredient_list, annex_vi_source))
    if mixture_document:
        consolidation = _CONSOLIDATION.search(mixture_document)
        if consolidation:
            mixture_document = "Annex I of " + eu_clp_version(
                consolidation.group(0))
        elif regulation in _MIXTURE_SOURCES:
            mixture_document = _version(_MIXTURE_SOURCES[regulation])
        lines.append(f"Mixture rules: {mixture_document}")
    if upcoming is not None:
        lines.append(f"Upcoming: {upcoming_version(upcoming)}")
    return lines


def describe(path: str) -> str:
    """Where to get one source document, in words a reader can act on."""
    source = BY_PATH.get(path)
    if source is None:
        return f"data/sources/{path}"
    where = source.url or "no download link on record"
    return (f"data/sources/{source.path} - {source.title}, {source.edition}. "
            f"Download it from {where} and put it at that path. "
            f"See data/sources/README.md.")


def source_note(path: str, missing: Path | None = None) -> str:
    """The line a parse report carries when a source file is not there.

    The builders degrade rather than stop - a missing file becomes a
    pending_source key, so one absent document does not block the others - but
    the note has to say which file and where to get it, or the key is a dead
    end for whoever reads it.
    """
    where = missing or (data_dir() / "sources" / path)
    return f"source file not found at {where}. {describe(path)}"


def require(path: str) -> Path:
    """The source file, or an error saying which file and where to get it.

    Builders call this instead of letting an absent file turn into an empty key
    or a traceback: the one thing a person needs is the name of the file and
    the page it comes from.
    """
    source = BY_PATH.get(path)
    where = source.where if source else data_dir() / "sources" / path
    if not where.exists():
        raise SourceUnavailable(describe(path))
    return where


def readme() -> str:
    """data/sources/README.md, generated so it cannot drift from the table."""
    lines = [
        "# Official source documents",
        "",
        "The regulations the answer keys are built from. **These files are not",
        "committed**: they are large published documents - a hundred megabytes",
        "of them - that anyone can download from the publisher, and carrying",
        "every edition in every clone forever is not worth it.",
        "",
        "Download what you need and put it at the path below. Builders that",
        "cannot find their file say which file and where it comes from; only",
        "`eu_clp` and the OSHA fallback reach the network on their own.",
        "",
        "This file is generated from `keys/builders/sources.py`. Edit that.",
        "",
        "| Path | Document | Edition | Downloaded from | Added | Read by |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for source in SOURCES:
        url = f"[link]({source.url})" if source.url else "_not recorded_"
        lines.append(f"| `{source.path}` | {source.title} | {source.edition} "
                     f"| {url} | {source.added} | {source.used_by} |")
    lines += [
        "",
        "## Notes",
        "",
        "* `japan/GHS_Rev9_ja_annex2-3.pdf` is **not** JIS Z 7252/7253. It is the",
        "  Japanese edition of UN GHS Rev.9, a different document, and nothing is",
        "  taken from it for the `jp_jis` key. Its text cannot be read in any",
        "  case: the PDF carries no ToUnicode map for its Japanese font.",
        "* `us-osha/appendix_c.html` is a convenience copy. The OSHA builder",
        "  fetches the page itself when the file is absent.",
        "* \"Added\" is the date the file was first committed to this repository,",
        "  which is the closest record we have of when it was downloaded.",
        "",
    ]
    return "\n".join(lines)


def write_readme() -> Path:
    target = data_dir() / "sources" / "README.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(readme(), encoding="utf-8")
    return target
