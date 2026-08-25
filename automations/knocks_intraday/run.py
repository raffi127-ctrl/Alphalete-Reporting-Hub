"""The intraday knock boards — every enrolled office, the CURRENT day.

THREE MOMENTS IN A REP'S DAY, EACH ON THAT OFFICE'S OWN CLOCK:

  2:00 PM  first knocks   — did we get out the door
  5:15 PM  money lap      — knocks going into the start of money lap
  9:00 PM  end of day     — the full breakdown to read at night

Cody Cannon asked for all three (Slack DM 2026-08-24). Raf asked for the 9 PM
board org-wide the next morning, writing "9:00PM CEN" — which read as one clock
for everybody. Megan settled it 2026-08-25: **office-local, all three**, Mon-Sat.
That distinction is not cosmetic. Four of the eleven enrolled offices are
EASTERN (aya, hammad, salik, nii), so a single Central fire would have handed
them their "first knocks" board at 3 PM — an hour into the afternoon it exists
to check on — and their EOD board at 10 PM.

WHICH OFFICE IS OWED WHICH SLOT lives in `schedule.py`, which is pure clock
arithmetic and testable without a browser. This file pulls, renders and posts
what that module says is due.

TONIGHT'S PULL MUST NOT BECOME TOMORROW'S ANSWER. Every slot is a partial day —
reps keep knocking after it. Tomorrow morning the same calendar date is
"yesterday", and the morning board has to re-collect it from ownerville. So this
module writes NOTHING either of the morning readers looks at:

  · the `/knocks` cache — never touched. We call the pull directly, so
    `knocks_request.service.save_rows` is never reached. (It would refuse today
    anyway: it stores only finished days.)
  · the captainship build's sidecar — our PNGs and rows go under
    `output/knocks_intraday/`, never under `captainship_drafts` RENDER_DIR,
    which is the tree `service.cached_rows` globs for `daily_knocks_*`.

`test_no_morning_reuse` pins both. It is the test to run before changing where
this module writes anything.

Nothing here scrapes or draws anything new: the pull is the same
`pull_offices_days` the morning boards use and the image is the same
`render_knocks_boards`. What is new is the trigger and the post.

    python -m automations.knocks_intraday.run --tick              # what's due now
    python -m automations.knocks_intraday.run --slot eod           # dry-run, all
    python -m automations.knocks_intraday.run --slot first --office cody
    python -m automations.knocks_intraday.run --tick --send        # posts
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

from automations.knocks_intraday import roster

OUT_DIR = Path("output") / "knocks_intraday"
# Our OWN Chrome profile: the shared one is first-come-first-served and this
# job runs alongside whatever else the evening has going. Ownerville itself
# parallelises fine — the limit is one browser per profile dir.
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / "_shared" / ".browser_profile_knocks_intraday")

POST_EMOJI = ":door:"
# How a zone is SPELLED in the caption. Standard-time spelling year-round, on
# purpose: Megan 2026-08-25 ("CST instead of central") — nobody here writes CDT
# in August, and an office reading its own board wants the abbreviation it uses.
# Keyed by IANA zone, so an office in a new zone must be spelled here rather
# than silently posting a zone name nobody recognises.
ZONE_ABBR = {
    "America/Chicago": "CST",
    "America/Detroit": "EST",
    "America/New_York": "EST",
    "America/Indiana/Indianapolis": "EST",
}
DEFAULT_ABBR = "CST"


def central_today() -> dt.date:
    from automations.total_knocks.pull import central_today as _ct
    return _ct()


def compare_office() -> str:
    """Whose TOTAL rides every board as the teal comparison line. Resolved
    through the same alias table the morning boards use, so a re-spelling of
    his name in ownerville doesn't silently drop the line."""
    from automations.knocks_request.service import compare_office as _c
    try:
        return _c()
    except Exception:  # noqa: BLE001 — no comparison is not a failed board
        return ""


def _norm(name: str) -> str:
    return " ".join((name or "").lower().split())


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


