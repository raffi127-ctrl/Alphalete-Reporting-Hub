"""One-shot BOX campaign history backfill — Sales Metrics only.

Fills the hidden 'Campaign Log' tab with FULL per-week history for the BOX
campaign (Ryan McSpadden + Roshan Amin), back to the funnel's first week
(WE 2026-01-04) or the campaign's true start on Tableau, whichever is later.

Per historical week (Mon-Sun, keyed by SUNDAY ISO) it pulls the
BoxSalesMetrics 'Sales Metrics' crosstab pinned '?Sale Date Weekending=<ISO>'
— the exact recipe pull_box.py uses for current+prior, looped — and stamps
per owner: Complete Sales, Sales per Rep, Selling Rep Count, Total Rep Count
on Tableau, ELE Sales, Gas Sales, Avg kWh per Sale, plus the Grand-Total
National Sales per Rep / National Avg kWh per Sale. Then "vs Prior Week"
(signed int %, from Complete Sales) for every week with a prior week.

Rank / acceptance / drop / order-log slots are NOT backfillable — those views
are live-computed with no week history — so they are skipped on purpose.

Earliest-week discovery: walks Sundays backwards; two consecutive weeks with
no owner rows ends the walk (floor WE 2026-01-04 regardless). One pull per
week, one tableau_session for the whole loop; a flaky pull is retried once.
Values go through sheet.upsert_values — additive merge-by-key, never deletes,
and re-stamping identical values is a no-op.

    python -m automations.org_campaign_metrics.backfill_box              # dry
    python -m automations.org_campaign_metrics.backfill_box --write
    python -m automations.org_campaign_metrics.backfill_box --write --ssid <id>

Dry runs print the per-week tuples and never touch Sheets. --ssid overrides
the target workbook (same as the ORG_CAMPAIGN_SSID env var). Python 3.9.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import Dict, List, Tuple

from automations.org_campaign_metrics import layout as L
from automations.org_campaign_metrics import pull_box as PB

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# The org funnel's first week — never probe earlier (Focus Report has no
# weeks before it even if Tableau did).
FLOOR_SUNDAY = dt.date(2026, 1, 4)          # Mon 2025-12-29 .. Sun 2026-01-04

VALUE_LABELS = (
    # (label, per-dict key, formatter)
    ("Total Rep Count on Tableau", "total_reps", PB._int_text),
    ("Selling Rep Count",          "selling",    PB._int_text),
    ("Complete Sales",             "complete",   PB._int_text),
    ("Sales per Rep",              "spr",        PB._spr_text),
    ("ELE Sales",                  "ele",        PB._int_text),
    ("Gas Sales",                  "gas",        PB._int_text),
    ("Avg kWh per Sale",           "avg_kwh",    PB._thousands_text),
)


def _is_empty_export(e):
    return isinstance(e, RuntimeError) and "empty" in str(e).lower()


def _pull_week(page, sunday, log):
    """-> (per, national) for one pinned week; ({}, {}) when the export is
    empty (pre-history week). Retries a flaky pull once — on top of the
    downloader's own 3 internal attempts."""
    tag = "bf_%s" % sunday.isoformat()
    try:
        return PB._sales_metrics(page, sunday, tag, log)
    except Exception as e:  # noqa: BLE001
        if _is_empty_export(e):
            return {}, {}
        log("  [backfill] WE %s pull failed (%s: %s) — retrying once"
            % (sunday.isoformat(), type(e).__name__, str(e)[:160]))
        try:
            return PB._sales_metrics(page, sunday, tag, log)
        except Exception as e2:  # noqa: BLE001
            if _is_empty_export(e2):
                return {}, {}
            raise


