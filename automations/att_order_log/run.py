"""ATT B2B Order Log (Carlos) -> the 'Lucy At&t Order Log' tab.

Carlos's ATT counterpart to the BOX Order Log he already reads each morning
(requested 2026-07-19 via Loom + Slack). Pulls the ATTTRACKER-B2B ORDERLOG
crosstab, un-pivots the per-measure row fan-out into one row per real sale,
and writes a rep/period-filtered, status-coloured log into the Vantura Master
Sales Board.

DRY-RUN BY DEFAULT — pulls and reports, writes nothing. Add --sheet to write.

    python -m automations.att_order_log.run                 # pull + report only
    python -m automations.att_order_log.run --sheet         # write the tabs
    python -m automations.att_order_log.run --from-file X   # offline, no Tableau

RUNS ON LUCY 2. The pull rides Carlos's real-Chrome Tableau identity; on Lucy 1
the export is a different slice, and pulling from the laptop evicts the mini's
ownerville session holder.

WHY THE PULL IS THE DIRECT .csv AND NOT cdp_pull.probe(): that helper ignores
its url/out arguments entirely (it hardcodes the bare ORDERLOG view and writes
/tmp/vantura_default.csv), which cost a run on 2026-07-19. The direct
authenticated .csv is the path that works: status=200, 47 columns, every
compute.COLS caption present.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — py3.9 / non-tty
    pass

WINDOW_DAYS = 31          # Carlos 2026-07-22: "just show the last 31 days of
                          # sales" (by sale date). Was 60; churn keeps its own
                          # 60-day window in vantura_churn — this scopes ONLY the
                          # order-log pull (standalone + the b2b_metrics item).
OWNER_PREFIX = "CARLOS HIDALGO"

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output" / "att_order_log"


def _csv_url(today: dt.date) -> str:
    start = today - dt.timedelta(days=WINDOW_DAYS)
    return ("https://us-east-1.online.tableau.com"
            "/t/sci/views/ATTTRACKER-B2B/ORDERLOG.csv?:refresh=yes"
            "&Start%20Date={}&End%20Date={}").format(
                start.isoformat(), today.isoformat())


def _pull(today: dt.date, dest: Path, log=print) -> Path:
    """Download the order-log crosstab through Carlos's real-Chrome session."""
    import time

    from patchright.sync_api import sync_playwright

    from automations.shared import tableau_patchright as tp
    from automations.vantura_churn import cdp_pull

    cdp_pull._kill_ours()
    proc = cdp_pull._launch()
    log("  [cdp] real Chrome pid={}; waiting 20s".format(proc.pid))
    time.sleep(20)
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(
                "http://127.0.0.1:{}".format(cdp_pull.CDP_PORT))
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            tp._ensure_tableau_authenticated(page, verbose=False,
                                             allow_form_login=True)
            log("  [cdp] auth OK")
            r = page.context.request.get(_csv_url(today), timeout=300_000)
            body = r.body() or b""
            log("  [csv] status={} bytes={:,}".format(r.status, len(body)))
            if r.status != 200 or len(body) < 1000:
                raise RuntimeError(
                    "order-log export failed: status={} bytes={}".format(
                        r.status, len(body)))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
            return dest
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        cdp_pull._kill_ours()


def _report(lines, stats, log=print) -> None:
    from . import colors, sheet
    log("  {:>7,} real sales for {}".format(len(lines), OWNER_PREFIX))
    if stats.get("ragged"):
        log("  {:>7,} RAGGED groups (measure count not a clean multiple) — "
            "these were emitted once each; investigate if non-zero".format(
                stats["ragged"]))
    statuses = {}
    for ln in lines:
        s = (ln.get("DTR Status (enriched)") or "").strip()
        if s:
            statuses[s] = statuses.get(s, 0) + 1
    log("  status mix:")
    for s, n in sorted(statuses.items(), key=lambda kv: -kv[1]):
        log("    {:>6,}  {:<22} {}".format(n, s, colors.color_for(s) or "UNMAPPED"))
    unknown = colors.unmapped(statuses)
    if unknown:
        log("  !! UNMAPPED statuses would render uncoloured: {}".format(
            ", ".join(sorted(unknown))))
    missing = [h for h in sheet.DISPLAY_HEADERS
               if lines and h not in lines[0]]
    if missing:
        log("  !! DISPLAY columns absent from the export: {}".format(missing))


