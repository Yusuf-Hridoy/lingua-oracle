"""Loader for data/regulations.yaml."""

from __future__ import annotations

import functools
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


def data_dir() -> Path:
    """Repo `data/` directory, overridable with LINGUA_DATA_DIR."""
    import os

    env = os.environ.get("LINGUA_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data"


class Regulation(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    display_name: str
    revision: str
    authority: str = ""
    official_languages: list[str] = Field(default_factory=list)
    required_languages: list[str] = Field(default_factory=list)
    supplemental_prefixes: list[str] = Field(default_factory=list)
    allowed_prefixes: list[str] = Field(default_factory=lambda: ["H", "P"])
    signal_words: list[str] = Field(default_factory=list)
    source_url: str | None = None
    source_note: str | None = None
    detect_patterns: list[str] = Field(default_factory=list)

    def matches(self, text: str) -> int:
        """Number of detect patterns present in `text`."""
        return sum(1 for p in self.detect_patterns if re.search(p, text, re.IGNORECASE))


class Registry(BaseModel):
    regulations: dict[str, Regulation]

    def get(self, reg_id: str) -> Regulation:
        try:
            return self.regulations[reg_id]
        except KeyError:
            raise KeyError(
                f"Unknown regulation {reg_id!r}. Known: {', '.join(sorted(self.regulations))}"
            ) from None

    def ids(self) -> list[str]:
        return sorted(self.regulations)


@functools.lru_cache(maxsize=1)
def load_registry() -> Registry:
    path = data_dir() / "regulations.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    regs = {k: Regulation(id=k, **v) for k, v in raw["regulations"].items()}
    return Registry(regulations=regs)
