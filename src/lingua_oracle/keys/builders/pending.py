"""Builders for regulations whose official text this tool cannot lawfully fetch.

Each of these was attempted against its official source and recorded here with
the exact reason it failed, verified on 2026-09-29:

* ``uk_clp``  - legislation.gov.uk serves every view (HTML, data.xml, data.akn)
  behind an AWS WAF JavaScript challenge. Working around a WAF is not something
  this tool does.
* ``un_ghs``  - unece.org returns HTTP 403 to non-browser clients for both the
  GHS landing pages and the Annex 3 PDFs.
* ``au_whs``  - safeworkaustralia.gov.au does not answer programmatic requests
  (connection read timeout).
* ``ca_whmis`` - the Hazardous Products Regulations full text is fetchable, but
  it contains no code-keyed hazard or precautionary statements, so no entry can
  be derived from it without inventing the code-to-text mapping.
* ``jp_jis``  - two separate reasons. JIS Z 7252/7253 is a paid standard and is
  deliberately not scraped. The file on record under data/sources/japan/ is *not*
  JIS: it is the Japanese edition of UN GHS Rev.9, a different document with a
  different revision, so nothing may be taken from it for a JIS key. Its text is
  unreadable in any case - the PDF's Japanese font carries no ToUnicode CMap, so
  neither PyMuPDF nor pdfplumber can recover characters, and OCR has not been run.

Rather than fill these from memory, each writes an empty key with
``status=pending_source``. Two supported ways to populate them:

* ``--from-file`` on ``lingua keys build``, pointing at a copy of the official
  source downloaded by hand.
* ``lingua keys import-csv`` for a sourced company glossary.
"""

from __future__ import annotations

from dataclasses import dataclass

from lingua_oracle.keys.builders.common import now
from lingua_oracle.keys.builders.pdf_tables import ParseIssues
from lingua_oracle.models import AnswerKey, Status
from lingua_oracle.registry import load_registry


@dataclass(frozen=True)
class PendingSpec:
    regulation: str
    reason: str
    #: Machine-readable reason, stored on the key as `status_reason`.
    code: str = "pending_source"


PENDING: dict[str, PendingSpec] = {
    "uk_clp": PendingSpec(
        "uk_clp",
        "legislation.gov.uk serves all views behind an AWS WAF challenge "
        "(x-amzn-waf-action: challenge); no machine-readable route is offered.",
    ),
    "un_ghs": PendingSpec(
        "un_ghs",
        "unece.org returns HTTP 403 to programmatic clients for the GHS pages "
        "and the Annex 3 PDFs.",
    ),
    "au_whs": PendingSpec(
        "au_whs",
        "safeworkaustralia.gov.au does not answer programmatic requests "
        "(read timeout); AUH statements could not be retrieved.",
    ),
    "ca_whmis": PendingSpec(
        "ca_whmis",
        "The Hazardous Products Regulations state hazard and precautionary "
        "statements by hazard class and category, never against a code, so a "
        "class/category -> statement -> GHS code mapping is needed before a key "
        "can be built. See data/answer_keys/ca_whmis/_design_note.md.",
        code="needs_class_category_mapping",
    ),
    "jp_jis": PendingSpec(
        "jp_jis",
        "The file on record is the Japanese edition of UN GHS Rev.9, not JIS Z "
        "7252/7253, so nothing may be taken from it for a JIS key. JIS itself is a "
        "paid standard and is deliberately not scraped. The file is unreadable "
        "regardless: its Japanese font carries no ToUnicode CMap, so no extractor "
        "can recover characters. OCR has not been run.",
        code="wrong_source",
    ),
}


def build(
    regulation: str, languages: list[str] | None = None
) -> tuple[list[AnswerKey], list[ParseIssues]]:
    if regulation not in PENDING:
        raise KeyError(f"No pending-source builder for {regulation!r}")
    spec = PENDING[regulation]
    reg = load_registry().get(regulation)
    langs = languages or reg.official_languages or ["en"]
    ts = now()
    issues = ParseIssues(source=f"{regulation} (no usable source)")
    issues.notes.append(f"status_reason: {spec.code}")
    issues.notes.append(spec.reason)
    if regulation == "jp_jis":
        issues.notes.append(
            "Nothing is extracted from data/sources/japan/GHS_Rev9_ja_annex2-3.pdf: "
            "it is UN GHS Rev.9 (Japanese), a different document from JIS Z "
            "7252/7253, and its text cannot be read. Supply a JIS source, or fill "
            "the key with `lingua keys import-csv`."
        )
    keys = [
        AnswerKey(
            regulation=regulation,
            language=lang,
            revision=reg.revision,
            status=Status.PENDING_SOURCE,
            status_reason=PENDING[regulation].code,
            source_url=reg.source_url,
            retrieved_at=ts,
            entries=[],
        )
        for lang in langs
    ]
    return keys, [issues]


def reason(regulation: str) -> str:
    spec = PENDING.get(regulation)
    return spec.reason if spec else ""
