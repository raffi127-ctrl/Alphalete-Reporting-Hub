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

TWO RUNS A DAY (Carlos via Megan, 2026-07-16). The morning batch posts every
board EXCEPT the late ones; a second run posts the late ones once their data is
actually in:
  4:31am  (no flag)     the 7 boards whose data is current -> full thread, with
                        Box listed in the header as still coming
  ~7am    --late-only   B2B Box only, once day_orchestrator's `box_daily`
                        readiness probe says its extract has landed -> appended
                        into each channel's SAME thread, header note cleared
Box's numbers don't settle until its extract refreshes ~7-8am, so at 4:31 it was
posting yesterday's figures into every channel, every morning. The gate is data
readiness, not a clock: the probe is shared (and cached) with org_sales_board,
which already waits on the same extract, so Box posts the moment it's real —
typically well before 7 — and never later than the probe's 08:00 fail-open floor.
Box's image lands LAST in the thread (Slack only appends replies) while keeping
its normal slot in the header list.

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

# The ~7am late catch-up (--late-only) reports SEPARATELY: Box lands hours after
# the morning batch, so folding it into the morning manifest would either re-open
# a finished run or overwrite its verify record. Its own id = its own Hub card,
# its own pill, its own retry button.
LATE_REPORT_ID = "tableau-screenshots-box"

