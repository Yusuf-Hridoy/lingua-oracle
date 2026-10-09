"""C-24: a UN number given in Section 14, with the fields the regulation's
own text requires beside it (data/section14/<regulation>.json):

* EU and GB - REACH Annex II 14.2-14.4, "shall be provided": a shipping
  name, class or packing group left empty or "not applicable" is a fault.
  The name is not needed where it is the product identifier (1.1) and, in
  the EU text, not repeated where it is the same in every mode;
* UN GHS - A4.3.14.2-A4.3.14.4, in a text that recommends: one to check;
* Australia, Canada, the US - the text requires none of the fields: a note.

The packing group is asked for only where the list entry has one ("if
applicable"); the list is the UN Dangerous Goods List.
"""

from __future__ import annotations

from lingua_oracle.consistency import transport
from lingua_oracle.keys.builders import lists, section14
from lingua_oracle.models import ConsistencyRow

CHECK = "C-24"
_LABELS = {"name": "proper shipping name", "class": "transport hazard class",
           "group": "packing group"}


def _row(status, key, text, rule=None, *, expected="") -> ConsistencyRow:
    return ConsistencyRow(section="14", check=CHECK, key=key, status=status, text=text,
                          quote=(rule or {}).get("quote", ""),
                          citation=(rule or {}).get("citation", ""), expected=expected)


def run(section_14: list[str], regulation: str, product_name: str | None) -> list[ConsistencyRow]:
    held = section14.load(regulation)
    if held is None or not section_14:
        return []
    said = [(mode, block) for mode, block in transport.read(section_14) if block["number"]]
    if not said:
        return []
    if held.get("note"):
        note = held["note"]
        return [_row("na", "Required fields", f"Not checked: {note['text']}", note)]
    fields = held["fields"]
    status = "fix" if held.get("binding") else "check"
    un = lists.load("un_dangerous_goods") or {}
    named = {block["number"] for _, block in said if block["name"]}
    rows: list[ConsistencyRow] = []
    for mode, block in said:
        number, title = block["number"], mode or "Transport"
        entries = [e for e in un.get("entries", []) if e["id"] == number]
        names = [n for e in entries for n in e.get("proper_shipping_names", [])]
        missing = []
        if not block["name"]:
            if number in named and held.get("name_once"):
                pass                                # given in another mode (14.2)
            elif product_name and any(transport._name_agrees(product_name, n, ordered=False)
                                      for n in names):
                pass                                # the product identifier is the name
            else:
                missing.append("name")
        if not block["class"]:
            missing.append("class")
        groups = sorted({g for e in entries for g in e["packing_groups"]})
        if not block["group"] and groups:
            missing.append("group")
        for field in missing:
            expected = {"name": " / ".join(names[:3]),
                        "class": ", ".join(sorted({e["class"] for e in entries})),
                        "group": ", ".join(groups)}[field]
            rows.append(_row(status, f"{title} {number} {_LABELS[field]}",
                             f"{number} is given, but Section 14 gives no {_LABELS[field]} "
                             "(empty or “not applicable”).", fields[field], expected=expected))
        if not missing:
            rows.append(_row("ok", f"{title} {number}", f"{number} is given with the "
                             + ("shipping name, class and packing group" if groups else
                                "shipping name and class") + " the text requires."))
    return rows
