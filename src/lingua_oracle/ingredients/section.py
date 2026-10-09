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
from lingua_oracle.ingredients.compare import Status, check_ingredient_on
from lingua_oracle.ingredients.from_pdf import (
    has_anything_to_check,
    ingredients_in_section_three,
)
from lingua_oracle.ingredients.matching import Match, match_product
from lingua_oracle.models import IngredientSection

NO_TABLE = ("Ingredient codes not printed on this sheet, nothing to check.")
NO_APP = ("ExactSDS not reachable, ingredient check skipped.")
PENDING = ("Choose the product above to check ingredients.")
NO_ENTRIES = ("None of the ingredients has an entry in the list this "
              "regulation is checked against, so there was nothing to check.")
LOOKED_UP = ("Section 3 prints no hazard codes, so nothing could be "
             "compared; each ingredient's official classification is shown.")
NO_LIST = ("No list of classified substances is on file for this regulation, "
           "so the ingredients were not checked against one.")


def _section_from(substances, source: str, **extra) -> IngredientSection:
    run = ingredient_report.new_run("")
    run.substances = substances
    counts = run.counts()
    section = IngredientSection(source=source, counts=counts, **extra)
    section.substances = ingredient_report.substance_payload(run)
    return section


def _substances_from(rows, table, index, *, name_of=None, upcoming=None):
    """Group (cas, codes) readings into the shape the report renders.

    `upcoming` is the list's adopted amendment that does not apply yet, if any.
    """
    from lingua_oracle.ingredients.report import SubstanceResult, Use

    uses: dict[str, list[tuple[int, tuple[str, ...]]]] = {}
    names: dict[str, str | None] = {}
    shares: dict[str, str | None] = {}
    for position, row in enumerate(rows):
        cas = (row.cas or "").strip()
        if not cas:
            continue
        uses.setdefault(cas, []).append(
            (position, tuple(sorted(set(row.h_codes)))))
        names.setdefault(cas, name_of(row) if name_of else getattr(row, "name", None))
        shares.setdefault(cas, getattr(row, "concentration", None))

    out = []
    for cas in sorted(uses):
        verdicts = {
            codes: check_ingredient_on(cas, list(codes), table, index,
                                       upcoming=upcoming)
            for codes in {c for _position, c in uses[cas]}
        }
        out.append(SubstanceResult(
            cas=cas, name=names.get(cas), concentration=shares.get(cas),
            uses=[Use(product_id=position, codes=codes, verdict=verdicts[codes])
                  for position, codes in uses[cas]]))
    return out


def _looked_up(rows, table, index):
    """One result per CAS number Section 3 prints, each its entry, unjudged."""
    from lingua_oracle.ingredients.compare import look_up
    from lingua_oracle.ingredients.report import SubstanceResult, Use

    out = []
    for position, row in enumerate(rows):
        cas = (row.cas or "").strip()
        if not cas or any(s.cas == cas for s in out):
            continue
        out.append(SubstanceResult(
            cas=cas, name=row.name, concentration=row.concentration, uses=[
                Use(product_id=position, codes=(), verdict=look_up(cas, table, index))]))
    return out


