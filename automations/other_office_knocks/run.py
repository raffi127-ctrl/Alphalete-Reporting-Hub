"""Knocks for other offices — the SAME knocks image Raf's office posts every
morning, but for the offices that don't have a metrics thread of their own,
in a SEPARATE #alphalete-sales thread that runs ALONGSIDE the Metrics one.

Thread (posted by this module, once a day):
    *Knocks for other offices — <Month> <ordinal> <year>*
      :door: Sahil Multani
      :door: Chan Park

Replies — ONE image per office, in list order:
    🚪 Total Knocks — Sahil Multani — Aug 17
    🚪 Total Knocks — Chan Park — Aug 17

Nothing here is new machinery — every piece is the one Raf's / Rashad's knocks
already use:
  * pull   = rashad_metrics.knocks_pull.pull_office_knocks (impersonates the
             office inside ONE ownerville session, scrapes Disposition by Rep +
             Time Tracker gaps, exits impersonation).
  * render = total_knocks.render.render_total_knocks(rows=…) — straight from
             the in-memory rows, so NO Sheet is read or written for these
             offices. Only the title carries the office name, because both
             images land in the SAME thread.
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

from automations.rashad_metrics.knocks_pull import pull_office_knocks
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

# Same emoji + Title Case label Raf's total_knocks.run uses, with the office
# name appended (both offices share one thread, so the label has to say whose).
POST_LABEL = "🚪 Total Knocks"

OUT_DIR = Path("output") / "other_office_knocks"


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

    # 1. Pull + render each office first, so the thread is only created once
    #    there is something to hang in it.
    rendered: list[tuple[str, Path | None, dt.date]] = []
    failed: list[str] = []
    for office in offices:
        try:
            day, rows = pull_office_knocks(office, target)
            print(f"[other_knocks] {office} — data date {day.isoformat()} — "
                  f"{len(rows)} rep(s).", flush=True)
            if not rows:
                # Visible absence, not a silent gap — same rule as Raf's run.
                rendered.append((office, None, day))
                continue
            if COL_TOTAL_KNOCKS not in rows[0]:
                # Gaps-only (wireless/NDS) office: no Disposition rows to draw,
                # so a Total Knocks image would be all blanks. Say so instead.
                print(f"[other_knocks] ⚠ {office} has no Disposition data "
                      f"(gaps-only office) — posting the no-data line.",
                      flush=True)
                rendered.append((office, None, day))
                continue
            # Per-office out dir: render_total_knocks names the file by DATE
            # only, so two offices in one run would overwrite each other.
            out_dir = OUT_DIR / _slug(office)
            out_dir.mkdir(parents=True, exist_ok=True)
            img = _render.render_total_knocks(day, out_dir=out_dir, rows=rows,
                                              title_suffix=office)
            print(f"[other_knocks] Rendered {office} -> {img}", flush=True)
            rendered.append((office, img, day))
        except Exception as e:   # noqa: BLE001 — one office must not kill the rest
            print(f"[other_knocks] ❌ {office} failed: "
                  f"{type(e).__name__}: {e}", flush=True)
            failed.append(office)

    if dry_run:
        print("[other_knocks] --dry-run — rendered only, NO Slack post.",
              flush=True)
        for office, img, day in rendered:
            what = str(img) if img else "'No data available' line"
            print(f"[other_knocks]   would post {office}: {what}", flush=True)
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
        lines=[f":door: {o}" for o in offices])
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

    # 3. One reply per office, in list order.
    for office, img, day in rendered:
        comment = f"{POST_LABEL} — {office} — {day.strftime('%b')} {day.day}"
        if img is None:
            resp = smp.post_reply_text_only(f"{comment} — No data available",
                                            today=slack_today,
                                            thread_ts=thread_ts)
        else:
            resp = smp.post_reply_with_image(
                Path(img), comment=comment, today=slack_today,
                thread_ts=thread_ts,
                file_name=f"total_knocks_{_slug(office)}_{day.isoformat()}.png")
        if resp.get("ok"):
            print(f"[other_knocks] ✅ Posted {office}.", flush=True)
        else:
            print(f"[other_knocks] ⚠ Slack response for {office}: {resp}",
                  flush=True)
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
