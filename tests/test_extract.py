"""PDF extraction, backend swapping, and line rejoining."""

from __future__ import annotations

import pytest

from lingua_oracle.extract import BACKENDS, extract, get_extractor
from lingua_oracle.extract.base import Line
from lingua_oracle.extract.rejoin import is_continuation, rejoin_lines, starts_new_block
from tests.conftest import pdf


@pytest.mark.parametrize("backend", sorted(BACKENDS))
def test_both_backends_read_the_same_statements(backend):
    document = extract(pdf("clean_eu_da"), backend=backend)
    assert document.backend == backend
    assert document.pages
    text = document.normalized_text
    assert "Meget brandfarlig væske og damp." in text
    assert "H225" in text


def test_get_extractor_rejects_unknown_backend():
    with pytest.raises(KeyError, match="Unknown PDF backend"):
        get_extractor("nope")


def test_lines_carry_page_and_bbox():
    document = extract(pdf("clean_eu_da"))
    line = document.lines[0]
    assert line.page == 1
    assert len(line.bbox) == 4


def test_label_page_is_a_second_page():
    document = extract(pdf("defect_b09_label"))
    assert len(document.pages) == 2
    assert any("ETIKET" in ln.text for ln in document.pages[1].lines)


def test_rejoin_merges_a_wrapped_sentence():
    lines = [Line("Holdes væk fra varme, gnister,", 1), Line("åben ild og andre", 1)]
    assert rejoin_lines(lines)[0].text == (
        "Holdes væk fra varme, gnister, åben ild og andre"
    )


def test_rejoin_does_not_swallow_a_heading():
    """The bug that broke section detection: headings must stay their own line."""
    lines = [Line("PUNKT 2: Fareidentifikation", 1), Line("Signalord: Fare", 1)]
    out = rejoin_lines(lines)
    assert len(out) == 2
    assert out[0].text == "PUNKT 2: Fareidentifikation"


def test_rejoin_repairs_hyphenation():
    lines = [Line("Meget brandfar-", 1), Line("lig væske og damp.", 1)]
    assert rejoin_lines(lines)[0].text == "Meget brandfarlig væske og damp."


def test_rejoin_never_crosses_a_page():
    lines = [Line("Holdes væk fra varme,", 1), Line("gnister og ild.", 2)]
    assert len(rejoin_lines(lines)) == 2


def test_starts_new_block():
    assert starts_new_block("H225 Highly flammable")
    assert starts_new_block("SECTION 2: Hazards identification")
    assert starts_new_block("Signalord: Fare")
    assert starts_new_block("ETIKET / LABEL")
    assert not starts_new_block("and vapour.")


def test_is_continuation():
    assert is_continuation("Highly flammable liquid", "and vapour.")
    assert not is_continuation("Highly flammable liquid and vapour.", "Keep away.")
    assert not is_continuation("Some text", "Signalord")
