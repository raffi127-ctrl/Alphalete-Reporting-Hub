"""Daily "Tableau Country Trackers" -> one thread per ORG.

The same 8 COUNTRY-wide boards go to three orgs (Raf, 2026-07-14) — identical
images, one Hub card each:
  --org alphalete   #alphalete-sales + #top-leaders-alphalete-org   (default)
  --org elevate     #elevate-sales
  --org indelible   #indelible-sales

Flow: reuse today's PNGs if another org already captured them, else open ONE warm
Tableau session -> capture each view to a PNG -> post them into today's own dated
thread for this org -> write a per-org run manifest. Only the first org of the
day drives Tableau (the boards are the same for everyone); --fresh overrides.

Usage
  # capture-only, writes PNGs to output/tableau_screenshots/, posts NOTHING:
  python -m automations.tableau_screenshots.run --dry-run
  python -m automations.tableau_screenshots.run --dry-run --full   # whole board
  python -m automations.tableau_screenshots.run --dry-run --only nds,b2b_box

  # live (captures + posts to Slack):
  python -m automations.tableau_screenshots.run                    # alphalete
  python -m automations.tableau_screenshots.run --org elevate      # reuses PNGs

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

# One manifest id PER ORG, or three runs would clobber each other's manifest and
# the orchestrator's verify step would read the wrong run. alphalete keeps the
# original id so its existing Hub card / verify history stays continuous.
_REPORT_ID = {"alphalete": "tableau-screenshots",
              "elevate": "tableau-screenshots-elevate",
              "indelible": "tableau-screenshots-indelible"}

# The 8 boards are COUNTRY-wide -- all three orgs post byte-identical images. So
# capture ONCE per day and let the other orgs reuse the PNGs: re-driving Tableau
# for 8 Download->Image exports is the slowest thing in the batch (~7 min) and
# every extra run is another chance to hit a Tableau flake, all for the same
# pixels. The reuse is a CACHE, not a dependency -- if today's capture is missing
# or incomplete (e.g. the alphalete run failed), the org captures for itself.
# --fresh forces a re-capture regardless.
STAMP = OUT_DIR / "_captured.json"


def _write_stamp(out_dir: Path, captured: list, today: dt.date) -> None:
    """Record which trackers were captured, and when, so a later org run can tell
    whether today's PNGs are complete enough to reuse."""
    import json
    try:
        (out_dir / STAMP.name).write_text(json.dumps({
            "date": today.isoformat(),
            "ids": [spec["id"] for spec, _ in captured],
        }))
    except Exception:            # best-effort — a missing stamp just means recapture
        pass


