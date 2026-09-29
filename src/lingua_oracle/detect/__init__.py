"""Detection of regulation, language, sections and codes."""

from lingua_oracle.detect.codes import (
    CodeHit,
    canonical_code,
    extract_document_hits,
    extract_hits,
    split_combined,
)
from lingua_oracle.detect.language import detect_language, looks_untranslated
from lingua_oracle.detect.regulation import RegulationUndetermined, detect_regulation
from lingua_oracle.detect.sections import (
    LABEL,
    SectionSpan,
    detect_sections,
    lines_in,
    section_of,
)

__all__ = [
    "LABEL",
    "CodeHit",
    "RegulationUndetermined",
    "SectionSpan",
    "canonical_code",
    "detect_language",
    "detect_regulation",
    "detect_sections",
    "extract_document_hits",
    "extract_hits",
    "lines_in",
    "looks_untranslated",
    "section_of",
    "split_combined",
]
