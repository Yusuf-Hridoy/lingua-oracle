"""Recalculating a mixture's classification from its ingredients.

CLP Annex I says what a mixture is classified as, given what is in it and at
what concentration. This package does that calculation and compares the result
with what Section 2 of the sheet states.

The rules implemented are named in `rules.py`, each with the Annex I paragraph
it comes from. Everything else - the aspiration, physical and acute-toxicity
classes, the bridging principles - is out of scope and reported as not
calculated rather than passed over.
"""
