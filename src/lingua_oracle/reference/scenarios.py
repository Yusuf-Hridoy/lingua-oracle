"""The scenario matrix (data/scenarios.yaml): what Lingua can and cannot
judge, and which scenarios a checked document falls under."""

from __future__ import annotations

import re
from functools import lru_cache

import yaml

from lingua_oracle.registry import data_dir


@lru_cache(maxsize=1)
def load() -> list[dict]:
    path = data_dir() / "scenarios.yaml"
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")).get("scenarios", [])


def hit(report) -> list[str]:
    """The scenarios this report's document falls under, read from what the
    checks found - never from the file name."""
    out: list[str] = []
    if report.unreadable:
        return ["scanned"]
    if getattr(report, "products", 0) > 1:
        out.append("several_products")
    found = set(report.sections_found or [])
    if "label" in found and not found & {"1", "3", "9", "16"}:
        out.append("label_only")
    if "+" in (report.language or "") and report.regulation == "ca_whmis":
        out.append("bilingual_canadian")
    if report.regulation == "eu_clp" and report.language and report.language != "en":
        out.append("eu_languages")
    held = report.hcodes
    codes = set(held.printed if held else [])
    rows = held.ingredients if held else []
    if report.composition == "substance":
        entry = report.substance
        on_list = bool(entry and getattr(entry, "state", "") not in ("no_entry", "no_list", "no_cas"))
        out.append("substance_on_list" if on_list else "substance_not_on_list")
    elif rows:
        shares = [r.get("concentration") or "" for r in rows]
        if any(re.search(r"\d\s*(?:-|–|to)\s*\d|[<>≤≥]", s) for s in shares):
            out.append("mixture_ranges")
        if any(s and not re.search(r"\d\s*(?:-|–|to)\s*\d|[<>≤≥]", s) for s in shares):
            out.append("mixture_exact_percent")
        if not any(shares):
            out.append("mixture_no_percent")
    if held and any(r.get("identified") for r in rows):
        out.append("substance_no_cas")
    if held and any("withheld" in a for a in held.assumptions):
        out.append("mixture_withheld")
    if held and any("(a mixture)" in (r["a"].get("source") or "") for r in rows):
        out.append("mixture_in_mixture")
    product = (held.product if held else {}) or {}
    if product.get("aerosol"):
        out.append("aerosol")
    if product.get("gas") or report.physical_state == "gas":
        out.append("gas_mixture")
    if report.physical_state == "solid":
        out.append("solid_powder")
    if held and held.state == "judged" and not any(re.fullmatch(r"H\d{3}\w*", c) for c in codes):
        out.append("not_classified")
    for code, scenario in (("EUH208", "euh208"), ("EUH210", "euh210"), ("EUH066", "euh066"),
                           ("EUH071", "euh071"), ("EUH401", "euh401"), ("H304", "aspiration_h304")):
        if code in codes or any(r["code"] == code for r in (held.rows if held else [])):
            out.append(scenario)
    if held and (held.section9 or {}).get("ph", {}).get("value") is not None:
        value = held.section9["ph"]["value"]
        if value <= 2 or value >= 11.5:
            out.append("extreme_ph")
    if any(c.startswith(("H340", "H341", "H350", "H351", "H360", "H361", "H362")) for c in codes):
        out.append("cmr_edges")
    if any(c in codes for c in ("H300", "H301", "H302", "H310", "H311", "H312", "H330", "H331",
                                "H332")):
        out.append("acute_routes")
    if held and any(r["b"].get("binding") for r in rows):
        out.append("annex_vi_limits")
    if held and any("Annex VI entry carries" in r["reason"] for r in held.rows):
        out.append("annex_vi_notes")
    return list(dict.fromkeys(out))
