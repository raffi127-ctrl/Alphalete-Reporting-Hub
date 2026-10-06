"""Activation Rate by Rep — NDS owner (Khalil Mansour), from the NDS-SN
(RES-ATT-OOF) ORDER LOG.

Carlos 2026-10-05: "recreate the activation rate by rep for Khalil Mansour,
where you get his order log ... the NDS-SN (RES-ATT-OOF) workbook ... It's a
little bit different than the B2B order log. Understand the differences and
then recreate the same thing."

HOW THE NDS LOG DIFFERS FROM B2B (and what this module does about it):
  * B2B's board reads Tableau's ACTIVATIONRATES view. The NDS side has no
    such view, so the rates are COMPUTED from the order log itself.
  * Activation lives in "DTR Active Date" (the house's "Activatoin Date"
    column), not spe.dtr Posted Date; statuses are Posted / Confirmed /
    Shipped / Canceled / Disconnected (office_metrics.nds_orderlog, Raf
    2026-08-06).
  * The view's Start/End Date parameters are PINNED to a stale saved week —
    the pull must pass its own Order Date window (same gotcha
    office_metrics.nds_orderlog documents).

THE RATE (stated on the image so it reads as what it is):
  * Buckets by ORDER (sale) date age: 0-30 and 31-60 days.
  * sold = every line in the bucket, cancels included (a cancel is a sale
    that never activated).
  * activated = the line has a DTR Active Date, or its status reached active
    (Posted — or Disconnected, which was active before it fell).
  * Color bands = the SAME office rules as the B2B board
    (vantura_churn.fill.BANDS: 0-30 green>=75%/yellow>=65%; 31-60 >=80/>=70).
  * Office Total = the whole owner's lines, never the sum of shown reps.
    Every rep in the window is shown — NDS has no sales-board roster here.

  python -m automations.nds_activation_by_rep.run                 # render + --push shot
  python -m automations.nds_activation_by_rep.run --dm U...,U...  # also DM the PNG
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

from automations.office_metrics import nds_orderlog as NO

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "output" / "nds_activation_by_rep"
SHOT_TAB = "NDS AR Shot"
DEFAULT_OWNER = "Khalil Mansour"
LOOKBACK_DAYS = 60
BUCKETS = ("0-30 Day", "31-60 Day")
_BAND_KEY = {"0-30 Day": "0-30", "31-60 Day": "31-60"}


def _parse_date(v: str) -> Optional[dt.date]:
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def pull(today: dt.date, verbose: bool = False) -> Path:
    """The ORDER LOG .csv with OUR 60-day Order-Date window (the view's own
    saved window is pinned stale — see module docstring)."""
    from automations.shared.tableau_patchright import tableau_session
    start = today - dt.timedelta(days=LOOKBACK_DAYS)
    url = NO._orderlog_url(start, today)
    cache = (Path(tempfile.gettempdir())
             / f"nds_ar_orderlog_{today.isoformat()}.csv")
    if cache.exists() and cache.stat().st_size > 500:
        return cache
    last = ""
    for attempt in (1, 2, 3):
        with tableau_session(verbose=verbose) as page:
            r = page.context.request.get(url, timeout=300_000)
            body = r.body() or b""
            print(f"[nds_ar] csv status={r.status} bytes={len(body):,} "
                  f"(try {attempt}/3, window {start}..{today})", flush=True)
            if r.status == 200 and len(body) >= 500:
                cache.write_bytes(body)
                return cache
            last = f"status={r.status} bytes={len(body)}"
    raise RuntimeError(f"NDS ORDER LOG export failed after 3 tries: {last}")


def _activated(status: str, active_date: Optional[dt.date]) -> bool:
    if active_date is not None:
        return True
    s = (status or "").strip().lower()
    return s == "posted" or "disconnect" in s


def tally(header, rows, today: dt.date, log=print) -> Dict[str, dict]:
    """{rep or '__TOTAL__': {bucket: {'sold': n, 'act': n}}}."""
    i_rep = NO._find(header, "rep")
    i_od = NO._find(header, "sp.order date", "order date")
    i_ad = NO._find(header, "dtr active date", "activatoin date",
                    "activation date")
    i_st = NO._find(header, "dtr status", "spe.status", "status")
    missing = [n for n, i in (("Rep", i_rep), ("Order Date", i_od),
                              ("Active Date", i_ad), ("Status", i_st))
               if i is None]
    if missing:
        raise RuntimeError(
            "NDS log columns not found: {} — header: {}".format(missing,
                                                                header))
    out: Dict[str, dict] = {}

    def slot(key, bucket):
        return out.setdefault(key, {b: {"sold": 0, "act": 0}
                                    for b in BUCKETS})[bucket]

    used = 0
    for r in rows:
        od = _parse_date(NO._cell(r, i_od))
        if od is None:
            continue
        age = (today - od).days
        if 0 <= age <= 30:
            bucket = "0-30 Day"
        elif 31 <= age <= 60:
            bucket = "31-60 Day"
        else:
            continue
        rep = NO._cell(r, i_rep) or "(no rep)"
        act = _activated(NO._cell(r, i_st), _parse_date(NO._cell(r, i_ad)))
        for key in (rep, "__TOTAL__"):
            c = slot(key, bucket)
            c["sold"] += 1
            if act:
                c["act"] += 1
        used += 1
    log(f"[nds_ar] {used} line(s) in the two buckets, "
        f"{len(out) - 1} rep(s)")
    return out


def build_png(counts: Dict[str, dict], owner: str, today: dt.date) -> Path:
    from automations.b2b_metrics.rep_boards import render_table_png
    from automations.vantura_churn.fill import BANDS

    def _color(bucket, rate):
        for floor, name in BANDS[_BAND_KEY[bucket]]:
            if rate >= floor:
                return name.capitalize()
        return ""

    def _cells(d):
        cells = {}
        for b in BUCKETS:
            c = d.get(b) or {}
            if not c.get("sold"):
                cells[b] = {}
                continue
            rate = c["act"] / c["sold"]
            cells[b] = {"act": str(c["sold"]), "disc": str(c["act"]),
                        "rate": f"{round(rate * 100, 1)}%",
                        "color": _color(b, rate)}
        return cells

    rows = [("Office Total (all reps)", "", True, _cells(counts["__TOTAL__"]))]
    for rep in sorted(k for k in counts if k != "__TOTAL__"):
        rows.append((rep, "", False, _cells(counts[rep])))
    return render_table_png(
        "ACTIVATION RATES BY REP",
        f"{owner} (NDS) — {today.strftime('%B %d, %Y')} "
        "(activated/sold by sale-date age, from the NDS-SN order log; "
        "cancels count as sold; total = whole office)",
        list(BUCKETS), rows, OUT_DIR / "nds_activation_by_rep.png")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nds_activation_by_rep")
    ap.add_argument("--owner", default=DEFAULT_OWNER)
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--push", action="store_true",
                    help=f"base64 the PNG into the control sheet "
                         f"({SHOT_TAB!r}) for the mini")
    ap.add_argument("--dm", default=None, metavar="U...,U...",
                    help="DM the PNG to these Slack user ids (as Lucy)")
    a = ap.parse_args(argv)
    today = (dt.date.fromisoformat(a.today) if a.today else dt.date.today())
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    path = pull(today, verbose=False)
    header, rows = NO.load(path, a.owner)
    if not rows:
        print(f"no rows for owner {a.owner!r} — check the Owner & Office "
              "spelling against the export")
        return 1
    counts = tally(header, rows, today)
    for b in BUCKETS:
        t = counts["__TOTAL__"][b]
        print(f"[nds_ar] OFFICE {b}: {t['act']}/{t['sold']}"
              + (f" = {100 * t['act'] / t['sold']:.1f}%" if t["sold"] else ""))
    png = build_png(counts, a.owner, today)
    print(f"[nds_ar] rendered {png} ({png.stat().st_size:,} bytes)")
    if a.push:
        from automations.sp_order_log.run import _push
        _push(png, SHOT_TAB)
    if a.dm:
        from automations.shared import slack_metrics_post as smp
        for uid in [u.strip() for u in a.dm.split(",") if u.strip()]:
            smp.dm_user_with_file(
                png, user=uid, file_name=png.name,
                comment=f"📈 *Activation Rates by Rep — {a.owner} (NDS)* — "
                        "computed from the NDS-SN (RES-ATT-OOF) order log "
                        "(activated/sold by sale-date age).")
            print(f"[nds_ar] DM'd {uid}")
    print("=== done ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
