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