def _dm_file(path: Path, user: str, log=print) -> None:
    """DM a built file to ONE user for review. Rejects channel ids so a preview
    can't become a channel post (same guard as thread/metrics_shot)."""
    from automations.shared import slack_metrics_post as smp
    u = (user or "").strip()
    if not u.upper().startswith("U"):
        raise ValueError(
            "refusing: {!r} is not a user id — preview DMs an individual, "
            "channel ids (C…/G…) are rejected".format(u))
    smp.dm_user_with_file(
        path, user=u, file_name=path.name,
        comment="ATT B2B Order Log workbook — All Reps + Posted-by-Week + a "
                "tab per rep. Preview, not posted anywhere.")
    log("  DM'd workbook to {}".format(u))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="att_order_log")
    ap.add_argument("--reformat", action="store_true",
                    help="also re-apply the code's visual formatting (borders, "
                         "freeze, colours). OMIT for daily runs — Megan hand-"
                         "formats the tab and the default preserves it.")
    ap.add_argument("--sheet", action="store_true",
                    help="write the Sheet tabs (default: dry run, no writes)")
    ap.add_argument("--xlsx", action="store_true",
                    help="build the daily workbook: All Reps + Posted-by-Week "
                         "+ one tab per rep, grouped by paycheck weeks "
                         "(box_order_log-style, for the Slack thread)")
    ap.add_argument("--from-file", default=None, metavar="CSV",
                    help="parse an existing export instead of pulling")
    ap.add_argument("--dm", default=None, metavar="USER_ID",
                    help="DM the built --xlsx workbook to ONE user (U…) for "
                         "review. Rejects channel ids.")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--owner", default=OWNER_PREFIX)
    ap.add_argument("--sheet-id", default=None, metavar="SHEET_ID",
                    help="write to THIS Google Sheet instead of Carlos's board "
                         "(e.g. another office's board). Pair with --owner.")
    args = ap.parse_args(argv)

    today = (dt.date.fromisoformat(args.today) if args.today
             else dt.date.today())
    log = print
    log("ATT B2B Order Log — {} (window {} days)".format(today, WINDOW_DAYS))

    try:
        if args.from_file:
            path = Path(args.from_file)
            log("  reading {}".format(path))
        else:
            path = OUTPUT_DIR / "orderlog_{}.csv".format(today.isoformat())
            _pull(today, path, log=log)

        from . import clean, sheet
        lines = clean.load_rows(path, owner_prefix=args.owner)
        stats = clean.stats(lines)
        _report(lines, stats, log=log)

        # Daily workbook (All Reps + Posted-by-Week + per-rep tabs). Separate
        # from --sheet; --xlsx writes a file to output/, no Sheet write.
        if args.xlsx:
            from . import pending, sheet as _sheet, xlsx
            out = OUTPUT_DIR / "ATT Order Log {}.xlsx".format(
                today.strftime("%m-%d-%Y"))
            pend = pending.read_for_key(args.sheet_id or _sheet.SHEET_ID, log=log)
            xlsx.build(lines, out, today=today, pending=pend)
            reps = len({l.get("Rep", "") for l in lines if l.get("Rep")})
            log("  workbook: {} ({} sales, {} rep tabs)".format(
                out.name, len(lines), reps))
            if args.dm:
                _dm_file(out, args.dm, log=log)

        if not args.sheet:
            log("")
            log("  {} — no Sheet write. Add --sheet to write '{}'.".format(
                "WORKBOOK BUILT" if args.xlsx else "DRY RUN", sheet.TAB_VIEW))
            return 0

        log("")
        log("  writing the Sheet…")
        res = sheet.push(lines, today=today, reformat=args.reformat,
                         sheet_id=args.sheet_id, log=log)
        log("  done: {sales:,} sales, {reps} reps".format(**res))
        if res.get("unmapped"):
            log("  NOTE: unmapped statuses present: {}".format(
                ", ".join(res["unmapped"])))
        return 0
    except Exception:  # noqa: BLE001 — report the failure, don't traceback-dump
        log("")
        log("FAILED:")
        for ln in traceback.format_exc().splitlines()[-14:]:
            log("  " + ln[:200])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
