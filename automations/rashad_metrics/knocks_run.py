"""Rashad's Knocks + Time Gaps — render & post the SAME two images Raf's
Total Knocks report posts, but for Rashad's office, WITHOUT writing any Sheet.

Flow:
  1. Pull Disposition by Rep + Time Tracker gaps for Rashad's office via
     `pull_office_knocks` (impersonates the office inside one ownerville
     session, scrapes, exits impersonation). Office is env-targetable
     (RASHAD_KNOCKS_OFFICE, default "Rashad Reed"), read by knocks_pull.
  2. Render the two PNGs straight from the in-memory rows — reusing Raf's
     `render_total_knocks` / `render_time_gaps` via their optional `rows=`
     param, so NO production Sheet is read or written. The images are
     identical to Raf's (same layout, same themes).
  3. Post both to today's Metrics thread via slack_metrics_post, which honors
     METRICS_CHANNEL_ID — the rashad_metrics runner sets that to Rashad's
     private #elevate-sales, so these land there instead of #alphalete-sales.

Each post leads with the workflow emoji + Title Case title, EXACTLY matching
Raf's total_knocks.run posts:
    🚪 Total Knocks   (reaction: door)
    🕐 Time Gaps      (reaction: clock1)

CLI:
  --dry-run   pull + render the PNG file(s) to output/, NO Slack post
  --live      pull + render + POST to the Metrics thread (honors
              METRICS_CHANNEL_ID set by the parent runner)
  date        optional YYYY-MM-DD positional (default: yesterday, Central)

No-data days post an explicit 'No data available' one-liner per metric (same
as Raf's), so the absence is visible and the parent reactions still mark both
metrics done.

Standalone preview (no Sheet, no Slack):
    python -m automations.rashad_metrics.knocks_run --dry-run
    python -m automations.rashad_metrics.knocks_run --dry-run 2026-06-27
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

# Keep emoji / checkmarks safe on the Windows console (cp1252 default).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os

from automations.rashad_metrics.knocks_pull import (
    DEFAULT_OFFICE,
    pull_office_knocks,
    pull_offices_knocks,
)
from automations.total_knocks import render as _render
from automations.total_knocks.pull import COL_TOTAL_KNOCKS, KnocksPullFailed
from automations.total_knocks.pull import central_today

# Same two posts, same order, same emoji+title strings as Raf's
# total_knocks.run (POST_TOTAL_KNOCKS / POST_TIME_GAPS): (comment label,
# reaction short-name). The comment leads with the workflow emoji + Title Case
# title; the same emoji is also added as a reaction on the parent.
POST_TOTAL_KNOCKS = ("🚪 Total Knocks", "door")
POST_TIME_GAPS    = ("🕐 Time Gaps", "clock1")

OUT_DIR = Path("output")

# Offices whose TOTAL line rides above this office's own on the fiber board
# (Raf 2026-08-23: "Chan's numbers on everyone's metric post"). Pulled in the
# SAME ownerville session as the office itself — one login covers both. The
# NDS runner entries set KNOCKS_EXTRA_TOTALS="" (a fiber totals row doesn't
# fit the wireless board); blank disables, comma-separated overrides.
EXTRA_TOTALS_OFFICES = [o.strip() for o in
                        os.environ.get("KNOCKS_EXTRA_TOTALS",
                                       "Chan Park").split(",") if o.strip()]


def run(target: dt.date | None = None, *, office_name: str | None = None,
        dry_run: bool = False) -> int:
    office_name = office_name or DEFAULT_OFFICE

    # 1. Pull (impersonate office → Disposition + Time Tracker gaps, merged).
    #    Extra-totals offices (Chan) ride in the same session; their failure
    #    or absence never blocks this office's post.
    extras = [o for o in EXTRA_TOTALS_OFFICES
              if o.strip().lower() != office_name.strip().lower()]
    try:
        rows, extra_totals, target = _pull(office_name, extras, target)
    except KnocksPullFailed as e:
        # A FAILED scrape, not a quiet day: post nothing (a "No data
        # available" line here would be a lie the thread can't tell from the
        # real thing) and exit non-zero so the runner's retry_on_fail fires
        # and the office lands in the manifest's failed list.
        print(f"[rashad_knocks] ❌ {office_name}: pull FAILED (not an empty "
              f"day) — {e}", flush=True)
        print("[rashad_knocks] Nothing posted; the runner's retry + failure "
              "alert take it from here.", flush=True)
        return 1
    print(f"[rashad_knocks] {office_name} — data date {target.isoformat()} — "
          f"{len(rows)} rep(s).", flush=True)

    # No-data day — VERIFIED empty (the scrape completed and the office
    # logged nothing). Post the 'No data available' one-liner per metric,
    # same as Raf's run.
    if not rows:
        print("[rashad_knocks] ⚠ No rows for that day (verified empty).",
              flush=True)
        if dry_run:
            for label, _ in (POST_TOTAL_KNOCKS, POST_TIME_GAPS):
                print(f"[rashad_knocks] --dry-run — would post 'No data "
                      f"available' for {label}.", flush=True)
            print("[rashad_knocks] ✅ Finished (dry-run, no data).", flush=True)
            return 0
        from automations.shared.slack_metrics_post import post_reply_text_only
        slack_today = central_today()   # post into TODAY's thread (Central)
        for label, emoji in (POST_TOTAL_KNOCKS, POST_TIME_GAPS):
            text = (f"{label} — {target.strftime('%b')} {target.day} "
                    f"— No data available")
            resp = post_reply_text_only(text, react_emoji=emoji,
                                        today=slack_today)
            if resp.get("ok"):
                print(f"[rashad_knocks] ✅ Posted '{label}' no-data notice.",
                      flush=True)
            else:
                print(f"[rashad_knocks] ⚠ Slack response for '{label}': {resp}",
                      flush=True)
        print("[rashad_knocks] ✅ Finished (no data).", flush=True)
        return 0

    return _render_and_post(office_name, target, rows, extra_totals,
                            dry_run=dry_run)


def _pull(office_name: str, extras: list, target):
    """The pull half of run(): this office's rows + any extra offices' totals.
    Raises KnocksPullFailed when THIS office's scrape failed; an extra
    office's failure only costs its comparison line."""
    if extras:
        target, pulled = pull_offices_knocks([office_name] + extras, target)
        _, rows, err0 = pulled[0]
        if err0 is not None:
            raise err0
        extra_totals = []
        for name, x_rows, x_err in pulled[1:]:
            if x_err is not None:
                print(f"[rashad_knocks] ⚠ {name} totals pull failed "
                      f"({type(x_err).__name__}) — posting without it.",
                      flush=True)
            elif x_rows and COL_TOTAL_KNOCKS in x_rows[0]:
                extra_totals.append((name, x_rows))
            else:
                print(f"[rashad_knocks] ⚠ {name}: no fiber rows — posting "
                      "without that totals line.", flush=True)
    else:
        target, rows = pull_office_knocks(office_name, target)
        extra_totals = []
    return rows, extra_totals, target


