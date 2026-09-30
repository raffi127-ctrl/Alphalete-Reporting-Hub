"""Southshore Org Sales Board — pull, render, text to Colten's org chat.

Runs on LUCY 1 in the 4am batch, right after the Org Sales Board.

  # dry-run (DEFAULT): pull + render + resolve the group, text NOTHING
  python -m automations.southshore_org_board.run

  # live: text the board, then drop today's .sent marker
  python -m automations.southshore_org_board.run --send

  # the schedule: build at 05:45, text at 06:00 Central (7am Eastern)
  python -m automations.southshore_org_board.run --send --send-at 06:00

  # redraw from the files already pulled today (no Tableau)
  python -m automations.southshore_org_board.run --skip-pull

The week shown is the Org Sales Board's reporting week (rolls Tuesday): on
Monday the text carries last week complete; Tue–Sun, this week through
yesterday. Python 3.9-safe (the mini's runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

from automations.southshore_org_board import config as cfg
from automations.southshore_org_board import data, render

try:
    from zoneinfo import ZoneInfo
    _CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    _CENTRAL = None


def _today() -> dt.date:
    return (dt.datetime.now(_CENTRAL) if _CENTRAL else dt.datetime.now()).date()


def build(today: dt.date, *, skip_pull: bool = False, verbose: bool = False):
    """Pull, update history, render. Returns (png, summary dict)."""
    from automations.org_sales_board import week as wk
    monday = wk.reporting_monday(today)
    week = data.week_of(monday)
    done = [d for d in week if d < today]
    out_dir = cfg.OUTPUT_DIR / today.isoformat()

    if skip_pull:
        nds_path = out_dir / "nds_thisweekandlast.csv"
        b2b_path = out_dir / "b2b_byday.csv"
    else:
        nds_path, b2b_path = data.pull(today, out_dir, verbose=verbose)
    nds = data.parse_twl(nds_path)
    b2b = data.parse_b2b(b2b_path, today)
    if not nds:
        raise RuntimeError(f"NDS crosstab came back empty ({nds_path.name})")

    # Which days each pull PROVES: every dated column of the NDS view; the B2B
    # view only the reporting week. Only days already over are recorded — a
    # proven 0 for an owner the view lists with no sale that day.
    nds_days = [d for d in data.twl_dates(nds_path) if d < today]
    if monday not in {d - dt.timedelta(days=d.weekday()) for d in nds_days} and done:
        raise RuntimeError(
            f"the NDS view doesn't cover the reporting week {monday} "
            f"(covers {sorted(set(nds_days))[:1]}…) — Tableau hasn't rolled?")
    owner_days = {}
    for owner, src in cfg.ROSTER:
        got = (nds if src == "nds" else b2b).get(owner, {})
        span = nds_days if src == "nds" else done
        owner_days[owner] = {d.isoformat(): got.get(d.isoformat(), 0) for d in span}
    missing = [o for o, src in cfg.ROSTER
               if src == "nds" and o not in nds] + \
              [o for o, src in cfg.ROSTER if src == "b2b" and o not in b2b]

    hist = data.load_history()
    mondays = sorted({d - dt.timedelta(days=d.weekday()) for d in nds_days} | {monday})
    data.record(hist, owner_days, mondays)
    data.save_history(hist)

    rows = []
    for owner, _src in cfg.ROSTER:
        vals = [owner_days[owner].get(d.isoformat()) if d in done else None
                for d in week]
        units = sum(v or 0 for v in vals)
        lw = data.owner_total(hist, monday - dt.timedelta(weeks=1), owner)
        pw = data.owner_total(hist, monday - dt.timedelta(weeks=2), owner)
        rows.append((owner.title(), vals, units, lw, pw))
    rows.sort(key=lambda r: (-r[2], -(r[3] or 0)))

    history = []
    for k in range(1, 5):
        m = monday - dt.timedelta(weeks=k)
        history.append((m + dt.timedelta(days=6), data.org_by_day(hist, m)))

    def _tot(k):
        vals = [r[3] if k == 1 else r[4] for r in rows]
        return None if any(v is None for v in vals) else sum(vals)

    png = render.render(out_dir / f"southshore_org_board_{today.isoformat()}.png",
                        week=week, done=done, rows=rows, history=history,
                        lw_total=_tot(1), pw_total=_tot(2), title=cfg.TITLE)
    org_now = sum(r[2] for r in rows)
    summary = {"week_ending": week[-1], "days": len(done), "org_units": org_now,
               "missing": missing, "rows": rows, "history": history}
    return png, summary


def _wait_until(hhmm: str) -> None:
    """Sleep until HH:MM Central today. Already past it = send now (a late run
    still delivers; it never waits for tomorrow)."""
    h, m = (int(x) for x in hhmm.split(":"))
    now = dt.datetime.now(_CENTRAL) if _CENTRAL else dt.datetime.now()
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    wait = (at - now).total_seconds()
    if wait > 0:
        print(f"  holding the text until {hhmm} Central ({int(wait)}s)", flush=True)
        time.sleep(wait)


def caption(week_ending: dt.date) -> str:
    return f"📊 {cfg.TITLE} — W.E. {week_ending.month}.{week_ending.day}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--send", action="store_true",
                    help="text the board (default: dry-run, texts nothing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit dry-run (already the default)")
    ap.add_argument("--skip-pull", action="store_true",
                    help="redraw from today's already-pulled files")
    ap.add_argument("--force", action="store_true",
                    help="text again although today's marker says it went — "
                         "ONLY when the first text was wrong")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--send-at", default=None, metavar="HH:MM",
                    help="build right away, then hold the text until this "
                         "Central time (Megan 2026-09-30: 7am Eastern = 06:00)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    today = dt.date.fromisoformat(args.day) if args.day else _today()
    dry = not args.send
    from automations.shared import run_manifest
    print(f"Southshore Org board — {'DRY-RUN' if dry else 'SEND'} — {today}",
          flush=True)

    marker = cfg.OUTPUT_DIR / today.isoformat() / "texted.sent"
    if not dry and marker.exists() and not args.force:
        print(f"  already texted today ({marker.read_text().strip()}) — skip")
        return 0

    try:
        png, s = build(today, skip_pull=args.skip_pull, verbose=args.verbose)
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {str(e)[:300]}"
        print(f"  FAILED: {msg}", flush=True)
        if not dry:
            run_manifest.write_manifest(cfg.REPORT_ID, failed=["board"], kind="part",
                                        note=msg)
        return 1
    for name, vals, units, lw, pw in s["rows"]:
        print(f"    {name:18} {units:>4}  LW {lw}  PW {pw}")
    print(f"  org {s['org_units']} over {s['days']} day(s); image {png}", flush=True)
    if s["missing"]:
        print(f"  no sales in the view this week/last for: {s['missing']} (shown as 0)")

    # Never text a board with nothing on it (Monday–Sunday all empty).
    if s["days"] and not s["org_units"]:
        note = "every ICD reads 0 — the pull came back empty; NOT texted"
        print(f"  FAILED: {note}")
        if not dry:
            run_manifest.write_manifest(cfg.REPORT_ID, failed=["board"], note=note)
        return 1
    if not s["days"]:
        print("  nothing closed yet this week (Tuesday roll) — nothing to text")
        return 0

    from automations.b2b_dispositions import text_post as tp
    if cfg.GROUP is None:
        print("  GROUP not set in config — can't resolve or send yet")
        return 0 if dry else 1
    text = caption(s["week_ending"])
    if args.send_at and not dry:
        _wait_until(args.send_at)
    try:
        res = tp.send_to_group(cfg.GROUP, text, [png], dry_run=dry)
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {str(e)[:300]}"
        print(f"  SEND FAILED: {msg}", flush=True)
        if not dry:
            run_manifest.write_manifest(cfg.REPORT_ID, failed=[cfg.GROUP],
                                        kind="part", note=msg)
        return 1
    verb = "WOULD TEXT" if dry else "TEXTED"
    print(f"  {verb} {cfg.GROUP!r} (chat {res.get('chat_id')}, "
          f"{res.get('participants')} people): {text}", flush=True)
    if not dry:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(dt.datetime.now().isoformat(timespec="seconds"))
        run_manifest.write_manifest(cfg.REPORT_ID, succeeded=[cfg.GROUP],
                                    note=f"texted W.E. {s['week_ending']} "
                                         f"({s['org_units']} units)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
