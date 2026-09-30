"""Typer command line for Lingua Oracle."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from lingua_oracle.detect.regulation import RegulationUndetermined

app = typer.Typer(
    add_completion=False,
    help="Check SDS and label PDFs against official regulatory wording.",
    no_args_is_help=True,
)
keys_app = typer.Typer(help="Build and inspect answer keys.", no_args_is_help=True)
app.add_typer(keys_app, name="keys")
validate_app = typer.Typer(
    help="Validate the checker against real documents (kept out of the repo).",
    no_args_is_help=False,
    invoke_without_command=True,
)
app.add_typer(validate_app, name="validate")

RegOpt = Annotated[str | None, typer.Option("--regulation", "-r", help="Regulation id.")]
LangOpt = Annotated[str | None, typer.Option("--language", "-l", help="BCP-47 language tag.")]
OutOpt = Annotated[Path | None, typer.Option("--out", "-o", help="Directory for reports.")]


def _echo_summary(report, html_path: Path) -> None:
    s = report.summary
    colour = typer.colors.RED if s.fail else (typer.colors.YELLOW if s.warn else typer.colors.GREEN)
    typer.secho(
        f"{report.file_name}: {s.fail} fail, {s.warn} warn, {s.info} info, "
        f"{s.unverified} unverified  "
        f"[{report.regulation} / {report.language}, coverage {report.coverage.percent}%]",
        fg=colour,
    )
    for finding in report.findings:
        if finding.severity != "fail" or finding.unverified:
            continue
        typer.echo(f"  {finding.check_id} {finding.code or ''}: {finding.message}")
    typer.echo(f"  report: {html_path}")


@app.command()
def check(
    pdf: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    regulation: RegOpt = None,
    language: LangOpt = None,
    out: OutOpt = None,
    backend: Annotated[str | None, typer.Option("--backend", help="pymupdf|pdfplumber")] = None,
) -> None:
    """Check one PDF."""
    from lingua_oracle.pipeline import check_pdf
    from lingua_oracle.report.render import save

    try:
        report = check_pdf(str(pdf), regulation, language, backend=backend)
    except RegulationUndetermined as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None
    _json, html_path = save(report, out)
    _echo_summary(report, html_path)
    raise typer.Exit(code=1 if report.summary.fail else 0)


@app.command("check-folder")
def check_folder(
    directory: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    regulation: RegOpt = None,
    language: LangOpt = None,
    out: OutOpt = None,
) -> None:
    """Check every PDF in a folder (drop-folder mode)."""
    from lingua_oracle.pipeline import check_pdf
    from lingua_oracle.report.render import save

    pdfs = sorted(directory.glob("*.pdf"))
    if not pdfs:
        typer.secho(f"No PDFs in {directory}", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    failed = 0
    for pdf in pdfs:
        try:
            report = check_pdf(str(pdf), regulation, language)
        except RegulationUndetermined as exc:
            typer.secho(f"{pdf.name}: {exc}", fg=typer.colors.RED, err=True)
            failed += 1
            continue
        _json, html_path = save(report, out)
        _echo_summary(report, html_path)
        failed += 1 if report.summary.fail else 0
    typer.echo(f"\n{len(pdfs)} file(s) checked, {failed} with failures.")
    raise typer.Exit(code=1 if failed else 0)


@app.command()
def compare(
    pdf_a: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    pdf_b: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    regulation: RegOpt = None,
    language: LangOpt = None,
    out: OutOpt = None,
) -> None:
    """Compare two PDFs (runs B-11 on top of the usual checks)."""
    from lingua_oracle.pipeline import compare_pdfs
    from lingua_oracle.report.render import save

    report = compare_pdfs(str(pdf_a), str(pdf_b), regulation, language)
    _json, html_path = save(report, out)
    _echo_summary(report, html_path)
    raise typer.Exit(code=1 if report.summary.fail else 0)


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Run the upload page and API."""
    import uvicorn

    uvicorn.run("lingua_oracle.api.app:app", host=host, port=port, reload=reload)


# --------------------------------------------------------------------------
# keys
# --------------------------------------------------------------------------


