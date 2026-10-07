"""Every report names the sources it was judged against, with their versions."""

from __future__ import annotations

from lingua_oracle.ingredients import report as ingredient_report
from lingua_oracle.keys.builders import sources
from lingua_oracle.keys.builders.substance_lists import CATALOGUES
from lingua_oracle.models import Report
from lingua_oracle.pipeline import check_pdf
from lingua_oracle.report.render import render_html
from tests.conftest import pdf
from tests.test_combined_report import FakeApp

EU = "EU CLP, Regulation (EC) No 1272/2008, consolidated version of 01/07/2026"


def test_every_source_names_its_version():
    for source in sources.SOURCES:
        assert source.version, source.path


def test_the_eu_consolidation_is_named_by_its_date():
    assert sources.eu_clp_version("02008R1272-20260701") == EU


def test_an_unrecognised_revision_is_printed_as_it_is():
    assert sources.eu_clp_version("something-else").endswith("something-else")


def test_the_list_files_are_the_ones_the_lists_are_built_from():
    # Two tables name the same files; this keeps them from drifting apart.
    assert {c.name: c.source for c in CATALOGUES} == sources._LIST_SOURCES


def test_eu_names_one_consolidation_for_all_three_halves():
    lines = sources.used(
        "eu_clp", "da", "02008R1272-20260701",
        ingredient_list="annex_vi", annex_vi_source="02008R1272-20260701",
        mixture_document="Regulation (EC) No 1272/2008, consolidated "
                         "02008R1272-20260701")
    assert lines == [
        f"Wording: {EU}",
        f"Ingredients: CLP Annex VI Part 3, Table 3, from the {EU}",
        f"Mixture rules: Annex I of {EU}",
    ]


def test_gb_names_the_mcl_list_by_its_version():
    lines = sources.used("uk_clp", "en", "retained-1272-2008",
                         ingredient_list="gb_mcl",
                         mixture_document="Regulation (EC) No 1272/2008 as "
                                          "retained in GB law")
    assert "Ingredients: GB MCL list, 8th version (file last modified " \
           "2026-05-19)" in lines
    assert any(line.startswith("Mixture rules: GB CLP") and "2026-09-29" in line
               for line in lines)


def test_australia_names_the_hcis_export_by_its_date():
    lines = sources.used("au_whs", "en", "GHS-Rev7-AU", ingredient_list="au_hcis")
    assert "Wording: UN GHS Rev.7 (2017), English edition" in lines
    assert any("HCIS export 2026-10-07" in line for line in lines)


def test_canada_names_the_edition_the_hpr_incorporates():
    wording = sources.used("ca_whmis", "fr", "SOR-2015-17")
    assert wording[0] == (
        "Wording: UN GHS Rev.7 (2017), English and French editions, as "
        "incorporated by the Hazardous Products Regulations (SOR/2015-17), "
        "current to 2026-09-21, last amended 2022-12-15")
    assert "Rev.8 (2019), for chemicals under pressure" in wording[1]


def test_osha_says_where_its_codes_came_from():
    lines = sources.used("us_osha", "en", "29-CFR-1910.1200-AppC",
                         mixture_document="29 CFR 1910.1200 Appendix A")
    assert lines[0].startswith("Wording: OSHA 29 CFR 1910.1200 Appendix C")
    assert lines[1].startswith("Statement codes: matched against UN GHS Rev.7")
    assert lines[2] == ("Mixture rules: OSHA 29 CFR 1910.1200 Appendix A "
                        "(osha.gov), on file since 2026-10-06")


def test_un_ghs_names_the_edition_in_the_documents_language():
    assert sources.used("un_ghs", "es", "Rev.11") == [
        "Wording: UN GHS Rev.11 (2025), Spanish edition"]


def test_a_regulation_without_text_says_so():
    assert sources.used("jp_jis", "ja", "JIS-Z-7253-2019") == [
        "Wording: no official text on file for this regulation and language"]


def test_a_report_names_only_what_it_used():
    report = check_pdf(pdf("clean_eu_da"))
    assert report.sources == [f"Wording: {EU}"]


def test_the_ingredient_halves_add_their_sources_when_they_run():
    report = check_pdf(pdf("pattern_supplier_ingredients"),
                       ingredients=True, client_factory=lambda: FakeApp())
    assert report.ingredients.source == "pdf"
    assert any(line.startswith("Ingredients: CLP Annex VI")
               for line in report.sources)
    assert f"Mixture rules: Annex I of {EU}" in report.sources


def test_technical_details_show_the_sources():
    page = render_html(check_pdf(pdf("clean_eu_da")))
    assert "Sources used" in page
    assert "consolidated version of 01/07/2026" in page


def test_a_report_saved_before_sources_were_recorded_still_renders():
    report = check_pdf(pdf("clean_eu_da"))
    stored = report.model_dump(mode="json")
    del stored["sources"]
    page = render_html(Report.model_validate(stored))
    assert "Sources used" not in page


def test_the_library_ingredient_report_names_its_annex_vi_version():
    run = ingredient_report.new_run("02008R1272-20260701")
    page = ingredient_report.render_html(run)
    assert "Sources used" in page
    assert f"CLP Annex VI Part 3, Table 3, from the {EU}" in page