# Per-channel outcome of today's run, read by the Hub card to show its ✅/❌
# checklist. One card posts to EVERY channel, so the card needs to say which
# channels actually landed -- a single red/green light would hide a lone failure.
STATUS_FILE = OUT_DIR / "_posted_today.json"
LATE_STATUS_FILE = OUT_DIR / "_posted_today_box.json"

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
    whether today's PNGs are complete enough to reuse.

    MERGES into today's stamp rather than replacing it: the late catch-up captures
    only Box, and a blind overwrite would drop the morning's 7 ids, so a later
    re-post would re-drive Tableau for boards already sitting on disk. Yesterday's
    stamp is discarded, not merged — stale images must never be reusable."""
    import json
    stamp = out_dir / STAMP.name
    have: list = []
    try:
        prev = json.loads(stamp.read_text())
        if prev.get("date") == today.isoformat():
            have = list(prev.get("ids") or [])
    except Exception:            # no stamp yet, or unreadable — start clean
        have = []
    for spec, _ in captured:
        if spec["id"] not in have:
            have.append(spec["id"])
    try:
        stamp.write_text(json.dumps({"date": today.isoformat(), "ids": have}))
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


def _write_status(out_dir: Path, results: list, today: dt.date,
                  status_file: Path = STATUS_FILE) -> None:
    """Today's per-channel outcome, for the Hub card's checklist."""
    import json
    try:
        (out_dir / status_file.name).write_text(json.dumps({
            "date": today.isoformat(),
            "channels": results,
        }, indent=2))
    except Exception:            # best-effort — the post already happened
        pass


def _select(only: str | None, *, late_only: bool = False,
            include_late: bool = False) -> list:
    """The trackers this run posts.

    Default = every board EXCEPT the late ones (pages.py `late`): at 4:31am their
    data isn't in yet, so posting them means posting yesterday's numbers. The late
    catch-up run picks them up with --late-only once the readiness probe clears.
    An explicit --only always wins — naming a tracker means you want that tracker.
    """
    if not only:
        if late_only:
            late = [p for p in pages_mod.PAGES if pages_mod.is_late(p)]
            if not late:
                raise SystemExit("--late-only: no tracker is marked late in pages.py")
            return late
        if include_late:
            return list(pages_mod.PAGES)
        return [p for p in pages_mod.PAGES if not pages_mod.is_late(p)]
    if late_only:
        raise SystemExit("--late-only and --only are mutually exclusive — "
                         "--only already names exactly what to post.")
    wanted = [s.strip() for s in only.split(",") if s.strip()]
    out = []
    for w in wanted:
        p = pages_mod.by_id(w)
        if p is None:
            raise SystemExit(f"--only: no tracker with id {w!r}. "
                             f"Known: {[p['id'] for p in pages_mod.PAGES]}")
        out.append(p)
    return out


def _gate_email_sources(selected: list) -> tuple:
    """Drop an email-sourced board (pages.py `source: "email"`) whose source .xlsx
    isn't in the inbox yet, so the morning run only ATTEMPTS a board it can render
    — a genuine source gap becomes a clean omit (board simply not in today's
    thread), not a fetch that raises into a false failure.

    Returns (kept_specs, dropped_ids). Probes are cheap (headers only) and FAIL
    OPEN: a probe that errors keeps the board (capture() still self-guards). An
    explicit --only bypasses this entirely (the caller only gates the default
    selection) — naming a board means you want it regardless."""
    kept, dropped = [], []
    for spec in selected:
        if spec.get("source") != "email":
            kept.append(spec)
            continue
        from automations.tableau_screenshots import email_tracker as et
        try:
            ready, detail = et.source_ready()
        except Exception as e:                        # noqa: BLE001 — fail open
            ready, detail = True, f"probe error ({type(e).__name__})"
        if ready:
            print(f"   ✓ {spec['id']}: source ready — {detail}", flush=True)
            kept.append(spec)
        else:
            print(f"   ⏭ {spec['id']}: source not in yet — {detail}; omitting from "
                  f"this run (no false failure; it returns once the .xlsx lands)",
                  flush=True)
            dropped.append(spec["id"])
    return kept, dropped


def _capture_one(spec: dict, page, out_dir: Path, force_crop):
    """Capture ONE tracker to a PNG. Dispatches on the spec's source: an
    email-sourced tracker (pages.py `source: "email"`) renders from its daily
    .xlsx via email_tracker; everything else is a live Tableau Download→Image.
    Same return (a PNG path) either way, so the post pipeline is source-agnostic."""
    if spec.get("source") == "email":
        from automations.tableau_screenshots import email_tracker as et
        return et.capture(page, spec, out_dir, force_crop=force_crop, verbose=True)
    return cap.capture_page(page, spec, out_dir, force_crop=force_crop, verbose=True)


def _capture_all(selected: list, page, out_dir: Path, force_crop):
    """Capture every selected tracker; a per-tracker failure is flagged (its id in
    `failed`) but never stops the others — a short thread is better than none, and
    the failed ids drive the manifest's retry list. `page` may be None when the
    selection is email-only (no Tableau session opened)."""
    captures, failed = [], []
    for spec in selected:
        try:
            captures.append((spec, _capture_one(spec, page, out_dir, force_crop)))
        except Exception as e:                        # noqa: BLE001
            failed.append(spec["id"])
            print(f"   ⚠ {spec['id']} FAILED: "
                  f"{type(e).__name__}: {str(e).splitlines()[0][:120]}", flush=True)
    return captures, failed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Capture PNGs to output/ but post NOTHING to Slack.")
    ap.add_argument("--only", default=None,
                    help="Comma-separated tracker id(s) to run (default: every "
                         "tracker except the late ones — see --late-only).")
    ap.add_argument("--late-only", action="store_true",
                    help="Post ONLY the late tracker(s) — the boards whose data "
                         "isn't current at 4:31am (B2B Box). This is the ~7am "
                         "catch-up: it captures Box once its extract has landed "
                         "and posts it into today's existing thread in every "
                         "channel. Safe to re-run — a channel that already has "
                         "today's Box image is left alone.")
    ap.add_argument("--include-late", action="store_true",
                    help="Post every tracker INCLUDING the late ones, in one go. "
                         "For a manual same-day re-post after Box has landed "
                         "(pair with --replace to fix the whole thread's order).")
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
    selected = _select(args.only, late_only=args.late_only,
                       include_late=args.include_late)
    out_dir = Path(args.out_dir)
    force_crop = "full" if args.full else None

    orgs = _select_orgs(args.orgs)
    # The late catch-up is its OWN report to the Hub + orchestrator: its own
    # manifest (else it overwrites the morning run's verify record) and its own
    # per-channel status file (else the morning card's checklist gets rewritten
    # to show one tracker). Same code, same channels, separate accounting.
    report_id = LATE_REPORT_ID if args.late_only else REPORT_ID
    status_file = LATE_STATUS_FILE if args.late_only else STATUS_FILE
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

    # Gate email-sourced boards on their source .xlsx actually being in the inbox,
    # so the run only attempts a board it can render. A genuine source gap → the
    # board is omitted from BOTH the capture set AND today's header (post_pages),
    # so the thread never shows a board with no image. An explicit --only bypasses
    # the gate (naming a board means you want it regardless).
    gated_out: list = []
    if not args.only:
        selected, gated_out = _gate_email_sources(selected)
    # Header/thread pages for the poster: the full list minus anything gated out
    # this run, so the omitted board isn't listed with a missing image.
    post_pages = [p for p in pages_mod.PAGES if p["id"] not in set(gated_out)]

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
        #
        # Email-sourced trackers (pages.py `source: "email"`) render from an .xlsx,
        # not Tableau — so they capture OUTSIDE the Tableau session, BEFORE it
        # opens. Not a preference: they render in their own short-lived chromium,
        # and Playwright's sync API refuses to start while another sync session is
        # already live ("Playwright Sync API inside the asyncio loop"). Rendering
        # them inside the `with tableau_session(...)` block failed vzftr on every
        # batch run — invisibly, because the standalone `--only vzftr` test opens
        # no Tableau session and passes (2026-07-21).
        email_specs = [s for s in selected if s.get("source") == "email"]
        tableau_specs = [s for s in selected if s.get("source") != "email"]
        captures, failed = _capture_all(email_specs, None, out_dir, force_crop)
        # Open a Tableau session ONLY if a selected tracker actually needs one, so
        # an email-only selection can't be blocked by a cold Tableau login.
        if tableau_specs:
            with tableau_session(headless=args.headless, allow_form_login=False,
                                 verbose=True) as page:
                tab_caps, tab_failed = _capture_all(tableau_specs, page, out_dir,
                                                    force_crop)
            captures += tab_caps
            failed += tab_failed
        # Capture order drives the Slack reply order, so put both groups back into
        # pages.py order (the email ones were captured first, not posted first).
        rank = {s["id"]: i for i, s in enumerate(selected)}
        captures.sort(key=lambda c: rank[c[0]["id"]])
        failed.sort(key=lambda fid: rank.get(fid, len(rank)))
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
        pv = sp.preview_dm(captures, post_pages, users, today,
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
            result = sp.post_all(captures, post_pages, today, dry_run=True,
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
    # Which selected boards are actually PRESENT in the channels after this run —
    # unioned across every channel we didn't outright fail on. A tracker that
    # failed to CAPTURE this run isn't a real gap if a prior run already delivered
    # it (all channels then skip and report it in `present_ids`); it's only a gap
    # if it's genuinely absent from a channel.
    present_everywhere: set = set()
    present_seen = False
    for org in orgs:
        label = sp.ORG_LABEL[org]
        try:
            result = sp.post_all(captures, post_pages, today,
                                 replace=args.replace, org=org)
        except Exception as e:                        # noqa: BLE001
            result = {"ok": False, "channels": [],
                      "error": f"{type(e).__name__}: {str(e)[:120]}"}
        for c in result.get("channels", []):
            if c.get("skipped"):
                print(f"↷ [{org}] {c['channel']} already had today's images — "
                      f"left alone", flush=True)
            elif c.get("ok"):
                rm = c.get("removed") or 0
                print(f"✓ [{org}] posted {len(c.get('posted', []))} image(s) to "
                      f"{c['channel']} thread {c.get('thread_ts')}"
                      + (f", replaced {rm} old" if rm else ""), flush=True)
            else:
                print(f"⚠ [{org}] {c['channel']} post FAILED: "
                      f"{c.get('error', 'see above')}", flush=True)
            # Only channels that DIDN'T error carry a trustworthy present set. A
            # board must be present in EVERY such channel to count as delivered,
            # so intersect (seed on the first one seen).
            if c.get("ok") and c.get("present_ids") is not None:
                p = set(c.get("present_ids") or [])
                present_everywhere = p if not present_seen else (present_everywhere & p)
                present_seen = True
        (posted_ok if result.get("ok") else posted_bad).append(org)
        status_rows.append({
            "org": org, "label": label, "ok": bool(result.get("ok")),
            "channels": [{"channel": c.get("channel"), "ok": bool(c.get("ok")),
                          "thread_ts": c.get("thread_ts"),
                          "error": c.get("error")}
                         for c in result.get("channels", [])],
            "error": result.get("error"),
        })
    _write_status(out_dir, status_rows, today, status_file)

    print(f"\n=== POSTED: {len(posted_ok)}/{len(orgs)} org(s)", flush=True)
    for org in orgs:
        print(f"  {'✅' if org in posted_ok else '❌'} {sp.ORG_LABEL[org]}", flush=True)

    # A capture failure is only a REAL gap when the board is genuinely absent from
    # the channels. A board that failed to capture NOW but is already sitting in
    # every channel (an earlier run posted it; this run's channels all skipped) is
    # NOT missing — re-flagging it would cry wolf on every idempotent re-run. When
    # we couldn't read any channel's present set (e.g. every org errored), fall
    # back to treating all capture failures as gaps (can't prove they landed).
    missing_trackers = ([f for f in failed if f not in present_everywhere]
                        if present_seen else list(failed))
    if failed:
        covered = [f for f in failed if f not in missing_trackers]
        if covered:
            print(f"  ℹ {len(covered)} tracker(s) failed to capture but are already "
                  f"in every channel from an earlier run: {', '.join(covered)}", flush=True)

    # Manifest drives BOTH the Hub's "Retry failed only" button and its pill
    # colour. `succeeded` lets the Hub tell a PARTIAL run (orange — most channels
    # landed) from a total failure (red). A GENUINELY-absent board is surfaced as
    # a failed part too, since a short thread is a real gap — but one already
    # delivered by an earlier run is not, so it's excluded.
    ok = (not missing_trackers) and not posted_bad
    parts = [sp.ORG_LABEL[o] for o in posted_bad] + [f"tracker:{f}" for f in missing_trackers]
    # A channel miss re-posts exactly the missed channels; a lone capture gap
    # re-captures just that tracker (self-heals a transient Tableau flake; a board
    # whose SOURCE isn't in yet — e.g. an email tracker — stays flagged, softly).
    if posted_bad:
        retry_args = (["--late-only"] if args.late_only else []) + \
                     ["--orgs", ",".join(posted_bad), "--replace"]
    elif missing_trackers:
        # --late-only and --only are mutually exclusive (a late run already selects
        # exactly the late trackers), so re-run the late catch-up as-is; a normal
        # run re-captures just the missing tracker(s).
        retry_args = (["--late-only"] if args.late_only
                      else ["--only", ",".join(missing_trackers)])
    else:
        retry_args = []
    run_manifest.write_manifest(
        report_id, ok=bool(ok), failed=parts, kind="channel",
        succeeded=[sp.ORG_LABEL[o] for o in posted_ok],
        retry_args=retry_args,
        note=("" if ok else
              "; ".join(filter(None, [
                  f"{len(posted_bad)} channel(s) missed: "
                  f"{', '.join(sp.ORG_LABEL[o] for o in posted_bad)}" if posted_bad else "",
                  f"{len(missing_trackers)} tracker(s) missing from the thread: "
                  f"{', '.join(missing_trackers)}" if missing_trackers else "",
              ]))))

    # EXIT CODE — hard failure ONLY when a channel genuinely failed to post (a
    # real "some org didn't get images" error): the orchestrator treats non-zero
    # as FAILED and fires the immediate failure email, so that path must mean a
    # human is actually needed. A capture GAP is NOT hard-failed here: exit 0 lets
    # the manifest flow through reconcile, which marks it soft INCOMPLETE (Hub
    # checklist + a bounded self-heal retry), instead of a hard 4:31am page for a
    # single board — while "everything already posted, nothing to re-post" stays a
    # clean exit 0. (A total capture failure still returns 1 above.)
    if posted_bad:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
