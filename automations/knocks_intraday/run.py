"""The 9 PM Central knock board — every enrolled office, the CURRENT day.

Raf, Slack 2026-08-25 8:31 AM: "Can we have this Daily knocks Post for every
office at 9:00PM CEN please? I want people to look at it at night for break
downs, a full view. / the next morning it'll have to recollect the data because
extra knocks could come in after 9:00 CEN"

TWO THINGS THAT ASK IS REALLY SAYING, and both are load-bearing:

1. ONE CLOCK, NOT ELEVEN. 9:00 PM **Central** for everybody — not each office's
   own 9 PM. That matters because it is the whole reason this module could be
   built today: an office-local schedule needs a timezone per office, and
   nothing in this repo stores where an office IS (no field on `Office`, none in
   the onboarding schema or `onboarded_offices.json`). A single Central fire
   needs none of that. If office-local times are ever wanted, THAT is the work
   to do first — see `output/cody-knocks-intraday-plan.md`.

2. TONIGHT'S PULL MUST NOT BECOME TOMORROW'S ANSWER. A 9 PM board is a partial
   day: reps keep knocking after it. Tomorrow morning the same calendar date is
   "yesterday", and the morning board has to re-collect it from ownerville. So
   this module writes NOTHING either of the morning readers looks at:

     · the `/knocks` cache — never touched. We call `pull_offices_knocks`
       directly, so `knocks_request.service.save_rows` is never reached. (It
       would refuse today anyway: it stores only finished days.)
     · the captainship build's sidecar — our PNGs and rows go under
       `output/knocks_intraday/`, never under `captainship_drafts` RENDER_DIR,
       which is the tree `service.cached_rows` globs for `daily_knocks_*`.

   `test_no_morning_reuse` pins both. It is the test to run before changing
   where this module writes anything.

Nothing here scrapes or draws anything new: the pull is the same
`pull_offices_knocks` the morning boards use and the image is the same
`render_knocks_boards`. What is new is the trigger and the post.

    python -m automations.knocks_intraday.run                 # dry-run, all
    python -m automations.knocks_intraday.run --office cody    # dry-run, one
    python -m automations.knocks_intraday.run --send           # posts
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, best effort
    pass

from automations.knocks_intraday.roster import enrolled, excluded_lines

OUT_DIR = Path("output") / "knocks_intraday"
# Our OWN Chrome profile: the shared one is first-come-first-served and this
# job runs alongside whatever else the evening has going. Ownerville itself
# parallelises fine — the limit is one browser per profile dir.
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / "_shared" / ".browser_profile_knocks_intraday")

SLOT_LABEL = "End of Day"
POST_EMOJI = ":door:"
# Abbreviation, not the word (Megan 2026-08-25: "CST instead of central").
# NOTE it is the literal string, not the live zone: on 2026-08-25 Central is
# actually on daylight time (CDT). CST is what everyone here writes year-round,
# so it is what the post says — change this one constant if that ever bites.
POST_TZ = "CST"


def central_today() -> dt.date:
    from automations.total_knocks.pull import central_today as _ct
    return _ct()


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def first_name(owner: str) -> str:
    """'Cody Cannon' -> 'Cody'. The board posts in that office's OWN channel,
    so the full ICD name in the header is saying what the channel already says
    (Megan 2026-08-25). The first name stays because two offices SHARE
    #elite-prime-sales — Hammad and Salik — and with no name at all their two
    boards are indistinguishable sitting next to each other."""
    return (owner or "").strip().split()[0] if (owner or "").strip() else ""


def _date_text(day: dt.date) -> str:
    """'8/25' — no leading zeros. Built by hand, not %-m/%-d, which is
    glibc/BSD only and throws on Windows (the cross-platform rule)."""
    return f"{day.month}/{day.day}"


def _caption(owner: str, day: dt.date, partial: bool) -> str:
    """What rides above the image.

    A 9 PM board is a partial day, so it carries the time it was taken —
    a screenshot of it outlives this message. Just the stamp, though: how the
    morning re-pull works is our plumbing, not something the channel needs
    reading every night (Megan 2026-08-25)."""
    who = first_name(owner)
    who = f"{who} — " if who else ""
    cap = (f"{POST_EMOJI} *Total Knocks — {SLOT_LABEL} — {who}"
           f"{_date_text(day)}*")
    if partial:
        cap += f"\n_As of 9:00 PM {POST_TZ}._"
    return cap


def build(target: Optional[dt.date] = None, *, only: Optional[str] = None,
          logfn=print) -> List[dict]:
    """Pull + render every enrolled office's CURRENT-day board.

    Returns one dict per office: {office, label, channel_id, channel_name,
    token_file, png, rows, error}. A per-office failure rides in its own dict
    and never aborts the others — one dark office must not cost the other ten
    their board.
    """
    from automations.rashad_metrics.knocks_pull import pull_offices_days
    from automations.total_knocks import render as knocks_render

    day = target or central_today()
    offices = enrolled()
    if only:
        offices = [o for o in offices if o.key == only]
        if not offices:
            raise SystemExit(f"No enrolled office with key {only!r}. "
                             f"Enrolled: {', '.join(o.key for o in enrolled())}")
    for line in excluded_lines():
        logfn(f"[knocks9pm] not included: {line}")
    logfn(f"[knocks9pm] {len(offices)} office(s) for {day.isoformat()}: "
          + ", ".join(o.key for o in offices))

    jobs = [(o.knocks_office, [day]) for o in offices]
    pulled = {name: (by_day, err) for name, by_day, err in
              pull_offices_days(jobs, verbose=True, profile_dir=PROFILE_DIR)}

    out: List[dict] = []
    for o in offices:
        rec = {"office": o.knocks_office, "key": o.key,
               "label": o.header_label or o.owner,
               "channel_id": o.channel_id, "channel_name": o.channel_name,
               # Only set where two offices SHARE a channel (Hammad + Salik →
               # #elite-prime-sales), so each board is attributable.
               "header_label": o.header_label,
               "token_file": o.slack_token_file,
               "png": None, "rows": [], "error": None}
        by_day, err = pulled.get(o.knocks_office, ({}, None))
        try:
            if err is not None:
                raise err
            rows = by_day.get(day) or []
            rec["rows"] = rows
            if not rows:
                # Visible absence, never a blank board (standing rule): no post
                # goes out for this office and the log says which one.
                logfn(f"[knocks9pm] ⚠ {o.key}: no rows — nothing to post")
                out.append(rec)
                continue
            # Per-office out dir: the renderers name files by DATE, so two
            # offices in one run would otherwise overwrite each other.
            pngs, shape = knocks_render.render_knocks_boards(
                day, rows=rows, out_dir=OUT_DIR / _slug(o.knocks_office),
                title_suffix=first_name(rec["label"]),
                date_text=_date_text(day))
            rec["png"] = pngs[0]
            rec["shape"] = shape
            logfn(f"[knocks9pm] {o.key}: {len(rows)} rep(s) -> {pngs[0].name}")
        except Exception as e:  # noqa: BLE001 — one office ≠ the run
            rec["error"] = e
            logfn(f"[knocks9pm] ❌ {o.key}: {type(e).__name__}: {str(e)[:160]}")
        out.append(rec)
    return out


def token_path(rec: dict) -> Optional[Path]:
    """Where a cross-workspace office's own bot token lives on this machine
    (trang → FRESH SUCCESS), or None for an office that posts as Lucy. Same
    file `office_metrics.runner` and the weekly board read."""
    tf = rec.get("token_file")
    if not tf:
        return None
    return Path.home() / ".config" / "recruiting-report" / tf


def post(results: List[dict], day: dt.date, *, dry_run: bool = True,
         logfn=print) -> int:
    """Post each office's board to its own channel. Returns an exit code.

    An office with no rows is SKIPPED, not posted as an empty board — the
    standing never-post-blank rule. It still shows in the log so a silent
    office is visible to whoever reads the run.

    CROSS-WORKSPACE OFFICES POST WITH THEIR OWN TOKEN, never Lucy's. Trang's
    channel lives in the FRESH SUCCESS workspace; posting her board on the AO
    token would either fail or, worse, land a channel id that means something
    different over there. When the token file isn't on this machine that is a
    structural SKIP — the office simply can't be posted from this box — not a
    failure, and never a fallback to the default token.
    """
    import os

    from automations.shared import slack_metrics_post as smp

    partial = (day == central_today())
    posted = failed = skipped = 0
    for rec in results:
        cap = _caption(rec["label"], day, partial)
        if rec["error"] is not None or rec["png"] is None:
            skipped += 1
            why = ("no rows" if rec["error"] is None
                   else f"{type(rec['error']).__name__}")
            logfn(f"[knocks9pm] skip {rec['key']} ({why}) — nothing posted")
            continue
        tok = token_path(rec)
        if tok is not None and not tok.exists():
            skipped += 1
            logfn(f"[knocks9pm] skip {rec['key']} — cross-workspace token "
                  f"({tok}) isn't on this machine; not posting with Lucy's")
            continue
        if dry_run:
            who = " (own workspace token)" if tok else ""
            logfn(f"[knocks9pm] would post to {rec['channel_name']}{who}: "
                  f"{rec['png']}")
            posted += 1
            continue
        keep_chan, keep_label = smp.CHANNEL_ID, smp.HEADER_LABEL
        keep_tok = os.environ.get("SLACK_USER_TOKEN")
        try:
            smp.CHANNEL_ID = rec["channel_id"]
            smp.HEADER_LABEL = rec.get("header_label", "") or ""
            if tok is not None:
                # _client() reads SLACK_USER_TOKEN per call, so this office's
                # thread lookup AND its image both ride its own workspace
                # token. Restored in the finally, always.
                os.environ["SLACK_USER_TOKEN"] = tok.read_text(
                    encoding="utf-8-sig").strip()
            smp.post_reply_with_image(
                Path(rec["png"]), comment=cap, today=day,
                channel_id=rec["channel_id"],
                file_name=f"{rec['label']} knocks {day} 9pm.png",
                wait_visible=True)
            posted += 1
            logfn(f"[knocks9pm] ✓ posted {rec['key']} -> {rec['channel_name']}")
        except Exception as e:  # noqa: BLE001 — one channel ≠ the run
            failed += 1
            logfn(f"[knocks9pm] ❌ post {rec['key']}: {type(e).__name__}: {e}")
        finally:
            smp.CHANNEL_ID, smp.HEADER_LABEL = keep_chan, keep_label
            if keep_tok is None:
                os.environ.pop("SLACK_USER_TOKEN", None)
            else:
                os.environ["SLACK_USER_TOKEN"] = keep_tok
    logfn(f"[knocks9pm] {'DRY-RUN ' if dry_run else ''}posted={posted} "
          f"skipped={skipped} failed={failed}")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="9 PM Central knock board for every enrolled office.")
    ap.add_argument("--send", action="store_true",
                    help="actually post to Slack (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="render only, no Slack post (the default)")
    ap.add_argument("--office", help="one office key, e.g. cody")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    a = ap.parse_args()

    day = dt.date.fromisoformat(a.date) if a.date else central_today()
    dry = not a.send
    print(f"[knocks9pm] {day.isoformat()} — {'DRY-RUN' if dry else 'LIVE'}",
          flush=True)
    results = build(day, only=a.office)
    return post(results, day, dry_run=dry)


if __name__ == "__main__":
    raise SystemExit(main())