@keys_app.command("build")
def keys_build(
    regulation: Annotated[str, typer.Argument(help="A regulation id, or 'all'.")],
    languages: Annotated[str | None, typer.Option("--languages", help="Comma-separated.")] = None,
    from_file: Annotated[Path | None, typer.Option(
        "--from-file", help="Local copy of the official source to parse.")] = None,
    sources: Annotated[Path | None, typer.Option(
        "--sources", help="Root of the source tree (default data/sources).")] = None,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Ignore the HTTP cache.")] = False,
) -> None:
    """Build answer keys from official sources.

    Builders read local files under data/sources/ where one is present; only
    EU CLP and the OSHA fallback reach the network.
    """
    from lingua_oracle.keys.builders import (
        au_whs,
        ca_whmis,
        eu_clp,
        pending,
        uk_clp,
        un_ghs,
        us_osha,
    )
    from lingua_oracle.keys.builders.common import SourceUnavailable, sanity_report
    from lingua_oracle.keys.store import keys_root, save_key
    from lingua_oracle.registry import load_registry

    wanted = load_registry().ids() if regulation == "all" else [regulation]
    langs = [x.strip() for x in languages.split(",")] if languages else None
    file_arg = str(from_file) if from_file else None
    root_arg = sources

    for reg_id in wanted:
        typer.secho(f"\n=== {reg_id} ===", bold=True)
        reports = []
        try:
            if reg_id == "eu_clp":
                keys = eu_clp.build(langs, use_cache=not no_cache)
            elif reg_id == "us_osha":
                keys, reports = us_osha.build(
                    use_cache=not no_cache, from_file=file_arg, sources_root=root_arg
                )
            elif reg_id == "un_ghs":
                keys, reports = un_ghs.build(langs, from_file=file_arg, sources_root=root_arg)
            elif reg_id == "uk_clp":
                keys, reports = uk_clp.build(langs, from_file=file_arg, sources_root=root_arg)
            elif reg_id == "au_whs":
                keys, reports = au_whs.build(langs, from_file=file_arg, sources_root=root_arg)
            elif reg_id == "ca_whmis":
                keys, reports = ca_whmis.build(langs, from_file=file_arg, sources_root=root_arg)
            elif reg_id in pending.PENDING:
                keys, reports = pending.build(reg_id, langs)
                typer.secho(
                    f"  {pending.PENDING[reg_id].code}: {pending.reason(reg_id)}",
                    fg=typer.colors.YELLOW,
                )
            else:
                typer.secho(f"  no builder for {reg_id}", fg=typer.colors.RED)
                continue
        except SourceUnavailable as exc:
            typer.secho(f"  source unavailable: {exc}", fg=typer.colors.RED, err=True)
            typer.secho("  writing a pending_source key instead.", fg=typer.colors.YELLOW)
            if reg_id in pending.PENDING:
                keys, reports = pending.build(reg_id, langs)
            else:
                keys = []

        entries = []
        for key in keys:
            save_key(key)
            entries.extend(key.entries)
        typer.echo(f"  wrote {len(keys)} key file(s), {len(entries)} entries")

        if reports:
            rendered = "\n".join(r.render() for r in reports)
            typer.echo(rendered)
            target = keys_root() / reg_id
            target.mkdir(parents=True, exist_ok=True)
            (target / "_parse_issues.txt").write_text(rendered + "\n", encoding="utf-8")
            typer.secho(
                f"  parse issues written to {target / '_parse_issues.txt'}",
                fg=typer.colors.BLUE,
            )

        if entries:
            typer.echo(sanity_report(reg_id, entries))
        if reg_id == "us_osha" and us_osha.UNMAPPED.get("us_osha"):
            typer.secho(
                f"  note: {us_osha.UNMAPPED['us_osha']} OSHA statement(s) could not be keyed "
                "to a code, because Appendix C states no codes. Fill via import-csv.",
                fg=typer.colors.YELLOW,
            )


@keys_app.command("import-csv")
def keys_import_csv(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    regulation: Annotated[str, typer.Option("--regulation", "-r")],
    language: Annotated[str, typer.Option("--language", "-l")],
    tier: Annotated[str, typer.Option("--tier")] = "C",
    replace: Annotated[bool, typer.Option("--replace")] = False,
) -> None:
    """Import a company glossary into an answer key."""
    from lingua_oracle.keys.csv_import import import_csv
    from lingua_oracle.models import Tier

    key = import_csv(file, regulation, language, Tier(tier.upper()), replace=replace)
    typer.secho(
        f"{regulation}/{language}: {len(key.entries)} entries (tier {tier.upper()})",
        fg=typer.colors.GREEN,
    )


