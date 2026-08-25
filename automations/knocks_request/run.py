"""CLI for `/knocks` — the same request the Slack popup makes, without Slack.

    python -m automations.knocks_request.run "Rafael Hidalgo"
    python -m automations.knocks_request.run "Chan Park" --date 2026-08-23
    python -m automations.knocks_request.run "Chan Park" --cache-only

Prints where the PNG landed. `--cache-only` never opens ownerville, so it is
the safe way to check the plumbing on a machine whose session is in use (or on
Windows, where the busy-guard can't see the mini's processes).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

# Keep emoji / checkmarks safe on the Windows console (cp1252 default).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.knocks_request import service


def main() -> int:
    ap = argparse.ArgumentParser(description="One office's knock board, on demand.")
    ap.add_argument("office", help="ICD / owner name, e.g. 'Rafael Hidalgo'")
    ap.add_argument("--date", help="YYYY-MM-DD (default: yesterday, Central)")
    ap.add_argument("--cache-only", action="store_true",
                    help="never open ownerville — answer from stored pulls only")
    a = ap.parse_args()
    target = dt.date.fromisoformat(a.date) if a.date else service.default_target()

    busy = service.ownerville_busy()
    if busy:
        print(f"[knocks] ownerville is busy: {', '.join(busy)}", flush=True)
    try:
        b = service.board_for(a.office, target, allow_live=not a.cache_only)
    except Exception as e:  # noqa: BLE001 — the CLI reports, it doesn't trace
        if service.access_gap(e):
            print(f"[knocks] ACCESS GAP: '{a.office}' is not on this "
                  "ownerville account — a permissions gap, not a spelling one.")
        else:
            print(f"[knocks] FAILED: {type(e).__name__}: {e}")
        return 1

    if b.png is None:
        print(f"[knocks] {b.office} {b.target}: {b.note}")
        return 0
    print(f"[knocks] {b.office} {b.target}: {len(b.rows)} rep(s) "
          f"({b.source}) -> {b.png}")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
