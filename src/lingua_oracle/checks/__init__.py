"""The 15 checks, registered by ID.

Importing this package registers every check. Order here is the order findings
are produced in.
"""

from lingua_oracle.checks import (  # noqa: F401
    a01_signal_word,
    a02_a04_statements,
    a05_untranslated,
    a06_placeholders,
    a07_broken_chars,
    b08_section16,
    b09_label_vs_section2,
    b10_signal_fits_codes,
    b11_compare,
    c02_consistency,
    c12_valid_for_regulation,
    c13_revision,
    c14_required_languages,
)
from lingua_oracle.checks.base import (
    CheckContext,
    all_checks,
    register,
    run_all,
    run_check,
    title_of,
)

__all__ = [
    "CheckContext",
    "all_checks",
    "register",
    "run_all",
    "run_check",
    "title_of",
]