@keys_app.command("stats")
def keys_stats(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Show answer-key coverage per regulation and language."""
    from lingua_oracle.keys.store import available_languages, load_key
    from lingua_oracle.registry import load_registry

    registry = load_registry()
    rows = []
    for reg_id in registry.ids():
        reg = registry.get(reg_id)
        langs = available_languages(reg_id)
        populated, pending_langs, total = [], [], 0
        statuses: set[str] = set()
        reasons: set[str] = set()
        for lang in langs:
            key = load_key(reg_id, lang)
            if key is None:
                continue
            statuses.add(str(key.status))
            if key.status_reason:
                reasons.add(key.status_reason)
            if key.entries:
                populated.append(lang)
                total += len(key.entries)
            else:
                pending_langs.append(lang)
        rows.append(
            {
                "regulation": reg_id,
                "display_name": reg.display_name,
                "revision": reg.revision,
                "languages_populated": populated,
                "languages_pending": pending_langs,
                "entries": total,
                # Report what the keys actually say, rather than inferring "ok"
                # from a non-empty file: a `partial` key is populated but
                # knowingly incomplete.
                "status": (
                    "partial" if "partial" in statuses
                    else "ok" if populated
                    else "pending_source"
                ),
                "status_reasons": sorted(reasons),
            }
        )

    if as_json:
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    width = max(len(r["display_name"]) for r in rows)
    typer.secho(f"{'REGULATION'.ljust(width)}  {'LANGS':>5}  {'ENTRIES':>7}  STATUS", bold=True)
    for row in rows:
        colour = typer.colors.GREEN if row["status"] == "ok" else typer.colors.YELLOW
        langs = row["languages_populated"]
        detail = ", ".join(langs[:8]) + ("…" if len(langs) > 8 else "")
        typer.secho(
            f"{row['display_name'].ljust(width)}  {len(langs):>5}  {row['entries']:>7}  "
            f"{row['status']}"
            + (f"  [{detail}]" if detail else ""),
            fg=colour,
        )
        if row["languages_pending"]:
            typer.echo(
                f"{' ' * width}  pending: {', '.join(row['languages_pending'][:12])}"
            )
        if row["status_reasons"]:
            typer.echo(f"{' ' * width}  reason: {', '.join(row['status_reasons'])}")


def main() -> None:
    try:
        app()
    except KeyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------


@validate_app.callback(invoke_without_command=True)
def validate_main(ctx: typer.Context) -> None:
    """Run every validation case and write the summary."""
    if ctx.invoked_subcommand is not None:
        return
    from lingua_oracle.validate import run, validation_dir, validation_reports_dir
    from lingua_oracle.validate.diagnostics import write_extraction_report
    from lingua_oracle.validate.report import write

    try:
        summary = run()
    except FileNotFoundError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None

    out = validation_reports_dir()
    json_path, html_path = write(summary, out)

    typer.secho("\nTARGETS", bold=True)
    for t in summary.targets():
        if t["skipped"]:
            mark, colour = "n/a ", typer.colors.YELLOW
        else:
            mark, colour = ("PASS", typer.colors.GREEN) if t["passed"] else (
                "FAIL", typer.colors.RED)
        typer.secho(f"  [{mark}] {t['name']:<40} target {t['target']:<7} actual {t['actual']}",
                    fg=colour)

    if summary.unconfirmed:
        typer.secho(
            f"\n{len(summary.unconfirmed)} case(s) NOT SCORED - awaiting confirmation",
            fg=typer.colors.YELLOW, bold=True,
        )
        for r in summary.unconfirmed:
            typer.echo(f"    {r.case.file}")
        typer.secho(
            "    These were drafted by the tool. Check each against the authoring UI, "
            "then set confirmed: true in cases.yaml.",
            fg=typer.colors.YELLOW,
        )

    typer.secho("\nDOCUMENTS", bold=True)
    for r in summary.results:
        if r.unconfirmed:
            continue
        if r.error:
            typer.secho(f"  ERROR {r.case.file}: {r.error}", fg=typer.colors.RED)
            continue
        recall = "n/a" if r.recall is None else f"{r.recall * 100:.0f}%"
        c = r.counts
        colour = typer.colors.RED if (c["fail"] or r.defects_missed) else typer.colors.GREEN
        typer.secho(
            f"  {r.case.file:<40} recall {recall:>5}  "
            f"{c['fail']} fail  {c['warn']} warn  {c['unverified']} unverified",
            fg=colour,
        )
        if r.missed:
            typer.secho(f"      missed: {', '.join(sorted(r.missed))}", fg=typer.colors.YELLOW)
            written = write_extraction_report(
                validation_dir() / r.case.file,
                r.report.language if r.report else (r.case.language or "en"),
                out,
                r.missed,
            )
            typer.secho(f"      extraction diagnostic: {written}", fg=typer.colors.BLUE)

    counts = summary.triage_counts
    if counts:
        typer.echo("\ntriage: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    typer.echo(f"\nsummary: {html_path}")
    typer.echo(f"         {json_path}")
    raise typer.Exit(code=0 if summary.passed else 1)


@validate_app.command("init")
def validate_init() -> None:
    """Create the gitignored validation folder and copy the case template in."""
    import shutil
    import subprocess

    from lingua_oracle.validate import cases_path, template_path, validation_dir

    folder = validation_dir()
    folder.mkdir(parents=True, exist_ok=True)

    check = subprocess.run(
        ["git", "check-ignore", "-q", str(folder / "probe.pdf")],
        capture_output=True, check=False,
    )
    if check.returncode != 0:
        typer.secho(
            f"REFUSING to continue: {folder} is not gitignored. Real documents are "
            "company data. Add 'data/validation/' to .gitignore first.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2)

    target = cases_path()
    if target.exists():
        typer.secho(f"{target} already exists; leaving it alone.", fg=typer.colors.YELLOW)
    else:
        shutil.copy(template_path(), target)
        typer.secho(f"created {target}", fg=typer.colors.GREEN)
    typer.echo(f"  folder   : {folder}  (gitignored)")
    typer.echo("  next     : put your PDFs in that folder and fill in cases.yaml,")
    typer.echo("             then run `lingua validate`.")


@validate_app.command("triage")
def validate_triage(
    show_all: Annotated[bool, typer.Option("--all", help="Include classified findings.")] = False,
) -> None:
    """List findings awaiting classification."""
    from lingua_oracle.validate import CLASSES, run, triage_path

    try:
        summary = run()
    except FileNotFoundError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from None

    pending = [
        (r, f) for r in summary.results for f in r.findings
        if show_all or not f["classification"]
    ]
    if not pending:
        typer.secho("Nothing awaiting classification.", fg=typer.colors.GREEN)
        raise typer.Exit(code=0)

    typer.secho(f"{len(pending)} finding(s) to classify", bold=True)
    typer.echo(f"Classify each in {triage_path()} as one of: {', '.join(CLASSES)}\n")
    for r, f in pending:
        flag = " [known defect]" if f["known_defect"] else ""
        good = " [on a known_good document]" if r.case.known_good else ""
        typer.secho(f"  {f['id']}", bold=True)
        typer.echo(f"      {f['severity']} {f['check_id']} {f['code'] or ''}{flag}{good}")
        typer.echo(f"      {f['message'][:110]}")
        if f["classification"]:
            typer.echo(f"      classified: {f['classification']}")
    typer.echo("\nExample entry:\n")
    typer.echo("findings:")
    typer.echo(f"  - id: {pending[0][1]['id']}")
    typer.echo("    classification: false_alarm")
    typer.echo('    note: "why"')
    typer.echo("    fixed: false")


@keys_app.command("sample")
def keys_sample(
    n: Annotated[int, typer.Option("--n", help="How many entries to sample.")] = 20,
    regulation: Annotated[str | None, typer.Option("--regulation", "-r")] = None,
    seed: Annotated[int | None, typer.Option("--seed", help="Reproducible sample.")] = None,
) -> None:
    """Sample answer-key entries for a human spot check.

    Writes data/validation/spot_check.yaml with a blank verdict per entry; fill
    each in as `correct` or `wrong`, then re-run `lingua validate` to score it.
    """
    import random
    from datetime import UTC, datetime

    from lingua_oracle.keys.store import iter_all_keys
    from lingua_oracle.models import Status
    from lingua_oracle.validate import (
        SpotCheckEntry,
        SpotCheckFile,
        load_spot_check,
        save_spot_check,
        spot_check_path,
    )

    pool = [
        (key, entry)
        for key in iter_all_keys()
        if key.status in (Status.OK, Status.PARTIAL) and key.entries
        for entry in key.entries
        if regulation is None or key.regulation == regulation
    ]
    if not pool:
        typer.secho("No entries to sample.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    rng = random.Random(seed)
    chosen = rng.sample(pool, min(n, len(pool)))

    existing = {(e.regulation, e.language, e.code): e for e in load_spot_check().entries}
    entries = []
    for key, entry in chosen:
        previous = existing.get((key.regulation, key.language, entry.code))
        entries.append(
            SpotCheckEntry(
                regulation=key.regulation, language=key.language, code=entry.code,
                text=entry.text, source_ref=entry.source_ref or "",
                source_url=entry.source_url,
                verdict=previous.verdict if previous else "",
            )
        )

    save_spot_check(
        SpotCheckFile(sampled_at=datetime.now(UTC).isoformat(), entries=entries)
    )
    typer.secho(f"{len(entries)} entries sampled for review\n", bold=True)
    for i, e in enumerate(entries, start=1):
        typer.secho(f"{i:>3}. {e.regulation}/{e.language}  {e.code}", bold=True)
        typer.echo(f"     text      : {e.text}")
        typer.echo(f"     source_ref: {e.source_ref}")
        if e.source_url:
            typer.echo(f"     source_url: {e.source_url}")
        typer.echo("")
    typer.secho(
        f"Record a verdict (correct/wrong) for each in {spot_check_path()}",
        fg=typer.colors.BLUE,
    )
