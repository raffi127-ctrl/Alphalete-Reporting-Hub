"""Daily Tableau tracker screenshots -> #alphalete-sales.

Flow: open ONE warm Tableau session (reused for all pages) -> capture each view
to a PNG -> post them into today's own dated thread -> write a run manifest.

Usage
  # capture-only, writes PNGs to output/tableau_screenshots/, posts NOTHING:
  python -m automations.tableau_screenshots.run --dry-run
  python -m automations.tableau_screenshots.run --dry-run --full   # whole board
  python -m automations.tableau_screenshots.run --dry-run --only nds,b2b_box

  # live (captures + posts to Slack):
  python -m automations.tableau_screenshots.run

Build discipline (CLAUDE.md): stays on --dry-run until Megan confirms the PNGs +
crop look right; a scratch channel can be forced via TABLEAU_TRACKERS_CHANNEL_ID
so a test post never lands in the real channel.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from automations.tableau_screenshots import pages as pages_mod
from automations.tableau_screenshots import capture as cap
from automations.tableau_screenshots import slack_post as sp

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "tableau_screenshots"
REPORT_ID = "tableau-screenshots"


def _select(only: str | None) -> list:
    if not only:
        return list(pages_mod.PAGES)
    wanted = [s.strip() for s in only.split(",") if s.strip()]
    out = []
    for w in wanted:
        p = pages_mod.by_id(w)
        if p is None:
            raise SystemExit(f"--only: no tracker with id {w!r}. "
                             f"Known: {[p['id'] for p in pages_mod.PAGES]}")
        out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Capture PNGs to output/ but post NOTHING to Slack.")
    ap.add_argument("--only", default=None,
                    help="Comma-separated tracker id(s) to run (default: all).")
    ap.add_argument("--full", action="store_true",
                    help="Force full_page capture (whole board) for every "
                         "tracker, overriding each page's crop -- use on the "
                         "first mini run to see everything, then tune crop.")
    ap.add_argument("--preview-dm", default=None,
                    help="Comma-separated Slack user id(s)/emails/names. Capture "
                         "then DM the full thread (header + real images) to them "
                         "for review, posting NOTHING to the channels.")
    ap.add_argument("--inspect", action="store_true",
                    help="Read-only: dump each view's dashboard tab strip + "
                         "Download→Image dialog so we can target a single page. "
                         "No capture, no post.")
    ap.add_argument("--headless", action="store_true",
                    help="Run the browser headless (default: headed, matches the "
                         "other Tableau reports + renders more reliably).")
    ap.add_argument("--out-dir", default=str(OUT_DIR),
                    help="Where to write PNGs (default: output/tableau_screenshots).")
    args = ap.parse_args(argv)

    today = dt.date.today()
    selected = _select(args.only)
    out_dir = Path(args.out_dir)
    force_crop = "full" if args.full else None

    print(f"Tableau tracker screenshots -- {len(selected)} view(s), "
          f"{'DRY-RUN (no Slack)' if args.dry_run else 'LIVE'}, "
          f"out={out_dir}", flush=True)

    from automations.shared.tableau_patchright import tableau_session
    from automations.shared import run_manifest

    captures: list = []
    failed: list = []

    # allow_form_login=False -> unattended reuse-only; fails fast (with the
    # re-export message) if the warm session is cold, instead of touching the
    # Cloudflare Turnstile.
    if args.inspect:
        infos = []
        with tableau_session(headless=args.headless, allow_form_login=False,
                             verbose=True) as page:
            for spec in selected:
                try:
                    infos.append(cap.inspect_view(page, spec, verbose=True))
                except Exception as e:
                    infos.append({"id": spec["id"],
                                  "error": f"{type(e).__name__}: {str(e)[:200]}"})
        # Write full findings to a sheet tab (lucy status truncates to 280 chars,
        # so the structure never survives the result cell). Read 'Inspect Out' on
        # the control workbook from any machine to see tabs + dialog per tracker.
        try:
            import json as _json
            import gspread
            from automations.recruiting_report import fill as _fill
            from automations.day_orchestrator.mini_control import CONTROL_SHEET_ID
            sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
            try:
                ws = sh.worksheet("Inspect Out")
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title="Inspect Out", rows=50, cols=6)
            rows = [["id", "active_tab", "download_menu", "tabs",
                     "dialog/frame_text", "err"]]
            for i in infos:
                rows.append([
                    i.get("id", ""), i.get("active_tab", ""),
                    i.get("download_menu", ""),
                    _json.dumps(i.get("tabs", []), ensure_ascii=False),
                    (i.get("dialog", ""))[:40000],
                    (i.get("dialog_err", "") or i.get("error", "")),
                ])
            ws.clear()
            ws.update(rows, "A1")
            print(f"INSPECT wrote {len(infos)} row(s) to 'Inspect Out' tab.",
                  flush=True)
        except Exception as e:
            print(f"INSPECT sheet-write failed: {type(e).__name__}: {str(e)[:160]}",
                  flush=True)
        return 0

    with tableau_session(headless=args.headless, allow_form_login=False,
                         verbose=True) as page:
        for spec in selected:
            try:
                png = cap.capture_page(page, spec, out_dir,
                                       force_crop=force_crop, verbose=True)
                captures.append((spec, png))
            except Exception as e:
                failed.append(spec["id"])
                print(f"   ⚠ {spec['id']} FAILED: "
                      f"{type(e).__name__}: {str(e).splitlines()[0][:120]}",
                      flush=True)

    # Per-tracker summary (lands in the mini log so match/parity is visible).
    print("\n=== CAPTURE SUMMARY ===", flush=True)
    for spec, png in captures:
        try:
            from PIL import Image
            with Image.open(png) as im:
                dims = f"{im.width}x{im.height}"
        except Exception:
            dims = "?x?"
        kb = Path(png).stat().st_size // 1024
        print(f"  ✓ {spec['id']:<28} {dims:>11}px  {kb:>5} KB  {Path(png).name}",
              flush=True)
    for fid in failed:
        print(f"  ✗ {fid:<28} FAILED (no image)", flush=True)
    print(f"  saved to: {out_dir}", flush=True)

    if not captures:
        run_manifest.write_manifest(
            REPORT_ID, ok=False, failed=failed, kind="tracker",
            retry_args=["--only", ",".join(failed)] if failed else [],
            note="no trackers captured")
        print("\n❌ Captured nothing. See errors above.", flush=True)
        return 1

    # Preview-DM mode: DM the captured thread to reviewers, post nothing to
    # the channels.
    if args.preview_dm:
        users = [u.strip() for u in args.preview_dm.split(",") if u.strip()]
        pv = sp.preview_dm(captures, pages_mod.PAGES, users, today,
                           dry_run=args.dry_run)
        if args.dry_run:
            print(f"\n✓ DRY-RUN: captured {len(captures)} PNG(s) to {out_dir}; "
                  f"would DM {', '.join(users)} (nothing to channels).", flush=True)
        else:
            print(f"\n✓ PREVIEW DM'd to {', '.join(pv.get('user_ids', users))} "
                  f"(mode={pv.get('mode')}) — {len(captures)} image(s), "
                  f"nothing posted to the channels.", flush=True)
        run_manifest.write_manifest(
            REPORT_ID, ok=bool(not failed), failed=failed, kind="tracker",
            note="preview-dm run" + (f"; {len(failed)} failed" if failed else ""))
        return 1 if failed else 0

    # Post (or preview) into today's own dated thread.
    result = sp.post_all(captures, pages_mod.PAGES, today, dry_run=args.dry_run)

    if args.dry_run:
        print(f"\n✓ DRY-RUN: captured {len(captures)} PNG(s) to {out_dir}",
              flush=True)
        print(f"  would post to channels {', '.join(result['channels'])} as:")
        print("  --- header ---")
        for ln in result["header"].splitlines():
            print(f"    {ln}")
        print("  --- replies ---")
        for r in result["replies"]:
            print(f"    {r['caption']}  [{r['file']}]  :{r['react']}:")
    else:
        for c in result.get("channels", []):
            if c.get("ok"):
                print(f"\n✓ posted {len(c.get('posted', []))} image(s) to "
                      f"thread {c.get('thread_ts')} in {c['channel']} "
                      f"(thread {'created' if c.get('created') else 'reused'})",
                      flush=True)
            else:
                print(f"\n⚠ channel {c['channel']} post FAILED: "
                      f"{c.get('error', 'see above')}", flush=True)

    # Manifest: clean iff every selected tracker captured (and, live, posted).
    ok = not failed and (args.dry_run or result.get("ok"))
    run_manifest.write_manifest(
        REPORT_ID, ok=bool(ok), failed=failed, kind="tracker",
        retry_args=["--only", ",".join(failed)] if failed else [],
        note=("" if ok else f"{len(failed)} tracker(s) failed: {', '.join(failed)}"))

    if failed:
        print(f"\n⚠ {len(failed)} failed: {', '.join(failed)}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
