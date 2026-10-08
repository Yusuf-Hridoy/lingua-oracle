"""Two things the structure reader needs from extraction, and one it must not
change for everything else."""

from __future__ import annotations

from lingua_oracle.detect.sections import detect_sections
from lingua_oracle.extract import extract
from lingua_oracle.extract.base import Document, Line, Page
from tests.make_fixtures import Sheet


def test_a_page_keeps_its_lines_as_drawn_beside_the_joined_ones(tmp_path):
    sheet = Sheet(tmp_path / "raw.pdf")
    sheet.line("H302 Harmful if swallowed")
    sheet.line("2 Hazard identification")         # opens with no capital
    sheet.save()
    document = extract(str(tmp_path / "raw.pdf"))
    assert [ln.text for ln in document.lines] == [
        "H302 Harmful if swallowed 2 Hazard identification"]
    assert [ln.text for ln in document.raw_lines] == [
        "H302 Harmful if swallowed", "2 Hazard identification"]


def test_a_sub_section_heading_is_not_a_section_heading():
    lines = ["SECTION 2: Hazards identification", "H225 Text.",
             "SECTION 9: Physical and chemical properties", "9.2. Other information",
             "SECTION 16: Other information", "H225 Text."]
    document = Document(path="x", pages=[Page(1, [Line(t, 1) for t in lines])])
    spans = {s.name: s.start for s in detect_sections(document, "en")}
    assert spans["16"] == 4                       # not line 3, "9.2. Other information"
