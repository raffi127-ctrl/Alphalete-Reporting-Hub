"""Rashad's daily metrics → #elevate-sales.

SHIM (2026-07-14): the runner + per-office config moved to
automations.office_metrics (offices.py = the one place to add an office). This
delegates to it with office="rashad" so `python -m automations.rashad_metrics.run`
and `lucy rerun rashad_metrics` keep working unchanged — the orchestrator entry,
the Hub card, and the manifest id (rashad_metrics) are all untouched. Rashad's
channel/owner/Sheet/views now live in office_metrics.offices.OFFICES["rashad"].

The knocks helpers (knocks_run/knocks_pull) still live in this package; only the
metric-list + runner logic moved.
"""
from __future__ import annotations

import sys

from automations.office_metrics.runner import main as _main


def main(argv=None) -> int:
    return _main(argv, office_key="rashad")


if __name__ == "__main__":
    sys.exit(main())
