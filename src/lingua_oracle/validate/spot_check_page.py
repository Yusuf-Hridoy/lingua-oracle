"""Build the answer-key spot-check evidence page.

For each sampled entry this shows the key's text beside the *source* it was read
from, so a reviewer judges the entry against the document rather than against the
tool's own claim about it:

* PDF sources - the cited page is rendered and cropped to the row containing the
  code, as a PNG embedded in the page.
* EU CLP - the source is the Publications Office XHTML, which has no pages, so
  the annex table row itself is extracted and shown as a table.

Verdicts are never pre-filled. The page records them locally and hands back a
complete spot_check.yaml to save over the existing one.
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from lingua_oracle.validate.cases import SpotCheckFile

_PDF_REF_RE = re.compile(r"\(([^()]*\.(?:pdf|html))(?:,\s*p(\d+))?\)", re.IGNORECASE)
CROP_PAD = 26


def _find_source_pdf(name: str, sources_root: Path) -> Path | None:
    for candidate in sources_root.rglob(name):
        return candidate
    return None


def crop_row(pdf: Path, page_no: int, code: str) -> bytes | None:
    """Render the cited page and crop to the row holding `code`."""
    import pymupdf

    doc = pymupdf.open(pdf)
    try:
        index = page_no - 1
        if not (0 <= index < doc.page_count):
            return None
        page = doc[index]
        needles = [code, code.replace("+", " + ")]
        rects = []
        for needle in needles:
            rects = page.search_for(needle)
            if rects:
                break
        box = page.rect
        if rects:
            r = rects[0]
            top = max(page.rect.y0, r.y0 - CROP_PAD)
            bottom = min(page.rect.y1, r.y1 + CROP_PAD * 3)
            candidate = pymupdf.Rect(page.rect.x0, top, page.rect.x1, bottom)
            # A degenerate clip makes the renderer fail outright, so fall back to
            # the whole page rather than lose the evidence.
            if candidate.width > 8 and candidate.height > 8:
                box = candidate
        try:
            return page.get_pixmap(clip=box, dpi=140).tobytes("png")
        except Exception:  # noqa: BLE001
            try:
                return page.get_pixmap(dpi=110).tobytes("png")
            except Exception:  # noqa: BLE001
                return None
    finally:
        doc.close()


def cellar_row(code: str, language: str) -> list[list[str]] | None:
    """The CLP annex table row for a code, read from the cached source document."""
    from lingua_oracle.keys.builders import eu_clp

    try:
        doc = eu_clp._doc("eng")
    except Exception:  # noqa: BLE001
        return None
    want = code.replace("+", "").replace(" ", "").upper()
    for table in doc.xpath("//table"):
        rows = table.xpath(".//tr")
        if not rows:
            continue
        head = eu_clp._row_cells(rows[0])
        if len(head) != 3 or head[1].strip() != "Language":
            continue
        if eu_clp.normalise_code(head[0]).replace("+", "").upper() != want:
            continue
        out = [["Code", head[0], head[2]]]
        for row in rows[1:]:
            cells = eu_clp._row_cells(row)
            if len(cells) == 3 and cells[1].strip().lower() == language.lower():
                out.append(cells)
        return out
    return None


def build(spot: SpotCheckFile, sources_root: Path) -> str:
    e = html.escape
    cards = []
    for i, entry in enumerate(spot.entries, start=1):
        match = _PDF_REF_RE.search(entry.source_ref or "")
        evidence = "<p class='none'>No source evidence could be rendered.</p>"
        if match and match.group(1).lower().endswith(".pdf") and match.group(2):
            pdf = _find_source_pdf(match.group(1), sources_root)
            if pdf:
                png = crop_row(pdf, int(match.group(2)), entry.code)
                if png:
                    b64 = base64.b64encode(png).decode()
                    evidence = (
                        f"<img alt='source row for {e(entry.code)}' "
                        f"src='data:image/png;base64,{b64}'>"
                    )
        elif entry.regulation == "eu_clp":
            rows = cellar_row(entry.code, entry.language)
            if rows:
                body = "".join(
                    "<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows
                )
                evidence = f"<table class='src'>{body}</table>"

        cards.append(f"""
<div class="card" data-i="{i}">
  <div class="head">
    <span class="n">{i}/{len(spot.entries)}</span>
    <span class="reg">{e(entry.regulation)}/{e(entry.language)}</span>
    <span class="code">{e(entry.code)}</span>
    <span class="verdict" id="v{i}">unreviewed</span>
  </div>
  <div class="cols">
    <div class="col">
      <h4>Key text</h4>
      <p class="keytext">{e(entry.text)}</p>
      <p class="ref">{e(entry.source_ref)}</p>
      {f'<p class="ref"><a href="{e(entry.source_url)}" target="_blank" rel="noopener">source</a></p>' if entry.source_url else ''}
    </div>
    <div class="col"><h4>Source</h4>{evidence}</div>
  </div>
  <div class="btns">
    <button class="ok"   onclick="setV({i},'correct')">Correct</button>
    <button class="bad"  onclick="setV({i},'wrong')">Wrong</button>
    <button class="clr"  onclick="setV({i},'')">Clear</button>
  </div>
