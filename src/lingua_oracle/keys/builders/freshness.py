"""Is what we hold still what the publisher shows? Read-only, and honest about it.

`lingua sources check-updates` asks each publisher, with a plain request under
this tool's own name, which version of a source it publishes now, and sets
that beside the version on file. Nothing is downloaded into data/, nothing is
rebuilt, and nothing is retried around a bot challenge: a publisher that
answers a plain request with a challenge or a refusal gets a row that says so
and gives the page to check by hand.

Where a publisher's own page cannot be read but the same publisher serves the
same fact another way, that is used and the row says which: EUR-Lex's CLP page
is behind an AWS WAF challenge, but the Publications Office's CELLAR - where
the EU CLP key is built from - lists the same consolidated versions; osha.gov
refuses plain requests, but eCFR publishes when 29 CFR 1910.1200 was amended.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urljoin

from lingua_oracle.keys.builders.common import USER_AGENT
from lingua_oracle.keys.builders.sources import BY_PATH

#: An export older than this is flagged. Safe Work Australia publishes HCIS
#: as a live database with no edition, so its age is the only measure there is.
HCIS_MAX_AGE_DAYS = 90

EUR_LEX_CLP = "https://eur-lex.europa.eu/legal-content/EN/ALL/?uri=CELEX:32008R1272"
CELLAR_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
HSE_MCL_PAGE = "https://www.hse.gov.uk/chemical-classification/classification/mcl-list.htm"
GB_CLP_PAGE = "https://www.legislation.gov.uk/eur/2008/1272/contents"
HPR_PAGE = "https://laws-lois.justice.gc.ca/eng/regulations/SOR-2015-17/"
ECFR_VERSIONS = ("https://www.ecfr.gov/api/versioner/v1/versions/title-29.json"
                 "?part=1910&section=1910.1200")
UNECE_GHS_PAGE = "https://unece.org/about-ghs"

YES, NO, BY_HAND, NOT_APPLICABLE = "yes", "NO", "check by hand", "n/a"


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


Fetch = Callable[[str], Response]


@dataclass
class Row:
    source: str
    held: str
    publisher: str
    up_to_date: str
    #: The page a person reads to confirm the row, or to do what it could not.
    url: str
    note: str = ""


def http_fetch(url: str) -> Response:
    """One plain GET under this tool's own name. No challenge is answered."""
    import httpx

    with httpx.Client(follow_redirects=True, timeout=30.0,
                      headers={"User-Agent": USER_AGENT}) as client:
        resp = client.get(url)
    return Response(resp.status_code,
                    {k.lower(): v for k, v in resp.headers.items()},
                    resp.content)


def refusal(resp: Response) -> str | None:
    """Why a response is not the page, in a few words - or None if it is."""
    if resp.headers.get("x-amzn-waf-action"):
        return f"bot challenge (HTTP {resp.status}, AWS WAF)"
    if resp.status == 202 or resp.status >= 400:
        return f"refused a plain request (HTTP {resp.status})"
    if not resp.body:
        return f"empty answer (HTTP {resp.status})"
    return None


def _ask(fetch: Fetch, url: str) -> tuple[Response | None, str | None]:
    """The response and None, or None and why there is no usable response."""
    try:
        resp = fetch(url)
    except Exception as exc:  # noqa: BLE001 - reported in the row, not raised
        return None, f"could not be reached ({type(exc).__name__})"
    why = refusal(resp)
    return (None, why) if why else (resp, None)


def _by_hand(why: str) -> str:
    return f"not checked automatically: {why}"