def _assemble(results, log):
    """results: {sunday: (per, national)} -> Campaign Log value tuples."""
    slots = L.slots_by_label("box")
    values: List[Tuple[str, str, int, str]] = []
    complete: Dict[Tuple[str, dt.date], float] = {}

    def put(mgr, sunday, label, num, fmt):
        if num is None:
            return
        values.append((mgr, sunday.isoformat(), slots[label], fmt(num)))

    for sunday in sorted(results):
        per, national = results[sunday]
        for mgr, v in per.items():
            for label, key, fmt in VALUE_LABELS:
                put(mgr, sunday, label, v.get(key), fmt)
            if v.get("complete") is not None:
                complete[(mgr, sunday)] = v["complete"]
        if per:  # national benchmark rows repeat per manager (pull_box pattern)
            for mgr, _tok in PB.MANAGERS:
                put(mgr, sunday, "National Sales per Rep",
                    national.get("spr"), PB._spr_text)
                put(mgr, sunday, "National Avg kWh per Sale",
                    national.get("avg_kwh"), PB._thousands_text)

    n_vs = 0
    for (mgr, sunday), cc in sorted(complete.items(), key=lambda kv: kv[0][1]):
        pc = complete.get((mgr, sunday - dt.timedelta(days=7)))
        if pc:                                  # prior week present & nonzero
            values.append((mgr, sunday.isoformat(), slots["vs Prior Week"],
                           PB._signed_pct_text((cc / pc - 1.0) * 100.0)))
            n_vs += 1
    log("  [backfill] assembled %d tuples (%d vs-prior)" % (len(values), n_vs))
    return values


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="actually write (default: dry preview, no Sheets I/O)")
    ap.add_argument("--ssid", help="target spreadsheet id (overrides "
                                   "ORG_CAMPAIGN_SSID / the live default)")
    a = ap.parse_args(argv)
    if a.ssid:
        os.environ["ORG_CAMPAIGN_SSID"] = a.ssid
    # sheet.py resolves its SSID at import — import only after the override.
    from automations.org_campaign_metrics import sheet as CL
    dry = not a.write
    log = print
    today = dt.date.today()
    wk_cur = today + dt.timedelta(days=6 - today.weekday())

    log("== backfill_box %s: weeks WE %s .. WE %s (floor)%s" % (
        today.isoformat(), wk_cur.isoformat(), FLOOR_SUNDAY.isoformat(),
        " (DRY RUN — no Sheets I/O)" if dry else ""))
    log("   target spreadsheet: %s%s" % (
        CL.SSID, "" if os.environ.get("ORG_CAMPAIGN_SSID") is None
        else "  (env/--ssid override)"))

    results = {}                        # sunday -> (per, national)
    misses: List[dt.date] = []
    empty: List[dt.date] = []

    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(verbose=True) as page:
        wk = wk_cur
        empty_streak = 0
        while wk >= FLOOR_SUNDAY:
            try:
                per, national = _pull_week(page, wk, log)
            except Exception as e:  # noqa: BLE001 — a miss, not an empty
                log("  [backfill] !! WE %s MISSED after retry: %s: %s"
                    % (wk.isoformat(), type(e).__name__, str(e)[:200]))
                misses.append(wk)
                wk -= dt.timedelta(days=7)
                continue
            if per:
                results[wk] = (per, national)
                empty_streak = 0
            else:
                empty.append(wk)
                empty_streak += 1
                log("  [backfill] WE %s: no owner rows (empty streak %d)"
                    % (wk.isoformat(), empty_streak))
                if empty_streak >= 2:
                    log("  [backfill] two consecutive empty weeks — "
                        "history exhausted, stopping the walk")
                    break
            wk -= dt.timedelta(days=7)

    if not results:
        log("!! no weeks returned owner rows — nothing to stamp")
        return 1

    first, last = min(results), max(results)
    log("-- pulled %d data weeks: WE %s .. WE %s; %d empty, %d missed"
        % (len(results), first.isoformat(), last.isoformat(),
           len(empty), len(misses)))
    if misses:
        log("   missed weeks (rerun to fill): %s"
            % ", ".join(d.isoformat() for d in misses))

    values = _assemble(results, log)

    if dry:
        cur_wk = None
        for mgr, week, slot, val in sorted(values, key=lambda t: (t[1], t[0],
                                                                  t[2])):
            if week != cur_wk:
                log("-- WE %s" % week)
                cur_wk = week
            log("   %s" % ((mgr, week, slot, val),))
        log("dry run: %d tuples NOT written (add --write)" % len(values))
        return 0

    from automations.funnel_board.auth import session as sheets_session
    S = sheets_session(verbose=True)
    changed = CL.upsert_values(S, values, dry_run=False, log=log)
    log("WROTE %d tuples (%d changed) to spreadsheet %s, tab %r"
        % (len(values), changed, CL.SSID, CL.TAB))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
