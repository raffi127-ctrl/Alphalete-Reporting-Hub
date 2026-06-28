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

from automations.rashad_metrics.knocks_pull import DEFAULT_OFFICE, pull_office_knocks
from automations.total_knocks import render as _render
from automations.total_knocks.pull import central_today

# Same two posts, same order, same emoji+title strings as Raf's
# total_knocks.run (POST_TOTAL_KNOCKS / POST_TIME_GAPS): (comment label,
# reaction short-name). The comment leads with the workflow emoji + Title Case
# title; the same emoji is also added as a reaction on the parent.
POST_TOTAL_KNOCKS = ("🚪 Total Knocks", "door")
POST_TIME_GAPS    = ("🕐 Time Gaps", "clock1")

OUT_DIR = Path("output")


def run(target: dt.date | None = None, *, office_name: str | None = None,
        dry_run: bool = False) -> int:
    office_name = office_name or DEFAULT_OFFICE

    # 1. Pull (impersonate office → Disposition + Time Tracker gaps, merged).
    target, rows = pull_office_knocks(office_name, target)
    print(f"[rashad_knocks] {office_name} — data date {target.isoformat()} — "
          f"{len(rows)} rep(s).", flush=True)

    # No-data day — post (or, on dry-run, describe) the 'No data available'
    # one-liner per metric, same as Raf's run.
    if not rows:
        print("[rashad_knocks] ⚠ No rows for that day.", flush=True)
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

    # 2. Render both images straight from the in-memory rows — no Sheet read,
    #    no Sheet write. Reuses Raf's render via its optional rows= param.
    img_tk = _render.render_total_knocks(target, out_dir=OUT_DIR, rows=rows)
    img_tg = _render.render_time_gaps(target, out_dir=OUT_DIR, rows=rows)
    print(f"[rashad_knocks] Rendered -> {img_tk} ; {img_tg}", flush=True)

    if dry_run:
        print("[rashad_knocks] --dry-run — rendered only, NO Slack post.",
              flush=True)
        print("[rashad_knocks] ✅ Finished (dry-run).", flush=True)
        return 0

    # 3. Post both to the Metrics thread (honors METRICS_CHANNEL_ID).
    from automations.shared.slack_metrics_post import post_reply_with_image
    slack_today = central_today()   # post into TODAY's thread (Central)
    for img, (label, emoji) in ((img_tk, POST_TOTAL_KNOCKS),
                                (img_tg, POST_TIME_GAPS)):
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
