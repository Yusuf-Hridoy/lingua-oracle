"""The ingredient half of one upload.

Given an uploaded document, this decides which of three things can be done and
does it: check the product's record in ExactSDS, check what the sheet's own
Section 3 prints, or say plainly that there was nothing to check. It never
fails the upload - the wording check is the part that must always run, and an
application that cannot be reached is a fact about the application, not a
finding about the document.
"""

from __future__ import annotations

from lingua_oracle.ingredients import report as ingredient_report
from lingua_oracle.ingredients.compare import Status, check_ingredient
from lingua_oracle.ingredients.from_pdf import (
    has_anything_to_check,
    ingredients_in_section_three,
)
from lingua_oracle.ingredients.matching import Match, match_product
from lingua_oracle.models import IngredientSection

NO_TABLE = ("Ingredient codes not printed on this sheet, nothing to check.")
NO_APP = ("ExactSDS not reachable, ingredient check skipped.")
NO_ENTRIES = ("None of the ingredients has a harmonised entry in Annex VI "
              "Table 3, so there was nothing to check against.")


def _section_from(substances, source: str, **extra) -> IngredientSection:
    run = ingredient_report.new_run("")
    run.substances = substances
    counts = run.counts()
    section = IngredientSection(source=source, counts=counts, **extra)
    section.substances = ingredient_report.substance_payload(run)
    return section


def _substances_from(rows, table, index, *, name_of=None):
    """Group (cas, codes) readings into the shape the report renders."""
    from lingua_oracle.ingredients.report import SubstanceResult, Use

    uses: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    names: dict[str, str | None] = {}
    for position, row in enumerate(rows):
        cas = (row.cas or "").strip()
        if not cas:
            continue
        uses.setdefault(cas, []).append(
            (position, tuple(sorted(set(row.h_codes)))))
        names.setdefault(cas, name_of(row) if name_of else None)

    out = []
    for cas in sorted(uses):
        verdicts = {
            codes: check_ingredient(cas, list(codes), table, index)
            for codes in {c for _position, c in uses[cas]}
        }
        out.append(SubstanceResult(
            cas=cas, name=names.get(cas),
            uses=[Use(product_id=position, codes=codes, verdict=verdicts[codes])
                  for position, codes in uses[cas]]))
    return out


def check(path: str, file_name: str, lines, *, client_factory=None
          ) -> IngredientSection:
    """The ingredient section for one uploaded document."""
    from lingua_oracle.ingredients.client import ExactSdsClient
    from lingua_oracle.keys.builders.annex_vi import load_table

    table = load_table()
    if table is None:
        return IngredientSection(
            source="skipped", message="No Annex VI table on file; run "
                                      "`lingua keys build annex_vi`.")
    index = table.by_cas()

    client = None
    match = Match(state="unavailable", evidence="ExactSDS was not reached")
    try:
        client = (client_factory or ExactSdsClient)()
        client.login()
        match = match_product(client, file_name, lines)
    except Exception as exc:  # noqa: BLE001
        # Anything at all here means the application is not answering. The
        # wording check has already run and must not be lost over it.
        match = Match(state="unavailable",
                      evidence=f"ExactSDS could not be reached: {exc}"[:200])

    try:
        if match.state == "matched" and client is not None:
            rows = client.ingredients(match.product_id)
            substances = _substances_from(rows, table, index,
                                          name_of=lambda row: row.name)
            section = _section_from(
                substances, "app", match_state=match.state,
                product_id=match.product_id, product_name=match.name,
                evidence=match.evidence)
            if not section.checked_anything:
                section.message = NO_ENTRIES
            return section
    finally:
        if client is not None:
            client.close()

    # Not one of ours, or the application could not say: read the sheet.
    rows = ingredients_in_section_three(path)
    if not has_anything_to_check(rows):
        message = NO_APP if match.state == "unavailable" else NO_TABLE
        return IngredientSection(
            source="skipped" if match.state == "unavailable" else "nothing",
            match_state=match.state, evidence=match.evidence, message=message,
            candidates=[{"product_id": c.product_id, "name": c.name}
                        for c in match.candidates])

    substances = _substances_from(rows, table, index)
    section = _section_from(
        substances, "pdf", match_state=match.state, evidence=match.evidence,
        candidates=[{"product_id": c.product_id, "name": c.name}
                    for c in match.candidates])
    if not section.checked_anything:
        section.message = NO_ENTRIES
    return section


def worst(section: IngredientSection | None) -> Status | None:
    """The hardest thing this section has to say, for the overall verdict."""
    if section is None or not section.counts:
        return None
    if section.counts.get("fix"):
        return Status.FIX
    if section.counts.get("inconsistent_substances"):
        return Status.INFO
    if section.counts.get("with_entry"):
        return Status.OK
    return None