</div>""")

    meta = [
        {"regulation": x.regulation, "language": x.language, "code": x.code,
         "text": x.text, "source_ref": x.source_ref, "source_url": x.source_url}
        for x in spot.entries
    ]
    import json as _json
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Answer-key spot check</title><style>
 :root{{--bg:#f7f7f8;--card:#fff;--ink:#1b1b1f;--muted:#5f6368;--line:#e2e3e7;
        --ok:#1d6b3a;--bad:#b3261e}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);
   font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
 .wrap{{max-width:1180px;margin:0 auto;padding:22px 20px 80px}}
 h1{{font-size:20px;margin:0 0 4px}} h4{{margin:0 0 6px;font-size:12px;color:var(--muted);
   text-transform:uppercase;letter-spacing:.04em}}
 .card{{background:var(--card);border:1px solid var(--line);border-radius:10px;
   padding:14px 16px;margin:14px 0}}
 .head{{display:flex;gap:10px;align-items:center;margin-bottom:10px;flex-wrap:wrap}}
 .n{{color:var(--muted);font-size:12px}}
 .reg{{background:#eceff1;border-radius:999px;padding:2px 10px;font-size:12px}}
 .code{{font-family:ui-monospace,Menlo,monospace;font-weight:700}}
 .verdict{{margin-left:auto;font-size:12px;color:var(--muted)}}
 .verdict.correct{{color:var(--ok);font-weight:700}} .verdict.wrong{{color:var(--bad);font-weight:700}}
 .cols{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
 @media(max-width:860px){{.cols{{grid-template-columns:1fr}}}}
 .keytext{{font-family:ui-monospace,Menlo,monospace;font-size:13px;background:#fafafb;
   border:1px solid var(--line);border-radius:6px;padding:10px;margin:0 0 8px}}
 .ref{{color:var(--muted);font-size:11px;margin:0}}
 img{{max-width:100%;border:1px solid var(--line);border-radius:6px}}
 table.src{{border-collapse:collapse;width:100%;font-size:12px}}
 table.src td{{border:1px solid var(--line);padding:5px 7px;vertical-align:top}}
 table.src tr:first-child td{{background:#fafafb;font-weight:600}}
 .none{{color:var(--muted);font-style:italic}}
 .btns{{margin-top:12px;display:flex;gap:8px}}
 button{{border:1px solid var(--line);background:#fff;border-radius:7px;padding:7px 16px;
   font-size:13px;cursor:pointer}}
 button.ok:hover{{border-color:var(--ok);color:var(--ok)}}
 button.bad:hover{{border-color:var(--bad);color:var(--bad)}}
 .bar{{position:sticky;top:0;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);
   z-index:5;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
 .bar b{{font-size:13px}} .note{{color:var(--muted);font-size:12px;margin-top:20px}}
</style></head><body><div class="wrap">
<h1>Answer-key spot check</h1>
<div class="sub" style="color:var(--muted)">Judge each entry against the source shown
beside it. Nothing is pre-filled.</div>

<div class="bar">
  <b id="progress">0 / {len(spot.entries)} reviewed</b>
  <span id="tally" style="color:var(--muted);font-size:12px"></span>
  <button onclick="save()" style="margin-left:auto">Download spot_check.yaml</button>
  <button onclick="copyYaml()">Copy YAML</button>
</div>

{''.join(cards)}

<p class="note">Save the downloaded file over
<code>data/validation/spot_check.yaml</code>, then re-run <code>lingua validate</code>
to score it. This page quotes real source documents and stays in
reports/validation/, which is gitignored.</p>
</div>
<script>
const META = {_json.dumps(meta, ensure_ascii=False)};
const KEY = "lingua-spotcheck";
let V = JSON.parse(localStorage.getItem(KEY) || "{{}}");
function setV(i, v) {{
  if (v) V[i] = v; else delete V[i];
  localStorage.setItem(KEY, JSON.stringify(V));
  render();
}}
function render() {{
  let ok = 0, bad = 0;
  META.forEach((_, idx) => {{
    const i = idx + 1, el = document.getElementById("v" + i), v = V[i] || "";
    el.textContent = v || "unreviewed";
    el.className = "verdict " + v;
    if (v === "correct") ok++; if (v === "wrong") bad++;
  }});
  document.getElementById("progress").textContent =
    (ok + bad) + " / " + META.length + " reviewed";
  document.getElementById("tally").textContent =
    ok + " correct, " + bad + " wrong";
}}
function yaml() {{
  const esc = s => '"' + String(s == null ? "" : s).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, '\\\\"') + '"';
  let out = "sampled_at: " + esc({_json.dumps(spot.sampled_at)}) + "\\nentries:\\n";
  META.forEach((m, idx) => {{
    out += "  - regulation: " + esc(m.regulation) + "\\n";
    out += "    language: " + esc(m.language) + "\\n";
    out += "    code: " + esc(m.code) + "\\n";
    out += "    text: " + esc(m.text) + "\\n";
    out += "    source_ref: " + esc(m.source_ref) + "\\n";
    out += "    source_url: " + (m.source_url ? esc(m.source_url) : "null") + "\\n";
    out += "    verdict: " + esc(V[idx + 1] || "") + "\\n";
  }});
  return out;
}}
function save() {{
  const b = new Blob([yaml()], {{type: "text/yaml"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(b); a.download = "spot_check.yaml"; a.click();
}}
function copyYaml() {{ navigator.clipboard.writeText(yaml()); }}
render();
</script></body></html>
"""
