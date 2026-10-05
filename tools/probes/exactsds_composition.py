#!/usr/bin/env python3
"""Phase 0b discovery probe: what the ExactSDS API holds for Section 3.

NOT part of the checker. Nothing in `src/` imports this, no test runs it, and
it must never be wired into the check path - Lingua Oracle does not touch the
network at check time. It exists so the Phase 0b findings in
`docs/classification/phase0_extraction.md` can be reproduced.

Read-only by construction. The only request that is not a GET is the login
that exchanges the credentials in `.env` for a session token; every call that
reads product data is a GET. It never creates, edits, publishes, generates or
deletes anything.

Credentials come from `.env` (EXACTSDS_URL, EXACTSDS_USER, EXACTSDS_PASSWORD)
and are never printed. Product names are never printed either: the report
identifies products by reference only, because this repo holds no customer or
product data.

Usage:
    uv run python tools/probes/exactsds_composition.py            # summary
    uv run python tools/probes/exactsds_composition.py --json     # raw shapes
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

TIMEOUT = 60.0


def read_env(path: str = ".env") -> dict[str, str]:
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


class Api:
    """A thin GET-only client. The single POST is the login."""

    def __init__(self, env: dict[str, str]) -> None:
        root = env["EXACTSDS_URL"].rstrip("/")
        if root.endswith("/dashboard"):
            root = root.rsplit("/", 1)[0]
        self.base = f"{root}/api/v1"
        self.client = httpx.Client(timeout=TIMEOUT, follow_redirects=True)
        self.user = env["EXACTSDS_USER"]
        self.password = env["EXACTSDS_PASSWORD"]
        self.token: str | None = None

    def login(self) -> None:
        resp = self.client.post(
            f"{self.base}/users/login",
            json={"email": self.user, "password": self.password},
        )
        resp.raise_for_status()
        body = resp.json()
        token = (body.get("access_token") or body.get("token")
                 or (body.get("tokens") or {}).get("access_token")
                 or (body.get("data") or {}).get("access_token"))
        if not token:
            raise SystemExit(f"no token in login response: {sorted(body)}")
        self.token = token
        self.client.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, **params: Any) -> Any:
        resp = self.client.get(f"{self.base}{path}", params=params or None)
        if resp.status_code >= 400:
            return {"_status": resp.status_code, "_body": resp.text[:200]}
        try:
            return resp.json()
        except ValueError:
            return {"_status": resp.status_code, "_text": resp.text[:200]}


def as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="*", type=int,
                        help="product ids to inspect (default: sample the library)")
    parser.add_argument("--sample", type=int, default=60,
                        help="how many library products to sample for field shapes")
    parser.add_argument("--json", action="store_true", help="print the raw records")
    args = parser.parse_args()

    api = Api(read_env())
    api.login()

    ids = args.ids
    if not ids:
        page = api.get("/library", page_size=min(args.sample, 100), page=1)
        rows = page.get("results") or []
        print(f"library: {page.get('count')} products, sampling {len(rows)}")
        ids = [r["primary_product_id"] for r in rows if r.get("primary_product_id")]

    component_fields: Counter[str] = Counter()
    mixture_fields: Counter[str] = Counter()
    per_product: Counter[int] = Counter()
    totals: Counter[str] = Counter()
    records = []

    for pid in ids[: args.sample]:
        product = api.get(f"/products/{pid}")
        mixtures = api.get(f"/products/{pid}/ingredients")
        if not isinstance(mixtures, list):
            continue
        components = []
        for mixture in mixtures:
            mixture_fields.update(mixture.keys())
            components += mixture.get("components") or []
        for component in components:
            component_fields.update(component.keys())
        declared = sum((as_decimal(c.get("concentration")) or Decimal(0))
                       for c in components)
        per_product[len(components)] += 1
        totals[str(declared)] += 1
        records.append({
            "id": pid,
            "regulation": product.get("regulation"),
            "language": product.get("language"),
            "is_hazardous": product.get("is_hazardous"),
            "mixtures": len(mixtures),
            "components": len(components),
            "declared_total": str(declared),
            # Identifiers and hazard codes only. Names are company data and are
            # never printed by this probe.
            "component_shapes": [
                {"cas_no": c.get("cas_no"),
                 "concentration": c.get("concentration"),
                 "pdf_percentage": c.get("pdf_percentage"),
                 "hazard_codes": c.get("chemical_hazard_code"),
                 "proprietary": c.get("is_proprietary_blend")}
                for c in components],
        })
        if args.ids:
            print(f"  {pid}: reg={product.get('regulation')} "
                  f"components={len(components)} total={declared}")

    print()
    print("components per product:", dict(per_product))
    print("declared totals:", dict(totals.most_common(8)))
    print("mixture-level fields:", dict(mixture_fields))
    print("component fields:", dict(component_fields))
    missing = [f for f in ("ec_no", "hazard_class", "category", "scl", "m_factor", "ate")
               if f not in component_fields]
    print("absent from every component record:", missing)

    if args.json:
        print(json.dumps(records, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