def check(path: str, file_name: str, lines, *, client_factory=None,
          regulation: str | None = None, product_id: int | None = None
          ) -> IngredientSection:
    """The ingredient section for one uploaded document.

    An ingredient is judged against the list the sheet's own regulation
    publishes - Annex VI for the EU, the GB MCL for Great Britain, HCIS for
    Australia - and whether a difference from it is a fault depends on whether
    that regulation makes the list binding. Where a regulation has no list,
    nothing is borrowed from another one.

    `product_id` forces the match, which is what a reader choosing between
    candidates does: the same report is recalculated against the product they
    named, without uploading anything again.
    """
    from lingua_oracle.ingredients.client import session
    from lingua_oracle.substances.load import for_check
    from lingua_oracle.substances.upcoming import for_list

    use, table = for_check(regulation)
    if use is None or table is None:
        return IngredientSection(source="nothing", message=NO_LIST)
    index = table.by_cas()
    upcoming = for_list(use.name)
    about_list = {"list_name": use.name, "list_title": use.title,
                  "list_binding": use.binding, "list_authority": use.authority}

    client = None
    match = Match(state="unavailable", evidence="ExactSDS was not reached")
    try:
        if client_factory is not None:
            client = client_factory()
            client.login()
        else:
            client = session()
        if product_id is not None:
            detail = client.product(product_id) or {}
            match = Match(state="matched", product_id=product_id,
                          name=detail.get("product_name"),
                          evidence="chosen by you")
        else:
            match = match_product(client, file_name, lines, regulation)
    except Exception as exc:  # noqa: BLE001
        # Anything at all here means the application is not answering. The
        # wording check has already run and must not be lost over it.
        match = Match(state="unavailable",
                      evidence=f"ExactSDS could not be reached: {exc}"[:200])

    try:
        if match.state == "matched" and client is not None:
            rows = client.ingredients(match.product_id)
            substances = _substances_from(rows, table, index,
                                          name_of=lambda row: row.name,
                                          upcoming=upcoming)
            section = _section_from(
                substances, "app", match_state=match.state,
                product_id=match.product_id, product_name=match.name,
                evidence=match.evidence, **about_list)
            if not section.checked_anything:
                section.message = NO_ENTRIES
            return section
    finally:
        # The session is shared and stays open; a client the caller supplied is
        # the caller's to close.
        if client is not None and client_factory is not None:
            client.close()

    # Several products could be this sheet. Nothing is calculated until a
    # person says which: a guess here would be shown as fact.
    if match.state == "ambiguous":
        return IngredientSection(
            source="nothing", match_state=match.state, evidence=match.evidence,
            message=PENDING, **about_list,
            candidates=[{"product_id": c.product_id, "name": c.name,
                         "regulation": c.regulation}
                        for c in match.candidates])

    # Not one of ours, or the application could not say: read the sheet.
    rows = ingredients_in_section_three(path)
    if not has_anything_to_check(rows) and any(r.cas for r in rows):
        # Names and CAS numbers without codes: nothing to compare, but each
        # ingredient's entry is still worth showing.
        substances = _looked_up(rows, table, index)
        section = _section_from(
            substances, "pdf", match_state=match.state, evidence=match.evidence,
            candidates=[{"product_id": c.product_id, "name": c.name}
                        for c in match.candidates], **about_list)
        section.message = LOOKED_UP
        return section
    if not has_anything_to_check(rows):
        message = NO_APP if match.state == "unavailable" else NO_TABLE
        return IngredientSection(
            source="skipped" if match.state == "unavailable" else "nothing",
            match_state=match.state, evidence=match.evidence, message=message,
            candidates=[{"product_id": c.product_id, "name": c.name}
                        for c in match.candidates], **about_list)

    substances = _substances_from(rows, table, index, upcoming=upcoming)
    section = _section_from(
        substances, "pdf", match_state=match.state, evidence=match.evidence,
        candidates=[{"product_id": c.product_id, "name": c.name}
                    for c in match.candidates], **about_list)
    if not section.checked_anything:
        section.message = NO_ENTRIES
    return section


def worst(section: IngredientSection | None) -> Status | None:
    """The hardest thing this section has to say, for the overall verdict.

    A code missing against a binding list is a fault in the sheet. The same
    code missing against a list the regulation does not adopt is worth
    checking and nothing more: no one is obliged to follow another
    jurisdiction's classification.
    """
    if section is None or not section.counts:
        return None
    if section.counts.get("fix"):
        return Status.FIX if section.list_binding else Status.INFO
    if section.counts.get("inconsistent_substances"):
        return Status.INFO
    if section.counts.get("with_entry"):
        return Status.OK
    return None


def recheck(report, product_id: int, *, client_factory=None):
    """Recalculate the ingredient and mixture halves against a chosen product.

    Nothing from the uploaded file is needed: the composition comes from the
    application, and what Section 2 states was kept on the report when it was
    first checked. So a reader choosing between candidates gets the same report
    page filled in, rather than being asked to upload again.
    """
    from lingua_oracle.ingredients.client import session
    from lingua_oracle.mixture import section as mixture_section
    from lingua_oracle.substances.load import for_check
    from lingua_oracle.substances.upcoming import for_list

    client = (client_factory() if client_factory else session())
    if client_factory is not None:
        client.login()
    detail = client.product(product_id) or {}
    rows = client.ingredients(product_id)

    use, table = for_check(report.regulation)
    index = table.by_cas() if table else {}
    upcoming = for_list(use.name) if use else None
    substances = _substances_from(rows, table, index,
                                  name_of=lambda row: row.name,
                                  upcoming=upcoming) if table else []
    section = _section_from(
        substances, "app", match_state="matched", product_id=product_id,
        product_name=detail.get("product_name"), evidence="chosen by you",
        list_name=use.name if use else "", list_title=use.title if use else "",
        list_binding=bool(use and use.binding),
        list_authority=use.authority if use else "")
    if not section.checked_anything:
        section.message = NO_ENTRIES
    report.ingredients = section

    report.mixture = mixture_section.build(
        mixture_section.rows_from_app(rows), [], [], report.regulation, table,
        stated_override=(report.mixture.stated if report.mixture else []),
        state_override=(report.mixture.physical_state if report.mixture
                        else None),
        upcoming=upcoming)
    if report.hcodes is not None and report.hcodes.state != "skipped":
        # The codes, judged on the chosen product's composition with the
        # app's stored codes as input A - the sheet's context was kept.
        from lingua_oracle.reference import composition, verdict

        found, app_codes = composition.from_app(rows)
        report.hcodes = verdict.rebuild(
            report.hcodes, report.regulation, found, app_codes=app_codes,
            state=(report.mixture.physical_state if report.mixture else None) or None)
    if client_factory is not None:
        client.close()
    return report
