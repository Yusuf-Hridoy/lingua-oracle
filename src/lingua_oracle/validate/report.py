"""Rendering the validation summary to JSON and a self-contained HTML page."""

from __future__ import annotations

import html
import json
from pathlib import Path

from lingua_oracle.validate.runner import Summary


def to_dict(summary: Summary) -> dict:
    return {
        "created_at": summary.created_at.isoformat(),
        "passed": summary.passed,
        "targets": summary.targets(),
        "triage_counts": summary.triage_counts,
        "spot_check": {
            "total": summary.spot_check_total,
            "reviewed": summary.spot_check_reviewed,
            "correct": summary.spot_check_correct,
        },
        "documents": [
            {
                "file": r.case.file,
                "regulation": r.case.regulation,
                "language": r.case.language,
                "known_good": r.case.known_good,
                "error": r.error,
                "recall": r.recall,
                "expected": sorted(r.expected),
                "found": sorted(r.found),
                "missed": sorted(r.missed),
                "extra": sorted(r.extra),
                "counts": r.counts,
                "known_defects_caught": r.defects_caught,
                "known_defects_missed": r.defects_missed,
                "findings": r.findings,
            }
            for r in summary.results
        ],
    }


def _badge(passed: bool, skipped: bool = False) -> str:
    if skipped:
        return '<span class="badge b-skip">not measured</span>'
    return (
        '<span class="badge b-pass">PASS</span>' if passed
        else '<span class="badge b-fail">FAIL</span>'
    )


