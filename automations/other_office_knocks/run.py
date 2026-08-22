"""Knocks for other offices — the SAME knocks image Raf's office posts every
morning, but for the offices that don't have a metrics thread of their own,
in a SEPARATE #alphalete-sales thread that runs ALONGSIDE the Metrics one.

Thread (posted by this module, once a day):
    *Knocks for other offices — <Month> <ordinal> <year>*
      :door: Sahil Multani
      :door: Chan Park

Replies — ONE combined image per office (Raf's Loom 2026-08-22: Total
Knocks carries Gaps + Total Gaps + a TOTAL row, Time Gaps retired):
    🚪 Total Knocks — Sahil Multani — Aug 17
    🚪 Total Knocks — Chan Park — Aug 17

Nothing here is new machinery — every piece is the one Raf's / Rashad's knocks
already use:
  * pull   = rashad_metrics.knocks_pull.pull_offices_knocks — ONE ownerville
             session for BOTH offices (impersonate, scrape Disposition by Rep +
             Time Tracker gaps, exit impersonation, next office). A session per
             office lost the Chrome-profile race: the second launch got adopted
             by the first Chrome before it exited and the office dropped.
  * render = total_knocks.render.render_time_gaps / render_total_knocks
             (rows=…) — straight from the in-memory rows, so NO Sheet is read
             or written for these offices. Every title carries the office name,
             because all four images land in the SAME thread.
  * post   = shared.slack_metrics_post.ensure_named_thread +
             post_reply_with_image(thread_ts=…).

Offices are config — override without a code change:
    OTHER_OFFICE_KNOCKS="Sahil Multani,Chan Park"

CLI:
  --dry-run    pull + render the PNGs to output/, NO Slack post (default)
  --live       pull + render + post into today's 'Knocks for other offices'
               thread in #alphalete-sales
  --office X   run ONE office (repeatable) instead of the configured list
  date         optional YYYY-MM-DD positional (default: yesterday, Central)

Its OWN scheduler entry + Hub card ('other_office_knocks', order 6.1) — it goes
out with the morning metrics (immediately after daily_metrics) but is a report
in its own right: every LIVE run writes output/manifests/other_office_knocks.json,
so a dropped office turns the Hub card red and fires the failure alert instead of
disappearing inside the Daily Metrics summary.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

# Keep emoji / checkmarks safe on the Windows console (cp1252 default).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from automations.rashad_metrics.knocks_pull import pull_offices_knocks
from automations.total_knocks import render as _render
from automations.total_knocks.pull import COL_TOTAL_KNOCKS, central_today

# The thread's name — also the string find_named_thread_ts matches on, so
# changing it starts a NEW thread instead of finding today's.
THREAD_TITLE = "Knocks for other offices"

# Offices whose knocks land in that thread, in post order. Comma-separated env
# override so a new office is config, not a code change.
DEFAULT_OFFICES = ["Sahil Multani", "Chan Park"]
OFFICES = [o.strip() for o in os.environ.get("OTHER_OFFICE_KNOCKS", "").split(",")
           if o.strip()] or DEFAULT_OFFICES

# The same two emoji + Title Case labels Raf's total_knocks.run posts, with the
# office name appended (every office shares ONE thread, so the label has to say
# whose). ORDER MATTERS: Time Gaps first, then Total Knocks, and both of an
# office's images before the next office's (Eve 2026-08-18).
POST_TIME_GAPS = "🕐 Time Gaps"
POST_TOTAL_KNOCKS = "🚪 Total Knocks"

OUT_DIR = Path("output") / "other_office_knocks"

# OUR OWN Chrome profile. The shared one (automations/uploaded/.browser_profile)
# is first-come, first-served: whoever launches while another run holds it gets
# "Opening in existing browser session" and loses the office. This report runs
# inside the morning batch alongside other browser reports, so it gets its own
# — the same escape hatch the Owner Showdown preview uses. The ownerville login
# comes from the shared storage_state, not the profile, so a separate profile
# authenticates identically.
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_other_knocks")


REPORT_ID = "other_office_knocks"      # manifest / Hub-card / orchestrator id


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def _retry_args(offices: list[str]) -> list[str]:
    """The exact CLI that re-runs ONLY the offices that dropped — what the Hub's
    'Retry failed only' button and the orchestrator's auto-retry run. A blind
    full re-run would RE-POST the offices that already landed (there's no
    already-posted guard), so scoping matters."""
    out = ["--live"]
    for o in offices:
        out += ["--office", o]
    return out


def _write_manifest(offices: list[str], failed: list[str]) -> None:
    """Record the run for the Hub + the failure alert. Best-effort: a manifest
    problem must never fail a run whose images already posted.

    A SCOPED re-run (`--office X`, what the retry button fires) speaks only for
    the offices it ran: its result is MERGED into today's manifest so fixing one
    office clears just that office, and doesn't declare the whole report clean
    while the other one is still missing from the thread.
    """
    try:
        from automations.shared import run_manifest as _rm
        ok_offices = [o for o in offices if o not in failed]
        if set(offices) != set(OFFICES):        # scoped re-run → merge
            prior = _rm.read_manifest(REPORT_ID) or {}
            # Only TODAY's manifest may carry over; yesterday's misses are not
            # this run's business.
            if str(prior.get("run_ts") or "").startswith(
                    dt.date.today().isoformat()):
                failed = [o for o in prior.get("failed", [])
                          if o not in offices] + failed
                ok_offices = [o for o in prior.get("succeeded", [])
                              if o not in offices] + ok_offices
            offices = [o for o in OFFICES if o in set(failed) | set(ok_offices)]
        rem = None
        if failed:
            rem = _rm.make_remediation(
                reason=f"{len(failed)} office(s) missing from today's "
                       f"'{THREAD_TITLE}' thread in #alphalete-sales: "
                       f"{', '.join(failed)}.",
                fix="Re-run ONLY the missing office(s) — the others already "
                    "posted, so don't re-run the whole report: "
                    f"lucy rerun {REPORT_ID} "
                    + " ".join(_retry_args(failed)),
                message=f"The '{THREAD_TITLE}' thread is missing "
                        f"{', '.join(failed)}. Usual cause: the ownerville "
                        "impersonation couldn't reach that office (session "
                        "expired, or the office was renamed — then add the new "
                        "spelling to the ICD Aliases tab).")
        _rm.write_manifest(
            REPORT_ID, kind="office", failed=failed, succeeded=ok_offices,
            retry_args=(_retry_args(failed) if failed else []),
            note=(f"{len(ok_offices)}/{len(offices)} office(s) posted to the "
                  f"'{THREAD_TITLE}' thread"
                  + (f"; ⚠ MISSING: {', '.join(failed)}" if failed else "")),
            remediation=rem)
    except Exception:  # noqa: BLE001 — manifest write must never fail the run
        pass


def run(target: dt.date | None = None, *, offices: list[str] | None = None,
        dry_run: bool = True) -> int:
    offices = offices or OFFICES
    slack_today = central_today()      # the thread lives on TODAY (Central)
    print(f"[other_knocks] {len(offices)} office(s): {', '.join(offices)} "
          f"— {'DRY-RUN' if dry_run else 'LIVE'}", flush=True)

    # 1. Pull every office in ONE ownerville session, then render. `rendered`
    #    is ALREADY in post order: office by office, Time Gaps before Total
    #    Knocks. A per-office error rides in the tuple — it never aborts the
    #    others.
    rendered: list[tuple[str, str, Path | None, dt.date]] = []
    failed: list[str] = []
    try:
        day, pulled = pull_offices_knocks(offices, target,
                                          profile_dir=PROFILE_DIR)
    except Exception as e:  # noqa: BLE001 — the session itself never opened
        print(f"[other_knocks] ❌ ownerville session failed: "
              f"{type(e).__name__}: {e}", flush=True)
        # Every office is missing, and the manifest has to say so — otherwise a
        # dead session reads as 'nothing to report' and the card stays green.
        if not dry_run:
            _write_manifest(offices, list(offices))
        return 1
    for office, rows, err in pulled:
        try:
            if err is not None:
                raise err
            print(f"[other_knocks] {office} — data date {day.isoformat()} — "
                  f"{len(rows)} rep(s).", flush=True)
            if not rows:
                # Visible absence, not a silent gap — same rule as Raf's run.
                rendered.append((office, POST_TOTAL_KNOCKS, None, day))
                continue
            # Per-office out dir: the renderers name their files by DATE only,
            # so two offices in one run would overwrite each other.
            out_dir = OUT_DIR / _slug(office)
            out_dir.mkdir(parents=True, exist_ok=True)
            if COL_TOTAL_KNOCKS in rows[0]:
                # Raf's Loom 2026-08-22: ONE combined board — Total Knocks now
                # carries Gaps + Total Gaps, so no separate Time Gaps post.
                img_tk = _render.render_total_knocks(day, out_dir=out_dir,
                                                     rows=rows,
                                                     title_suffix=office)
                rendered.append((office, POST_TOTAL_KNOCKS, img_tk, day))
                print(f"[other_knocks] Rendered {office} -> {img_tk}",
                      flush=True)
            else:
                # Gaps-only (wireless/NDS) office: no Disposition rows — Time
                # Gaps still draws on its own (it comes from the Time Tracker).
                img_tg = _render.render_time_gaps(day, out_dir=out_dir,
                                                  rows=rows,
                                                  title_suffix=office)
                rendered.append((office, POST_TIME_GAPS, img_tg, day))
                print(f"[other_knocks] ⚠ {office} has no Disposition data "
                      f"(gaps-only office) — Time Gaps only.", flush=True)
                rendered.append((office, POST_TOTAL_KNOCKS, None, day))
        except Exception as e:   # noqa: BLE001 — one office must not kill the rest
            print(f"[other_knocks] ❌ {office} failed: "
                  f"{type(e).__name__}: {e}", flush=True)
            failed.append(office)

    if dry_run:
        print("[other_knocks] --dry-run — rendered only, NO Slack post.",
              flush=True)
        for office, label, img, day in rendered:
            what = str(img) if img else "'No data available' line"
            print(f"[other_knocks]   would post {label} — {office}: {what}",
                  flush=True)
        print(f"[other_knocks] {'⚠' if failed else '✅'} Finished (dry-run)"
              + (f" — failed: {', '.join(failed)}" if failed else ""),
              flush=True)
        return 1 if failed else 0

    if not rendered:
        print("[other_knocks] ❌ Nothing to post — every office failed.",
              flush=True)
        _write_manifest(offices, failed)
        return 1

    # 2. The day's own thread (posted only if it isn't there yet).
    from automations.shared import slack_metrics_post as smp
    head = smp.ensure_named_thread(
        THREAD_TITLE, slack_today,
        lines=[f":door: Total Knocks — {o}"
               for o in offices])
    thread_ts = head.get("thread_ts")
    if not thread_ts:
        print(f"[other_knocks] ❌ Couldn't open the '{THREAD_TITLE}' thread: "
              f"{head}", flush=True)
        # Nothing posted at all — every office counts as missing, so the Hub
        # card goes red instead of reading green off an empty thread.
        _write_manifest(offices, [o for o in offices if o not in failed] + failed)
        return 1
    print(f"[other_knocks] Thread {'found' if head.get('existed') else 'posted'}"
          f" ({thread_ts}).", flush=True)

    # 3. Replies in `rendered` order: per office, Time Gaps then Total Knocks.
    # wait_visible: files_upload_v2 returns when the UPLOAD is done, but Slack
    # posts the share message when it has finished PROCESSING the file — so four
    # uploads fired back to back land in SIZE order, not call order. On
    # 2026-08-19 (the first day both offices ran in one pass — before that they
    # ran half an hour apart, which hid it) the thread came out as both Time Gaps
    # then both Total Knocks, instead of the per-office grouping Eve asked for on
    # 8/18. Waiting for each image to be visible before sending the next is what
    # makes the posted order OUR order. Costs a couple of seconds per image and
    # gives up after 20s rather than holding the report.
    for office, label, img, day in rendered:
        comment = f"{label} — {office} — {day.strftime('%b')} {day.day}"
        if img is None:
            resp = smp.post_reply_text_only(f"{comment} — No data available",
                                            today=slack_today,
                                            thread_ts=thread_ts)
        else:
            resp = smp.post_reply_with_image(
                Path(img), comment=comment, today=slack_today,
                thread_ts=thread_ts, wait_visible=True,
                file_name=f"{Path(img).stem}_{_slug(office)}.png")
        if resp.get("ok"):
            print(f"[other_knocks] ✅ Posted {label} — {office}.", flush=True)
        else:
            print(f"[other_knocks] ⚠ Slack response for {label} — {office}: "
                  f"{resp}", flush=True)
            # An office is only 'posted' when BOTH its images land — a half-
            # posted office is a miss, and its retry re-runs that office.
            if office not in failed:
                failed.append(office)

    _write_manifest(offices, failed)
    print(f"[other_knocks] {'⚠' if failed else '✅'} Finished"
          + (f" — failed: {', '.join(failed)}" if failed else ""), flush=True)
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="other_office_knocks",
        description="Post other offices' Total Knocks images into their own "
                    "#alphalete-sales thread.")
    ap.add_argument("date", nargs="?", default=None,
                    help="YYYY-MM-DD (default: yesterday, Central)")
    ap.add_argument("--office", action="append", default=None,
                    help="run ONE office (repeatable) instead of the "
                         f"configured list ({', '.join(OFFICES)})")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + render the PNGs to output/, NO Slack post")
    ap.add_argument("--live", action="store_true",
                    help="pull + render + POST into today's thread")
    args = ap.parse_args(argv)

    if args.live and args.dry_run:
        print("✗ --live and --dry-run are mutually exclusive.")
        return 2
    # Default to dry-run if neither given, so nothing posts unintentionally.
    dry_run = not args.live
    target = (dt.datetime.strptime(args.date, "%Y-%m-%d").date()
              if args.date else None)
    return run(target, offices=args.office, dry_run=dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
