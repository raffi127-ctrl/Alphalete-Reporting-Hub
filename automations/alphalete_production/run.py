"""Daily 'Alphalete Production' post -- combines Jolie's two manual morning
screenshot posts into ONE automated thread in #alphalete-sales (as Lucy).

    python -m automations.alphalete_production.run --dry-run            # render PNGs, post nothing
    python -m automations.alphalete_production.run --preview-dm U04G5HJBGFN
    python -m automations.alphalete_production.run --only daily_production --dry-run
    python -m automations.alphalete_production.run                      # LIVE post to #alphalete-sales

Renders each section off a hidden, auto-deleted copy of the current-week Sales Board
tab (live sheet never touched), then posts the dated 🐺 parent + threaded image replies.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from automations.alphalete_production import capture, slack_post
from automations.alphalete_production.pages import SECTIONS
from automations.shared import run_manifest

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "alphalete_production"
REPORT_ID = "alphalete-production"          # matches schedule_config verify.report_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="render PNGs to output/, post nothing")
    ap.add_argument("--preview-dm", nargs="+", metavar="USER",
                    help="DM the full thread to these Slack user id(s)/name(s) for review")
    ap.add_argument("--only", nargs="+", metavar="ID",
                    help="only these section ids (default: all)")
    ap.add_argument("--out", default=str(OUT_DIR), help="PNG output dir")
    args = ap.parse_args()

    today = dt.date.today()
    out_dir = Path(args.out)
    live = not (args.dry_run or args.preview_dm)

    try:
        print(f"[alphalete_production] {today}  rendering sections"
              f"{' ' + ','.join(args.only) if args.only else ''}...", flush=True)
        captures, _grid, tab = capture.capture_all(SECTIONS, today, out_dir, only=args.only)
        print(f"  tab: {tab}   images: {len(captures)}", flush=True)
        for meta, png in captures:
            print(f"    {meta['title']:48} -> {Path(png).name}", flush=True)

        if args.dry_run:
            res = slack_post.post_all(captures, SECTIONS, today, dry_run=True)
            print("[dry-run] would post:\n" + json.dumps(res, indent=2), flush=True)
            return
        if args.preview_dm:
            res = slack_post.preview_dm(captures, SECTIONS, args.preview_dm, today)
            print("[preview-dm] " + json.dumps({k: res.get(k) for k in ("ok", "mode")},
                                                indent=2), flush=True)
            return
        res = slack_post.post_all(captures, SECTIONS, today)
        print("[posted] " + json.dumps({"ok": res["ok"], "thread_ts": res.get("thread_ts"),
                                         "created": res.get("created")}, indent=2), flush=True)
        if not res.get("ok"):
            raise RuntimeError("slack post reported not ok: " + json.dumps(res)[:300])
        run_manifest.mark_clean(REPORT_ID)
    except Exception as e:
        if live:
            run_manifest.write_manifest(
                REPORT_ID, ok=False, failed=["post"], retry_args=[],
                remediation={"reason": f"{type(e).__name__}: {str(e)[:200]}",
                             "fix": "lucy rerun alphalete_production",
                             "message": "Alphalete Production post failed — "
                                        f"{type(e).__name__}: {str(e)[:150]}"})
        raise


if __name__ == "__main__":
    main()