def _reusable(out_dir: Path, selected: list, today: dt.date) -> list | None:
    """Today's captures as [(spec, png)] if EVERY selected tracker was captured
    today and its PNG is still on disk — else None (→ capture fresh). Deliberately
    strict: a partial set would silently post a short thread."""
    import json
    stamp = out_dir / STAMP.name
    if not stamp.exists():
        return None
    try:
        data = json.loads(stamp.read_text())
    except Exception:
        return None
    if data.get("date") != today.isoformat():
        return None              # yesterday's images — never post stale boards
    have = set(data.get("ids") or [])
    out = []
    for spec in selected:
        png = out_dir / f"{cap._sanitize(spec['title'])}.png"
        if spec["id"] not in have or not png.exists():
            return None
        out.append((spec, png))
    return out


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
    ap.add_argument("--org", default=sp.DEFAULT_ORG, choices=sp.ORGS,
                    help="Which org's channel(s) to post into. "
                         "alphalete = #alphalete-sales + #top-leaders-alphalete-org, "
                         "elevate = #elevate-sales, indelible = #indelible-sales. "
                         "Same 8 country-wide images for every org.")
    ap.add_argument("--fresh", action="store_true",
                    help="Force a re-capture even if today's PNGs already exist. "
                         "By default an org reuses images captured earlier today "
                         "(the boards are identical for all orgs), so only the "
                         "first run of the day drives Tableau.")
    ap.add_argument("--retitle-only", action="store_true",
                    help="Rename today's already-posted thread header to the "
                         "current title and do nothing else (no capture, no "
                         "post). For the day the title changed.")
    ap.add_argument("--replace", action="store_true",
                    help="Re-post TODAY's thread: delete the image replies "
                         "already under today's parent, then post this capture "
                         "in header order. Use after a crop fix so the corrected "
                         "images land in the right position (Slack appends "
                         "replies, so a plain re-post would land at the bottom). "
                         "Run with all 8 trackers -- it replaces the whole set.")
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

    report_id = _REPORT_ID[args.org]
    print(f"Tableau country trackers -- {len(selected)} view(s), org={args.org} "
          f"({sp.ORG_LABEL[args.org]}), "
          f"{'DRY-RUN (no Slack)' if args.dry_run else 'LIVE'}, "
          f"out={out_dir}", flush=True)

    # Header-only rename of today's existing thread — no browser, no capture, no
    # new messages. Runs before anything else touches Tableau.
    if args.retitle_only:
        res = sp.retitle_today(pages_mod.PAGES, today, org=args.org)
        for r in res["results"]:
            print(f"  {r['channel']}: {r['status']}", flush=True)
        bad = [r for r in res["results"] if str(r["status"]).startswith("FAILED")]
        print(f"\n{'⚠' if bad else '✓'} retitle-only ({args.org}): "
              f"{sp.header_title(today)}", flush=True)
        return 1 if bad else 0

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

    # Reuse today's images when another org already captured them — no browser, no
    # Tableau session at all, so elevate/indelible finish in seconds. --fresh (and
    # --full, which changes how the boards are captured) always re-captures.
    reused = None if (args.fresh or args.full) else _reusable(out_dir, selected, today)
    if reused is not None:
        captures = reused
        print(f"   ↺ reusing {len(captures)} image(s) captured earlier today "
              f"(same country-wide boards; --fresh to re-capture)", flush=True)
    else:
        # NOTE: device_scale=2 (2x DPI) broke the live all-8 run 2026-07-05 (SSO/session
        # setup failed before any capture) — reverted to native res, which captured all
        # 8 cleanly in testing. Re-add the zoom only after debugging why it fails at
        # scale (the single-tracker dry-run worked, the full run didn't).
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
        # Only a COMPLETE capture is worth reusing — stamp it so the next org can.
        if captures and not failed:
            _write_stamp(out_dir, captures, today)

    # Per-tracker summary (lands in the mini log) + written to the 'Inspect Out'
    # sheet (readable from any machine, since lucy status truncates to 280 chars).
    print("\n=== CAPTURE SUMMARY ===", flush=True)
    sheet_rows = [["id", "dims(px)", "KB", "status", "crop_debug", "trim_debug"]]
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
        sheet_rows.append([spec["id"], dims, str(kb), "ok",
                           cap.CROP_DEBUG.get(spec["id"], ""),
                           cap.TRIM_DEBUG.get(spec["id"], "")])
    for fid in failed:
        print(f"  ✗ {fid:<28} FAILED (no image)", flush=True)
        sheet_rows.append([fid, "", "", "FAILED", "", ""])
    print(f"  saved to: {out_dir}", flush=True)
    try:
        import gspread
        from automations.recruiting_report import fill as _fill
        from automations.day_orchestrator.mini_control import CONTROL_SHEET_ID
        sh = _fill._client().open_by_key(CONTROL_SHEET_ID)
        try:
            ws = sh.worksheet("Inspect Out")
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title="Inspect Out", rows=50, cols=6)
        ws.clear()
        ws.update(sheet_rows, "A1")
        print("  (capture summary written to 'Inspect Out' sheet)", flush=True)
    except Exception as e:
        print(f"  (sheet-write failed: {type(e).__name__}: {str(e)[:120]})",
              flush=True)

    if not captures:
        run_manifest.write_manifest(
            report_id, ok=False, failed=failed, kind="tracker",
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
            report_id, ok=bool(not failed), failed=failed, kind="tracker",
            note="preview-dm run" + (f"; {len(failed)} failed" if failed else ""))
        return 1 if failed else 0

    # Post (or preview) into today's own dated thread.
    result = sp.post_all(captures, pages_mod.PAGES, today, dry_run=args.dry_run,
                         replace=args.replace, org=args.org)

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
                rm = c.get("removed") or 0
                print(f"\n✓ posted {len(c.get('posted', []))} image(s) to "
                      f"thread {c.get('thread_ts')} in {c['channel']} "
                      f"(thread {'created' if c.get('created') else 'reused'}"
                      + (f", replaced {rm} old image(s)" if rm else "") + ")",
                      flush=True)
            else:
                print(f"\n⚠ channel {c['channel']} post FAILED: "
                      f"{c.get('error', 'see above')}", flush=True)

    # Manifest: clean iff every selected tracker captured (and, live, posted).
    ok = not failed and (args.dry_run or result.get("ok"))
    run_manifest.write_manifest(
        report_id, ok=bool(ok), failed=failed, kind="tracker",
        retry_args=["--only", ",".join(failed)] if failed else [],
        note=("" if ok else f"{len(failed)} tracker(s) failed: {', '.join(failed)}"))

    if failed:
        print(f"\n⚠ {len(failed)} failed: {', '.join(failed)}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
