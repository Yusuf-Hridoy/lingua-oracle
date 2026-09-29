"""PyMuPDF extraction backend.

PyMuPDF is AGPL-licensed, so it sits behind the `Extractor` protocol and can be
swapped for the pdfplumber backend with `LINGUA_PDF_BACKEND=pdfplumber`.
"""

from __future__ import annotations

from lingua_oracle.extract.base import Document, Line, Page
from lingua_oracle.extract.rejoin import rejoin_lines


class PyMuPDFExtractor:
    name = "pymupdf"

    def extract(self, path: str) -> Document:
        import pymupdf

        doc = Document(path=str(path), backend=self.name)
        with pymupdf.open(path) as pdf:
            for index, page in enumerate(pdf, start=1):
                raw: list[Line] = []
                data = page.get_text("dict")
                for block in data.get("blocks", []):
                    for line in block.get("lines", []):
                        text = "".join(span.get("text", "") for span in line.get("spans", []))
                        if not text.strip():
                            continue
                        x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))
                        raw.append(Line(text=text, page=index, bbox=(x0, y0, x1, y1)))
                raw.sort(key=lambda ln: (round(ln.bbox[1], 1), ln.bbox[0]))
                doc.pages.append(Page(number=index, lines=rejoin_lines(raw)))
        return doc
