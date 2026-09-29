"""Language detection via lingua-py.

Used for two jobs: the document's own language, and (for check A-05) whether an
individual phrase has been left in English inside a translated document.
"""

from __future__ import annotations

import functools

# `lingua` here is the lingua-py language detector, not this package.
from lingua import Language, LanguageDetectorBuilder

from lingua_oracle.match.normalize import normalize

# BCP-47 tag -> lingua-py Language, for every language the tool supports.
_TAGS: dict[str, str] = {
    "bg": "BULGARIAN", "cs": "CZECH", "da": "DANISH", "de": "GERMAN", "el": "GREEK",
    "en": "ENGLISH", "es": "SPANISH", "et": "ESTONIAN", "fi": "FINNISH", "fr": "FRENCH",
    "ga": "IRISH", "hr": "CROATIAN", "hu": "HUNGARIAN", "it": "ITALIAN",
    "lt": "LITHUANIAN", "lv": "LATVIAN", "nl": "DUTCH", "pl": "POLISH",
    "pt": "PORTUGUESE", "ro": "ROMANIAN", "sk": "SLOVAK", "sl": "SLOVENE",
    "sv": "SWEDISH", "ru": "RUSSIAN", "ar": "ARABIC", "zh": "CHINESE", "ja": "JAPANESE",
}
# Languages lingua-py has no model for; they can still be named with a flag.
UNSUPPORTED_BY_DETECTOR = {"mt"}


def tag_to_language(tag: str) -> Language | None:
    name = _TAGS.get(tag.lower().split("-")[0])
    return getattr(Language, name, None) if name else None


def language_to_tag(language: Language) -> str | None:
    # lingua-py's Language is a pyo3-backed enum whose members do not survive
    # `is` comparison between lookups, so compare with `==`.
    for tag, name in _TAGS.items():
        member = getattr(Language, name, None)
        if member is not None and member == language:
            return tag
    return None


@functools.lru_cache(maxsize=4)
def _detector(tags: tuple[str, ...] | None = None):
    if tags:
        langs = [lang for t in tags if (lang := tag_to_language(t))]
        if len(langs) >= 2:
            return LanguageDetectorBuilder.from_languages(*langs).build()
    return LanguageDetectorBuilder.from_all_languages().build()


def detect_language(text: str, flag: str | None = None,
                    candidates: tuple[str, ...] | None = None) -> tuple[str, str]:
    """Return (bcp47_tag, "flag" | "auto"). Falls back to 'en' on no signal."""
    if flag:
        return flag.lower(), "flag"
    body = normalize(text)[:20000]
    if not body:
        return "en", "auto"
    result = _detector(candidates).detect_language_of(body)
    if result is None:
        return "en", "auto"
    return language_to_tag(result) or "en", "auto"


def looks_untranslated(text: str, doc_language: str, *, min_chars: int = 25,
                       margin: float = 0.15) -> bool:
    """True when a phrase looks like English left behind in a non-English document.

    Absolute confidence thresholds do not work here: lingua-py returns a relative
    distribution, so a correct English sentence of SDS length scores well under
    0.7. Instead English is compared against the document's own language and must
    win by a clear margin. Short strings are skipped because per-phrase detection
    is unreliable below roughly this length.
    """
    doc_tag = doc_language.lower().split("-")[0]
    if doc_tag == "en":
        return False
    body = normalize(text)
    if len(body) < min_chars:
        return False
    target = tag_to_language(doc_tag)
    if target is None:
        return False
    values = _detector().compute_language_confidence_values(body)
    scores = {v.language: v.value for v in values}
    english = next((v for k, v in scores.items() if k == Language.ENGLISH), 0.0)
    native = next((v for k, v in scores.items() if k == target), 0.0)
    return english > native + margin
