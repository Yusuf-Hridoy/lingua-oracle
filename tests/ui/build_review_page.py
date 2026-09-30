"""Build reports/ui_review/index.html - one card per screenshot, for a human.

Run after the UI suite:  uv run python tests/ui/build_review_page.py

The page is for someone who did not write the tool. Each card says, in plain
words, what the document is wrong about and what the report is supposed to show,
so a reviewer can judge the screenshot without reading any code.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.ui.manifest import CASES  # noqa: E402

OUT = ROOT / "reports" / "ui_review"
REAL = ROOT / "data" / "validation" / "ui_review"

CSS = """
:root{--bg:#f7f7f8;--card:#fff;--ink:#1b1b1f;--muted:#5f6368;--line:#e2e3e7;
      --accent:#0b5cad;--ok:#0a7d38;--bad:#b3261e;--warn:#8a6100}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:40px 20px 120px}
h1{font-size:26px;margin:0 0 6px}
p.sub{color:var(--muted);margin:0 0 8px}
.bar{position:sticky;top:0;z-index:5;background:var(--bg);padding:14px 0 12px;
     border-bottom:1px solid var(--line);margin-bottom:26px;display:flex;
     gap:12px;align-items:center;flex-wrap:wrap}
button{padding:9px 16px;border:0;border-radius:8px;background:var(--accent);
       color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button.ghost{background:#fff;color:var(--ink);border:1px solid var(--line)}
button:hover{filter:brightness(.94)}
.counter{color:var(--muted);font-size:13px}
h2.sec{font-size:15px;text-transform:uppercase;letter-spacing:.06em;
       color:var(--muted);margin:34px 0 14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
      padding:20px;margin-bottom:22px}
.card h3{margin:0 0 2px;font-size:17px}
.tag{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.04em;
     padding:2px 8px;border-radius:999px;margin-left:8px;vertical-align:2px}
.t-clean{background:#e6f4ea;color:var(--ok)}
.t-defect{background:#fce8e6;color:var(--bad)}
.t-regression{background:#fff4e5;color:var(--warn)}
.t-compare{background:#e8eefc;color:var(--accent)}
dl.what{display:grid;grid-template-columns:150px 1fr;gap:6px 16px;margin:14px 0 0}
dt{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;
   letter-spacing:.04em;padding-top:2px}
dd{margin:0}
.shot{margin-top:16px;border:1px solid var(--line);border-radius:10px;
      overflow:hidden;background:#fafafa}
.shot img{display:block;width:100%}
.note{margin-top:16px;display:grid;gap:8px}
.verdicts{display:flex;gap:8px;flex-wrap:wrap}
label.v{font-size:13px;border:1px solid var(--line);border-radius:999px;
        padding:6px 14px;cursor:pointer;background:#fff}
label.v input{margin-right:6px}
label.v.on-ok{border-color:var(--ok);background:#e6f4ea;color:var(--ok)}
label.v.on-bad{border-color:var(--bad);background:#fce8e6;color:var(--bad)}
textarea{width:100%;min-height:74px;padding:10px;border:1px solid var(--line);
         border-radius:8px;font:14px/1.5 inherit;resize:vertical}
.warnbox{background:#fff4e5;border:1px solid #f0d8b0;border-radius:10px;
         padding:12px 16px;margin:10px 0 0;font-size:14px}
"""

JS = """
const KEYS = __KEYS__;
function val(k){
  const v = document.querySelector(`input[name="v-${k}"]:checked`);
  return v ? v.value : "";
}
function refresh(){
  let done = 0;
  KEYS.forEach(k => {
    const v = val(k);
    if (v) done++;
    document.querySelectorAll(`label[data-for="${k}"]`).forEach(l => {
      l.classList.remove("on-ok","on-bad");
      if (v && l.dataset.val === v) l.classList.add(v === "ok" ? "on-ok" : "on-bad");
    });
  });
  document.getElementById("counter").textContent =
    `${done} of ${KEYS.length} reviewed`;
}
function yamlString(s){
  return '"' + String(s).replace(/\\\\/g,"\\\\\\\\").replace(/"/g,'\\\\"')
                        .replace(/\\n/g,"\\\\n") + '"';
}
function buildYaml(){
  const lines = ["# Lingua Oracle UI review", "notes:"];
  KEYS.forEach(k => {
    const note = (document.getElementById("n-"+k).value || "").trim();
    lines.push(`  ${k}:`);
    lines.push(`    verdict: ${val(k) || '""'}`);
    lines.push(`    note: ${note ? yamlString(note) : '""'}`);
  });
  return lines.join("\\n") + "\\n";
}
function download(){
  const blob = new Blob([buildYaml()], {type:"text/yaml"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "ui_review_notes.yaml";
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
}
document.addEventListener("change", e => {
  if (e.target.name && e.target.name.startsWith("v-")) refresh();
  save();
});
document.addEventListener("input", e => { if (e.target.tagName === "TEXTAREA") save(); });
function save(){
  const d = {};
  KEYS.forEach(k => d[k] = {v: val(k), n: document.getElementById("n-"+k).value});
  try { localStorage.setItem("lingua-ui-review", JSON.stringify(d)); } catch (_) {}
}
function restore(){
  let d = {};
  try { d = JSON.parse(localStorage.getItem("lingua-ui-review") || "{}"); } catch (_) {}
  KEYS.forEach(k => {
    const e = d[k]; if (!e) return;
    if (e.v) { const r = document.querySelector(`input[name="v-${k}"][value="${e.v}"]`);
               if (r) r.checked = true; }
    if (e.n) document.getElementById("n-"+k).value = e.n;
  });
  refresh();
}
document.getElementById("dl").addEventListener("click", download);
document.getElementById("clear").addEventListener("click", () => {
  try { localStorage.removeItem("lingua-ui-review"); } catch (_) {}
  location.reload();
});
restore();
"""

TAGS = {"clean": ("t-clean", "correct document"),
        "regression": ("t-regression", "false alarm, must stay clean"),
        "compare": ("t-compare", "comparison"),
        "": ("t-defect", "planted defect")}


def _card(key: str, title: str, tag: str, plain: str, should: str, img: str) -> str:
    cls, label = TAGS[tag]
    return f"""
  <div class="card" id="c-{key}">
    <h3>{html.escape(title)}<span class="tag {cls}">{label}</span></h3>
    <dl class="what">
      <dt>What it is</dt><dd>{html.escape(plain)}</dd>
      <dt>Report should show</dt><dd>{html.escape(should)}</dd>
    </dl>
    <div class="shot"><img loading="lazy" src="{html.escape(img)}" alt="report for {html.escape(key)}"></div>
    <div class="note">
      <div class="verdicts">
        <label class="v" data-for="{key}" data-val="ok">
          <input type="radio" name="v-{key}" value="ok"> Looks right</label>
        <label class="v" data-for="{key}" data-val="problem">
          <input type="radio" name="v-{key}" value="problem"> Something is wrong</label>
      </div>
      <textarea id="n-{key}" placeholder="Notes - anything confusing, missing, or wrong"></textarea>
    </div>
  </div>"""


def build() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    keys, cards = [], []

    cards.append('<h2 class="sec">Synthetic test documents</h2>')
    for case in CASES:
        img = f"{case.name}.png"
        if not (OUT / img).exists():
            continue
        tag = next((t for t in ("clean", "regression", "compare") if t in case.tags), "")
        keys.append(case.name)
        cards.append(_card(case.name, case.name, tag, case.plain, case.should_show, img))

    real = sorted(REAL.glob("*.png")) if REAL.exists() else []
    if real:
        cards.append('<h2 class="sec">Real documents from the app</h2>')
        cards.append('<div class="warnbox"><b>Company data.</b> These screenshots '
                     'live outside the repository and are not committed. Do not '
                     'share this section outside the team.</div>')
        for png in real:
            key = f"real_{png.stem}"
            keys.append(key)
            rel = "../../data/validation/ui_review/" + png.name
            cards.append(_card(
                key, png.stem, "",
                "A real export from the authoring app.",
                "Regulation, language and findings should match what the app holds "
                "for this product. Judge whether the page is understandable.",
                rel))

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lingua Oracle - UI review</title><style>{CSS}</style></head><body>
<div class="wrap">
  <h1>Lingua Oracle &mdash; UI review</h1>
  <p class="sub">One card per document. Each says what the document is wrong
  about and what the report is supposed to show. Mark each one and add notes;
  the button saves them as <code>ui_review_notes.yaml</code>.</p>
  <div class="bar">
    <button id="dl">Download ui_review_notes.yaml</button>
    <button class="ghost" id="clear">Clear my answers</button>
    <span class="counter" id="counter"></span>
  </div>
  {"".join(cards)}
</div>
<script>{JS.replace("__KEYS__", json.dumps(keys))}</script>
</body></html>
"""
    target = OUT / "index.html"
    target.write_text(page, encoding="utf-8")
    return target


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")