def _plain_text(html: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


# -- EU CLP ----------------------------------------------------------------------

_CONSOLIDATED = re.compile(r"^02008R1272-(\d{4})(\d{2})(\d{2})$")


def consolidation_date(celex: str) -> date | None:
    match = _CONSOLIDATED.match(celex.strip())
    return date(*map(int, match.groups())) if match else None


def eu_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def consolidations_from_sparql(payload: dict) -> list[date]:
    """Every consolidated version of 1272/2008 CELLAR lists, oldest first."""
    found = {consolidation_date(row["celex"]["value"])
             for row in payload.get("results", {}).get("bindings", [])}
    return sorted(day for day in found if day)


_SPARQL_QUERY = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex WHERE {
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(STR(?celex), "02008R1272-"))
}"""


def check_eu(fetch: Fetch, today: date) -> list[Row]:
    from lingua_oracle.keys.builders.annex_vi import load_table
    from lingua_oracle.registry import load_registry

    held_rev = load_registry().get("eu_clp").revision
    table = load_table()
    held = {"EU CLP wording and mixture rules (eu_clp key)": held_rev,
            "CLP Annex VI Table 3 (ingredient list)": table.source if table else ""}

    url = CELLAR_SPARQL + "?" + urlencode(
        {"query": _SPARQL_QUERY, "format": "application/sparql-results+json"})
    resp, why = _ask(fetch, url)
    versions: list[date] = []
    if resp is not None:
        try:
            versions = consolidations_from_sparql(json.loads(resp.body))
        except ValueError:
            why = "CELLAR answered, but not with the list of versions"
    current = max((d for d in versions if d <= today), default=None)
    later = [d for d in versions if d > today]

    rows = []
    for name, revision in held.items():
        held_day = consolidation_date(revision)
        held_text = (f"consolidated version of {eu_date(held_day)}" if held_day
                     else revision or "nothing on file")
        if current is None:
            rows.append(Row(name, held_text, _by_hand(why or "no versions listed"),
                            BY_HAND, EUR_LEX_CLP))
            continue
        shows = f"current consolidated version {eu_date(current)}"
        if later:
            shows += ("; also published, applying later: "
                      + ", ".join(eu_date(d) for d in later))
        note = ("EUR-Lex's own page answers a plain request with an AWS WAF "
                "challenge; the versions are CELLAR's, the Publications Office "
                "service EUR-Lex is published from.")
        if later:
            note += (" A version applying later is already published; what it "
                     "changes is not compared here.")
        rows.append(Row(name, held_text, shows,
                        YES if held_day == current else NO, EUR_LEX_CLP, note))
    return rows


# -- GB MCL list -------------------------------------------------------------------

_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh",
             "eighth", "ninth", "tenth", "eleventh", "twelfth", "thirteenth",
             "fourteenth", "fifteenth", "sixteenth", "seventeenth",
             "eighteenth", "nineteenth", "twentieth")


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def latest_mcl_version(rows: list[dict[str, str]]) -> str | None:
    """The last version the list's own Version log records, as "8th version".

    The log numbers its early versions in column A ("1", "1.1", ... "7") and
    names the latest in its text ("Eighth version. ..."), so both are read and
    the last one wins.
    """
    latest = None
    for row in rows:
        number = (row.get("A") or "").strip()
        text = (row.get("B") or "").strip().lower()
        if re.fullmatch(r"\d+(\.\d+)?", number):
            value = float(number)
            latest = (f"{_ordinal(int(value))} version" if value.is_integer()
                      else f"version {round(value, 1)}")
            continue
        named = re.match(r"(\w+) (?:version|edition)\b", text)
        if named and named.group(1) in _ORDINALS:
            latest = f"{_ordinal(_ORDINALS.index(named.group(1)) + 1)} version"
    return latest


def mcl_version_of(path: Path) -> str | None:
    from lingua_oracle.keys.builders import xlsx

    return latest_mcl_version(xlsx.rows(path, "Version log"))


def mcl_link(page_html: str) -> str | None:
    match = re.search(r'href="([^"]*mcl-list[^"]*\.xlsx)"', page_html, re.I)
    return urljoin(HSE_MCL_PAGE, match.group(1)) if match else None


def check_gb_mcl(fetch: Fetch) -> Row:
    source = BY_PATH["uk-gb-clp/gb_mcl_list.xlsx"]
    name = "GB MCL list (uk_clp ingredient list)"
    local = source.where
    # The file itself where it is on this machine; a fresh clone does not
    # carry it, and the version recorded for it stands in.
    recorded = re.search(r"\d+(?:st|nd|rd|th) version", source.version)
    held = (mcl_version_of(local) if local.exists()
            else recorded.group(0) if recorded else None)
    held_text = held or source.version
    resp, why = _ask(fetch, HSE_MCL_PAGE)
    link = mcl_link(resp.text) if resp else None
    if resp is not None and link is None:
        why = "the HSE page links no spreadsheet"
    if link:
        resp, why = _ask(fetch, link)
    if resp is None or link is None:
        return Row(name, held_text, _by_hand(why), BY_HAND, HSE_MCL_PAGE)

    with tempfile.TemporaryDirectory() as tmp:
        published = Path(tmp) / "mcl-list.xlsx"
        published.write_bytes(resp.body)
        try:
            shows = mcl_version_of(published)
        except Exception:  # noqa: BLE001 - a file we cannot read is a row, not a crash
            shows = None
    if shows is None:
        return Row(name, held_text, _by_hand("no Version log in HSE's file"),
                   BY_HAND, HSE_MCL_PAGE)
    note = ""
    if local.exists():
        same = (hashlib.sha256(local.read_bytes()).hexdigest()
                == hashlib.sha256(resp.body).hexdigest())
        note = ("HSE's file is byte-identical to ours." if same else
                "HSE's file differs from ours byte for byte.")
    return Row(name, held_text, f"{shows} (Version log of HSE's file)",
               YES if shows == held else NO, HSE_MCL_PAGE, note)


# -- Australia ---------------------------------------------------------------------

def check_hcis(today: date) -> Row:
    path = "australia/hcis_hazard_classification_export_2026-10-07.xlsx"
    source = BY_PATH[path]
    exported = date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", path).group(0))
    age = (today - exported).days
    return Row(
        "Safe Work Australia HCIS (au_whs ingredient list)",
        f"export of {exported.isoformat()}",
        f"HCIS is a live database with no edition; ours is {age} days old "
        f"(limit {HCIS_MAX_AGE_DAYS})",
        YES if age <= HCIS_MAX_AGE_DAYS else NO,
        source.url or "",
        "Re-export from HCIS and rebuild when this says NO.")


# -- Canada ------------------------------------------------------------------------

_HPR_DATES = re.compile(
    r"current to (\d{4}-\d{2}-\d{2}),? and last amended on (\d{4}-\d{2}-\d{2})",
    re.I)


def hpr_dates(page_html: str) -> tuple[str, str] | None:
    match = _HPR_DATES.search(_plain_text(page_html))
    return match.groups() if match else None


def check_hpr(fetch: Fetch) -> Row:
    source = BY_PATH["ca-whmis/hpr_bilingual.pdf"]
    name = "Hazardous Products Regulations (ca_whmis)"
    held = re.search(r"current to (\S+), last amended (\S+)", source.version)
    held_text = (f"last amended {held.group(2)} (current to {held.group(1)})"
                 if held else source.version)
    resp, why = _ask(fetch, HPR_PAGE)
    dates = hpr_dates(resp.text) if resp else None
    if dates is None:
        return Row(name, held_text,
                   _by_hand(why or "no amendment date on the page"),
                   BY_HAND, HPR_PAGE)
    current_to, amended = dates
    return Row(name, held_text,
               f"last amended {amended} (current to {current_to})",
               YES if held and held.group(2) == amended else NO, HPR_PAGE,
               "A later 'current to' date alone is not a change: it is the "
               "date Justice Canada last confirmed the text.")


# -- US OSHA -------------------------------------------------------------------------

def last_amendment(payload: dict) -> str | None:
    days = [v.get("amendment_date") for v in payload.get("content_versions", [])
            if v.get("identifier") == "1910.1200" and v.get("amendment_date")]
    return max(days) if days else None


def check_osha(fetch: Fetch) -> list[Row]:
    resp, why = _ask(fetch, ECFR_VERSIONS)
    amended = None
    if resp is not None:
        try:
            amended = last_amendment(json.loads(resp.body))
        except ValueError:
            why = "eCFR answered, but not with the list of versions"
    rows = []
    for path, name in (("us-osha/appendix_c.html", "OSHA Appendix C (us_osha wording)"),
                       ("us-osha/appendix_a.html", "OSHA Appendix A (us_osha mixture rules)")):
        source = BY_PATH[path]
        held = f"osha.gov page, on file since {source.added}"
        if amended is None:
            rows.append(Row(name, held, _by_hand(why or "no amendment dates"),
                            BY_HAND, source.url or ""))
            continue
        rows.append(Row(
            name, held, f"29 CFR 1910.1200 last amended {amended} (eCFR)",
            YES if amended <= source.added else NO, source.url or "",
            "osha.gov refuses plain requests (HTTP 403); eCFR dates every "
            "amendment of the section. Our copy postdating the last amendment "
            "is what YES means."))
    return rows


# -- pages with no machine-readable version -----------------------------------------

def check_page(fetch: Fetch, name: str, held: str, url: str,
               reads: Callable[[str], str | None] | None = None) -> Row:
    """A publisher page that may or may not say anything comparable."""
    resp, why = _ask(fetch, url)
    if resp is not None and reads is not None:
        shows = reads(resp.text)
        if shows:
            return Row(name, held, shows, BY_HAND, url,
                       "Read from the page; whether it changes what we hold "
                       "is a judgement for a person.")
    return Row(name, held, _by_hand(why or "the page states no version to compare"),
               BY_HAND, url)


def newest_ghs_revision(page_html: str) -> str | None:
    revisions = [int(n) for n in re.findall(r"\bRev(?:ision)?\.?\s*(\d{1,2})\b",
                                             _plain_text(page_html))]
    return f"newest revision mentioned: Rev.{max(revisions)}" if revisions else None


# -- all of it -------------------------------------------------------------------------

def check_updates(fetch: Fetch = http_fetch, today: date | None = None) -> list[Row]:
    """One row per source, in the order a reader thinks of them."""
    today = today or datetime.now(UTC).date()
    rev11 = BY_PATH["un-ghs/GHS_Rev11_en.pdf"]
    return [
        *check_eu(fetch, today),
        check_page(fetch, "GB CLP text (uk_clp wording)",
                   BY_PATH["uk-gb-clp/gb_clp_full.pdf"].version, GB_CLP_PAGE),
        check_gb_mcl(fetch),
        check_hcis(today),
        check_page(fetch, "SWA classification guidance (au_whs AUH wording)",
                   BY_PATH["australia/swa_classification_guidance.pdf"].version,
                   BY_PATH["australia/swa_classification_guidance.pdf"].url or ""),
        check_hpr(fetch),
        *check_osha(fetch),
        check_page(fetch, "UN GHS (un_ghs wording)", rev11.version,
                   UNECE_GHS_PAGE, newest_ghs_revision),
        Row("UN GHS Rev.7 / Rev.8 (au_whs, ca_whmis, us_osha)",
            "Rev.7 (2017) and Rev.8 (2019)",
            "the edition is the one each regulation names; a newer GHS "
            "revision does not replace it", NOT_APPLICABLE,
            BY_PATH["ghs-rev7/GHS_Rev7_en.pdf"].url or "",
            "Changes when a regulation adopts a newer revision - which the "
            "HPR and eCFR rows above would show as an amendment."),
    ]


def table(rows: list[Row]) -> str:
    """The rows as a Markdown table, then each row's URL and note under it.

    Markdown because the table is read in a terminal and pasted into tickets,
    and a pipe table survives both.
    """
    out = ["| | source | we hold | publisher shows | up to date? |",
           "| --- | --- | --- | --- | --- |"]
    for n, r in enumerate(rows, 1):
        out.append(f"| [{n}] | {r.source} | {r.held} | {r.publisher} | {r.up_to_date} |")
    out.append("")
    for n, row in enumerate(rows, 1):
        out.append(f"[{n}] {row.source}: {row.url}")
        if row.note:
            out.append(f"    {row.note}")
    return "\n".join(out)