def render_html(summary: Summary) -> str:
    data = to_dict(summary)
    e = html.escape
    rows = []
    for t in data["targets"]:
        rows.append(
            f"<tr><td>{e(t['name'])}</td><td class='num'>{e(t['target'])}</td>"
            f"<td class='num'>{e(str(t['actual']))}</td>"
            f"<td>{_badge(t['passed'], t['skipped'])}</td></tr>"
        )

    docs = []
    for d in data["documents"]:
        recall = "n/a" if d["recall"] is None else f"{d['recall'] * 100:.1f}%"
        cls = "err" if d["error"] else ("good" if d["known_good"] else "")
        head = (
            f"<h3>{e(d['file'])} <small>{e(d['regulation'] or 'auto')} / "
            f"{e(d['language'] or 'auto')}"
            + (" · known good" if d["known_good"] else "")
            + "</small></h3>"
        )
        if d["error"]:
            docs.append(f"<div class='card {cls}'>{head}<p class='error'>{e(d['error'])}</p></div>")
            continue
        c = d["counts"]
        chips = (
            f"<span class='chip c-fail'>{c['fail']} fail</span>"
            f"<span class='chip c-warn'>{c['warn']} warn</span>"
            f"<span class='chip'>{c['info']} info</span>"
            f"<span class='chip'>{c['unverified']} unverified</span>"
            f"<span class='chip c-recall'>recall {recall}</span>"
        )
        missed = (
            f"<p class='missed'><strong>Missed codes:</strong> {e(', '.join(d['missed']))}</p>"
            if d["missed"] else ""
        )
        extra = (
            f"<p class='extra'><strong>Extra codes found:</strong> "
            f"{e(', '.join(d['extra']))}</p>" if d["extra"] else ""
        )
        defects = ""
        if d["known_defects_missed"]:
            items = "".join(
                f"<li>{e(x['check'])} {e(x['code'] or '')} — {e(x['note'])}</li>"
                for x in d["known_defects_missed"]
            )
            defects += f"<p class='missed'><strong>Known defects NOT caught:</strong></p><ul>{items}</ul>"
        if d["known_defects_caught"]:
            items = "".join(
                f"<li>{e(x['check'])} {e(x['code'] or '')} — {e(x['note'])}</li>"
                for x in d["known_defects_caught"]
            )
            defects += f"<p class='ok'><strong>Known defects caught:</strong></p><ul>{items}</ul>"

        frows = "".join(
            "<tr>"
            f"<td>{e(f['severity'])}</td><td>{e(f['check_id'])}</td>"
            f"<td class='code'>{e(f['code'] or '')}</td>"
            f"<td>{e(f['classification'] or '—')}</td>"
            f"<td>{e(f['message'])}</td>"
            f"<td class='id'>{e(f['id'])}</td>"
            "</tr>"
            for f in d["findings"]
        )
        table = (
            "<div class='scroll'><table><thead><tr><th>Sev</th><th>Check</th><th>Code</th>"
            "<th>Class</th><th>Message</th><th>Finding id</th></tr></thead>"
            f"<tbody>{frows}</tbody></table></div>" if frows else "<p class='ok'>No findings.</p>"
        )
        docs.append(f"<div class='card {cls}'>{head}<div class='chips'>{chips}</div>"
                    f"{missed}{extra}{defects}{table}</div>")

    triage = "".join(
        f"<span class='chip'>{e(k)}: {v}</span>" for k, v in sorted(data["triage_counts"].items())
    )
    overall = _badge(data["passed"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lingua Oracle — validation</title>
<style>
 :root {{ --bg:#f7f7f8; --card:#fff; --ink:#1b1b1f; --muted:#5f6368; --line:#e2e3e7;
          --fail:#b3261e; --warn:#8a5a00; --ok:#1d6b3a; }}
 *{{box-sizing:border-box}}
 body{{margin:0;background:var(--bg);color:var(--ink);
   font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
 .wrap{{max-width:1180px;margin:0 auto;padding:24px 20px 60px}}
 h1{{font-size:20px;margin:0 0 4px}} h3{{font-size:15px;margin:0 0 8px}}
 small{{color:var(--muted);font-weight:400}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:10px;
   padding:16px;margin:14px 0}}
 .card.good{{border-left:4px solid var(--ok)}} .card.err{{border-left:4px solid var(--fail)}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{text-align:left;padding:7px 10px;border-top:1px solid var(--line);vertical-align:top}}
 th{{background:#fafafb;font-size:12px;color:var(--muted);border-top:none}}
 td.num{{font-variant-numeric:tabular-nums}} td.code,td.id{{font-family:ui-monospace,Menlo,monospace}}
 td.id{{font-size:11px;color:var(--muted)}}
 .badge{{display:inline-block;font-size:11px;font-weight:700;padding:3px 10px;border-radius:999px}}
 .b-pass{{background:#e7f5ec;color:var(--ok)}} .b-fail{{background:#fdecea;color:var(--fail)}}
 .b-skip{{background:#eceff1;color:#546e7a}}
 .chips{{margin:6px 0 10px}} .chip{{display:inline-block;background:#eceff1;color:#37474f;
   border-radius:999px;padding:2px 10px;font-size:12px;margin-right:6px}}
 .c-fail{{background:#fdecea;color:var(--fail)}} .c-warn{{background:#fff5e0;color:var(--warn)}}
 .c-recall{{background:#e8f1fb;color:#0b5cad}}
 .missed{{color:var(--fail)}} .ok{{color:var(--ok)}} .extra{{color:var(--warn)}}
 .error{{color:var(--fail);font-family:ui-monospace,Menlo,monospace;font-size:12px}}
 .scroll{{overflow-x:auto}}
 .note{{color:var(--muted);font-size:12px;margin-top:18px}}
</style></head><body><div class="wrap">
<h1>Validation {overall}</h1>
<div class="sub" style="color:var(--muted)">{e(data['created_at'])} ·
{len(data['documents'])} document(s)</div>

<div class="card"><h3>Targets</h3><div class="scroll"><table>
<thead><tr><th>Metric</th><th>Target</th><th>Actual</th><th></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></div>

<div class="card"><h3>Triage</h3><div class="chips">{triage or "<em>none</em>"}</div>
<p class="note">A finding on a known-good document counts as a false alarm while it is
unclassified, or classified false_alarm / key_error / extraction_error and not yet
fixed.</p></div>

{''.join(docs)}

<p class="note">This report quotes real documents and stays in reports/validation/,
which is gitignored. Do not paste its contents into the repository.</p>
</div></body></html>
"""


def write(summary: Summary, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "summary.json"
    html_path = out_dir / "summary.html"
    json_path.write_text(
        json.dumps(to_dict(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    html_path.write_text(render_html(summary), encoding="utf-8")
    return json_path, html_path
