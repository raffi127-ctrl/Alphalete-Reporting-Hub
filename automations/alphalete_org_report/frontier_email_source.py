"""Fetch Frontier OPT's 3 source PDFs from the reporting inbox (auto-ingest).

The Frontier OPT report (opt_frontier.py) reads 3 PDFs a human used to download
from email + upload to the Hub: by-store, events, and the events quality
scorecard. Credico emails them from reports@credicousa.com — but that sender
ALSO sends the parallel "Residential" Frontier PDFs, so we match the EVENTS
filenames specifically (the Residential ones must NOT land in the upload dir,
or opt_frontier's broad 'Quality Scorecard - Frontier*' glob would grab the
wrong scorecard).

Partial-safe: opt_frontier already updates only the PDF types present, so if
one email hasn't arrived yet we fetch what's there and the rest stays as-is.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from automations.shared import email_ingest

SENDER = "reports@credicousa.com"

# Events-specific globs — NOT the Residential Frontier PDFs from the same
# sender, and the '(SCI)' quality scorecard (not the 'Abyl … Agent Level' variant
# Credico also sends). CONFIRM with Eve that '(SCI)' is the one the report parses.
GLOBS = [
    "Daily Sales - Frontier - Events by Store*.pdf",
    "Daily Sales - Frontier - Events - SCI*.pdf",
    "Quality Scorecard - Frontier - Events - (SCI)*.pdf",
]


def fetch(dest_dir: str | Path, *, verbose: bool = True) -> Dict[str, Path]:
    """Download the newest of each of the 3 Frontier Events PDFs into dest_dir.
    Returns {glob: saved_path} for whichever arrived (partial-safe)."""
    return email_ingest.fetch_by_globs(SENDER, GLOBS, dest_dir, verbose=verbose)


def latest_available() -> Dict[str, tuple]:
    """Cheap probe for the readiness gate: {glob: (filename, email_date)} for
    the newest of each Events PDF, without downloading bodies."""
    return email_ingest.list_matches(SENDER, GLOBS)
