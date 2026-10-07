"""What the courts annulled is not held against a sheet.

Titanium dioxide's Table 3 row and the statements EUH211 and EUH212 were
annulled with Delegated Regulation (EU) 2020/217 (notice C/2025/6670). The
consolidation the keys are built from still prints them.
"""

from __future__ import annotations

from lingua_oracle.ingredients.compare import Reason, Status, check_ingredient
from lingua_oracle.keys.builders import annulled
from lingua_oracle.keys.builders.annex_vi import load_table
from lingua_oracle.keys.store import load_key
from lingua_oracle.keys.tierb import resolve
from lingua_oracle.models import Status as KeyStatus

TITANIUM_DIOXIDE = "13463-67-7"


def test_it_applies_until_the_consolidation_that_drops_them():
    assert annulled.applies_to("02008R1272-20260701")
    assert not annulled.applies_to("02008R1272-20270101")
    assert not annulled.applies_to("02008R1272-20270201")


def test_the_titanium_dioxide_row_is_not_in_table_3():
    table = load_table()
    assert "022-006-00-2" not in {e.index_no for e in table.entries}
    assert "Left out as annulled: 022-006-00-2" in table.note


def test_a_sheet_without_h351_for_titanium_dioxide_is_not_under_classified():
    table = load_table()
    verdict = check_ingredient(TITANIUM_DIOXIDE, [], table)
    assert verdict.status is Status.NOT_CHECKED
    assert verdict.reason is Reason.NO_ENTRY


def test_euh211_and_euh212_are_kept_visible_and_never_judged_with():
    for language in ("en", "de", "ga"):
        key = load_key("eu_clp", language)
        held = {e.code: e for e in key.entries}
        reference = resolve("eu_clp", language).entries
        for code in sorted(annulled.STATEMENTS):
            assert held[code].status is KeyStatus.NOT_ON_FILE, (language, code)
            assert "C/2025/6670" in held[code].source_ref
            assert code not in reference, (language, code)


def test_euh210_which_refers_to_them_is_untouched():
    key = load_key("eu_clp", "en")
    euh210 = next(e for e in key.entries if e.code == "EUH210")
    assert euh210.status is KeyStatus.OK
