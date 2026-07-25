"""Per-office pay structures + the paycheck-estimate math.

An ICD (office owner) enters their own pay structure — what a rep earns per
unit of each product, at each leader level — through a self-serve web editor.
Each office sees ONLY its own structure. Every morning the office Order Log
reads that office's structure and, on each rep's tab, shows what that rep
would earn at Level 1, Level 2, Level 3 ... from the active lines they sold.

We deliberately DON'T ask the ICD to tag each rep with a level (we don't have
their sales boards to know it, and Megan didn't want that): the log shows the
pay at every level side by side, so a rep can see what the next level pays.

Three pieces:
  * offices.py  — which owner is which office, and its access code.
  * store.py    — load/save a per-office grid (Product Type x Level -> $/unit).
  * estimate.py — turn a rep's active-line counts into pay-by-level.
"""
