"""PDF extraction behind a swappable interface."""

from __future__ import annotations

import os

from lingua_oracle.extract.base import Document, Extractor, Line, Page
from lingua_oracle.extract.pdfplumber_backend import PdfplumberExtractor
from lingua_oracle.extract.pymupdf_backend import PyMuPDFExtractor

BACKENDS: dict[str, type] = {
    "pymupdf": PyMuPDFExtractor,
    "pdfplumber": PdfplumberExtractor,
}


def get_extractor(name: str | None = None) -> Extractor:
    chosen = name or os.environ.get("LINGUA_PDF_BACKEND", "pymupdf")
    try:
        return BACKENDS[chosen]()
    except KeyError:
        raise KeyError(
            f"Unknown PDF backend {chosen!r}. Available: {', '.join(sorted(BACKENDS))}"
        ) from None


def extract(path: str, backend: str | None = None) -> Document:
    """Read a PDF into a Document. Falls back to pdfplumber if PyMuPDF fails."""
    primary = get_extractor(backend)
    try:
        return primary.extract(path)
    except Exception:
        if backend is not None or primary.name == "pdfplumber":
            raise
        return PdfplumberExtractor().extract(path)


__all__ = ["BACKENDS", "Document", "Extractor", "Line", "Page", "extract", "get_extractor"]
