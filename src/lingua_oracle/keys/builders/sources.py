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

    @property
    def where(self) -> Path:
        return data_dir() / "sources" / self.path


SOURCES: tuple[Source, ...] = (
    Source("un-ghs/GHS_Rev11_en.pdf",
           "UN GHS (Purple Book), English", "Rev.11 (2025)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025",
           "2026-09-29", "un_ghs"),
    Source("un-ghs/GHS_Rev11_fr.pdf",
           "UN GHS (Purple Book), French", "Rev.11 (2025)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025",
           "2026-09-29", "un_ghs"),
    Source("un-ghs/GHS_Rev11_es.pdf",
           "UN GHS (Purple Book), Spanish", "Rev.11 (2025)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev11-2025",
           "2026-09-29", "un_ghs"),
    Source("ghs-rev7/GHS_Rev7_en.pdf",
           "UN GHS (Purple Book), English", "Rev.7 (2017)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev7-2017",
           "2026-09-29", "au_whs, ca_whmis, us_osha, ghs_index"),
    Source("ghs-rev7/GHS_Rev7_fr.pdf",
           "UN GHS (Purple Book), French", "Rev.7 (2017)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev7-2017",
           "2026-09-29", "ca_whmis, ghs_index"),
    Source("ghs-rev8/GHS_Rev8_en.pdf",
           "UN GHS (Purple Book), English", "Rev.8 (2019)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev8-2019",
           "2026-09-30", "ca_whmis, ghs_index"),
    Source("ghs-rev8/GHS_Rev8_fr.pdf",
           "UN GHS (Purple Book), French", "Rev.8 (2019)",
           "https://unece.org/transport/standards/transport/dangerous-goods/ghs-rev8-2019",
           "2026-09-30", "ca_whmis, ghs_index"),
    Source("uk-gb-clp/gb_clp_full.pdf",
           "GB CLP - Regulation (EC) No 1272/2008 as retained",
           "consolidated, as published by legislation.gov.uk",
           "https://www.legislation.gov.uk/eur/2008/1272/contents",
           "2026-09-29", "uk_clp"),
    Source("uk-gb-clp/gb_mcl_list.xlsx",
           "GB mandatory classification and labelling list (GB MCL List)",
           "eighth version; file last modified 2026-05-19",
           "https://www.hse.gov.uk/chemical-classification/classification/mcl-list.htm",
           "2026-10-07", "nothing yet"),
    Source("ca-whmis/hpr_bilingual.pdf",
           "Hazardous Products Regulations (SOR/2015-17), bilingual",
           "consolidated",
           "https://laws-lois.justice.gc.ca/eng/regulations/SOR-2015-17/",
           "2026-09-29", "ca_whmis"),
    Source("australia/swa_classification_guidance.pdf",
           "Safe Work Australia - GHS classification and labelling guidance",
           "as published",
           "https://www.safeworkaustralia.gov.au/doc/ghs-classification-and-labelling-chemicals",
           "2026-09-29", "au_whs"),
    Source("australia/hcis_hazard_classification_export_2026-10-07.xlsx",
           "Safe Work Australia HCIS, hazard classification data export",
           "7 062 chemicals, exported 2026-10-07",
           "https://hcis.safeworkaustralia.gov.au/search/?filter=all",
           "2026-10-07", "nothing yet"),
    Source("us-osha/appendix_c.html",
           "OSHA 29 CFR 1910.1200 Appendix C", "as published",
           "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppC",
           "2026-09-29", "us_osha (falls back to the network if absent)"),
    Source("us-osha/appendix_a.html",
           "OSHA 29 CFR 1910.1200 Appendix A", "as published",
           "https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.1200AppA",
           "2026-10-06", "us_osha mixture rules (falls back to the network if absent)"),
    Source("japan/GHS_Rev9_ja_annex2-3.pdf",
           "UN GHS (Purple Book), Japanese - NOT JIS", "Rev.9 (2021)",
           None,
           "2026-09-29", "nothing: see builders/pending.py"),
)

BY_PATH = {source.path: source for source in SOURCES}


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
