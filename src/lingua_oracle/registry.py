"""Loader for data/regulations.yaml."""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


def data_dir() -> Path:
    """Repo `data/` directory, overridable with LINGUA_DATA_DIR."""
    import os

    env = os.environ.get("LINGUA_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data"


class Marker(BaseModel):
    """One way a sheet can name the regulation it follows."""

    model_config = ConfigDict(extra="forbid")

    pattern: str
    weight: int = 1


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
    #: True when the authority's own rendering omits the closing full stop, so
    #: a document that supplies one has not changed the wording. Set for
    #: us_osha only; see the note in data/regulations.yaml.
    statements_lack_terminal_punctuation: bool = False
    #: How to report a code this regulation has not adopted but a later GHS
    #: edition defines (check C-15). Whether a sheet may run ahead of the
    #: regulation it cites is a compliance decision, not a technical one, so it
    #: is set per regulation rather than assumed.
    newer_ghs_wording: Literal["warn", "info", "fail"] = "warn"
    #: The GHS edition this regulation's statements are taken from, as the GHS
    #: index labels it. Set only where that is a fact of the build, never
    #: inferred - it decides whether a code this edition has withdrawn should be
    #: reported as deleted.
    ghs_edition: str = ""
    source_url: str | None = None
    source_note: str | None = None
    #: Weighted markers that identify this regulation in a sheet's own words.
    #: Weight 3 names an instrument and can only mean one regulation; weight 1
    #: is context that supports a reading without making it.
    detect_markers: list[Marker] = Field(default_factory=list)

    def found_markers(self, text: str) -> list[tuple[str, int]]:
        """(what was found, weight) for every marker present, as written."""
        out: list[tuple[str, int]] = []
        for marker in self.detect_markers:
            match = re.search(marker.pattern, text, re.IGNORECASE)
            if match:
                out.append((" ".join(match.group(0).split()), marker.weight))
        return out


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
