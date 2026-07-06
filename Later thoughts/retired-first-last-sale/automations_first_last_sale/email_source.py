"""Fetch First/Last Sale's weekly workbook from the reporting inbox (auto-ingest).

Smart Circle (Campbell D'Eliscu) emails the 'B2B.D2D First Last Sale WE <date>.xlsx'
every Monday (observed ~8:50am–1:11pm CT; usually ~10–11am). first_last_sale.run
parses its 3 channel tabs (B2B / RES IF / RES OOF) and fills the FK/LK section
across the ATT tabs — and the week comes from the FILENAME — so this just drops
the newest matching workbook into the dest dir and lets the report do the rest.

Partial-safe: if the email hasn't landed yet, nothing is fetched and the report
finds no file (a no-op that leaves the sheet as-is).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

from automations.shared import email_ingest

SENDER = "cdeliscu@thesmartcircle.com"
# The attachment is 'B2B.D2D First Last Sale WE 6.28.2026.xlsx'. Match on the
# distinctive 'First Last Sale' phrase (case-insensitive) so a minor prefix/date
# change still catches it; run.gather_files applies the same first+last check.
GLOBS = ["*First Last Sale*.xlsx"]


def fetch(dest_dir: str | Path, *, verbose: bool = True) -> Dict[str, Path]:
    """Download the newest First/Last Sale workbook into dest_dir. Returns
    {glob: saved_path} for whatever arrived (partial-safe — empty if none)."""
    return email_ingest.fetch_by_globs(SENDER, GLOBS, dest_dir, verbose=verbose)


def latest_available() -> Dict[str, Tuple[str, str]]:
    """Cheap probe (no body download): {glob: (filename, email_date)} for the
    newest matching workbook — used to confirm this week's file has landed."""
    return email_ingest.list_matches(SENDER, GLOBS)
