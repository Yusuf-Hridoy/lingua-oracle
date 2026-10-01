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


def presence_path() -> Path:
    return data_dir() / "ghs_index" / "source_presence.json"


def presence_key(text: str) -> str:
    """Comparison key for "does this wording appear in the source at all".

    The builder's own `_core_key` - normalised, case-folded, US/UK spelling
    folded, fill-ins collapsed - with a trailing plural folded off each word.
    That last step is the only tolerance, and it exists for one observed
    difference: GHS writes "static discharges" where Appendix C writes "static
    discharge". Everything else must match exactly.

    Deliberately not a similarity score. The question here is whether the
    regulation's own source carries this wording, and a score cannot separate
    "discharge/discharges" from "medical help"/"medical advice" - which is the
    distinction the whole thing turns on.
    """
    from lingua_oracle.keys.builders.us_osha import _core_key

    return " ".join(
        word[:-1] if len(word) > 3 and word.endswith("s") else word
        for word in _core_key(text).split()
    )


def write_source_presence(regulation: str, source: str, statements) -> Path:
    """Record which GHS codes' wording appears in a regulation's own source.

    Only meaningful for a regulation whose key is knowingly incomplete. Without
    it, a code missing from such a key can only be called "our gap" - which is
    wrong when the regulation's source does not contain the wording at all, and
    hides a sheet that is running ahead of the regulation it cites.
    """
    pool = {presence_key(s) for s in statements if s}
    index = json.loads(index_path().read_text(encoding="utf-8"))
    present = sorted(
        code for code, editions in index.get("codes", {}).items()
        if any(presence_key(text) in pool for text in editions.values())
    )

    target = presence_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {}
    if target.exists():
        record = json.loads(target.read_text(encoding="utf-8"))
    record[regulation] = {
        "source": source,
        "statements_read": len(pool),
        "present": present,
    }
    target.write_text(
        json.dumps(dict(sorted(record.items())), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return target


def build(sources_root: str | Path | None = None) -> Path:
    """Read every edition on file and write the index. Offline."""
    root = Path(sources_root or (data_dir() / "sources"))
    index: dict[str, dict[str, str]] = {}
    deleted: dict[str, list[str]] = {}
    present: list[str] = []
    for label, relative in EDITIONS:
        source = root / relative
        if not source.exists():
            continue
        present.append(label)
        for code, text in annex3(str(source)).items():
            if not text:
                continue
            # A later edition prints "[Deleted]" where it has withdrawn a code.
            # That is a statement about the code, not a statement to put on a
            # label: the edition does not define it, and a sheet still citing
            # it is using something the edition has withdrawn.
            if text.strip().lower() in ("[deleted]", "deleted"):
                deleted.setdefault(code, []).append(label)
                continue
            index.setdefault(code, {})[label] = text

    target = index_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"editions": present,
                    "codes": dict(sorted(index.items())),
                    "deleted": dict(sorted(deleted.items()))},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return target
