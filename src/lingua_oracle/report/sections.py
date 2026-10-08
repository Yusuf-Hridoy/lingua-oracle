"""The report arranged the way a reviewer reads an SDS: section by section.

Every result the checks produced is placed in the SDS section it is about and
becomes one row - correct ones included, so a reader can see what was checked
and not only what failed. A problem row carries both wordings with the
differences marked; a correct one is a single compact line. The banner, the
"What to do" list and the counts are all computed from these same rows, so they
cannot disagree with what is on the page.

Nothing here decides anything: the verdicts are the checks'. This only says
where each one goes and how it reads.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field

from lingua_oracle.models import Report, Severity
from lingua_oracle.report import labels

#: Section titles as the SDS format names them (Annex II to REACH, and the
#: same sixteen headings in GHS Annex 4).
TITLES = {
    "1": "Identification", "2": "Hazards identification",
    "3": "Composition", "9": "Physical and chemical properties",
    "16": "Other information", "label": "Label",
}
#: The sections this tool reads. The others are listed and not judged.
CHECKED = ("1", "2", "3", "9", "16")
NOT_CHECKED_RANGES = (("4", "8"), ("10", "15"))

PILL = {
    "ok": ("Correct", "✓", "ok"),
    "fix": ("Fix", "✕", "fix"),
    "wrong": ("Wrong", "✕", "fix"),
    "check": ("Check", "!", "check"),
    "na": ("Not checked", "–", "na"),
    "info": ("Note", "i", "na"),
    #: A fact about the document - its product, regulation, language - with no
    #: verdict of its own, so no pill and no count.
    "plain": ("", "", ""),
}
#: How the navigator names each section, as the design board does.
NAV = {"1": "Identification", "2": "Hazards", "3": "Composition",
       "9": "Physical state", "16": "Other information"}

#: Checks whose results are statements, shown from the statement verdicts.
_STATEMENT_CHECKS = {"A-01", "A-02", "A-03", "A-04", "C-15"}
#: Checks about the document as a whole, shown in Section 1.
_WHOLE_DOCUMENT = {"B-11", "C-14", "C-02", "A-05", "A-07"}


@dataclass
class Row:
    key: str
    status: str                      # ok | fix | wrong | check | na | info | plain
    text: str = ""
    mono: bool = False
    note: str = ""
    #: For a problem row: both wordings, differences marked.
    found_html: str = ""
    expected_html: str = ""
    expected: str = ""
    official_heading: str = "Official wording"
    #: One column only - a blank to fill, or a finding with no official text.
    single: bool = False
    action: str = ""
    #: Rows whose actions are grouped into one line ("align punctuation in ...").
    minor: bool = False
    #: One "What to do" line for every row sharing it, the keys put in at
    #: {keys} - three codes missing their full text are one task, not three.
    group: str = ""
    #: Where the action is carried out, where that is not the section the row
    #: is shown in: Section 3's table compares Section 2's codes.
    act_in: str = ""
    #: A mixture result: the row shows Section 2's class against the
    #: calculated one, with the ingredients that contributed.
    mixture: dict | None = None
    #: Values the author typed into the official text's blanks.
    fillins: list[str] = field(default_factory=list)
    #: For a blank left unfilled: the official wording, as a reference line.
    reference: str = ""
    #: Where the official wording comes from, as a reader would cite it.
    source: str = ""
    #: A blank never filled in: something to do, but not a contradiction of
    #: the official text, so it does not by itself hold the sheet.
    blank: bool = False

    @property
    def pill(self) -> tuple[str, str, str]:
        return PILL[self.status]

    @property
    def problem(self) -> bool:
        return self.status in ("fix", "wrong", "check")

    @property
    def compare(self) -> bool:
        return bool(self.found_html or self.expected_html)


@dataclass
class Sub:
    title: str
    rows: list[Row] = field(default_factory=list)


@dataclass
class Section:
    number: str
    title: str
    subs: list[Sub] = field(default_factory=list)
    intro: str = ""
    #: Section 3's ingredient table: {"list_heading", "rows": [...]}.
    table: dict | None = None

    @property
    def anchor(self) -> str:
        return f"s{self.number}"

    @property
    def heading(self) -> str:
        if self.number == "label":
            return "Label"
        return f"Section {self.number} · {self.title}"

    @property
    def rows(self) -> list[Row]:
        rows = [r for s in self.subs for r in s.rows]
        if self.table:
            rows += [r["row"] for r in self.table["rows"]]
        return rows

    def count(self, *statuses: str) -> int:
        return sum(1 for r in self.rows if r.status in statuses)

    @property
    def status(self) -> str:
        if self.count("fix", "wrong"):
            return "fix"
        if self.count("check"):
            return "check"
        if self.count("ok") or self.count("plain"):
            return "ok"
        return "na"

    @property
    def judged(self) -> bool:
        return self.count("ok", "fix", "wrong", "check") > 0


# -- small helpers ---------------------------------------------------------------

def _esc(text: str | None) -> str:
    return html.escape(text or "")


def _code_key(code: str) -> str:
    return labels.code_label(code) or code


def _statement_row(verdict, display: str) -> Row:
    """One statement verdict as a row."""
    from lingua_oracle.report.render import word_diff

    code = verdict.code
    key = "Signal word" if code == "SIGNAL" else _code_key(code)
    mono = code != "SIGNAL"
    if verdict.status == "correct":
        return Row(key, "ok", text=verdict.found or verdict.expected, mono=mono,
                   note=verdict.match_note, fillins=list(verdict.fillins))
    if verdict.status == "not_checked":
        return Row(key, "na", text=verdict.why or "Not checked.", mono=mono,
                   note=verdict.found and f"Your document: {verdict.found}")
    heading = (f"Closest {display} statement · {verdict.nearest_code}"
               if verdict.nearest_code else "Official wording")
    if verdict.blank_unfilled:
        from lingua_oracle.report.render import _highlight_blank

        return Row(key, "fix", mono=mono,
                   found_html=_highlight_blank(verdict.found),
                   single=True, expected=verdict.expected,
                   reference=verdict.expected, source=verdict.source, blank=True,
                   note=labels.blank_instruction(code, verdict.expected),
                   action=f"fill in the blank in {key}")
    left, right = word_diff(verdict.expected, verdict.found)
    if verdict.status == "wrong":
        target = "the signal word" if code == "SIGNAL" else key
        return Row(key, "wrong", mono=mono, found_html=right, expected_html=left,
                   expected=verdict.expected, official_heading=heading,
                   note=verdict.why, source=verdict.source,
                   fillins=list(verdict.fillins),
                   action=f"correct {target} to “{verdict.expected}”")
    minor = bool(verdict.minor_difference)
    return Row(key, "check", mono=mono, found_html=right, expected_html=left,
               expected=verdict.expected, official_heading=heading,
               note=(f"{verdict.why} {verdict.match_note}".strip()
                     if verdict.match_note else verdict.why),
               minor=minor, source=verdict.source,
               fillins=list(verdict.fillins),
               group=("align punctuation and capital letters in {keys}, or "
                      "confirm they do not matter" if minor else ""),
               action=("" if minor else
                       f"check {key}: {verdict.why}".rstrip(".")))


def _finding_row(finding, display: str) -> Row | None:
    from lingua_oracle.report.render import word_diff

    if finding.unverified or finding.check_id in _STATEMENT_CHECKS:
        return None
    if finding.severity is Severity.INFO and finding.code:
        return None  # a fill-in note; the statement's own row carries it
    status = "fix" if finding.severity is Severity.FAIL else "check"
    key = labels.code_label(finding.code) if finding.code else ""
    from lingua_oracle.checks import title_of

    row = Row(key or title_of(finding.check_id), status, text=finding.message,
              mono=bool(key), action=labels.action_for(finding, display).rstrip("."))
    if finding.check_id == "B-08" and key:
        row.group = "write out the full text of {keys}"
    if finding.expected and finding.found:
        left, right = word_diff(finding.expected, finding.found)
        row.found_html, row.expected_html = right, left
        row.expected = finding.expected
        row.note, row.text = finding.message, ""
    return row


def _where(section: str | None) -> str:
    if section in ("2", "3", "16", "label"):
        return section
    return "1"


# -- the sections ------------------------------------------------------------------

def _section_one(report: Report, display: str, set_by: str) -> Section:
    from lingua_oracle.detect.language import language_name

    sec = Section("1", TITLES["1"])
    ident = Sub("")
    ing = report.ingredients
    if ing is not None and ing.product_id:
        ident.rows.append(Row("Product", "plain",
                              text=f"{ing.product_name} · ExactSDS product "
                                   f"{ing.product_id}",
                              note=ing.evidence))
    elif ing is not None and ing.match_state == "ambiguous":
        ident.rows.append(Row("Product", "check",
                              text="Several ExactSDS products could be this sheet "
                                   "— choose one above.",
                              action="say which product this is"))
    elif ing is not None and ing.source in ("pdf", "nothing"):
        ident.rows.append(Row("Product", "plain",
                              text="Not an ExactSDS product (supplier sheet) "
                                   "— read from the sheet itself"))
    elif ing is not None and ing.source == "skipped":
        ident.rows.append(Row("Product", "plain",
                              text=ing.message or "ExactSDS could not be reached."))
    evidence = next((n for n in report.notes
                     if n.startswith("Regulation read from the sheet")), "")
    why = (evidence.replace("Regulation read from the sheet's own words: ",
                            "read from the sheet: “") + "”"
           if evidence else set_by)
    ident.rows.append(Row("Regulation", "plain", text=f"{display}, {why}"))
    ident.rows.append(Row("Language", "plain",
                          text=f"{language_name(report.language)}, {set_by}"))
    if report.composition:
        what = {"substance": "Substance", "mixture": "Mixture",
                "unknown": "Not stated"}[report.composition]
        ident.rows.append(Row("Substance or mixture", "plain",
                              text=f"{what} — {report.composition_evidence}"))
    sec.subs.append(ident)
    return sec


def _classification(report: Report, display: str) -> Sub:
    sub = Sub("2.1 Classification")
    found = report.substance
    if found is not None:
        list_name = found.list_title or "the list"
        ref = (f" for {found.official_name.split(';')[0]} ({found.entry_index_no})"
               if found.entry_index_no else "")
        if found.state != "checked":
            sub.rows.append(Row("Substance", "na", text=found.message))
        for row in found.classes:
            key = row["stated"] or row["official"]
            status = {"ok": "ok", "fix": "fix" if found.list_binding else "check",
                      "info": "info", "na": "na"}[row["result"]]
            action = ""
            if status in ("fix", "check"):
                action = (f"change {row['stated']} to {row['official']}" if row["stated"]
                          else f"add {row['official']}") + f", as {list_name} gives{ref}"
            sub.rows.append(Row(key, status,
                                text=(f"Matches {list_name}{ref}" if status == "ok"
                                      else row["note"]),
                                action=action))
    mixture = report.mixture
    if mixture is None and found is None:
        sub.rows.append(Row("Mixture", "na",
                            text="The mixture calculation was not run."))
    if mixture is not None and mixture.state == "calculated":
        undisclosed = (f" ({mixture.undisclosed}% not disclosed)"
                       if mixture.undisclosed not in ("0", "") else "")
        read_as = {"gas": ", read as a gas", "liquid": ", read as a liquid",
                   "solid": ", read as a solid",
                   "solid/liquid": ", read as a solid or a liquid"}.get(
                       mixture.physical_state, "")
        if mixture.undisclosed in ("0", ""):
            # The upper bounds reach 100 %: nothing hidden, and the only
            # uncertainty is the ranges', which is why both ends are shown.
            basis = (f"Calculated from the declared ranges - their upper ends "
                     f"total {mixture.declared_total} %, so nothing is "
                     f"undisclosed{read_as}, at both ends of every range")
        else:
            basis = (f"Calculated from {mixture.declared_total}% of the "
                     f"mixture{undisclosed}{read_as}")
        sub.rows.append(Row("Mixture", "plain",
                            text=f"{basis}, by {mixture.source_document}."))
        for result in mixture.results:
            status = {"consistent": "ok", "inconsistent": "fix",
                      "cannot_tell": "check"}.get(result["verdict"], "na")
            family = result.get("family") or str(result.get("hazard_class") or "")
            calculated = result.get("calculated_class") or "no classification"
            stated = result.get("stated_class") or "nothing"
            sub.rows.append(Row(
                family, status, mixture=result,
                text=(result.get("message")
                      or f"Calculated {calculated}; Section 2 states {stated}."),
                action=(f"check {family}: the ingredients give {calculated}, "
                        f"Section 2 states {stated}"
                        if status in ("fix", "check") else "")))
    elif mixture is not None and (mixture.state == "not_applicable"
                                  or (mixture.state and found is None)):
        # Said in plain words: not applicable to a substance, can't be
        # calculated, or not run - never left blank.
        sub.rows.append(Row("Mixture",
                            "plain" if mixture.state == "not_applicable" else "na",
                            text=mixture.message))
    return sub


def _upcoming(report: Report) -> Sub:
    sub = Sub("Changes coming to Annex VI")
    notes = list(report.substance.upcoming if report.substance else [])
    notes += list(report.mixture.upcoming if report.mixture else [])
    for s in (report.ingredients.substances if report.ingredients else []) or []:
        notes += [f"{s.get('name') or s['cas']}: {n}" for n in s.get("upcoming") or []]
    for note in dict.fromkeys(notes):
        sub.rows.append(Row("23rd ATP", "info", text=note))
    return sub


def _statement_subs(report: Report, section: str, display: str) -> list[Sub]:
    verdicts = [v for v in report.statements if _where(v.section) == section]
    hazard = Sub("2.2 Label elements — signal word & hazard statements"
                 if section == "2" else "Signal word & hazard statements")
    prec = Sub("2.2 Label elements — precautionary statements"
               if section == "2" else "Precautionary statements")
    order = sorted(verdicts, key=lambda v: (v.code != "SIGNAL", v.code))
    for verdict in order:
        target = prec if verdict.code.startswith("P") else hazard
        target.rows.append(_statement_row(verdict, display))
    return [s for s in (hazard, prec) if s.rows]


def _ingredient_table(report: Report, display: str) -> dict | None:
    from lingua_oracle.ingredients.report import REASONS

    ing = report.ingredients
    found = report.substance
    if found is not None and found.state == "checked":
        list_heading = (f"{found.list_title} "
                        f"({'binding' if found.list_binding else 'reference only'})")
        missing = [r["code"] for r in found.codes if r["result"] == "fix"]
        extra = [r["code"] for r in found.codes if r["result"] == "info"]
        status = (("fix" if found.list_binding else "check") if missing else "ok")
        result = (f"Missing {', '.join(missing)}" if missing else
                  "Matches" + (f"; also classifies {', '.join(extra)}" if extra else ""))
        ref = (f" for {found.official_name.split(';')[0]} ({found.entry_index_no})"
               if found.entry_index_no else "")
        action = (f"add {', '.join(missing)}, which {found.list_title} requires{ref}"
                  if missing else "")
        return {"list_heading": list_heading, "rows": [{
            "name": found.name or found.official_name.split(";")[0],
            "cas": found.cas, "share": found.concentration,
            "sheet": " ".join(found.sheet_codes),
            "official": " ".join(found.official_codes),
            "row": Row(found.cas, status, text=result, action=action,
                       act_in="2")}]}
    if ing is None or not ing.substances:
        return None
    list_heading = (f"{ing.list_title} ({'binding' if ing.list_binding else 'reference only'})"
                    if ing.list_title else "Official list")
    rows = []
    for s in ing.substances:
        status = {"ok": "ok", "info": "ok", "not_checked": "na"}.get(s["status"])
        missing = s.get("missing_codes") or []
        if s["status"] == "fix":
            status = "fix" if ing.list_binding else "check"
        if status == "ok":
            text = "Matches"
        elif status == "fix":
            text = f"Missing {', '.join(missing)}"
        elif status == "check":
            # Somebody else's law: worth knowing, not a fault in the sheet.
            text = (f"{ing.list_title} lists {', '.join(missing)}; {display} has "
                    "no binding list")
        elif s.get("reason") == "sheet_gives_no_codes":
            text, status = "Listed — Section 3 prints no codes to compare", "info"
        else:
            text = REASONS.get(s.get("reason") or "", "Not checked")
        name = s.get("name") or s["cas"]
        sheet = sorted({c for cs in s.get("code_sets") or [] for c in cs.get("codes", [])}) \
            if s.get("code_sets") else []
        rows.append({
            "name": name, "cas": s["cas"], "share": s.get("concentration") or "",
            "sheet": " ".join(sheet), "official": " ".join(s.get("harmonised_codes") or []),
            "row": Row(s["cas"], status, text=text,
                       action=(f"add {', '.join(missing)} for {name} ({s['cas']}), "
                               f"as {ing.list_title or 'the list'} requires"
                               if status == "fix" else
                               f"compare {name} ({s['cas']}) with {ing.list_title}, "
                               f"which lists {', '.join(missing)}"
                               if status == "check" else ""))})
    return {"list_heading": list_heading, "rows": rows}


def _section_three(report: Report, display: str) -> Section:
    sec = Section("3", TITLES["3"])
    ing = report.ingredients
    if report.composition == "substance":
        sec.intro = ("Substance — the classification in Section 2 is compared "
                     "with the official entry for its CAS number. No mixture "
                     "calculation is needed.")
    elif ing is not None and ing.substances:
        where = ("from the ExactSDS record for this product" if ing.source == "app"
                 else "from Section 3 of this sheet")
        sec.intro = (f"Mixture — ingredients read {where}; each one’s codes "
                     "are compared with the official entry for its CAS number.")
    sec.table = _ingredient_table(report, display)
    if sec.table is None:
        message = (ing.message if ing is not None and ing.message else
                   "The ingredient check was not run." if ing is None else
                   "No ingredients with CAS numbers were found.")
        sec.subs.append(Sub("", [Row("Ingredients", "na", text=message)]))
    elif ing is not None and ing.message and report.composition != "substance":
        sec.subs.append(Sub("", [Row("Ingredients", "info", text=ing.message)]))
    sec.subs += _statement_subs(report, "3", display)
    return sec


def _section_nine(report: Report) -> Section:
    sec = Section("9", TITLES["9"])
    state = report.physical_state or (report.mixture.physical_state
                                      if report.mixture else "")
    use = ("used where the rules set different limits for gas and solid/liquid, "
           "and for the form inhalation toxicity is calculated in")
    text = {
        "gas": f"Gas — {use} (gas)",
        "liquid": f"Liquid — {use} (vapour)",
        "solid": f"Solid — {use} (dust/mist)",
        "solid/liquid": ("Solid or liquid — Section 9 does not say which; "
                         "inhalation toxicity is calculated both as a vapour and "
                         "as a dust/mist"),
    }.get(state, "Section 9 does not say whether this is a gas; where a limit "
                 "depends on it, both were tried")
    sec.subs.append(Sub("", [Row("Physical state", "ok" if state else "na",
                                 text=text)]))
    return sec


def _section_sixteen(report: Report, display: str) -> Section:
    sec = Section("16", TITLES["16"])
    full = Sub("")
    missing = [f for f in report.findings if f.check_id == "B-08"
               and not f.unverified]
    from lingua_oracle.keys.builders import section16

    rule = section16.load(report.regulation)
    if "16" not in report.sections_found:
        full.rows.append(Row("Full text of H-statements", "na",
                             text="No Section 16 was found in this document."))
    elif rule is None or rule.status == "pending_source":
        full.rows.append(Row("Full text of H-statements", "na",
                             text="Not checked: what this regulation asks of "
                                  "Section 16 is not on file."))
    elif rule.status == "no_rule":
        full.rows.append(Row("Full text of H-statements", "na",
                             text=f"Not required: {rule.citation} asks nothing "
                                  "of Section 16 about hazard statements."))
    elif not any(f.severity is Severity.FAIL for f in missing):
        full.rows.append(Row("Full text of H-statements", "ok",
                             text="Every statement Sections 2 to 15 give only as "
                                  "a code is written out here, as "
                                  f"{rule.citation} requires."))
    for finding in missing:
        row = _finding_row(finding, display)
        if row:
            full.rows.append(row)
    sec.subs.append(full)
    sec.subs += _statement_subs(report, "16", display)
    return sec


# -- the page --------------------------------------------------------------------

@dataclass
class Page:
    sections: list[Section]
    actions: list[str]
    stats: dict
    tone: str
    release: str
    detail: str
    nav: list[dict]


def build(report: Report, display: str, set_by: str) -> Page:
    sections: dict[str, Section] = {}
    label_only = report.sections_found == ["label"] or (
        report.sections_found and set(report.sections_found) <= {"label"})

    sections["1"] = _section_one(report, display, set_by)
    two = Section("2", TITLES["2"])
    classification = _classification(report, display)
    if classification.rows:
        two.subs.append(classification)
    upcoming = _upcoming(report)
    if upcoming.rows:
        two.subs.append(upcoming)
    two.subs += _statement_subs(report, "2", display)
    sections["2"] = two
    if label_only:
        label = Section("label", TITLES["label"])
        label.subs += _statement_subs(report, "label", display)
        sections["label"] = label
    else:
        label_subs = _statement_subs(report, "label", display)
        for sub in label_subs:
            sub.title = "Label — " + sub.title.split("—")[-1].strip()
        two.subs += label_subs
    sections["3"] = _section_three(report, display)
    sections["9"] = _section_nine(report)
    sections["16"] = _section_sixteen(report, display)

    # Findings that are not a statement's wording, each where it was found.
    others: dict[str, Sub] = {}
    for finding in report.findings:
        if finding.check_id == "B-08":
            continue
        row = _finding_row(finding, display)
        if row is None:
            continue
        where = ("1" if finding.check_id in _WHOLE_DOCUMENT
                 else _where(finding.section))
        if where == "label" and "label" not in sections:
            where = "2"
        title = "Whole document" if where == "1" else "Other checks"
        others.setdefault(where, Sub(title)).rows.append(row)
    for where, sub in others.items():
        sections[where].subs.append(sub)
    for sec in sections.values():
        sec.subs = [s for s in sec.subs if s.rows]

    order = ["1", "2", "label", "3", "9", "16"]
    shown = [sections[n] for n in order if n in sections]
    rows = [r for sec in shown for r in sec.rows]
    stats = {
        "must_fix": sum(1 for r in rows if r.status in ("fix", "wrong")),
        "to_check": sum(1 for r in rows if r.status == "check"),
        "correct": sum(1 for r in rows if r.status == "ok"),
        "sections": sum(1 for s in shown if s.number in CHECKED and s.judged),
        "codes_found": report.coverage.codes_found,
        "codes_checked": report.coverage.codes_checked,
        "codes_percent": (int(report.coverage.percent)
                          if float(report.coverage.percent).is_integer()
                          else report.coverage.percent),
    }
    actions = _actions(shown)
    # The release word comes from contradictions, as it always has: an
    # unfinished blank is a row to act on, not a reason to hold the sheet.
    holding = any(r.status in ("fix", "wrong") and not r.blank for r in rows)
    pending = stats["to_check"] or any(r.blank for r in rows)
    tone = "fix" if holding else "check" if pending else "ok"
    release = {"fix": labels.FIX, "check": labels.REVIEW, "ok": labels.READY}[tone]
    return Page(sections=shown, actions=actions, stats=stats, tone=tone,
                release=release, detail=_detail(shown), nav=_nav(shown))


def _actions(sections: list[Section]) -> list[str]:
    out: list[str] = []
    for urgency in (("fix", "wrong"), ("check",)):
        for sec in sections:
            where = "Label" if sec.number == "label" else f"Section {sec.number}"
            groups: dict[str, list[str]] = {}
            for row in sec.rows:
                if row.status not in urgency:
                    continue
                if row.group:
                    groups.setdefault(row.group, []).append(row.key)
                    continue
                if row.action:
                    line = (f"Section {row.act_in}: {row.action}" if row.act_in
                            else f"{where}: {row.action}")
                    if line not in out:
                        out.append(line)
            for template, keys in groups.items():
                listed = (", ".join(keys[:-1]) + " and " + keys[-1]
                          if len(keys) > 1 else keys[0])
                out.append(f"{where}: " + template.format(keys=listed))
    return out


def _detail(sections: list[Section]) -> str:
    """One sentence under the verdict, written from the rows on the page."""
    problems, clean = [], []
    for sec in sections:
        name = "the label" if sec.number == "label" else f"Section {sec.number}"
        blanks = sum(1 for r in sec.rows if r.blank)
        wrong = sec.count("fix", "wrong") - blanks
        checks = sec.count("check")
        parts = []
        if wrong:
            parts.append(labels.plural(wrong, "problem"))
        if checks:
            parts.append(f"{checks} to check")
        if blanks:
            parts.append(f"{labels.plural(blanks, 'blank')} to fill in")
        if parts:
            phrase = ", ".join(parts)
            problems.append(f"{phrase}{',' if phrase.endswith('fill in') else ''} in {name}")
        elif sec.judged and sec.number != "1":
            clean.append(name.replace("Section ", ""))
    out = "; ".join(problems) + "." if problems else ""
    if clean:
        tail = (f"Sections {', '.join(clean[:-1])} and {clean[-1]} are correct."
                if len(clean) > 1 else f"Section {clean[0]} is correct.")
        out = f"{out} {tail}".strip()
    return out or "Nothing on this document could be checked."


def _nav(sections: list[Section]) -> list[dict]:
    by_number = {s.number: s for s in sections}
    out: list[dict] = []

    def add(sec: Section) -> None:
        label = ("Label" if sec.number == "label"
                 else f"{sec.number} · {NAV[sec.number]}")
        out.append({"href": f"#{sec.anchor}", "label": label, "status": sec.status})

    add(by_number["1"])
    add(by_number["2"])
    if "label" in by_number:
        add(by_number["label"])
    add(by_number["3"])
    out.append({"href": None, "label": "4–8 · not checked", "status": "none"})
    add(by_number["9"])
    out.append({"href": None, "label": "10–15 · not checked", "status": "none"})
    add(by_number["16"])
    return out
