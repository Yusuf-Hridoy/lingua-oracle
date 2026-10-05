"""The ingredient report: the same shape as the wording report.

A verdict line, the counts beside it, one card per thing to fix with what the
app says against what Annex VI requires, then the rest collapsed. Product and
compound names appear here and nowhere else - the report is written under
reports/, which is not committed.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lingua_oracle.ingredients.compare import Status, Verdict
from lingua_oracle.report.render import report_css


@dataclass
class _SubstanceLabel:
    """Gives a substance the two fields the card template reads off a product."""

    substance: SubstanceResult

    @property
    def name(self) -> str | None:
        return self.substance.name

    @property
    def where(self) -> str:
        count = self.substance.product_count
        return f"in {count} product{'' if count == 1 else 's'}"

    @property
    def product_id(self) -> str:
        return self.substance.cas


@dataclass
class ProductResult:
    product_id: int
    name: str | None
    regulation: str | None
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def where(self) -> str:
        return f"product {self.product_id}"


@dataclass
class SubstanceResult:
    """One substance checked once, however many products contain it.

    Checking per product counts the same discrepancy as many times as the
    substance is used, which says more about the library than about the data.
    """

    cas: str
    name: str | None
    verdict: Verdict
    product_count: int = 0


@dataclass
class Run:
    started_at: datetime
    annex_vi_source: str
    products: list[ProductResult] = field(default_factory=list)
    substances: list[SubstanceResult] = field(default_factory=list)
    #: How many products were read to find the substances. Only set when the
    #: run was by substance.
    products_scanned: int = 0

    @property
    def by_substance(self) -> bool:
        return bool(self.substances)

    @property
    def all_verdicts(self) -> list[Verdict]:
        if self.substances:
            return [s.verdict for s in self.substances]
        return [v for p in self.products for v in p.verdicts]

    def counts(self) -> dict[str, int]:
        verdicts = self.all_verdicts
        return {
            "products": self.products_scanned or len(self.products),
            "substances": len(self.substances),
            "ingredients": len(verdicts),
            "with_entry": sum(1 for v in verdicts if v.entry_index_no
                              and v.status is not Status.NOT_CHECKED),
            "fix": sum(1 for v in verdicts if v.status is Status.FIX),
            "info": sum(1 for v in verdicts if v.status is Status.INFO),
            "ok": sum(1 for v in verdicts if v.status is Status.OK),
            "not_checked": sum(1 for v in verdicts
                               if v.status is Status.NOT_CHECKED),
        }

    def reasons(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for verdict in self.all_verdicts:
            if verdict.reason:
                out[verdict.reason.value] = out.get(verdict.reason.value, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def missing_patterns(self) -> list[tuple[str, int]]:
        """The codes most often absent where Annex VI has them."""
        counts: dict[str, int] = {}
        for verdict in self.all_verdicts:
            for code in verdict.missing_codes:
                counts[code] = counts.get(code, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def reach(self) -> list[tuple[str, int]]:
        """How many products each under-classified substance appears in."""
        return sorted(
            ((s.cas, s.product_count) for s in self.substances
             if s.verdict.status is Status.FIX),
            key=lambda kv: (-kv[1], kv[0]))

    def sources(self) -> dict[str, int]:
        """Where the app says each substance record came from. Metadata only."""
        out: dict[str, int] = {}
        for verdict in self.all_verdicts:
            key = verdict.data_source or "not stated"
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items()))


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def headline(counts: dict[str, int]) -> tuple[str, str, str]:
    """(release word, tone, the sentence under it)."""
    if counts["fix"]:
        return ("Fix before release", "fix",
                f"{_plural(counts['fix'], 'ingredient')} "
                f"{'is' if counts['fix'] == 1 else 'are'} classified below what "
                "Annex VI requires.")
    if counts["with_entry"] == 0:
        return ("Nothing to compare", "check",
                "No ingredient had a harmonised entry in Annex VI Table 3, so "
                "there was nothing to check against.")
    return ("Matches Annex VI", "ok",
            f"Every ingredient with a harmonised entry carries what Annex VI "
            f"requires ({_plural(counts['with_entry'], 'ingredient')} checked).")


def write_json(run: Run, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": run.started_at.isoformat(),
        "annex_vi_source": run.annex_vi_source,
        "counts": run.counts(),
        "not_checked_reasons": run.reasons(),
        "missing_code_patterns": run.missing_patterns(),
        "data_sources": run.sources(),
        "substances": [
            {
                "cas": s.cas,
                "name": s.name,
                "product_count": s.product_count,
                "status": s.verdict.status.value,
                "reason": s.verdict.reason.value if s.verdict.reason else None,
                "entry_index_no": s.verdict.entry_index_no,
                "missing_codes": s.verdict.missing_codes,
                "source_ref": s.verdict.source_ref,
                "data_source": s.verdict.data_source,
            }
            for s in run.substances
        ],
        "under_classified_reach": run.reach(),
        "products": [
            {
                "product_id": p.product_id,
                "name": p.name,
                "regulation": p.regulation,
                "ingredients": [
                    {**asdict(v), "status": v.status.value,
                     "reason": v.reason.value if v.reason else None,
                     "findings": [{**asdict(f), "status": f.status.value}
                                  for f in v.findings]}
                    for v in p.verdicts
                ],
            }
            for p in run.products
        ],
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False,
                               default=str) + "\n", encoding="utf-8")
    return path


def _e(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


def render_html(run: Run) -> str:
    counts = run.counts()
    release, tone, detail = headline(counts)
    fixes = [(p, v) for p in run.products for v in p.verdicts
             if v.status is Status.FIX]
    rest = [(p, v) for p in run.products for v in p.verdicts
            if v.status in (Status.OK, Status.INFO)]
    unchecked = [(p, v) for p in run.products for v in p.verdicts
                 if v.status is Status.NOT_CHECKED]

    if run.by_substance:
        fixes = [(_SubstanceLabel(s), s.verdict) for s in run.substances
                 if s.verdict.status is Status.FIX]
        rest = [(_SubstanceLabel(s), s.verdict) for s in run.substances
                if s.verdict.status in (Status.OK, Status.INFO)]
        unchecked = [(_SubstanceLabel(s), s.verdict) for s in run.substances
                     if s.verdict.status is Status.NOT_CHECKED]

    cards = []
    for product, verdict in fixes:
        rows = "".join(
            f"<tr><td class='code'>{_e(f.required or f.code or '')}</td>"
            f"<td>{_e(f.message)}</td></tr>"
            for f in verdict.findings if f.status is Status.FIX)
        cards.append(f"""
  <article class="issue" data-status="fix">
    <header>
      <span class="pill fix"><span aria-hidden="true">✕</span> Fix this</span>
      <span class="code">{_e(verdict.cas)}</span>
      <span class="where">{_e(product.name)} &middot; {_e(product.where)}</span>
    </header>
    <div class="body">
      <div class="side">
        <h3>The app says</h3>
        <div class="txt">{_e(', '.join(sorted(set(_stated(verdict))))
                             or '(no extra codes recorded)')}</div>
      </div>
      <div class="side official">
        <header><h3>Annex VI requires</h3></header>
        <div class="txt">{_e(', '.join(verdict.missing_codes))} (missing)</div>
      </div>
    </div>
    <table class="minor-table">{rows}</table>
    <footer>
      <span class="src">Source: {_e(verdict.source_ref)}</span>
    </footer>
  </article>""")

    def listing(pairs, title):
        if not pairs:
            return ""
        items = "".join(
            f"<li><span class='code'>{_e(v.cas)}</span><span>{_e(p.name)} - "
            f"{_e(v.findings[0].message if v.findings else 'Matches Annex VI.')}"
            f"</span></li>" for p, v in pairs)
        return (f"<details class='block'><summary>{len(pairs)} {title}</summary>"
                f"<div class='inner'><ul class='statements'>{items}</ul></div>"
                f"</details>")

    tech = "".join(
        f"<dt>{_e(k)}</dt><dd>{_e(v)}</dd>" for k, v in (
            ("Annex VI source", run.annex_vi_source),
            ("Run at", run.started_at.isoformat(timespec="seconds")),
            ("Products read", counts["products"]),
            ("Distinct substances checked", counts["substances"] or "-"),
            ("Ingredients checked", counts["ingredients"]),
            ("Substance data sources (as the app reports them)",
             ", ".join(f"{k}: {v}" for k, v in run.sources().items())),
            ("Not checked, by reason",
             ", ".join(f"{k}: {v}" for k, v in run.reasons().items()) or "none"),
        ))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ingredient check</title>
<style>{report_css(20000)}</style></head><body>
<div class="wrap page">
  <div class="report-head"><div><h1>Ingredient check</h1>
    <div class="meta"><span>against CLP Annex VI Table 3</span>
      <span>{_e(run.annex_vi_source)}</span></div></div></div>

  <div class="verdict v-{tone}">
    <div class="banner"><span class="vico" aria-hidden="true">
      {'✕' if tone == 'fix' else '✓' if tone == 'ok' else '!'}</span>
      <div><h2>{_e(release)}</h2><p>{_e(detail)}</p></div></div>
    <div class="stats">
      <div><div class="n fix">{counts['fix']}</div><div class="l">Fix this</div></div>
      <div><div class="n ok">{counts['ok']}</div><div class="l">Matches Annex VI</div></div>
      <div><div class="n">{counts['info']}</div><div class="l">Extra classes</div></div>
      <div><div class="n">{counts['not_checked']}</div><div class="l">Not checked</div></div>
      <div><div class="n">{counts['products']}</div><div class="l">Products</div></div>
    </div>
  </div>
  {"".join(cards)}
  {listing(rest, "ingredients match Annex VI, or add classes it does not cover")}
  {listing(unchecked, "ingredients were not checked")}
  <details class="block"><summary>Technical details</summary>
    <div class="inner"><dl class="tech">{tech}</dl></div></details>
</div></body></html>
"""


def _stated(verdict: Verdict) -> list[str]:
    """The codes the app had, recovered from the findings for display."""
    for finding in verdict.findings:
        if finding.stated:
            return [c.strip() for c in finding.stated.split(",")]
    return []


def save(run: Run, directory: Path | None = None) -> tuple[Path, Path]:
    target = directory or Path("reports") / "ingredients"
    target.mkdir(parents=True, exist_ok=True)
    stamp = run.started_at.strftime("%Y%m%d-%H%M%S")
    json_path = write_json(run, target / f"{stamp}.json")
    html_path = target / f"{stamp}.html"
    html_path.write_text(render_html(run), encoding="utf-8")
    return json_path, html_path


def new_run(annex_vi_source: str) -> Run:
    return Run(started_at=datetime.now(UTC), annex_vi_source=annex_vi_source)