def zone_abbr(office) -> str:
    """How this office's zone is written in its own caption."""
    return ZONE_ABBR.get(getattr(office, "timezone", "") or "", DEFAULT_ABBR)


def _clock(slot) -> str:
    """'2:00 PM' / '5:15 PM' — no leading zero, no %-I (Windows rejects it)."""
    hh = slot.hour % 12 or 12
    return f"{hh}:{slot.minute:02d} {'AM' if slot.hour < 12 else 'PM'}"


def _caption(owner: str, day: dt.date, slot, abbr: str) -> str:
    """What rides above the image.

    Every slot is a partial day, so each carries the time it was taken — a
    screenshot of it outlives this message, and "Total Knocks" with no stamp
    reads as a finished day. The time is the OFFICE's, in the office's own
    abbreviation: a Michigan office reading "9:00 PM CST" would be looking at a
    board stamped an hour off its own evening. Just the stamp, though: how the
    morning re-pull works is our plumbing, not something the channel needs
    reading every night (Megan 2026-08-25)."""
    who = first_name(owner)
    who = f"{who} — " if who else ""
    return (f"{POST_EMOJI} *Total Knocks — {slot.label} — {who}"
            f"{_date_text(day)}*\n_As of {_clock(slot)} {abbr}._")


def build(slot, jobs_in, *, logfn=print) -> List[dict]:
    """Pull + render the CURRENT-day board for each office owed `slot`.

    `jobs_in` is [(office, local_date), …] — the office's OWN date, not the
    runner's. At 9 PM Central it is already tomorrow in UTC and still today in
    Denver; "which day did this office knock" is a question about the office's
    calendar, so the caller (schedule.due) answers it and this function trusts
    it rather than re-deriving a date from the machine clock.

    Returns one dict per office: {office, label, day, channel_id, channel_name,
    token_file, png, rows, error}. A per-office failure rides in its own dict
    and never aborts the others — one dark office must not cost the other ten
    their board.
    """
    from automations.rashad_metrics.knocks_pull import pull_offices_days
    from automations.total_knocks import render as knocks_render

    offices = [o for o, _d in jobs_in]
    days = {o.key: d for o, d in jobs_in}
    for line in roster.blocked_lines():
        logfn(f"[knocks] not included: {line}")
    logfn(f"[knocks] {slot.key}: {len(offices)} office(s) — "
          + ", ".join(f"{o.key} {days[o.key].isoformat()}" for o in offices))

    # Chan's TOTAL rides every board as the comparison line (Raf 2026-08-23,
    # the same teal row the morning boards carry) — Megan asked for it here
    # too, 2026-08-25. He is pulled in the SAME session as the offices, never
    # a second one: a comparison is a nicety and must not cost its own login.
    compare = compare_office()
    compare_days = sorted({d for d in days.values()})
    jobs = [(o.knocks_office, [days[o.key]]) for o in offices]
    if compare and _norm(compare) not in {_norm(o.knocks_office) for o in offices}:
        jobs.append((compare, compare_days))
    pulled = {name: (by_day, err) for name, by_day, err in
              pull_offices_days(jobs, verbose=True, profile_dir=PROFILE_DIR)}

    # A failed comparison costs one line, never the board.
    chan_by_day, chan_err = pulled.get(compare, ({}, None))
    if chan_err is not None:
        logfn(f"[knocks] ⚠ {compare} comparison pull failed "
              f"({type(chan_err).__name__}) — boards go out without the line")
        chan_by_day = {}

    out: List[dict] = []
    for o in offices:
        day = days[o.key]
        rec = {"office": o.knocks_office, "key": o.key, "day": day,
               "abbr": zone_abbr(o),
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
                logfn(f"[knocks] ⚠ {o.key}: no rows — nothing to post")
                out.append(rec)
                continue
            # Per-office out dir: the renderers name files by DATE, so two
            # offices in one run would otherwise overwrite each other.
            extra = []
            chan_rows = chan_by_day.get(day) or []
            if chan_rows and _norm(o.knocks_office) != _norm(compare):
                extra.append((compare, chan_rows))
                rec["compared_to"] = compare
            elif not chan_rows:
                logfn(f"[knocks] {o.key}: no {compare} rows for {day} — "
                      "board goes out without the comparison line")
            pngs, shape = knocks_render.render_knocks_boards(
                day, rows=rows, out_dir=OUT_DIR / _slug(o.knocks_office),
                title_suffix=first_name(rec["label"]),
                date_text=_date_text(day), extra_totals=extra)
            rec["png"] = pngs[0]
            rec["shape"] = shape
            logfn(f"[knocks] {o.key}: {len(rows)} rep(s) -> {pngs[0].name}")
        except Exception as e:  # noqa: BLE001 — one office ≠ the run
            rec["error"] = e
            logfn(f"[knocks] ❌ {o.key}: {type(e).__name__}: {str(e)[:160]}")
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


def post(results: List[dict], slot, *, dry_run: bool = True,
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

    posted = failed = skipped = 0
    for rec in results:
        day = rec["day"]
        cap = _caption(rec["label"], day, slot, rec["abbr"])
        if rec["error"] is not None or rec["png"] is None:
            skipped += 1
            why = ("no rows" if rec["error"] is None
                   else f"{type(rec['error']).__name__}")
            logfn(f"[knocks] skip {rec['key']} ({why}) — nothing posted")
            continue
        tok = token_path(rec)
        if tok is not None and not tok.exists():
            skipped += 1
            logfn(f"[knocks] skip {rec['key']} — cross-workspace token "
                  f"({tok}) isn't on this machine; not posting with Lucy's")
            continue
        if dry_run:
            who = " (own workspace token)" if tok else ""
            logfn(f"[knocks] would post to {rec['channel_name']}{who}: "
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
                file_name=f"{rec['label']} knocks {day} {slot.key}.png",
                wait_visible=True,
                # EVERY slot posts to the CHANNEL, not into the day's Metrics
                # thread (Megan 2026-08-25, of the 9 PM board and then of Cody's
                # 2 PM / 5:15 PM: "should NOT go in a thread but just be posted
                # to the channel so everyone can see it"). The whole point of
                # the night board is that people read it without digging — Raf
                # asked for it so "people can look at it at night for break
                # downs". A thread reply is exactly the burial that defeats it.
                top_level=True)
            posted += 1
            logfn(f"[knocks] ✓ posted {rec['key']} -> {rec['channel_name']}")
        except Exception as e:  # noqa: BLE001 — one channel ≠ the run
            failed += 1
            logfn(f"[knocks] ❌ post {rec['key']}: {type(e).__name__}: {e}")
        finally:
            smp.CHANNEL_ID, smp.HEADER_LABEL = keep_chan, keep_label
            if keep_tok is None:
                os.environ.pop("SLACK_USER_TOKEN", None)
            else:
                os.environ["SLACK_USER_TOKEN"] = keep_tok
    logfn(f"[knocks] {slot.key}: {'DRY-RUN ' if dry_run else ''}"
          f"posted={posted} skipped={skipped} failed={failed}")
    return 1 if failed else 0


def _ran_path() -> Path:
    """Per-machine 'already posted' markers. Never committed — two machines
    running the same slot is a deploy question, not a state question."""
    return (Path.home() / ".config" / "recruiting-report"
            / "knocks-intraday-ran.json")


def load_markers() -> set:
    import json
    try:
        return set(json.loads(_ran_path().read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 — no file / bad file = nothing posted yet
        return set()


def record_marker(marker: str) -> None:
    """Written only AFTER a successful post, so a crash mid-slot retries on the
    next tick instead of marking a board that never landed."""
    import json
    p = _ran_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        keep = load_markers() | {marker}
        # Markers are date-stamped; keep it from growing forever.
        today = dt.date.today().isoformat()
        cutoff = (dt.date.today() - dt.timedelta(days=7)).isoformat()
        keep = {m for m in keep if m.rsplit(":", 1)[-1] >= cutoff or
                m.endswith(today)}
        p.write_text(json.dumps(sorted(keep)), encoding="utf-8")
    except Exception:  # noqa: BLE001 — a marker that won't write is not fatal
        pass


def run_slot(slot, jobs_in, *, dry_run: bool, logfn=print) -> int:
    """One slot, the offices due for it. Markers are recorded per office, so a
    single office failing is retried next tick without re-posting the ten that
    already landed."""
    if not jobs_in:
        return 0
    results = build(slot, jobs_in, logfn=logfn)
    rc = post(results, slot, dry_run=dry_run, logfn=logfn)
    if not dry_run:
        for rec in results:
            if rec.get("png") is not None and rec.get("error") is None:
                record_marker(f"{rec['key']}:{slot.key}:{rec['day'].isoformat()}")
    return rc


def main() -> int:
    from automations.knocks_intraday import schedule as S
    from automations.office_metrics.offices import unconfirmed_timezones

    ap = argparse.ArgumentParser(
        description="Intraday knock boards, on each office's own clock.")
    ap.add_argument("--tick", action="store_true",
                    help="post whatever is due RIGHT NOW (what launchd runs)")
    ap.add_argument("--slot", choices=[s.key for s in S.SLOTS],
                    help="run one slot explicitly, ignoring the clock")
    ap.add_argument("--send", action="store_true",
                    help="actually post to Slack (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="render only, no Slack post (the default)")
    ap.add_argument("--office", help="one office key, e.g. cody")
    ap.add_argument("--date", help="YYYY-MM-DD (default: each office's today)")
    a = ap.parse_args()

    dry = not a.send
    bad = roster.unknown_keys()
    if bad:
        raise SystemExit(f"roster names offices that don't exist: {bad}")

    def _for(slot_key):
        offices = roster.enrolled(slot_key)
        if a.office:
            offices = [o for o in offices if o.key == a.office]
        return offices

    # A guessed timezone is not a fact. Say so out loud, every run.
    unknown = [k for k in unconfirmed_timezones()
               if k in {o.key for o in roster.everyone()}]
    if unknown:
        print(f"[knocks] ⚠ no confirmed timezone for {', '.join(unknown)} — "
              "running them on the Central default", flush=True)

    if a.tick:
        now = dt.datetime.now(dt.timezone.utc)
        markers = load_markers()
        rc = did = 0
        for slot in S.SLOTS:
            offices = _for(slot.key)
            jobs = [(d.office, d.local_date)
                    for d in S.due(now, offices, done=markers)
                    if d.slot is slot]
            if not jobs:
                continue
            did += 1
            print(f"[knocks] {slot.key} due: "
                  f"{', '.join(o.key for o, _ in jobs)}", flush=True)
            rc |= run_slot(slot, jobs, dry_run=dry)
        if not did:
            def _slots_for(office):
                return [s for s in S.SLOTS
                        if office.key in {o.key
                                          for o in roster.enrolled(s.key)}]

            for line in S.describe(now, roster.everyone(), _slots_for):
                print(f"[knocks] {line}", flush=True)
            print("[knocks] nothing due this tick", flush=True)
        return rc

    if not a.slot:
        raise SystemExit("Pick one: --tick (what's due now) or --slot "
                         f"<{'|'.join(s.key for s in S.SLOTS)}>.")
    slot = S.SLOTS_BY_KEY[a.slot]
    offices = _for(slot.key)
    if not offices:
        raise SystemExit(
            f"No office enrolled for --slot {slot.key}"
            + (f" matching --office {a.office}" if a.office else "")
            + f". Enrolled: {', '.join(o.key for o in roster.enrolled(slot.key))}")
    if a.date:
        day = dt.date.fromisoformat(a.date)
        jobs = [(o, day) for o in offices]
    else:
        now = dt.datetime.now(dt.timezone.utc)
        jobs = [(o, S.local_now(o, now).date()) for o in offices]
    print(f"[knocks] {slot.key} — {'DRY-RUN' if dry else 'LIVE'} — "
          f"{', '.join(o.key for o in offices)}", flush=True)
    return run_slot(slot, jobs, dry_run=dry)


if __name__ == "__main__":
    raise SystemExit(main())
