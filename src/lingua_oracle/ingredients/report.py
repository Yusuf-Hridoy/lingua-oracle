"""The ingredient report: the same shape as the wording report.

A verdict line, the counts beside it, one card per thing to fix with what the
app says against what Annex VI requires, then the rest collapsed. Product and
compound names appear here and nowhere else - the report is written under
reports/, which is not committed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lingua_oracle.ingredients.compare import Status, Verdict
from lingua_oracle.report.render import report_css


@dataclass
class Use:
    """One substance in one product, with the codes that product gave it."""

    product_id: int
    codes: tuple[str, ...]
    verdict: Verdict


@dataclass
class SubstanceResult:
    """One substance, and every product use of it, checked separately.

    Taking the union of a substance's codes across products was wrong: a code
    present in one product out of forty made the substance look classified in
    all forty. Each use is checked on its own and the results are grouped here,
    so a code missing in most products is still missing in most products.
    """

    cas: str
    name: str | None
    uses: list[Use] = field(default_factory=list)

    @property
    def product_count(self) -> int:
        return len(self.uses)

    @property
    def under_classified_uses(self) -> int:
        return sum(1 for u in self.uses if u.verdict.status is Status.FIX)

    @property
    def missing_code_counts(self) -> dict[str, int]:
        """{code: how many uses of this substance were missing it}."""
        out: dict[str, int] = {}
        for use in self.uses:
            for code in use.verdict.missing_codes:
                out[code] = out.get(code, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    @property
    def code_sets(self) -> int:
        """How many different sets of H codes the products give this substance."""
        return len({u.codes for u in self.uses})

    @property
    def inconsistent(self) -> bool:
        """The same substance classified differently in different products.

        A finding in its own right, whatever Annex VI says: one of the sets is
        wrong, or they describe different things under one CAS number.
        """
        return self.code_sets > 1

    def code_sets_detail(self) -> list[dict]:
        """Each distinct set of codes, the products that use it, and its verdict.

        What a reader needs to act: which products say what, and which of those
        sets falls below Annex VI.
        """
        grouped: dict[tuple[str, ...], list[int]] = {}
        verdicts: dict[tuple[str, ...], Verdict] = {}
        for use in self.uses:
            grouped.setdefault(use.codes, []).append(use.product_id)
            verdicts.setdefault(use.codes, use.verdict)
        out = []
        for codes, products in sorted(grouped.items(),
                                      key=lambda kv: (-len(kv[1]), kv[0])):
            verdict = verdicts[codes]
            out.append({
                "codes": list(codes),
                "products": sorted(products),
                "count": len(products),
                "missing": verdict.missing_codes,
                "status": verdict.status.value,
            })
        return out

    @property
    def affected_products(self) -> list[int]:
        """Every product whose use of this substance is under-classified."""
        return sorted(u.product_id for u in self.uses
                      if u.verdict.status is Status.FIX)

    @property
    def verdict(self) -> Verdict:
        """The worst verdict among the uses - what the substance needs."""
        order = (Status.FIX, Status.INFO, Status.OK, Status.NOT_CHECKED)
        for status in order:
            for use in self.uses:
                if use.verdict.status is status:
                    return use.verdict
        raise ValueError(f"{self.cas} has no uses")

    @property
    def status(self) -> Status:
        return self.verdict.status


@dataclass
class Run:
    started_at: datetime
    annex_vi_source: str
    substances: list[SubstanceResult] = field(default_factory=list)
    #: How many products were read. Separate from the substance count, because
    #: "one substance to fix" and "forty products to reissue" are different
    #: facts and a reader needs both.
    products_scanned: int = 0
    #: What this run is called - "Whole library" or "Product: <name>".
    label: str = ""

    @property
    def all_verdicts(self) -> list[Verdict]:
        return [s.verdict for s in self.substances]

    @property
    def uses(self) -> list[Use]:
        return [u for s in self.substances for u in s.uses]

    def counts(self) -> dict[str, int]:
        verdicts = self.all_verdicts
        return {
            "products": self.products_scanned,
            "substances": len(self.substances),
            "ingredients": len(verdicts),
            "with_entry": sum(1 for v in verdicts if v.entry_index_no
                              and v.status is not Status.NOT_CHECKED),
            "fix": sum(1 for v in verdicts if v.status is Status.FIX),
            "info": sum(1 for v in verdicts if v.status is Status.INFO),
            "ok": sum(1 for v in verdicts if v.status is Status.OK),
            "not_checked": sum(1 for v in verdicts
                               if v.status is Status.NOT_CHECKED),
            # Uses, not substances: one substance can be wrong in forty products
            # and right in one, and both numbers matter.
            "uses": len(self.uses),
            "uses_under_classified": sum(
                s.under_classified_uses for s in self.substances),
            "inconsistent_substances": sum(
                1 for s in self.substances if s.inconsistent),
        }

    def reasons(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for verdict in self.all_verdicts:
            if verdict.reason:
                out[verdict.reason.value] = out.get(verdict.reason.value, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def missing_patterns(self) -> list[tuple[str, int]]:
        """The codes most often absent, counted by product use."""
        counts: dict[str, int] = {}
        for substance in self.substances:
            for code, number in substance.missing_code_counts.items():
                counts[code] = counts.get(code, 0) + number
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def missing_by_substance(self) -> list[tuple[str, int]]:
        """The codes most often absent, counted by substance.

        A code missing from one substance used in four hundred products is one
        thing to fix; a code missing from forty substances is forty. Both
        orderings are reported, because neither answers the other's question.
        """
        counts: dict[str, int] = {}
        for substance in self.substances:
            for code in substance.missing_code_counts:
                counts[code] = counts.get(code, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def reach(self) -> list[tuple[str, int]]:
        """How many products each under-classified substance appears in."""
        return sorted(
            ((s.cas, s.under_classified_uses) for s in self.substances
             if s.under_classified_uses),
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
    if not counts.get("substances") and not counts.get("ingredients"):
        # A run that looked at nothing has nothing to say. "Fix before release"
        # over an empty run reads as a verdict on the product.
        return ("Nothing to check", "check",
                "No ingredient was read, so nothing was compared with Annex VI.")
    if counts["fix"]:
        uses = counts.get("uses_under_classified", 0)
        where = (f", in {_plural(uses, 'product use')}"
                 if uses and uses != counts["fix"] else "")
        return ("Fix before release", "fix",
                f"{_plural(counts['fix'], 'substance')} "
                f"{'is' if counts['fix'] == 1 else 'are'} classified below what "
                f"Annex VI requires{where}.")
    if counts["with_entry"] == 0:
        return ("Nothing to compare", "check",
                "No substance had a harmonised entry in Annex VI Table 3, so "
                "there was nothing to check against.")
    return ("Matches Annex VI", "ok",
            f"Every substance with a harmonised entry carries what Annex VI "
            f"requires ({_plural(counts['with_entry'], 'substance')} checked).")


def substance_payload(run: Run) -> list[dict]:
    """The substances in the shape the report template renders."""
    return _payload(run)["substances"]


def _payload(run: Run) -> dict:
    return {
        "started_at": run.started_at.isoformat(),
        "label": run.label,
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
                "uses_checked": s.product_count,
                "uses_under_classified": s.under_classified_uses,
                "missing_code_counts": s.missing_code_counts,
                "distinct_code_sets": s.code_sets,
                "code_sets": s.code_sets_detail(),
                "affected_products": s.affected_products,
                "inconsistent": s.inconsistent,
                "harmonised_codes": s.verdict.required_codes,
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
        "missing_code_by_substance": run.missing_by_substance(),
    }


def write_json(run: Run, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_payload(run), indent=1, ensure_ascii=False,
                               default=str) + "\n", encoding="utf-8")
    return path


#: Why a substance could not be checked, in words rather than enum names.
REASONS = {
    "no_harmonised_entry": "no harmonised entry in Annex VI Table 3",
    "ingredient_has_no_cas": "no CAS number, so Table 3 cannot be searched",
    "several_harmonised_entries": "the CAS number appears in more than one entry",
    "entry_covers_several_substances": "the entry covers several substances at once",
}


def render_html(run: Run | dict, *, nav: bool = False) -> str:
    """The run as a page. `nav` adds the application's navigation bar.

    Takes either a live Run or the JSON a saved run was written as, so the page
    served from History renders from the file and nothing is recomputed.
    """
    from jinja2 import Environment, FileSystemLoader
    from markupsafe import Markup

    from lingua_oracle.report.render import TEMPLATES

    payload = run if isinstance(run, dict) else json.loads(
        json.dumps(_payload(run), default=str))
    counts = payload["counts"]
    release, tone, detail = headline(counts)
    icon = {"fix": "\u2715", "ok": "\u2713"}.get(tone, "!")
    substances = payload.get("substances") or []

    under = [s for s in substances if s["uses_under_classified"]]
    inconsistent = [s for s in substances
                    if s["inconsistent"] and not s["uses_under_classified"]]
    matches = [s for s in substances
               if s["status"] == "ok" and not s["uses_under_classified"]]
    extra = [s for s in substances
             if s["status"] == "info" and not s["uses_under_classified"]]
    unchecked = [s for s in substances if s["status"] == "not_checked"]

    # Autoescaping on, deliberately: every name on this page comes from an
    # external system, and `select_autoescape(["html"])` does not fire on a
    # ".j2" suffix. The stylesheet is the one value that must not be escaped.
    environment = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                              autoescape=True)
    template = environment.get_template("ingredients.html.j2")
    return template.render(
        run=payload, counts=counts, release=release, tone=tone, detail=detail,
        icon=icon, under=under, inconsistent=inconsistent, matches=matches,
        extra=extra, unchecked=unchecked, reasons=REASONS, nav=nav,
        app_css=Markup(report_css(40000)),
    )


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
