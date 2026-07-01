"""Fetch the weekly Financial Summary workbooks from the reporting inbox.

financial_report parses each .xlsx's CONTENT (by owner/office) and is
INCREMENTAL — a missing owner is skipped, never wiped — so this just gathers the
week's financial workbooks from every sender into a folder; the report does the
parsing/mapping/week-detection. 3 senders, 7 owners (confirmed Megan 2026-07-01):
  - hubtruth.com (amber@/phil@ handoff): RAF, CARLOS, SAHIL, TRANG   (Tue PM)
  - melissab_hub@yahoo.com:              Romeo Hise, Coel Reif       (Wed PM)
  - jsanchezmasters@gmail.com:           German                      (Mon/Tue PM)

Windowed to the current week (since_days=7) so prior weeks aren't re-filled
(the report overwrites present cells). Dedup-by-filename handles resends and the
generic-named files (Coel/German reuse the same filename every week, so newest
wins). Partial-safe: whatever's arrived fills; the rest stays as-is.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from automations.shared import email_ingest

# (sender-or-domain, filename globs). Domain match catches the amber@/phil@
# hubtruth handoff. Case-insensitive fnmatch.
SOURCES = [
    ("hubtruth.com",              ["*financial summary*.xlsx"]),
    ("melissab_hub@yahoo.com",    ["*financials.xlsx"]),
    ("jsanchezmasters@gmail.com", ["*financial report*.xlsx"]),
]


def fetch(dest_dir: str | Path, *, since_days: int = 7,
          verbose: bool = True) -> List[Path]:
    """Gather this week's financial workbooks from all senders into dest_dir."""
    got: List[Path] = []
    for sender, globs in SOURCES:
        if verbose:
            print(f"  [{sender}]", flush=True)
        got += email_ingest.fetch_all(sender, globs, dest_dir,
                                      since_days=since_days, verbose=verbose)
    return got


def any_available(*, since_days: int = 7) -> int:
    """Cheap-ish probe for the readiness gate: how many financial files are in
    the inbox this week (across all senders)."""
    n = 0
    for sender, globs in SOURCES:
        n += len(email_ingest.list_matches(sender, globs, since_days=since_days))
    return n
