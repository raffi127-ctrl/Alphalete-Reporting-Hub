"""One-shot HISTORY backfill for Carlos Hidalgo's b2b_att campaign block.

Fills the hidden 'Campaign Log' tab with every COMPLETED Mon-Sun week from
2025-12-29 (the funnel's first week, WE 2026-01-04) through last Sunday —
or from wherever the ATTTRACKER-B2B ORDERLOG actually starts, whichever is
later. The current week is NEVER stamped (pull_b2b.collect_carlos owns it),
and the Activation/Churn quality slots are NEVER touched (rolling Tableau
views — they have no per-week history to backfill).

    python -m automations.org_campaign_metrics.backfill_carlos_b2b            # dry
    python -m automations.org_campaign_metrics.backfill_carlos_b2b --write    # stamp
    python -m automations.org_campaign_metrics.backfill_carlos_b2b --ssid ID  # target

--ssid overrides the workbook (same as exporting ORG_CAMPAIGN_SSID) — use the
TEST workbook first, then re-run --write with no override for the live sheet.

Mechanics: the ORDERLOG csv is pulled in FOUR-WEEK chunks (Tableau query =
pull_b2b.ORDERLOG_CSV, fetched with automations.att_order_log.run._fetch_csv
exactly like pull_b2b.collect_carlos), cached under
output/org_campaign_metrics/ and reused on re-runs, then
pull_b2b.orderlog_week_slots is run once per Mon-Sun week inside each chunk —
the identical computation the weekly stamper uses, so numbers match by
construction. Writes go through sheet.upsert_values (merge-by-key, additive —
never deletes anything already stored).

RUNS ON LUCY 2 when chunks need pulling (Tableau session); a fully-cached
re-run needs only Sheets auth. Python 3.9. Each chunk export is large
(~10-120MB) — the fetch has its own 300s/attempt x3 retry budget; waiting on
the shared profile lock is normal.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — py3.9 / non-tty
    pass

MANAGER = "Carlos Hidalgo"
CAMPAIGN = "b2b_att"
FIRST_MONDAY = dt.date(2025, 12, 29)      # funnel week 1 (WE 2026-01-04)
WEEKS_PER_CHUNK = 4

# Rolling-view slots the backfill must never emit (defense in depth —
# orderlog_week_slots doesn't produce them, but a label drift shouldn't
# ever let one through either).
_NEVER_LABELS = {"Activation Rate (31–60 Day)", "0–30 Day Churn Rate"}

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "org_campaign_metrics"


def _mondays(first, last):
    """Every Monday from first..last inclusive (both must be Mondays)."""
    out, d = [], first
    while d <= last:
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def _chunks(mondays):
    """[(chunk_start_monday, chunk_end_sunday, [mondays_in_chunk]), ...]"""
    out = []
    for i in range(0, len(mondays), WEEKS_PER_CHUNK):
        part = mondays[i:i + WEEKS_PER_CHUNK]
        out.append((part[0], part[-1] + dt.timedelta(days=6), part))
    return out


def _chunk_path(start, end):
    return OUT_DIR / ("b2b_backfill_%s_%s.csv" % (start.isoformat(), end.isoformat()))


def _fetch_chunk(page, start, end, log):
    """Download one chunk csv (cached). Returns the path, or None on failure."""
    from automations.att_order_log.run import _fetch_csv
    from automations.org_campaign_metrics.pull_b2b import ORDERLOG_CSV

    dest = _chunk_path(start, end)
    if dest.exists() and dest.stat().st_size >= 1000:
        log("  [chunk %s..%s] cached (%s, %.1f MB)"
            % (start, end, dest.name, dest.stat().st_size / 1e6))
        return dest
    url = ORDERLOG_CSV % (start.isoformat(), end.isoformat())
    log("  [chunk %s..%s] pulling export…" % (start, end))
    body = _fetch_csv(page, url, log=log)     # 3 attempts inside
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    log("  [chunk %s..%s] saved %s (%.1f MB)"
        % (start, end, dest.name, len(body) / 1e6))
    return dest


def collect_history(today, log=print, page_factory=None):
    """-> (values, unavailable) — values are (mgr, week_iso, slot, text) tuples
    for every completed week with data; unavailable is [(week_iso, reason)].

    page_factory: nullary -> Tableau page; called lazily only if a chunk is
    missing from the cache (so cached re-runs need no browser at all).
    """
    from automations.org_campaign_metrics import layout as L
    from automations.org_campaign_metrics.pull_b2b import orderlog_week_slots
    from automations.org_campaign_metrics.run import week_sunday

    cur_monday = today - dt.timedelta(days=today.weekday())
    last_done_monday = cur_monday - dt.timedelta(days=7)
    if last_done_monday < FIRST_MONDAY:
        log("nothing to backfill: no completed week on/after %s" % FIRST_MONDAY)
        return [], []
    mondays = _mondays(FIRST_MONDAY, last_done_monday)
    chunks = _chunks(mondays)
    log("backfill window: %s .. %s (%d weeks, %d chunks)"
        % (FIRST_MONDAY, last_done_monday + dt.timedelta(days=6),
           len(mondays), len(chunks)))

    slots = L.slots_by_label(CAMPAIGN)
    values, unavailable = [], []
    page = None
    for ci, (start, end, week_mondays) in enumerate(chunks, 1):
        log("-- chunk %d/%d: %s .. %s" % (ci, len(chunks), start, end))
        path = _chunk_path(start, end)
        if not (path.exists() and path.stat().st_size >= 1000):
            if page is None:
                if page_factory is None:
                    raise RuntimeError("chunk %s..%s not cached and no Tableau "
                                       "page available" % (start, end))
                page = page_factory()
            try:
                path = _fetch_chunk(page, start, end, log)
            except Exception as exc:  # noqa: BLE001 — one chunk must not sink the rest
                log("  !! chunk %s..%s export failed after retries: %s"
                    % (start, end, (str(exc).splitlines() or [""])[0][:160]))
                for m in week_mondays:
                    unavailable.append((week_sunday(m).isoformat(),
                                        "chunk export failed"))
                continue
        else:
            log("  [chunk %s..%s] cached (%s, %.1f MB)"
                % (start, end, path.name, path.stat().st_size / 1e6))
        for m in week_mondays:
            upto = m + dt.timedelta(days=6)
            week_iso = week_sunday(m).isoformat()
            named = orderlog_week_slots(path, m, upto, log)
            named = {lab: v for lab, v in named.items()
                     if lab in slots and lab not in _NEVER_LABELS}
            if not named:
                unavailable.append((week_iso, "no Carlos rows in export"))
                continue
            for lab, v in sorted(named.items(), key=lambda kv: slots[kv[0]]):
                values.append((MANAGER, week_iso, slots[lab], v))
    return values, unavailable


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true",
                    help="actually write (default: dry preview)")
    ap.add_argument("--ssid", help="target spreadsheet id "
                    "(overrides ORG_CAMPAIGN_SSID; default = live workbook)")
    a = ap.parse_args(argv)
    dry = not a.write
    if a.ssid:
        os.environ["ORG_CAMPAIGN_SSID"] = a.ssid
    # sheet.py resolves SSID at import time — import only after the env is set.
    from automations.org_campaign_metrics import sheet as CL
    log = print

    today = dt.date.today()
    log("== backfill_carlos_b2b %s -> sheet %s%s"
        % (today.isoformat(), CL.SSID, " (DRY RUN)" if dry else " (WRITE)"))

    from automations.funnel_board.auth import session as sheets_session
    S = sheets_session(verbose=True)

    def _page_factory():
        # Enter the Tableau session lazily and keep it open for the whole run.
        from automations.shared.tableau_patchright import tableau_session
        cm = tableau_session(verbose=True)
        page = cm.__enter__()
        _page_factory.cm = cm      # keep a ref so we can close it in finally
        return page

    _page_factory.cm = None
    try:
        values, unavailable = collect_history(today, log, _page_factory)
    finally:
        if _page_factory.cm is not None:
            _page_factory.cm.__exit__(None, None, None)

    weeks = sorted({w for _m, w, _s, _v in values})
    log("-- totals: %d value tuples across %d weeks%s"
        % (len(values), len(weeks),
           (" (%s .. %s)" % (weeks[0], weeks[-1])) if weeks else ""))
    if dry:
        for row in values:
            log("   %s" % (row,))
    if unavailable:
        log("-- weeks with no data:")
        for w, why in unavailable:
            log("   %s: %s" % (w, why))

    CL.upsert_values(S, values, dry_run=dry, log=log)
    log("done%s -> %s" % (" (dry, nothing written)" if dry else "", CL.SSID))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
