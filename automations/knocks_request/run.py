"""CLI for `/knocks` — the same request the Slack popup makes, without Slack.

    python -m automations.knocks_request.run "Rafael Hidalgo"
    python -m automations.knocks_request.run "Chan Park" --date 2026-08-23
    python -m automations.knocks_request.run "Chan Park" --date 2026-08-18 \
                                                         --through 2026-08-23
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
    ap.add_argument("--through",
                    help="YYYY-MM-DD — last day of a range (default: --date, "
                         "i.e. a single day)")
    ap.add_argument("--cache-only", action="store_true",
                    help="never open ownerville — answer from stored pulls only")
    a = ap.parse_args()
    target = dt.date.fromisoformat(a.date) if a.date else service.default_target()
    end = dt.date.fromisoformat(a.through) if a.through else target

    problem = service.check_span(target, end)
    if problem:
        print(f"[knocks] {problem}")
        return 1
    total = len(service.span_days(target, end))
    need, need_cmp = service.pull_plan(service.resolve_office(a.office),
                                       target, end)
    if need:
        print(f"[knocks] {len(need)} of {total} day(s) need a live pull: "
              f"{', '.join(d.isoformat() for d in need)}", flush=True)
    if need_cmp:
        # The comparison line covers the same span or it isn't drawn, so its
        # missing days are real work this run has to do.
        print(f"[knocks] {service.compare_office()} (comparison) needs "
              f"{len(need_cmp)} of {total} day(s): "
              f"{', '.join(d.isoformat() for d in need_cmp)}", flush=True)
    busy = service.ownerville_busy()
    if busy:
        print(f"[knocks] ownerville is busy: {', '.join(busy)}", flush=True)
    try:
        b = service.board_for(a.office, target, end, allow_live=not a.cache_only)
    except Exception as e:  # noqa: BLE001 — the CLI reports, it doesn't trace
        if service.access_gap(e):
            print(f"[knocks] ACCESS GAP: '{a.office}' is not on this "
                  "ownerville account — a permissions gap, not a spelling one.")
        else:
            # THE TRACEBACK, not just the message. This is the self-test — the
            # one place a failure is supposed to be readable — and it was
            # printing a one-line summary, which is why an AttributeError from
            # deep in the render was as opaque here as it was in Slack.
            import traceback
            print(f"[knocks] FAILED: {type(e).__name__}: {e}")
            traceback.print_exc()
        return 1

    span = b.target.isoformat() if not b.is_range else f"{b.target}..{b.end}"
    if b.png is None:
        print(f"[knocks] {b.office} {span}: {b.note}")
        return 0
    print(f"[knocks] {b.office} {span}: {len(b.rows)} rep(s) over "
          f"{b.days} day(s) ({b.source}) -> {b.png}")
    print("=== done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
