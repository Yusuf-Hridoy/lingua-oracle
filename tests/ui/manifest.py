"""What each fixture is, and what the report is supposed to say about it.

One table, used three ways: to drive the browser tests, to label the review
page, and to keep the plain-words description next to the assertion it belongs
to. `plain` and `should_show` are written for a reviewer who does not read code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    name: str
    #: What to choose in the form. "" means "detect automatically".
    regulation: str = ""
    language: str = ""
    #: Regulation and language the report must end up showing.
    expect_regulation: str = "eu_clp"
    expect_language: str = "da"
    #: True when the document is correct and the report must show no failures.
    clean: bool = False
    #: (check id, severity, code) rows that must appear. code None = any.
    expect: tuple[tuple[str, str, str | None], ...] = ()
    plain: str = ""
    should_show: str = ""
    compare_with: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


CLEAN = "The document is correct. Nothing should be reported as a failure."

CASES: tuple[Case, ...] = (
    # -- correct documents ---------------------------------------------------
    Case("clean_eu_da", regulation="eu_clp", expect_regulation="eu_clp", expect_language="da", clean=True,
         plain="A correct Danish EU CLP safety data sheet.",
         should_show=CLEAN, tags=("clean",)),
    Case("clean_eu_en", regulation="eu_clp", expect_regulation="eu_clp", expect_language="en", clean=True,
         plain="A correct English EU CLP safety data sheet.",
         should_show=CLEAN, tags=("clean",)),
    Case("clean_osha_en", regulation="", expect_regulation="us_osha",
         expect_language="en", clean=True,
         plain="A correct English US OSHA safety data sheet.",
         should_show=CLEAN, tags=("clean",)),
    Case("clean_whmis_enfr", regulation="", expect_regulation="ca_whmis",
         expect_language="fr", clean=True,
         plain="A correct Canadian WHMIS sheet, in both English and French as "
               "Canada requires.",
         should_show=CLEAN + " Having the same statement twice, once per "
                             "language, is correct here and must not be reported.",
         tags=("clean",)),

    # -- one planted defect each ---------------------------------------------
    Case("defect_a01_signal", regulation="eu_clp",
         expect=(("A-01", "fail", "SIGNAL"),),
         plain="The signal word is wrong - the sheet says the wrong one of "
               "'Danger' / 'Warning'.",
         should_show="A-01 fails, showing the official signal word as Expected "
                     "and the sheet's word as Found."),
    Case("defect_a02_hazard", regulation="eu_clp",
         expect=(("A-02", "fail", "H225"),),
         plain="A hazard statement (H225) has been reworded.",
         should_show="A-02 fails for H225 in section 2, with the official "
                     "wording as Expected and the altered wording as Found."),
    Case("defect_a03_precautionary", regulation="eu_clp",
         expect=(("A-03", "fail", "P210"),),
         plain="A precautionary statement (P210) has been reworded.",
         should_show="A-03 fails for P210 in section 2, Expected and Found "
                     "differing."),
    Case("defect_a04_supplemental", regulation="eu_clp",
         expect=(("A-04", "fail", "EUH066"),),
         plain="A supplemental EU statement (EUH066) has been reworded.",
         should_show="A-04 fails for EUH066."),
    Case("defect_a05_english", regulation="eu_clp",
         expect=(("A-05", "fail", "H319"),),
         plain="One statement was left in English inside a Danish sheet.",
         should_show="A-05 fails for H319, and A-02 fails too because English "
                     "text cannot match the Danish official wording."),
    Case("defect_a06_placeholder", regulation="eu_clp",
         expect=(("A-06", "fail", None),),
         plain="The sheet still contains unfilled placeholder text.",
         should_show="A-06 fails, quoting the placeholder it found."),
    Case("defect_a07_broken", regulation="eu_clp",
         expect=(("A-07", "fail", None),),
         plain="The sheet contains broken or mis-encoded characters.",
         should_show="A-07 fails, quoting the damaged text."),
    Case("defect_b08_missing_s16", regulation="eu_clp",
         expect=(("B-08", "fail", "H336"),),
         plain="A hazard code appears on the label but is missing from "
               "section 16.",
         should_show="B-08 fails for H336."),
    Case("defect_b09_label", regulation="eu_clp",
         expect=(("B-09", "fail", "H336"),),
         plain="The label elements and section 2 disagree.",
         should_show="B-09 fails for H336."),
    Case("defect_b10_signal_fit", regulation="eu_clp",
         expect=(("B-10", "fail", "H225"),),
         plain="The signal word does not fit the hazard codes on the sheet.",
         should_show="B-10 fails, naming the code that requires a different "
                     "signal word."),
    Case("defect_c02_inconsistent", regulation="eu_clp",
         expect=(("C-02", "warn", "H336"),),
         plain="The same code is written two different ways in one document.",
         should_show="C-02 warns for H336, showing both wordings."),
    Case("defect_c12_euh_on_osha", regulation="",
         expect_regulation="us_osha", expect_language="en",
         expect=(("C-12", "fail", None),),
         plain="An EU-only statement (EUH) appears on a US OSHA sheet, where "
               "it does not belong.",
         should_show="C-12 fails, naming the code that is not valid for OSHA."),
    Case("defect_c14_english_only", regulation="",
         expect_regulation="ca_whmis", expect_language="en",
         clean=True, tags=("warnings",),
         expect=(("C-14", "warn", None),),
         plain="A Canadian WHMIS sheet in English only. Canada requires both "
               "English and French.",
         should_show="C-14 warns, asking whether the French version exists. It "
                     "never fails: the French sheet may be a separate file."),

    Case("defect_c15_newer_ghs", regulation="",
         expect_language="en",
         expect=(("C-15", "warn", "P317"), ("C-15", "fail", "P999")),
         plain="An EU CLP sheet citing P317 and P332+P317 - wording from GHS "
               "Rev.8, which CLP has not adopted - and a made-up code, P999.",
         should_show="C-15 warns for the two Rev.8 codes, naming the edition "
                     "and the closest statement CLP does publish, and fails "
                     "P999 as not a code at all."),

    Case("pattern_unfilled_blanks", regulation="", expect_regulation="us_osha",
         expect_language="en", clean=True, tags=("warnings",),
         expect=(("A-03", "fix", "P501"),),
         plain="An OSHA sheet issued with its placeholders still in it: P501 "
               "ends in a blank for the disposal route and P280 in a slash "
               "list with a trailing one.",
         should_show="Both read Fix this, on one column rather than two - the "
                     "wording is right, so there is no second version to "
                     "compare against. Only the ellipsis is highlighted, and "
                     "each card says what belongs in it."),
    Case("pattern_conditional_slots", regulation="", expect_regulation="ca_whmis",
         expect_language="en", clean=True, tags=("warnings",),
         expect=(("C-14", "warn", None),),
         plain="A Canadian WHMIS sheet in English only. H373 leaves out its "
               "\"if known\" parts and H302 ends with a full stop the GHS "
               "tables do not print.",
         should_show="No wording failures - both statements are correct. One "
                     "warning asking whether the French version exists. The "
                     "banner reads REVIEW BEFORE RELEASE."),
    Case("pattern_legend_after_statement", regulation="",
         expect_regulation="ca_whmis", expect_language="en", clean=True,
         tags=("warnings",),
         plain="A WHMIS sheet whose Section 16 ends with an abbreviation "
               "legend and a footnote marker, right after the statements.",
         should_show="No wording failures: the statements stop where they "
                     "stop and do not swallow the glossary."),
    Case("defect_c15_osha_partial_key", regulation="",
         expect_regulation="us_osha", expect_language="en", clean=True,
         tags=("warnings",),
         expect=(("C-15", "warn", "P317"),),
         plain="An OSHA sheet citing P317, P319 and P332+P317 - GHS Rev.8 "
               "wording that is nowhere in Appendix C - alongside P243, whose "
               "wording IS in Appendix C but is not yet in our records.",
         should_show="C-15 warns for the three Rev.8 codes. P243 is reported "
                     "as not checked, because that gap is ours, not the "
                     "sheet's."),

    # -- false alarms that were fixed; these must stay clean ------------------
    Case("pattern_negative_declaration", regulation="",
         expect_language="en", clean=True,
         plain="A non-hazardous sheet that says it needs no signal word and no "
               "statements.",
         should_show="No failures. Saying 'no signal word required' must not be "
                     "read as claiming a signal word.",
         tags=("regression",)),
    Case("pattern_reach_registration", regulation="eu_clp",
         expect_language="en", clean=True,
         plain="A sheet carrying a REACH registration number, which is printed "
               "in the form 01-2119485491-33-XXXX.",
         should_show="No failures. The XXXX is part of the published number, "
                     "not unfilled placeholder text.",
         tags=("regression",)),
    Case("pattern_spacing_variant", regulation="un_ghs",
         expect_regulation="un_ghs", expect_language="en", clean=True,
         expect=(("A-03", "fix", "P370+P378"),),
         plain="A sheet whose spacing differs from the official text: a space "
               "before an ellipsis, and '50 °C' instead of '50°C'. It also "
               "leaves one slot unfilled.",
         should_show="No failures - where the spaces fall is not a wording "
                     "defect. One warning, because the sheet still shows '…' "
                     "where a value belongs.",
         tags=("regression",)),
    Case("pattern_optional_fillin", regulation="un_ghs",
         expect_regulation="un_ghs", expect_language="en", clean=True,
         plain="A sheet that fills in the optional slot in 'Wash hands [and…] "
               "thoroughly after handling.'",
         should_show="No failures, and an info line showing the text that was "
                     "filled in so a person can check it.",
         tags=("regression",)),
    Case("pattern_osha_terminator", regulation="us_osha",
         expect_regulation="us_osha", expect_language="en", clean=True,
         plain="A US OSHA sheet that ends its statements with a full stop. "
               "OSHA's own published text has none.",
         should_show="No failures. The closing full stop is not a wording "
                     "change.",
         tags=("regression",)),
    Case("pattern_capitalisation", regulation="eu_clp",
         expect_language="en", clean=True,
         expect=(("A-03", "warn", "P303+P361+P353"),),
         plain="A sheet with odd capitals mid-sentence: 'Take off Immediately', "
               "'Rinse SKIN'. The words themselves are correct.",
         should_show="No failures, one warning saying it differs only in "
                     "capitalisation. It must never pass silently.",
         tags=("regression",)),
    Case("pattern_language_outside_regulation", regulation="",
         expect_regulation="un_ghs", expect_language="da", clean=True,
         plain="A Danish sheet issued against UN GHS. UN GHS is not published "
               "in Danish.",
         should_show="Language shown as 'da', no failures, and the codes with "
                     "no Danish source marked unverified rather than wrong.",
         tags=("regression",)),

    # -- the compare pair ----------------------------------------------------
    Case("compare_b11_a", regulation="eu_clp", expect_language="en",
         compare_with="compare_b11_b",
         expect=(("B-11", "fail", "H336"),),
         plain="Two versions of the same product in different languages, "
               "compared against each other.",
         should_show="B-11 fails: H336 is in one document and missing from the "
                     "other.",
         tags=("compare",)),
)

BY_NAME = {c.name: c for c in CASES}
