"""pdfplumber extraction backend (non-AGPL fallback)."""

from __future__ import annotations

from lingua_oracle.extract.base import Document, Line, Page
from lingua_oracle.extract.rejoin import rejoin_lines


class PdfplumberExtractor:
    name = "pdfplumber"

    def extract(self, path: str) -> Document:
        import pdfplumber

        doc = Document(path=str(path), backend=self.name)
        with pdfplumber.open(path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                raw: list[Line] = []
                words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
                buckets: dict[float, list[dict]] = {}
                for word in words:
                    key = round(word["top"], 1)
                    buckets.setdefault(key, []).append(word)
                for top in sorted(buckets):
                    group = sorted(buckets[top], key=lambda w: w["x0"])
                    text = " ".join(w["text"] for w in group)
                    if not text.strip():
                        continue
                    raw.append(
                        Line(
                            text=text,
                            page=index,
                            bbox=(group[0]["x0"], top, group[-1]["x1"], group[-1]["bottom"]),
                        )
                    )
                doc.pages.append(Page(number=index, lines=rejoin_lines(raw), raw_lines=raw))
        return doc
