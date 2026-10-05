"""The ingredient check: an ingredient's H codes against Annex VI Table 3.

Where CLP Annex VI has harmonised a substance, the sheet has to carry at least
that classification. This package compares the two and says where it does not.

Nothing here judges where the ingredient data came from. A harmonised entry
either covers a substance or it does not, and the comparison is the same either
way; the source is recorded as metadata and never used to weigh a result.
"""

from lingua_oracle.ingredients.compare import (
    Verdict,
    check_ingredient,
    check_product,
)

__all__ = ["Verdict", "check_ingredient", "check_product"]
