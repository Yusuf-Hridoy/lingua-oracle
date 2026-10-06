"""Reading ingredients from the ExactSDS app. The only networked part.

Separated deliberately. `compare.py` is pure and the check path never reaches
the network; this module is the one place that does, it is called only by the
`lingua ingredients` command, and it reads. Every request is a GET apart from
the login that turns the credentials in `.env` into a session token.

Credentials come from `.env` and are never written to a report.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

TIMEOUT = 60.0
#: Reading the whole library is thousands of requests over many minutes, and a
#: server will close a connection in that time for reasons that have nothing to
#: do with the request. A transport error is retried; an answer is not, however
#: unwelcome - a 404 means the thing is not there and asking again will not
#: change that.
_ATTEMPTS = 4
_BACKOFF = 2.0


#: One login, not one per upload. Logging in costs two and a half seconds and
#: every uploaded document was paying it: the web suite went from thirty seconds
#: to three and a half minutes the day the ingredient check joined the upload
#: path. The session is reused until it is older than this.
_SESSION_TTL = 900.0
#: After a failure, do not try again for this long. Thirty uploads against an
#: application that is down should cost one timeout, not thirty.
_OFFLINE_FOR = 60.0
_SESSION: dict[str, object] = {}


def disabled() -> bool:
    """True when this installation is configured not to call ExactSDS.

    `LINGUA_EXACTSDS=off` turns the ingredient half off without removing the
    credentials - which is what a test suite wants, and what an installation
    that has not been given an account wants too.
    """
    import os

    return os.environ.get("LINGUA_EXACTSDS", "").strip().lower() in {
        "off", "0", "no", "false"}


def session(factory=None):
    """A logged-in client, reused across calls in this process.

    Raises AppUnavailable without touching the network when a recent attempt
    failed, so a run of uploads against an application that is down pays one
    timeout rather than one each.
    """
    if disabled():
        raise AppUnavailable("ExactSDS is switched off (LINGUA_EXACTSDS=off)")

    now = time.monotonic()
    failed_at = _SESSION.get("failed_at")
    if isinstance(failed_at, float) and now - failed_at < _OFFLINE_FOR:
        raise AppUnavailable(str(_SESSION.get("error") or "ExactSDS is not answering"))

    client = _SESSION.get("client")
    opened = _SESSION.get("opened_at")
    if client is not None and isinstance(opened, float) and now - opened < _SESSION_TTL:
        return client

    try:
        client = (factory or ExactSdsClient)()
        client.login()
    except Exception as exc:  # noqa: BLE001 - any failure means "not answering"
        _SESSION.update({"failed_at": now, "error": str(exc)[:200],
                         "client": None})
        raise AppUnavailable(str(exc)[:200]) from exc
    _SESSION.update({"client": client, "opened_at": now, "failed_at": None,
                     "error": None})
    return client


def forget_session() -> None:
    """Drop the cached session. For tests, and for a changed configuration."""
    import contextlib

    client = _SESSION.get("client")
    if client is not None:
        with contextlib.suppress(Exception):
            client.close()
    _SESSION.clear()


#: The settings that say which application to talk to and as whom. Only these
#: are read from the environment, so nothing else leaks in from a shell.
SETTINGS = ("EXACTSDS_URL", "EXACTSDS_USER", "EXACTSDS_PASSWORD")


def read_env(path: str | Path = ".env") -> dict[str, str]:
    """The application settings: `.env`, with the environment on top.

    The file is where a person keeps their credentials. The environment is how
    a deployment - or a test pointing at a stand-in application - says
    otherwise, and it wins, which is the usual way round and the only way a
    test can avoid talking to the live application at all.
    """
    out: dict[str, str] = {}
    source = Path(path)
    if source.exists():
        for line in source.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                out[key.strip()] = value.strip()
    for key in SETTINGS:
        value = os.environ.get(key)
        if value:
            out[key] = value
    return out


@dataclass
class Ingredient:
    """One component of one product, as the app holds it."""

    cas: str | None
    name: str | None
    h_codes: list[str]
    concentration: str | None
    data_source: str | None = None


class AppUnavailable(RuntimeError):
    """The app could not be reached or the credentials were refused."""


class ExactSdsClient:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        env = env or read_env()
        for key in ("EXACTSDS_URL", "EXACTSDS_USER", "EXACTSDS_PASSWORD"):
            if key not in env:
                raise AppUnavailable(f"{key} is not set in .env")
        root = env["EXACTSDS_URL"].rstrip("/")
        if root.endswith("/dashboard"):
            root = root.rsplit("/", 1)[0]
        self.base = f"{root}/api/v1"
        self._user = env["EXACTSDS_USER"]
        self._password = env["EXACTSDS_PASSWORD"]
        self.client = httpx.Client(timeout=TIMEOUT, follow_redirects=True)

    def login(self) -> None:
        try:
            resp = self.client.post(
                f"{self.base}/users/login",
                json={"email": self._user, "password": self._password})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppUnavailable(f"login failed: {exc}") from exc
        body = resp.json()
        token = (body.get("access_token") or body.get("token")
                 or (body.get("tokens") or {}).get("access_token"))
        if not token:
            raise AppUnavailable("the login response carried no token")
        self.client.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, **params: Any) -> Any:
        """GET one path, retrying only where the request never arrived."""
        url = f"{self.base}{path}"
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                resp = self.client.get(url, params=params or None)
            except (httpx.TransportError, httpx.RemoteProtocolError) as exc:
                if attempt == _ATTEMPTS:
                    raise AppUnavailable(
                        f"{path}: {type(exc).__name__} after {_ATTEMPTS} "
                        f"attempts") from exc
                time.sleep(_BACKOFF * attempt)
                continue
            if resp.status_code in (502, 503, 504) and attempt < _ATTEMPTS:
                time.sleep(_BACKOFF * attempt)
                continue
            if resp.status_code >= 400:
                return None
            try:
                return resp.json()
            except ValueError:
                return None
        return None

    def product_ids(self, limit: int) -> list[int]:
        page = self.get("/library", page_size=min(limit, 100), page=1) or {}
        rows = page.get("results") or []
        return [r["primary_product_id"] for r in rows
                if r.get("primary_product_id")][:limit]

    def walk_product_ids(self, page_size: int = 100):
        """Every product in the organisation's library, a page at a time."""
        page_number = 1
        while True:
            page = self.get("/library", page_size=page_size, page=page_number)
            if not isinstance(page, dict):
                return
            rows = page.get("results") or []
            if not rows:
                return
            for row in rows:
                if row.get("primary_product_id"):
                    yield row["primary_product_id"]
            if page_number >= (page.get("total_pages") or 1):
                return
            page_number += 1

    def product(self, product_id: int) -> dict:
        return self.get(f"/products/{product_id}") or {}

    def ingredients(self, product_id: int) -> list[Ingredient]:
        mixtures = self.get(f"/products/{product_id}/ingredients")
        if not isinstance(mixtures, list):
            return []
        out: list[Ingredient] = []
        for mixture in mixtures:
            for component in mixture.get("components") or []:
                codes = component.get("chemical_hazard_code") or ""
                out.append(Ingredient(
                    cas=(component.get("cas_no") or "").strip() or None,
                    name=component.get("chemical_name"),
                    h_codes=[c.strip() for c in codes.split(",") if c.strip()],
                    concentration=component.get("concentration"),
                ))
        return out

    def substance_source(self, cas: str) -> str | None:
        """What the app says the substance record came from. Metadata only."""
        body = self.get(f"/compound/{cas}")
        return (body or {}).get("source") if isinstance(body, dict) else None

    def close(self) -> None:
        self.client.close()
