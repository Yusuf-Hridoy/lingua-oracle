"""Reading ingredients from the ExactSDS app. The only networked part.

Separated deliberately. `compare.py` is pure and the check path never reaches
the network; this module is the one place that does, it is called only by the
`lingua ingredients` command, and it reads. Every request is a GET apart from
the login that turns the credentials in `.env` into a session token.

Credentials come from `.env` and are never written to a report.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

TIMEOUT = 60.0


def read_env(path: str | Path = ".env") -> dict[str, str]:
    out: dict[str, str] = {}
    source = Path(path)
    if not source.exists():
        return out
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
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
        resp = self.client.get(f"{self.base}{path}", params=params or None)
        if resp.status_code >= 400:
            return None
        try:
            return resp.json()
        except ValueError:
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
