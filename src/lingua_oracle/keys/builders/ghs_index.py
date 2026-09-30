"""An offline record of which codes each GHS edition on file defines.

Check time needs to answer one question without a network or a PDF parse: is a
code the tool has never seen a *newer GHS code* or a *nonexistent* one? That is
the difference between "this sheet is ahead of the regulation it claims" and
"this code does not exist", and the two deserve very different verdicts.

So the editions in `data/sources/` are read once, at key-build time, into
`data/ghs_index/en.json`: code -> {edition: official English text}. The file is
committed and is the only thing the check reads.

English only, deliberately. The index answers "does this edition define this
code", which is a property of the code, not of a translation - and the English
editions are the ones on file for every revision.
"""

from __future__ import annotations

import json
from pathlib import Path

from lingua_oracle.keys.builders.ghs_editions import annex3
from lingua_oracle.registry import data_dir

#: Edition label -> source, oldest first. The label is what a report shows.
EDITIONS: tuple[tuple[str, str], ...] = (
    ("GHS Rev.7", "ghs-rev7/GHS_Rev7_en.pdf"),
    ("GHS Rev.8", "ghs-rev8/GHS_Rev8_en.pdf"),
    ("GHS Rev.11", "un-ghs/GHS_Rev11_en.pdf"),
)


def index_path() -> Path:
    return data_dir() / "ghs_index" / "en.json"


def build(sources_root: str | Path | None = None) -> Path:
    """Read every edition on file and write the index. Offline."""
    root = Path(sources_root or (data_dir() / "sources"))
    index: dict[str, dict[str, str]] = {}
    present: list[str] = []
    for label, relative in EDITIONS:
        source = root / relative
        if not source.exists():
            continue
        present.append(label)
        for code, text in annex3(str(source)).items():
            # A later edition prints "[Deleted]" where it has withdrawn a code.
            # That is a statement about the code, not a statement to put on a
            # label, so the edition does not count as defining it.
            if text and text.strip().lower() not in ("[deleted]", "deleted"):
                index.setdefault(code, {})[label] = text

    target = index_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"editions": present, "codes": dict(sorted(index.items()))},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return target
