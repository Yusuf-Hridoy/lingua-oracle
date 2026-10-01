"""Shared helpers for answer-key builders.

Builders are the ONLY part of Lingua Oracle allowed to touch the network,
and they are never invoked at check time.
"""

from __future__ import annotations

import hashlib
import os
import random
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

USER_AGENT = "lingua-oracle/0.1 (internal SDS QA tool)"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def cache_dir() -> Path:
    d = Path(os.environ.get("LINGUA_CACHE_DIR", Path.home() / ".cache" / "lingua-oracle"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch(url: str, *, headers: dict[str, str] | None = None, timeout: float = 300.0,
          use_cache: bool = True) -> bytes:
    """GET a URL, caching the body on disk so repeat builds stay cheap."""
    h = {"User-Agent": USER_AGENT, **(headers or {})}
    tag = hashlib.sha256((url + repr(sorted(h.items()))).encode()).hexdigest()[:20]
    cached = cache_dir() / f"{tag}.bin"
    if use_cache and cached.exists() and cached.stat().st_size > 0:
        return cached.read_bytes()
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=h) as client:
        resp = client.get(url)
        resp.raise_for_status()
        body = resp.content
    cached.write_bytes(body)
    return body


class SourceUnavailable(RuntimeError):
    """Raised when an official source cannot be fetched.

    Builders turn this into a `pending_source` key rather than inventing text.
    """


def now() -> datetime:
    return datetime.now(UTC)


# Amendment markers that EUR-Lex/CELLAR interleaves into consolidated text.
# e.g. '\u25 baM2 \u25c4', '\u25bcM5', '\u25bcB' -- an arrow plus its amendment tag.
_MARKER_RE = re.compile(r"[\u25ba\u25bc\u25b2]\s*[A-Z]{1,2}\d{0,3}\s*\u25c4?|[\u25c4\u25ba\u25bc\u25b2\u2500]")


def strip_markers(text: str) -> str:
    """Remove consolidation markers such as '►M2 ◄', '▼M5', '▼B'."""
    out = _MARKER_RE.sub(" ", text)
    return " ".join(out.split())


# The degree sign is not a character in either source. CELLAR marks it up as
# <span class="superscript">o</span>, and the PDFs set it as a raised lower-case
# "o"; both flatten to a bare "o" against the unit, giving "50 oC/122oF" where
# the regulation prints "50 °C/122 °F". 99 entries carried it.
#
# Anchored tightly: the "o" must follow a number, a fill-in or the slash that
# joins the two units, and be followed by C or F at a word boundary. That is the
# only place this shape occurs - the Italian P413 reads "… °C/oF", with the
# second fill-in missing, so the slash has to count as an anchor too. Nothing
# where a word meaning "or" could stand matches: "or" is followed by "r".
_DEGREE_RE = re.compile(r"(?<=[\d\u2026/])(\s*)o(?=[CF]\b)")


def repair_degree_sign(text: str) -> str:
    return _DEGREE_RE.sub(lambda m: f"{m.group(1)}\u00b0", text or "")


#: What an edition prints where it has withdrawn a code. Three languages are on
#: file; the marker is bracketed in all of them.
_DELETED_RE = re.compile(
    r"^\[?\s*(?:deleted|supprim\w*|suprimido|borrado)\s*\]?\.?$", re.IGNORECASE
)


def is_deleted_marker(text: str) -> bool:
    """True when the cell says the code was withdrawn rather than giving text."""
    return bool(_DELETED_RE.match((text or "").strip()))


# legislation.gov.uk marks amended passages with "[X1 ... ]" and "[F1 ... ]".
# The opening marker and its closing bracket are editorial apparatus, not part
# of the statement: GB CLP's H351 read "[X1Suspected of causing cancer ...".
_AMENDMENT_RE = re.compile(r"\[\s*[XF]\d+\s*")


def strip_amendment_markers(text: str) -> str:
    """Remove amendment markers, and the closing bracket each one opened.

    Only an unmatched closing bracket is dropped. Official statements use
    brackets for optional parts - "Rinse skin with water [or shower]" - and
    those are balanced, so they survive.
    """
    out, removed = _AMENDMENT_RE.subn("", text or "")
    if not removed:
        return text or ""
    kept: list[str] = []
    depth = 0
    for char in out:
        if char == "[":
            depth += 1
        elif char == "]":
            if depth == 0:
                removed -= 1
                if removed >= 0:
                    continue
            else:
                depth -= 1
        kept.append(char)
    return " ".join("".join(kept).split())


def normalise_code(code: str) -> str:
    """'EUH 066' -> 'EUH066'; 'P303 + P361 + P353' -> 'P303+P361+P353'."""
    c = strip_markers(code).upper()
    c = re.sub(r"\s*\+\s*", "+", c)
    c = re.sub(r"\b(EUH|AUH|H|P)\s+(\d)", r"\1\2", c)
    return c.strip()


def sanity_report(name: str, entries: list, *, sample: int = 10) -> str:
    """Counts per kind plus random entries for human spot-check."""
    from collections import Counter

    lines = [f"=== {name} ==="]
    if not entries:
        lines.append("  (no entries)")
        return "\n".join(lines)
    kinds = Counter(str(e.kind) for e in entries)
    langs = Counter(e.language for e in entries)
    lines.append(f"  entries: {len(entries)}")
    for k, n in sorted(kinds.items()):
        lines.append(f"    {k:<16} {n}")
    lines.append(f"  languages: {len(langs)} ({', '.join(sorted(langs))})")
    lines.append(f"  --- {min(sample, len(entries))} random entries for spot-check ---")
    for e in random.sample(entries, min(sample, len(entries))):
        text = e.text if len(e.text) <= 90 else e.text[:87] + "..."
        lines.append(f"    [{e.language}] {e.code:<22} {text}")
    return "\n".join(lines)
