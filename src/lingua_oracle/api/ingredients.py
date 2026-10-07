"""The ingredient check in the web application.

Read-only, like the command: GETs to the ExactSDS API with the login as the
only POST. Nothing is created, edited, published or generated.

A library-wide run reads thousands of products over many minutes, so it cannot
happen inside a request. It runs on a worker thread and the page polls for
progress; the finished run is saved beside the command's own runs and served
from there, so History shows both kinds.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from lingua_oracle.ingredients import report as ingredient_report


def runs_dir() -> Path:
    return Path("reports") / "ingredients"


@dataclass
class Progress:
    """What a running check has done so far. Read by the polling page."""

    id: str
    scope: str
    #: "Whole library" or "Product: <name>" - what the run is called in History.
    label: str = "Whole library"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    products_read: int = 0
    substances_found: int = 0
    state: str = "reading"          # reading | grouping | done | failed
    message: str = ""
    run_file: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id, "scope": self.scope, "state": self.state,
            "products_read": self.products_read,
            "substances_found": self.substances_found,
            "message": self.message, "run_file": self.run_file,
            "label": self.label,
            "started_at": self.started_at.isoformat(timespec="seconds"),
        }


#: Runs started in this process. A run that finished is on disk; this is only
#: what is needed to show progress while it is still going.
RUNS: dict[str, Progress] = {}
_LOCK = threading.Lock()


def start(scope: str, product_id: int | None = None,
          client_factory=None, label: str | None = None) -> Progress:
    """Begin a check on a worker thread and return its progress handle."""
    name = ("Whole library" if scope != "product"
            else f"Product: {label}" if label
            else f"Product {product_id}")
    progress = Progress(id=uuid.uuid4().hex[:12], scope=scope, label=name)
    with _LOCK:
        RUNS[progress.id] = progress
    thread = threading.Thread(
        target=_work, args=(progress, product_id, client_factory), daemon=True)
    thread.start()
    return progress


def _work(progress: Progress, product_id: int | None, client_factory) -> None:
    from lingua_oracle.ingredients.client import AppUnavailable, ExactSdsClient
    from lingua_oracle.ingredients.compare import check_ingredient_on
    from lingua_oracle.ingredients.report import SubstanceResult, Use
    from lingua_oracle.keys.builders.annex_vi import load_table
    from lingua_oracle.substances.upcoming import for_list

    try:
        table = load_table()
        if table is None:
            raise AppUnavailable(
                "No Annex VI table on file. Run `lingua keys build annex_vi`.")
        client = (client_factory or ExactSdsClient)()
        client.login()

        index = table.by_cas()
        run = ingredient_report.new_run(table.source)
        uses_for: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
        names_for: dict[str, str | None] = {}

        ids = ([product_id] if product_id is not None
               else client.walk_product_ids())
        for pid in ids:
            run.products_scanned += 1
            progress.products_read = run.products_scanned
            for row in client.ingredients(pid):
                cas = (row.cas or "").strip()
                if not cas:
                    continue
                uses_for.setdefault(cas, []).append(
                    (pid, tuple(sorted(set(row.h_codes)))))
                names_for.setdefault(cas, row.name)
            progress.substances_found = len(uses_for)

        progress.state = "grouping"
        sources: dict[str, str | None] = {}
        upcoming = for_list("annex_vi")
        for cas in sorted(uses_for):
            sources[cas] = client.substance_source(cas)
            verdicts = {
                codes: check_ingredient_on(cas, list(codes), table, index,
                                           upcoming=upcoming,
                                           data_source=sources[cas])
                for codes in {c for _pid, c in uses_for[cas]}
            }
            run.substances.append(SubstanceResult(
                cas=cas, name=names_for.get(cas),
                uses=[Use(product_id=pid, codes=codes, verdict=verdicts[codes])
                      for pid, codes in uses_for[cas]]))
        client.close()

        run.label = progress.label
        json_path, _html = ingredient_report.save(run, runs_dir())
        progress.run_file = json_path.stem
        progress.state = "done"
    except Exception as exc:  # noqa: BLE001 - shown to the user, not swallowed
        progress.state = "failed"
        progress.message = str(exc) or exc.__class__.__name__


def recent_runs(limit: int = 50) -> list[dict]:
    """Saved ingredient runs, newest first, for History."""
    out = []
    directory = runs_dir()
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        counts = data.get("counts", {})
        release, tone, _detail = ingredient_report.headline(counts)
        out.append({
            "id": path.stem,
            "file_name": data.get("label") or (
                f"{counts.get('substances', 0)} substances, "
                f"{counts.get('products', 0)} products"),
            "regulation": "CLP Annex VI Table 3",
            "language": "ingredient check",
            "release": release,
            "pill": tone,
            "created_at": data.get("started_at", ""),
            "kind": "ingredients",
        })
        if len(out) >= limit:
            break
    return out


def load_run(run_id: str) -> dict | None:
    path = runs_dir() / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
