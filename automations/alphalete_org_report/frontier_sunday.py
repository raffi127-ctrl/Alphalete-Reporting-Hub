"""Sunday 6pm Frontier OPT runner — moved OFF the Monday 4am batch (Megan 2026-07-09).

Credico emails the completed sales week in Sunday's ~1:30pm daily, so by 6pm it's in
the inbox. This waits for the 2 sales PDFs (by-store + events) to actually be there,
then fills — a retry so the standalone Sunday job is as safe as the batch's
readiness-wait was (if the email is ever late, it keeps checking rather than missing
the week). The Quality Scorecard lags ~2 weeks by design and never gates.

    lucy rerun frontier_sunday        # (on-demand; normally the 6pm launchd job runs it)
"""
from __future__ import annotations

import subprocess
import sys
import time

from automations.alphalete_org_report import frontier_email_source as fes

TRIES = 8          # ~2h of coverage past 6pm before giving up
BACKOFF_S = 900    # 15 min between checks


def _sales_ready() -> bool:
    """True once BOTH sales PDFs (by-store + events) are in the inbox. The scorecard
    (GLOBS[2]) lags ~2wk and is intentionally NOT required."""
    try:
        avail = fes.latest_available() or {}
    except Exception as e:  # noqa: BLE001 — an IMAP blip shouldn't crash the job
        print(f"[frontier-sunday] inbox probe failed: {type(e).__name__}: {e}", flush=True)
        return False
    return all(avail.get(g) for g in fes.GLOBS[:2])


def main() -> int:
    for i in range(1, TRIES + 1):
        if _sales_ready():
            print("[frontier-sunday] sales PDFs present — filling", flush=True)
            return subprocess.run(
                [sys.executable, "-m",
                 "automations.alphalete_org_report.opt_frontier", "--email"]).returncode
        print(f"[frontier-sunday] Frontier sales email not in yet (try {i}/{TRIES}) "
              f"— waiting {BACKOFF_S // 60}m", flush=True)
        if i < TRIES:
            time.sleep(BACKOFF_S)
    print("[frontier-sunday] Frontier email never arrived — giving up. Use the Hub "
          "upload fallback or `lucy rerun frontier_opt`.", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
