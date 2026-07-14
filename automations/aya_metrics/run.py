"""Aya's daily metrics → #indelible-sales.

SHIM (2026-07-14): the runner + per-office config moved to
automations.office_metrics (offices.py = the one place to add an office). This
delegates to it with office="aya" so `python -m automations.aya_metrics.run` and
`lucy rerun aya_metrics` keep working unchanged — the orchestrator entry, the Hub
card, and the manifest id (aya_metrics) are all untouched. Aya's
channel/owner/Sheet/views now live in office_metrics.offices.OFFICES["aya"].
"""
from __future__ import annotations

import sys

from automations.office_metrics.runner import main as _main


def main(argv=None) -> int:
    return _main(argv, office_key="aya")


if __name__ == "__main__":
    sys.exit(main())
