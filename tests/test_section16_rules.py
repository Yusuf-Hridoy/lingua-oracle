"""What each regulation requires of Section 16, as read from its own text.

The files under data/section16/ are built by `lingua keys build section16`;
these tests read them and never the network.
"""

from __future__ import annotations

import pytest

from lingua_oracle.keys.builders import section16


@pytest.mark.parametrize(("regulation", "status", "where"), [
    ("eu_clp", "rule", "Annex II, Part A, Section 16(e)"),
    ("us_osha", "no_rule", "Table D.1, item 16"),
    ("ca_whmis", "no_rule", "Schedule 1, item 16"),
    ("un_ghs", "no_rule", "Annex 4, A4.3.16"),
    ("uk_clp", "rule", "Annex II, Part A, Section 16(e)"),
    ("au_whs", "pending_source", ""),
])
def test_each_regulation_has_its_own_finding(regulation, status, where):
    rule = section16.load(regulation)
    assert rule.status == status
    assert where in rule.section
    if status == "pending_source":
        assert rule.text == "" and rule.why     # nothing borrowed, and why
    else:
        assert rule.text                        # the passage read, quoted


def test_the_eu_rule_is_the_acts_own_sentence():
    rule = section16.load("eu_clp")
    assert "REACH" in rule.document and "02006R1907-" in rule.document
    assert rule.text.endswith("not written out in full under sections 2 to 15")


def test_a_passage_on_section_16_is_a_rule_only_if_it_says_one():
    said = section16._no_rule_or_rule(
        "x", "Act", "16", "(e) a list of relevant hazard statements and/or "
        "precautionary statements. Write out the full text of any statements, "
        "which are not written out in full under sections 2 to 15; (f) advice")
    silent = section16._no_rule_or_rule(
        "x", "Act", "16", "16. Other information The date of preparation.")
    assert said.status == "rule" and silent.status == "no_rule"
    assert silent.text == "16. Other information The date of preparation."


def test_the_gb_rule_is_read_from_the_gb_text_and_names_both_kinds():
    rule = section16.load("uk_clp")
    assert rule.document.startswith("GB REACH") and "legislation.gov.uk" in rule.document
    assert "hazard statements and/or precautionary statements" in rule.text
    assert rule.text.endswith("not written out in full under Sections 2 to 15")
