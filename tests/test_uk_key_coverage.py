"""What the GB key holds, measured against the EU key it is retained from.

GB CLP is retained EU law. Everything the EU had at retention, Great Britain
has too, so a code in the EU key and not in the GB one is either a gap in the
reading or an EU statement made after retention - and those are different
enough to be worth telling apart automatically.

Four statements were lost to the first: H200, H250, H290 and H318, whose
multilingual tables break across a page with the header - the code, the word
"Language", the hazard class - left at the foot of the page before as loose
text rather than as a table row. H318's code also had an amendment marker
glued to its front, "[F50H318", which leaves it with no word boundary to be
found by.
"""

from __future__ import annotations

import re

import pytest

from lingua_oracle.keys.store import load_key

#: EU statements made after Great Britain retained CLP. Each is absent from
#: the GB act, which is why it is absent from the key: the test below checks
#: the act rather than taking the list on trust.
AFTER_RETENTION = (
    "EUH211", "EUH212",   # Regulation (EU) 2020/1677
    "EUH380", "EUH381", "EUH430", "EUH431",
    "EUH440", "EUH441", "EUH450", "EUH451",
)


def codes(regulation: str) -> set[str]:
    return {entry.code for entry in load_key(regulation, "en").entries}


def test_every_hazard_statement_the_eu_key_has_is_in_the_uk_key():
    """H codes only: the supplemental EUH statements are tested separately,
    because that is where the genuine post-retention divergence lives."""
    missing = sorted(c for c in codes("eu_clp") - codes("uk_clp")
                     if re.fullmatch(r"H\d{3}[A-Za-z]*", c))
    assert not missing, f"GB key is missing {missing}"


@pytest.mark.parametrize("code", ["H200", "H250", "H290", "H318"])
def test_the_four_statements_lost_to_a_page_break(code):
    """Each one's table begins on a page whose header row is not a table row."""
    entry = next(e for e in load_key("uk_clp", "en").entries if e.code == code)
    assert entry.text
    assert entry.text == next(e.text for e in load_key("eu_clp", "en").entries
                              if e.code == code)


def test_a_combination_with_an_optional_member_is_its_own_code():
    """"P370 + P380 + P375[+ P378]" is not "P370 + P380 + P375", and the GB
    act prints both. The code cell pattern used to reject the bracketed one."""
    uk = codes("uk_clp")
    assert "P370+P380+P375" in uk
    assert "P370+P380+P375[+P378]" in uk


def test_what_is_left_is_only_what_the_gb_act_does_not_contain():
    """The remaining difference is EU statements made after retention. The
    evidence is the act: none of them is printed on any of its 663 pages."""
    import pymupdf

    from lingua_oracle.keys.builders.pdf_tables import strip_amendment
    from lingua_oracle.keys.builders.sources import BY_PATH

    absent = sorted(codes("eu_clp") - codes("uk_clp"))
    assert absent == sorted(AFTER_RETENTION), absent

    path = BY_PATH["uk-gb-clp/gb_clp_full.pdf"].where
    if not path.exists():
        pytest.skip(f"{path} is a source document and is not committed")
    document = pymupdf.open(str(path))
    try:
        pages = [strip_amendment(document[i].get_text())
                 for i in range(document.page_count)]
    finally:
        document.close()
    for code in absent:
        found = [i + 1 for i, text in enumerate(pages) if code in text]
        assert not found, f"{code} is in the GB act on pages {found}"