def _render_and_post(office_name: str, target, rows: list, extra_totals: list,
                     *, dry_run: bool) -> int:
    """Render this office's board(s) from the in-memory rows and post them.
    Only reached with a non-empty, successfully-pulled `rows`."""
    # 2. Render straight from the in-memory rows — no Sheet read/write.
    #    Three Disposition shapes (Raf 2026-08-22: "telemapper knocks … should
    #    be on there for the NDS guys"):
    #      house    — the standard amber Total Knocks board;
    #      wireless — an NDS office's own disposition shape (one Not
    #                 Interested bucket, no Sale): REAL knock counts, rendered
    #                 as Total Knocks with the wireless columns;
    #      gaps-only — no disposition rows at all: the Total Knocks slot gets
    #                 the TELEMAPPER KNOCKS board (the ownerville Time Tracker
    #                 table — first/last knock, breaks, gaps, sales time,
    #                 sales), so the thread never silently drops the metric.
    from automations.total_knocks.pull import COL_TALK_TO_NI
    wireless = (COL_TOTAL_KNOCKS in rows[0] and COL_TALK_TO_NI not in rows[0])
    gaps_only = COL_TOTAL_KNOCKS not in rows[0]
    posts = []
    if wireless:
        img_tk = _render.render_wireless_total_knocks(target, rows=rows,
                                                      out_dir=OUT_DIR)
    elif gaps_only:
        img_tk = _render.render_telemapper_knocks(target, rows=rows,
                                                  out_dir=OUT_DIR)
    else:
        img_tk = _render.render_total_knocks(target, out_dir=OUT_DIR, rows=rows,
                                             extra_totals=extra_totals)
    posts.append((img_tk, POST_TOTAL_KNOCKS))
    # Fiber (house shape): the combined board CARRIES Gaps + Total Gaps now
    # (Raf's Loom 2026-08-22) — no separate Time Gaps post. The NDS shapes
    # keep their Time Gaps post: their knocks board is the Time Tracker
    # mirror / wireless dispositions, approved as a pair.
    if wireless or gaps_only:
        img_tg = _render.render_time_gaps(target, out_dir=OUT_DIR, rows=rows)
        posts.append((img_tg, POST_TIME_GAPS))
    shape = ("wireless" if wireless else
             "telemapper-knocks fallback" if gaps_only else "house combined")
    print(f"[rashad_knocks] Rendered {shape} -> "
          f"{'; '.join(str(p[0]) for p in posts)}", flush=True)

    if dry_run:
        print("[rashad_knocks] --dry-run — rendered only, NO Slack post.",
              flush=True)
        print("[rashad_knocks] ✅ Finished (dry-run).", flush=True)
        return 0

    # 3. Post to the Metrics thread (honors METRICS_CHANNEL_ID).
    from automations.shared.slack_metrics_post import post_reply_with_image
    slack_today = central_today()   # post into TODAY's thread (Central)
    for img, (label, emoji) in posts:
        comment = f"{label} — {target.strftime('%b')} {target.day}"
        resp = post_reply_with_image(Path(img), comment=comment,
                                     react_emoji=emoji, today=slack_today)
        if resp.get("ok"):
            print(f"[rashad_knocks] ✅ Posted '{label}' "
                  f"(file {resp.get('file')}).", flush=True)
        else:
            print(f"[rashad_knocks] ⚠ Slack response for '{label}': {resp}",
                  flush=True)
    print("[rashad_knocks] ✅ Finished.", flush=True)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="rashad_metrics.knocks_run",
        description="Render & post Rashad's Knocks + Time Gaps images.")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: yesterday, Central)")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + render the PNG file(s) to output/, NO Slack post")
    ap.add_argument("--live", action="store_true",
                    help="pull + render + POST to the Metrics thread "
                         "(honors METRICS_CHANNEL_ID)")
    args = ap.parse_args(argv)

    if args.live and args.dry_run:
        print("✗ --live and --dry-run are mutually exclusive.")
        return 2
    # Default to dry-run if neither given, so nothing posts unintentionally.
    dry_run = not args.live

    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    return run(target, dry_run=dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
