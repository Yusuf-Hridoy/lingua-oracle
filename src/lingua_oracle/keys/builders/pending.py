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
* ``jp_jis``  - JIS Z 7252/7253 is a paid standard and is deliberately not
  scraped, exactly as the brief requires.

Rather than fill these from memory, each writes an empty key with
``status=pending_source``. Two supported ways to populate them:

* ``--from-file`` on ``lingua keys build``, pointing at a copy of the official
  source downloaded by hand.
* ``lingua keys import-csv`` for a sourced company glossary.
"""

from __future__ import annotations

from dataclasses import dataclass

from lingua_oracle.keys.builders.common import now
from lingua_oracle.models import AnswerKey, Status
from lingua_oracle.registry import load_registry


@dataclass(frozen=True)
class PendingSpec:
    regulation: str
    reason: str


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
        "The Hazardous Products Regulations (SOR/2015-17) full text is reachable "
        "but contains no code-keyed hazard or precautionary statements, so no "
        "entry can be derived without inventing the code-to-text mapping.",
    ),
    "jp_jis": PendingSpec(
        "jp_jis",
        "JIS Z 7252/7253 is a paid standard and is deliberately not scraped.",
    ),
}


def build(regulation: str, languages: list[str] | None = None) -> list[AnswerKey]:
    if regulation not in PENDING:
        raise KeyError(f'No pending-source builder for {regulation!r}')
    reg = load_registry().get(regulation)
    langs = languages or reg.official_languages or ["en"]
    ts = now()
    return [
        AnswerKey(
            regulation=regulation,
            language=lang,
            revision=reg.revision,
            status=Status.PENDING_SOURCE,
            source_url=reg.source_url,
            retrieved_at=ts,
            entries=[],
        )
        for lang in langs
    ]


def reason(regulation: str) -> str:
    spec = PENDING.get(regulation)
    return spec.reason if spec else ""
