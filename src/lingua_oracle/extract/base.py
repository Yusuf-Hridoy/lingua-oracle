"""The document model that every extractor backend must produce."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from lingua_oracle.match.normalize import normalize


@dataclass
class Line:
    text: str
    page: int
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    @property
    def y(self) -> float:
        return self.bbox[1]


@dataclass
class Page:
    number: int
    lines: list[Line] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass
class Document:
    path: str
    pages: list[Page] = field(default_factory=list)
    backend: str = ""

    @property
    def lines(self) -> list[Line]:
        return [line for page in self.pages for line in page.lines]

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)

    @property
    def normalized_text(self) -> str:
        return normalize(self.text.replace("\n", " "))


@runtime_checkable
class Extractor(Protocol):
    name: str

    def extract(self, path: str) -> Document: ...
