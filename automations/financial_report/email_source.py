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
# hubtruth renamed their main per-owner files WE 7/4 (Megan 2026-07-09):
# "CARLOS FINANCIAL SUMMARY …" -> "CARLOS SUMMARY REPORT …" (Raf/Sahil/Trang
# too). Only "RAF ADD 1 FINANCIAL SUMMARY" kept the old name, so 3 of 4 owners
# stopped matching and 105 ICDs went blank. Both globs kept — the internal
# layout is unchanged (parse.py already handles it), only the filename moved.
SOURCES = [
    ("hubtruth.com",              ["*summary report*.xlsx", "*financial summary*.xlsx"]),
    ("melissab_hub@yahoo.com",    ["*financials.xlsx"]),
    ("jsanchezmasters@gmail.com", ["*financial report*.xlsx"]),
]


# The weekly "books" we expect — one captain's workbook each — keyed by a
# STABLE email-SUBJECT signature. Deliberately NOT filename-based: hubtruth
# renamed their attachments WE 7/4 (see SOURCES note) but the subjects
# ("Carlos Summary Report…", "…Romeo Hise", "German - w/e…") have held for
# months. A whole book missing = a SENDER to nudge, which is far more
# actionable than a list of that book's ICDs showing blank. (label, sender-or-
# domain, subject substring.)
# Romeo Hise is NOT on our reporting (Maud, 2026-07-09) — deliberately left
# out so the alert never flags him. He emailed through w/e 6/20 then stopped;
# his tabs are not part of what we report.
EXPECTED_BOOKS = [
    ("Carlos (hubtruth)",    "hubtruth.com",              "Carlos"),
    ("Sahil (hubtruth)",     "hubtruth.com",              "Sahil"),
    ("Trang (hubtruth)",     "hubtruth.com",              "Trang"),
    ("Raf (hubtruth)",       "hubtruth.com",              "Raf"),
    ("Coel Reif (melissab)", "melissab_hub@yahoo.com",    "Coel"),
    ("German (jsanchez)",    "jsanchezmasters@gmail.com", "German"),
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


def missing_books(*, since_days: int = 7) -> List[str]:
    """Which EXPECTED_BOOKS have NO email in the window (by subject) — the
    whole-book gaps to chase a sender about. Fail-open: on any IMAP error
    returns [] so a probe hiccup never blocks the run."""
    missing: List[str] = []
    try:
        M = email_ingest._connect()
        try:
            for label, sender, subj in EXPECTED_BOOKS:
                if not email_ingest._search(M, sender, subj, since_days):
                    missing.append(label)
        finally:
            M.logout()
    except Exception as e:  # noqa: BLE001 — advisory only
        print(f"  ⚠ missing-book probe skipped ({e})")
        return []
    return missing


def any_available(*, since_days: int = 7) -> int:
    """Cheap-ish probe for the readiness gate: how many financial files are in
    the inbox this week (across all senders)."""
    n = 0
    for sender, globs in SOURCES:
        n += len(email_ingest.list_matches(sender, globs, since_days=since_days))
    return n
