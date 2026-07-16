"""Daily "Tableau Country Trackers" -> one thread per ORG.

The same 8 COUNTRY-wide boards go to five orgs (Raf, 2026-07-14) — identical
images, one Hub card each:
  --org alphalete     #alphalete-sales + #top-leaders-alphalete-org  (default)
  --org elevate       #elevate-sales
  --org indelible     #indelible-sales
  --org palace        #palace-sales
  --org elite_prime   #elite-prime-sales

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
REPORT_ID = "tableau-screenshots"

# Per-channel outcome of today's run, read by the Hub card to show its ✅/❌
# checklist. One card posts to EVERY channel, so the card needs to say which
# channels actually landed -- a single red/green light would hide a lone failure.
STATUS_FILE = OUT_DIR / "_posted_today.json"

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


def _select_orgs(orgs: str) -> list:
    """'all' -> every org, in channel order; else the named comma-separated subset."""
    raw = (orgs or "all").strip()
    if raw.lower() == "all":
        return list(sp.ORGS)
    want = [o.strip() for o in raw.split(",") if o.strip()]
    bad = [o for o in want if o not in sp.ORGS]
    if bad:
        raise SystemExit(f"--orgs: unknown org(s) {', '.join(bad)}. "
                         f"Known: {', '.join(sp.ORGS)} (or 'all')")
    return want


def _write_status(out_dir: Path, results: list, today: dt.date) -> None:
    """Today's per-channel outcome, for the Hub card's checklist."""
    import json
    try:
        (out_dir / STATUS_FILE.name).write_text(json.dumps({
            "date": today.isoformat(),
            "channels": results,
        }, indent=2))
    except Exception:            # best-effort — the post already happened
        pass


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
    ap.add_argument("--orgs", default="all",
                    help="Which org(s) to post to — comma-separated, or 'all' "
                         "(the default: every channel, in one run off ONE "
                         "capture). Use a subset to re-post just the channels "
                         "that missed, e.g. --orgs elevate,palace. Orgs: "
                         + "; ".join(f"{o} = {sp.ORG_LABEL[o]}" for o in sp.ORGS))
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

    orgs = _select_orgs(args.orgs)
    report_id = REPORT_ID
    print(f"Tableau country trackers -- {len(selected)} view(s) -> {len(orgs)} org(s): "
          f"{', '.join(sp.ORG_LABEL[o] for o in orgs)}, "
          f"{'DRY-RUN (no Slack)' if args.dry_run else 'LIVE'}, "
          f"out={out_dir}", flush=True)

    # Header-only rename of today's existing thread — no browser, no capture, no
    # new messages. Runs before anything else touches Tableau.
    if args.retitle_only:
        bad = []
        for org in orgs:
            res = sp.retitle_today(pages_mod.PAGES, today, org=org)
            for r in res["results"]:
                print(f"  [{org}] {r['channel']}: {r['status']}", flush=True)
            bad += [r for r in res["results"] if str(r["status"]).startswith("FAILED")]
        print(f"\n{'⚠' if bad else '✓'} retitle-only: {sp.header_title(today)}",
              flush=True)
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

    # Post into each org's own dated thread — ONE capture feeds them all. An org
    # that blows up must NOT take the rest down with it (that's the whole point of
    # posting them from one run but tracking them separately), so each is caught
    # and recorded; the failures come back as the manifest's retry list.
    if args.dry_run:
        for org in orgs:
            result = sp.post_all(captures, pages_mod.PAGES, today, dry_run=True,
                                 replace=args.replace, org=org)
            print(f"\n  [{org}] would post to {', '.join(result['channels'])} as "
                  f"{sp.header_title(today)}", flush=True)
        print(f"\n✓ DRY-RUN: captured {len(captures)} PNG(s) to {out_dir}; "
              f"posted NOTHING.", flush=True)
        run_manifest.write_manifest(
            report_id, ok=bool(not failed), failed=failed, kind="tracker",
            note="dry run")
        return 1 if failed else 0

    posted_ok, posted_bad, status_rows = [], [], []
    for org in orgs:
        label = sp.ORG_LABEL[org]
        try:
            result = sp.post_all(captures, pages_mod.PAGES, today,
                                 replace=args.replace, org=org)
        except Exception as e:                        # noqa: BLE001
            result = {"ok": False, "channels": [],
                      "error": f"{type(e).__name__}: {str(e)[:120]}"}
        for c in result.get("channels", []):
            if c.get("ok"):
                rm = c.get("removed") or 0
                print(f"✓ [{org}] posted {len(c.get('posted', []))} image(s) to "
                      f"{c['channel']} thread {c.get('thread_ts')}"
                      + (f", replaced {rm} old" if rm else ""), flush=True)
            else:
                print(f"⚠ [{org}] {c['channel']} post FAILED: "
                      f"{c.get('error', 'see above')}", flush=True)
        (posted_ok if result.get("ok") else posted_bad).append(org)
        status_rows.append({
            "org": org, "label": label, "ok": bool(result.get("ok")),
            "channels": [{"channel": c.get("channel"), "ok": bool(c.get("ok")),
                          "thread_ts": c.get("thread_ts"),
                          "error": c.get("error")}
                         for c in result.get("channels", [])],
            "error": result.get("error"),
        })
    _write_status(out_dir, status_rows, today)

    print(f"\n=== POSTED: {len(posted_ok)}/{len(orgs)} org(s)", flush=True)
    for org in orgs:
        print(f"  {'✅' if org in posted_ok else '❌'} {sp.ORG_LABEL[org]}", flush=True)

    # Manifest drives BOTH the Hub's "Retry failed only" button and its pill
    # colour. The failed PARTS are the channels that missed (not the trackers),
    # and retry_args re-posts exactly those. `succeeded` is what lets the Hub tell
    # a PARTIAL run (orange — most channels landed) from a total failure (red);
    # without it every miss would look equally fatal. A capture failure is
    # surfaced too, since a short thread is a real failure even when every channel
    # accepted it.
    ok = (not failed) and not posted_bad
    parts = [sp.ORG_LABEL[o] for o in posted_bad] + [f"tracker:{f}" for f in failed]
    run_manifest.write_manifest(
        report_id, ok=bool(ok), failed=parts, kind="channel",
        succeeded=[sp.ORG_LABEL[o] for o in posted_ok],
        retry_args=(["--orgs", ",".join(posted_bad), "--replace"]
                    if posted_bad else []),
        note=("" if ok else
              "; ".join(filter(None, [
                  f"{len(posted_bad)} channel(s) missed: "
                  f"{', '.join(sp.ORG_LABEL[o] for o in posted_bad)}" if posted_bad else "",
                  f"{len(failed)} tracker(s) failed to capture: "
                  f"{', '.join(failed)}" if failed else "",
              ]))))

    # Non-zero on any miss, so the orchestrator RETRIES — which is safe and
    # useful now that posting is idempotent: the retry skips the channels that
    # already have today's images and re-posts only the ones that missed.
    if posted_bad or failed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
