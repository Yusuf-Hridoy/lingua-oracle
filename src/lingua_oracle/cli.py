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
