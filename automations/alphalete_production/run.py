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
from automations.alphalete_production.pages import sections_for
from automations.shared import run_manifest

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "alphalete_production"
REPORT_ID = "alphalete-production"          # matches schedule_config verify.report_id
ORCH_ID = "alphalete_production"            # the key `lucy rerun` takes


def _still_open(rendered: set) -> list:
    """Sections TODAY's manifest still lists as failed that this run didn't cover.

    Only consulted after a `--only` rerun. Yesterday's manifest is not today's
    news, so a stale run_ts counts as nothing open."""
    m = run_manifest.read_manifest(REPORT_ID) or {}
    if (m.get("run_ts") or "")[:10] != dt.date.today().isoformat():
        return []
    return [f for f in m.get("failed", []) if f not in rendered]


def _alert_dropped(dropped: list, captures: list) -> None:
    """The thread posted but SHORT — say so in #claudecorrections.

    Eve 8/31: the New Starts table is often still empty at 4am because SHE fills
    it in around 6:30 Central. Before this, a skipped section was visible only in
    the log: the thread went out one image short and nobody knew, so the image
    was simply never added that day. write_manifest(failed=…) fires the shared
    section_drop_alert into the channel, and the ✅ goes back on it by itself the
    next time the report runs clean (run_manifest.mark_clean).

    Exit stays 0 on purpose — the orchestrator must NOT retry, because a full
    re-run re-posts every section that already landed into the same thread."""
    ids = [i for i, _ in dropped]
    landed = [m.get("id") for m, _ in captures if m.get("id")]
    only = " ".join(ids)
    run_manifest.write_manifest(
        REPORT_ID, ok=False, kind="section",
        failed=ids, succeeded=sorted(set(landed)),
        retry_args=["--only", *ids],
        note="; ".join(f"{i}: {why[:180]}" for i, why in dropped),
        remediation={
            "reason": "; ".join(f"{i}: {why[:180]}" for i, why in dropped),
            "fix": (f"re-run ONLY what dropped: `lucy rerun {ORCH_ID} "
                    f"--only {only}` — it finds today's 🐺 thread and appends the "
                    "missing image to it. Do NOT re-run the whole report: that "
                    "re-posts every section that already landed. If `new_starts` "
                    "is the one that dropped, it is usually just that the New "
                    "Starts table on the week's Sales Board tab has no names in "
                    "it yet — re-run it once the classroom is filled in."),
            "message": (f"Alphalete Production posted but is short {len(ids)} "
                        f"section(s): {only}")})


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
    # day-gated sections drop out on the days they can't be built (New Starts on
    # Monday); an explicit --only overrides that gate. pages.sections_for()
    sections = sections_for(today, only=args.only)

    dropped = []                       # (section_id, reason) for anything skipped

    try:
        print(f"[alphalete_production] {today}  rendering sections"
              f"{' ' + ','.join(args.only) if args.only else ''}...", flush=True)
        captures, _grid, tab = capture.capture_all(sections, today, out_dir,
                                                   only=args.only, failures=dropped)
        print(f"  tab: {tab}   images: {len(captures)}", flush=True)
        for meta, png in captures:
            print(f"    {meta['title']:48} -> {Path(png).name}", flush=True)

        if args.dry_run:
            res = slack_post.post_all(captures, sections, today, dry_run=True)
            print("[dry-run] would post:\n" + json.dumps(res, indent=2), flush=True)
            return
        if args.preview_dm:
            res = slack_post.preview_dm(captures, sections, args.preview_dm, today)
            print("[preview-dm] " + json.dumps({k: res.get(k) for k in ("ok", "mode")},
                                                indent=2), flush=True)
            return
        res = slack_post.post_all(captures, sections, today)
        print("[posted] " + json.dumps({"ok": res["ok"], "thread_ts": res.get("thread_ts"),
                                         "created": res.get("created")}, indent=2), flush=True)
        if not res.get("ok"):
            raise RuntimeError("slack post reported not ok: " + json.dumps(res)[:300])
        if dropped:
            _alert_dropped(dropped, captures)      # thread is live but SHORT
        else:
            rendered = {m.get("id") for m, _ in captures}
            still = _still_open(rendered) if args.only else []
            if still:
                # A `--only` rerun fixed ITS section but the thread is still
                # short something else — mark_clean() would clear the whole
                # manifest and put a ✅ on an incident nobody fixed.
                print("[alphalete_production] not marking clean — still missing: "
                      + ", ".join(still), flush=True)
            else:
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
