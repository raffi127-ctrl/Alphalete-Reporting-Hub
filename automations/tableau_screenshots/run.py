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
import contextlib
import datetime as dt
import os
import socket
import sys
from pathlib import Path

from automations.tableau_screenshots import pages as pages_mod
from automations.tableau_screenshots import capture as cap
from automations.tableau_screenshots import slack_post as sp

# OUR OWN Chrome profile. The shared one
# (automations/uploaded/.browser_profile) is first-come, first-served, and a
# launch that finds it taken waits for the holder — the three settle/box
# schedule entries only get 20 minutes, so a collision used to mean being
# killed mid-wait having captured nothing. This is the report the 2026-08-19
# cascade ate six times in one morning for exactly that reason. Same escape
# hatch as other_office_knocks and mobrium_list; the login comes from the
# shared storage_state, not the profile, so a separate dir needs no seeding.
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded"
               / ".browser_profile_trackers")

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

# The SETTLE passes (--settle), later in the morning. Same machinery as the Box
# catch-up — pick up whatever the morning held and post what has since caught up
# — but its own report id, because sharing LATE_REPORT_ID would overwrite the Box
# card's manifest and per-channel checklist with a run that was never about Box.
#
# WHY IT EXISTS (Megan 2026-08-26): the ~7am catch-up used to be the last attempt
# of the day, so a board whose data settled at 10am simply never posted. On 8/26
# NDS and AT&T were still loading at 10:30 — under "report it, don't send it"
# that means two boards silently missing for a whole day. A held board now gets
# more chances, spaced out, until its data actually lands.
SETTLE_REPORT_ID = "tableau-screenshots-settle"

# Per-channel outcome of today's run, read by the Hub card to show its ✅/❌
# checklist. One card posts to EVERY channel, so the card needs to say which
# channels actually landed -- a single red/green light would hide a lone failure.
STATUS_FILE = OUT_DIR / "_posted_today.json"
LATE_STATUS_FILE = OUT_DIR / "_posted_today_box.json"
SETTLE_STATUS_FILE = OUT_DIR / "_posted_today_settle.json"

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


@contextlib.contextmanager
def _org_slack_token(org: str, label: str):
    """Act as the workspace that OWNS this org's channel, then restore.

    trang's channel lives in the FRESH SUCCESS Slack, not ours, so anything that
    touches it — posting a board OR editing today's header — has to use that
    workspace's own token. smp._client() builds a fresh client from
    SLACK_USER_TOKEN on every call, so setting the env var here is enough.

    Yields "" when the org is good to go, or the reason it can't be reached from
    this machine. NEVER falls back to the AO token: it cannot see another
    workspace's channel, and Slack answers a non-member with `channel_not_found`
    — which reads as "Lucy got un-invited from one of our private channels" and
    is exactly the alert nobody could act on 8/19 and 8/23.
    [[project_trang_fresh_success]]"""
    saved, routed, missing = os.environ.get("SLACK_USER_TOKEN"), False, ""
    try:
        from automations.office_metrics.offices import CROSS_WS_TOKEN_FILES
        tok_file = CROSS_WS_TOKEN_FILES.get(org)
    except Exception:                                 # noqa: BLE001
        tok_file = None
    if tok_file:
        tok_path = Path.home() / ".config" / "recruiting-report" / tok_file
        if tok_path.exists():
            os.environ["SLACK_USER_TOKEN"] = tok_path.read_text(
                encoding="utf-8-sig").strip()
            routed = True
        else:
            missing = _cross_ws_token_missing(org, label, tok_file)
    try:
        yield missing
    finally:
        if routed:
            if saved is None:
                os.environ.pop("SLACK_USER_TOKEN", None)
            else:
                os.environ["SLACK_USER_TOKEN"] = saved


def _select_orgs(orgs: str) -> list:
    """'all' -> every org, in channel order; else the named comma-separated subset."""
    raw = (orgs or "all").strip()
    if raw.lower() == "all":
        return list(sp.ORGS)
    want = [o.strip() for o in raw.split(",") if o.strip()]
    bad = [o for o in want if o not in sp.ORGS]
    if bad:
        # A PAUSED org is not a typo — say so, or the next person re-onboards a
        # channel we took out on purpose (slack_post.PAUSED_ORGS).
        paused = [o for o in bad if o in getattr(sp, "PAUSED_ORGS", {})]
        if paused:
            raise SystemExit("--orgs: " + "; ".join(
                f"{o} is PAUSED — {sp.PAUSED_ORGS[o]}" for o in paused)
                + ". Delete its entry in slack_post.PAUSED_ORGS to resume.")
        raise SystemExit(f"--orgs: unknown org(s) {', '.join(bad)}. "
                         f"Known: {', '.join(sp.ORGS)} (or 'all')")
    return want


def _write_status(out_dir: Path, results: list, today: dt.date,
                  status_file: Path = STATUS_FILE, omitted: list | None = None) -> None:
    """Today's per-channel outcome, for the Hub card's checklist. `omitted` names
    boards this run deliberately left out because their source wasn't in yet (an
    email tracker whose .xlsx hasn't landed) — recorded so the card can say EXACTLY
    which boards posted vs. which are still owed, instead of implying all did."""
    import json
    try:
        (out_dir / status_file.name).write_text(json.dumps({
            "date": today.isoformat(),
            "channels": results,
            "omitted": omitted or [],
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


def _hold_stale_boards(today: dt.date, *, dry_run: bool,
                       orgs: list | None = None) -> dict:
    """Measure each tracker's Tableau extract and HOLD any board whose extract
    hasn't reached the latest completed reporting day. Returns {board_id: why}.

    Megan 2026-07-29: "trackers were sent out today without being updated and we
    ran them anyway — I thought we had a guard set up for that?" There was no
    guard. The orchestrator gate (data_sources -> readiness._probe_tracker_extract)
    now holds the whole run while an extract is behind, but it FAIL-OPENS at 06:30
    so it can never skip the trackers — and past that floor the run proceeds with
    whatever Tableau has. This is the other half: a board that is still stale when
    the run proceeds is held out of the thread and flagged, instead of being
    photographed and posted as though it were fresh (fill-but-flag).

    "Held" reuses Box's machinery end to end: pages.mark_late() drops the board
    from this run's selection, the thread header still lists it with the "data
    lands ~7am" note, and the ~7am --late-only catch-up posts it. Nothing is
    silently dropped.

    Never holds on a probe ERROR — only on a confirmed "the extract has not
    refreshed". A broken probe must not keep a good board off the thread."""
    from automations.tableau_screenshots import freshness as fr
    # Only the boards the morning run would post: permanently-late (Box) and
    # email-sourced boards have their own gates.
    candidates = [p["id"] for p in pages_mod.PAGES
                  if not p.get("late") and p.get("source") != "email"]
    # …and only the ones THIS RUN's channels actually receive. An org-wide run is
    # every board, so nothing changes there; a single-org run is that channel's
    # subscription.
    #
    # WHY (Megan 2026-08-26): the 21:03 onboarding run for #alisei-b2b-sales —
    # an office enrolled in exactly THREE boards — probed all nine and told the
    # corrections channel that five were held, two of which (NDS, Order Tiered
    # Bonus) that office does not get and would not have been posted either way.
    # Gating a board nobody in this run subscribes to can only produce a false
    # alarm, and it spends a Tableau pull to do it [[project_tableau_access_budget]].
    if orgs:
        subscribed = set()
        for org in orgs:
            subscribed.update(sp.tracker_ids_for(org, pages_mod.PAGES))
        candidates = [b for b in candidates if b in subscribed]
    print("\n=== FRESHNESS GATE ===", flush=True)
    tgt = fr.target_day(today)
    print(f"  extracts must have data through "
          f"{tgt.isoformat() if tgt else 'n/a'}", flush=True)
    try:
        held, _verdicts = fr.stale_boards(candidates, today, verbose=True)
    except Exception as e:                            # noqa: BLE001 — fail open
        print(f"  ⚠ freshness check errored ({type(e).__name__}: {str(e)[:120]}) "
              f"— posting every board (a broken gate never holds a report)",
              flush=True)
        return {}
    for bid, why in fr.UNGATED.items():
        if bid in candidates:
            print(f"   • {bid}: NOT GATED — {why}", flush=True)
    if not held:
        print("  ✓ every gated extract is fresh", flush=True)
        # Nothing held → close the hold thread if one is open, so the channel
        # stops showing a stale extract as live work. Free when nothing is open.
        try:
            from automations.shared import incident_thread as _inc
            _inc.resolve_if_open("tracker-freshness",
                                 what="*Country Trackers*",
                                 detail="Every gated extract is fresh again — "
                                        "all boards posted.", dry_run=dry_run)
        except Exception:  # noqa: BLE001 — closing must never sink a good run
            pass
    fr.write_held(today, held)
    if held:
        pages_mod.mark_late(held.keys())
        handoff = _held_handoff_note(today, dt.datetime.now())
        for bid, why in held.items():
            title = (pages_mod.by_id(bid) or {}).get("title") or bid
            print(f"  ⏸ HOLDING {title} — {why}", flush=True)
        print(f"  {handoff}", flush=True)
        _alert_held(today, held, dry_run=dry_run)
    return held


# The passes that pick a held board back up, in the order they fire. Read from
# schedule_config rather than written here, so moving a settle pass moves what the
# channel is TOLD — the two drifting apart is exactly the bug below.
#
# Box has no not_before (it is data-gated, not clock-gated); its readiness probe
# fail-open floor is 08:00 and it lands ~06:50-08:00, so 08:00 is when it has
# certainly either run or given up.
_CATCH_UP_FALLBACK_HHMM = "08:00"


def _catch_up_passes(today: dt.date) -> list:
    """[(HH:MM, display name)] of today's later tracker passes, earliest first.

    Best-effort: an unreadable config just means the note below says less."""
    try:
        from automations.day_orchestrator import registry as _reg
        cfg = _reg.load_config()
    except Exception:                                 # noqa: BLE001
        return []
    out = []
    for rid, r in (cfg.reports or {}).items():
        if not rid.startswith("tableau_screenshots"):
            continue
        if not any(a in r.base_args for a in ("--late-only", "--settle")):
            continue
        if today.weekday() not in (r.weekdays or []):
            continue
        out.append((r.not_before or _CATCH_UP_FALLBACK_HHMM, r.display_name))
    return sorted(out)


def _held_handoff_note(today: dt.date, now: dt.datetime) -> str:
    """What will ACTUALLY pick these boards up, given the time right now.

    WHY THIS IS COMPUTED (Megan 2026-08-26): this sentence used to be the fixed
    string "the ~7am catch-up posts it once its extract lands". The 21:03
    onboarding run for #alisei-b2b-sales posted it at nine at night, about a
    catch-up that had finished fourteen hours earlier and would not run again —
    so the channel was told a board was on its way that nothing was going to
    send. A note that names a pass which has already gone is worse than no note:
    it reads as handled."""
    later = [(hhmm, name) for hhmm, name in _catch_up_passes(today)
             if hhmm > now.strftime("%H:%M")]
    if not later:
        return ("Held, not posted — and NO automatic pass is left today, so it "
                "will not post unless someone re-runs it.")
    hhmm, name = later[0]
    # Times only for the passes after the next one — the names are long and the
    # useful fact is "there are more chances, and here is when they stop".
    rest = (" (then %s)" % ", ".join(t for t, _ in later[1:])) if later[1:] else ""
    return ("Held, not posted: the board is listed in today's thread header as "
            "still coming, and *%s* picks it up from %s%s once its extract lands."
            % (name, hhmm, rest))


def _alert_held(today: dt.date, held: dict, *, dry_run: bool) -> None:
    """Tell #claudecorrections-and-requests, in real time, that a board was held
    for a stale extract (Megan's standing rule: every fail / glitch / missed part
    posts there). Best-effort — an alert must never sink the run."""
    lines = [f"*Tableau Country Trackers — {len(held)} board(s) held for stale "
             f"data* ({today.isoformat()})"]
    for bid, why in held.items():
        title = (pages_mod.by_id(bid) or {}).get("title") or bid
        lines.append(f"• {title} — {why}")
    lines += [
        "",
        _held_handoff_note(today, dt.datetime.now()),
        "Post it by hand once the data is in:",
        "`python -m automations.tableau_screenshots.run --only "
        + ",".join(held) + " --fresh`",
    ]
    try:
        from automations.day_orchestrator import notify
        # An extract that's late today is usually late tomorrow too, and this
        # posted fresh every run. One thread; the repeats go inside it and it
        # closes itself the first time the boards post clean.
        notify.post_alert("", lines, tag="tracker-freshness", dry_run=dry_run,
                          incident="tracker-freshness")
    except Exception as e:                            # noqa: BLE001
        print(f"  (corrections alert failed: {type(e).__name__}: {str(e)[:120]})",
              flush=True)


def withhold_still_behind(selected: list, still_behind: dict) -> list:
    """`selected` minus the boards whose Tableau data is still behind.

    Megan 2026-08-26: "the updated ones are sent and the non updated ones are
    reported in the slack channel and NOT sent." Only the SEND set is trimmed —
    the caller leaves these boards in post_pages on purpose, so each keeps its
    header line and its "Tableau hasn't updated this one yet" note. Dropping them
    from the header too would make a missing board look like a board that was
    never supposed to be there, which is the failure the note exists to prevent."""
    behind = set(still_behind or ())
    for bid in behind:
        title = (pages_mod.by_id(bid) or {}).get("title") or bid
        print(f"  ⛔ NOT sending {title} — {still_behind[bid]}; the thread "
              f"reports it as not updated", flush=True)
    return [p for p in selected if p["id"] not in behind]


def _report_rendered_dates(today: dt.date, captures: list, *,
                           dry_run: bool) -> list:
    """Compare what each board VISIBLY shows against the day it should cover.

    Every other gate here reads the data behind the picture. This reads the
    picture — the gap that let quantum_fiber through on 2026-08-26 would have
    been caught by the data gate too, but a board whose data is current and whose
    VIEW is stuck on last week is invisible to all of them.

    REPORT ONLY, deliberately. A board is flagged, never held. The rule ("the
    newest date the board displays is older than the day it should cover") is
    sound on the four boards read off the 8/26 PNGs, but it has not been watched
    across a month-end, a Monday rollover, or the six boards nobody has sampled.
    A false hold costs 15 channels a real board — strictly worse than the miss it
    would prevent. Flip to holding once the flags have matched reality for a
    while; the withhold machinery is already there (withhold_still_behind)."""
    from automations.tableau_screenshots import capture as _cap
    from automations.tableau_screenshots import freshness as _fr
    target = _fr.target_day(today)
    if not target:
        return []
    suspect = []
    for spec, _png in captures:
        shown = _cap.RENDERED_DATES.get(spec["id"]) or []
        if not shown:
            continue                        # read nothing -> say nothing
        if _cap.RENDERED_TRUNCATED.get(spec["id"]):
            # Tableau cut the date labels off to fit the column ("Mon (0..").
            # That is UNREADABLE, not old, and the two are not the same claim:
            # on 2026-08-31 att_country went from two day columns to seven, its
            # headers truncated, and the newest date left legible anywhere on
            # the dashboard was last week's page -- so a board showing the
            # correct completed week read as five days behind. Read nothing,
            # say nothing, the same rule the probe already follows.
            print(f"  · {spec['title']}: date labels cut off — not judged",
                  flush=True)
            continue
        newest = max(shown)
        if newest < target:
            suspect.append((spec, newest))
    if not suspect:
        return []
    lines = [f"*Tableau Country Trackers — {len(suspect)} board(s) may be showing "
             f"an old period* ({today.isoformat()})"]
    for spec, newest in suspect:
        lines.append(f"• {spec['title']} — newest date on the board is "
                     f"{newest.isoformat()}, expected {target.isoformat()}")
    lines += [
        "",
        "These POSTED — this check only watches for now. It reads the rendered "
        "board, not the data behind it, so it sees a view stuck on the wrong "
        "week, which every other gate is blind to.",
        "Worth eyeballing one of them against Tableau; if it's right, the check "
        "needs tuning, and if it's wrong we should start holding on it.",
    ]
    try:
        from automations.day_orchestrator import notify
        notify.post_alert("", lines, tag="tracker-rendered-date", dry_run=dry_run,
                          incident="tracker-rendered-date")
    except Exception as e:                            # noqa: BLE001
        print(f"  (rendered-date alert failed: {type(e).__name__}: {str(e)[:120]})",
              flush=True)
    return suspect


def _alert_not_sent(today: dt.date, still_behind: dict, *, dry_run: bool) -> None:
    """Tell #claudecorrections a board was WITHHELD from the catch-up because its
    data never caught up — the end-of-the-line version of _alert_held.

    Different message from the morning's on purpose. The morning alert says "held,
    the ~7am catch-up will post it"; this one says the catch-up came and went and
    the board is not going out today at all. Threaded under the same incident so a
    board that is behind for days is one conversation, not one post per run."""
    lines = [f"*Tableau Country Trackers — {len(still_behind)} board(s) NOT sent* "
             f"({today.isoformat()})"]
    for bid, why in still_behind.items():
        title = (pages_mod.by_id(bid) or {}).get("title") or bid
        lines.append(f"• {title} — {why}")
    lines += [
        "",
        "These were held this morning and their Tableau data STILL hasn't "
        "refreshed, so the catch-up did not post them either. Every channel's "
        "thread lists them as not updated — nothing stale went out.",
        # Same correction as _held_handoff_note: "they post on their own" was a
        # flat promise, and after the day's last settle pass nobody is coming.
        _held_handoff_note(today, dt.datetime.now()),
        "To force one out as-is:",
        "`python -m automations.tableau_screenshots.run --only "
        + ",".join(still_behind) + " --fresh`",
    ]
    try:
        from automations.day_orchestrator import notify
        notify.post_alert("", lines, tag="tracker-freshness", dry_run=dry_run,
                          incident="tracker-freshness")
    except Exception as e:                            # noqa: BLE001
        print(f"  (corrections alert failed: {type(e).__name__}: {str(e)[:120]})",
              flush=True)


def _queue_tracker_texts(captured_ids: set, posted_somewhere: bool,
                         *, dry_run: bool) -> None:
    """Queue the B2B AT&T / B2B Box boards for texting on Lucy 2 (Carlos 2026-08-09).

    Runs on the mini right after a successful post, so the text fires "at the same
    time" the board hits Slack. The texting itself CANNOT happen here — the
    iMessage groups and the Messages permission grant live on Lucy 2 — so we drop
    a `text_tracker <id>` row onto LUCY 2's control tab and let its poller (the
    identity that holds the grant) re-capture the board and send it. Same
    cross-machine handoff shape b2b_dispositions uses for the poller.

    Only the boards that ACTUALLY posted this run are queued (a held/failed board
    isn't in the Slack thread, so it mustn't be texted). Idempotency is the
    poller's job: tracker_texts drops a per-(id, day) `.sent` marker, so a retry
    that re-queues the same board never double-texts ~20 leaders.

    Best-effort: a queue failure must never fail an otherwise-good Slack post, but
    it IS a silent gap in an outward send, so it pings #claudecorrections."""
    from automations.tracker_texts import config as tt_cfg
    to_text = [tid for tid in tt_cfg.TARGET_IDS if tid in captured_ids]
    if not to_text or not posted_somewhere:
        return
    if dry_run:
        print(f"\n  (--text-trackers dry-run: would queue text_tracker for "
              f"{', '.join(to_text)} on Lucy 2)", flush=True)
        return
    from automations.day_orchestrator import mini_control as mc
    for tid in to_text:
        try:
            mc.enqueue("text_tracker", tid, by="tableau_screenshots",
                       machine="Lucy 2")
            print(f"  → queued text_tracker {tid} on Lucy 2 "
                  f"(→ {', '.join(tt_cfg.route_for(tid))})", flush=True)
        except Exception as e:                            # noqa: BLE001
            print(f"  ⚠ could NOT queue text_tracker {tid}: "
                  f"{type(e).__name__}: {str(e)[:140]}", flush=True)
            try:
                from automations.day_orchestrator import notify
                notify.post_alert("", [
                    f"*Tracker text handoff failed — {tid}*",
                    f"The board posted to Slack but the text_tracker hand-off to "
                    f"Lucy 2 raised {type(e).__name__}: {str(e)[:160]}.",
                    f"The leaders' groups did NOT get today's {tid} text. Re-queue "
                    f"by hand: `lucy text_tracker {tid} --machine \"Lucy 2\"`.",
                ], tag="tracker-text-handoff", dry_run=False,
                    incident=f"tracker-text-{tid}")
            except Exception:                             # noqa: BLE001
                pass


def _cross_ws_token_missing(org: str, label: str, token_file: str) -> str:
    """Why a cross-workspace org can't be posted from THIS machine, or "".

    WHY (Megan 2026-08-24). trang's channel lives in the FRESH SUCCESS Slack, not
    ours, so it is posted with that workspace's own bot token
    (CROSS_WS_TOKEN_FILES). When the token file isn't on the machine the run is
    on — which is what the 8/23 move of the trackers to Lucy 3 changed — the code
    used to just leave SLACK_USER_TOKEN alone and post with the AO 'Lucy' token.
    That token cannot see a channel in another workspace, and Slack answers a
    non-member with `channel_not_found`, so the alert read
    "#freshsuccess-all-leaders (channel unreadable)" — indistinguishable from Lucy
    being un-invited to one of OUR private channels. Two people looked at that
    alert on 8/19 and 8/23 and neither could act on it, because the fix is a file
    on a machine, not an invite.

    Naming the file and the machine is the whole point.
    [[project_trang_fresh_success]]"""
    if not token_file:
        return ""
    path = Path.home() / ".config" / "recruiting-report" / token_file
    if path.exists():
        return ""
    return (f"{label} is in a DIFFERENT Slack workspace and its token file is "
            f"not on this machine ({socket.gethostname()}): expected "
            f"{path}. Nothing was posted for '{org}' — the AO Lucy token can't "
            f"see that workspace, and using it would report a misleading "
            f"'channel unreadable'. Copy the token file to this machine, or run "
            f"'{org}' from the machine that has it.")


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
    ap.add_argument("--settle", action="store_true",
                    help="A later pass for boards the morning HELD: re-check "
                         "each one and post the ones whose Tableau data has "
                         "since finished loading. Implies --late-only (same "
                         "pick-up-what-was-held machinery) but reports under its "
                         "own id, so it can't overwrite the Box catch-up's card. "
                         "A no-op when nothing was held.")
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
    ap.add_argument("--new-thread", action="store_true",
                    help="Post a SECOND, complete thread for today instead of "
                         "reusing today's existing one: a fresh parent + every "
                         "image, in every channel. The morning thread is left "
                         "untouched (nothing edited, nothing deleted). For the "
                         "day the source data was wrong when the first thread "
                         "went out — pair with --fresh so the images are "
                         "re-captured, and --include-late so Box is in it too.")
    ap.add_argument("--updated", action="store_true",
                    help="Tag every channel's parent header with a bold "
                         "*UPDATED* after the title, so a corrected thread is "
                         "obvious next to an earlier wrong one. Appended only — "
                         "the title itself is unchanged, so find_thread_ts still "
                         "matches today's parent on a later retry.")
    ap.add_argument("--no-freshness-gate", action="store_true",
                    help="Post every board even if its Tableau extract hasn't "
                         "refreshed yet. By default a board whose extract is "
                         "still on yesterday's data is HELD out of the thread "
                         "(listed in the header as still coming, posted by the "
                         "~7am catch-up) rather than posted as if it were fresh. "
                         "Use only when you deliberately want today's render, "
                         "stale or not.")
    ap.add_argument("--header-note", default=None,
                    help="One italic line under the thread title (e.g. why a "
                         "second thread exists). Used with --new-thread.")
    ap.add_argument("--notice", nargs="?", const=sp.STALE_NOTICE, default=None,
                    metavar="TEXT",
                    help="Tell every channel, in one line, that Tableau is "
                         "behind — then stop. No browser, no capture, no new "
                         "message: today's already-posted thread header gets an "
                         "italic heads-up line under the title, in every channel "
                         "of every org. Bare --notice uses the standard wording "
                         "(\"the updated ones get posted right here as soon as "
                         "Tableau refreshes\"); pass your own text to override. "
                         "Pair with --dry-run to see the exact header first.")
    ap.add_argument("--text-trackers", action="store_true",
                    help="After a successful post, queue the B2B AT&T and B2B Box "
                         "boards to be TEXTED to their iMessage groups on Lucy 2 "
                         "(Carlos 2026-08-09: B2B AT&T -> 'ATT B2B Leaders' + 'New "
                         "A Players'; B2B Box -> 'Box B2B' + 'New A Players'). OFF "
                         "by default -- nothing is ever texted unless this is "
                         "passed. Only boards that actually posted this run are "
                         "queued; the poller on Lucy 2 does the send and dedupes "
                         "per day, so a retry can't double-text.")
    ap.add_argument("--headless", action="store_true",
                    help="Run the browser headless (default: headed, matches the "
                         "other Tableau reports + renders more reliably).")
    ap.add_argument("--out-dir", default=str(OUT_DIR),
                    help="Where to write PNGs (default: output/tableau_screenshots).")
    args = ap.parse_args(argv)

    # --new-thread creates a brand-new parent, so there are no old replies under
    # it to clear — --replace would be a silent no-op, and the pair reads like it
    # means "replace the old thread", which is the opposite of what happens.
    if args.new_thread and args.replace:
        raise SystemExit("--new-thread and --replace are mutually exclusive: "
                         "--new-thread posts a SECOND thread and leaves the "
                         "existing one alone; --replace fixes the images inside "
                         "today's EXISTING thread. Pick one.")
    if args.new_thread and args.retitle_only:
        raise SystemExit("--new-thread and --retitle-only are mutually exclusive.")

    # --settle IS a late-only run (pick up what the morning held); it only
    # differs in which card it reports under. Set before the freshness gate,
    # which branches on late_only.
    if args.settle:
        args.late_only = True

    today = dt.date.today()
    # FRESHNESS GATE — runs BEFORE the selection, because holding a stale board
    # works by marking it late, and _select() reads lateness.
    #   normal run   measure each extract; hold + flag whatever is stale.
    #   --late-only  don't re-measure: pick up whatever THIS MORNING held, so the
    #                ~7am catch-up posts those boards alongside Box. It posts them
    #                even if the extract is still behind — the catch-up is the
    #                last stop, and a late board beats a missing one.
    #   --only       bypassed entirely: naming a board means you want that board.
    held: dict = {}
    still_behind: dict = {}
    if args.retitle_only or args.inspect or args.no_freshness_gate:
        pass
    elif args.late_only or args.notice:
        from automations.tableau_screenshots import freshness as _fr
        held = _fr.read_held(today)
        if held:
            pages_mod.mark_late(held.keys())
            what = ("this note re-renders the header for"
                    if args.notice else "catch-up also carries")
            print(f"  ↺ {what} {len(held)} board(s) this morning "
                  f"held for stale data: {', '.join(held)}", flush=True)
            if args.late_only:
                # Re-measure ONLY what this morning held — usually nothing, so
                # this costs a pull on the rare day it matters. What comes back
                # still behind is NOT posted (see the withhold below): the old
                # "last stop, a late board beats a missing one" rule is what put
                # a 0-sales quantum_fiber board in front of 15 channels on
                # 2026-08-26, three hours after the morning gate held it. A board
                # nobody has refreshed is not a late board, it is a wrong one.
                try:
                    still_behind, _v = _fr.stale_boards(list(held), today,
                                                        verbose=True)
                except Exception as e:            # noqa: BLE001 — never sink the catch-up
                    print(f"  (re-check skipped: {type(e).__name__}) — keeping "
                          f"this morning's note", flush=True)
                    still_behind = dict(held)
                for bid in still_behind:
                    title = (pages_mod.by_id(bid) or {}).get("title") or bid
                    print(f"  ⚠ {title} is STILL behind — it will be reported in "
                          f"the thread, not sent", flush=True)
    elif not args.only:
        held = _hold_stale_boards(today, dry_run=args.dry_run,
                                  orgs=_select_orgs(args.orgs))

    # The thread's own heads-up line: every channel's header says Tableau is
    # behind and that the updated boards land here on their own (Megan
    # 2026-08-26). It is tied to the DATA being behind, not to the boards being
    # absent — the ~7am catch-up posts a still-behind board (last stop) and KEEPS
    # the line, because a 0-sales board landing with a clean header is the exact
    # thing this whole gate exists to stop. The line clears the moment the data
    # is actually current, which for the catch-up means still_behind is empty.
    if args.notice:
        auto_note = ""                       # the notice supplies its own text
    elif args.late_only:
        auto_note = sp.STALE_NOTICE if still_behind else ""
    else:
        auto_note = sp.STALE_NOTICE if held else ""

    selected = _select(args.only, late_only=args.late_only,
                       include_late=args.include_late)
    out_dir = Path(args.out_dir)
    force_crop = "full" if args.full else None

    orgs = _select_orgs(args.orgs)
    # The late catch-up is its OWN report to the Hub + orchestrator: its own
    # manifest (else it overwrites the morning run's verify record) and its own
    # per-channel status file (else the morning card's checklist gets rewritten
    # to show one tracker). Same code, same channels, separate accounting.
    if args.settle:
        report_id, status_file = SETTLE_REPORT_ID, SETTLE_STATUS_FILE
    elif args.late_only:
        report_id, status_file = LATE_REPORT_ID, LATE_STATUS_FILE
    else:
        report_id, status_file = REPORT_ID, STATUS_FILE
    print(f"Tableau country trackers -- {len(selected)} view(s) -> {len(orgs)} org(s): "
          f"{', '.join(sp.ORG_LABEL[o] for o in orgs)}, "
          f"{'DRY-RUN (no Slack)' if args.dry_run else 'LIVE'}, "
          f"out={out_dir}", flush=True)

    # Heads-up line into today's existing thread, every channel — no browser, no
    # capture, no new message. Megan 2026-08-26, the morning Tableau was behind:
    # "can we post in every channel letting them know updated ones will be posted
    # when it's updated." Editing the header they're already watching beats a
    # second post: one place to look, and it disappears on tomorrow's thread.
    if args.notice:
        bad = []
        for org in orgs:
            with _org_slack_token(org, sp.ORG_LABEL[org]) as missing_tok:
                if missing_tok:
                    print(f"  [{org}] SKIPPED — {missing_tok}", flush=True)
                    bad.append({"channel": sp.ORG_LABEL[org],
                                "status": f"SKIPPED — {missing_tok}"})
                    continue
                res = sp.annotate_today(pages_mod.PAGES, today, org=org,
                                        note=args.notice, dry_run=args.dry_run)
            if res.get("dry_run"):
                # Worst case on purpose: a preview does no Slack READ either, so
                # it can't know which late boards already landed — every late
                # board is shown as still pending. The live run reads the thread.
                print(f"  [{org}] DRY-RUN → {', '.join(res['channels'])} "
                      f"(late-board notes shown worst-case)", flush=True)
                for line in res["header"].splitlines():
                    print(f"      {line}", flush=True)
                continue
            for r in res["results"]:
                print(f"  [{org}] {r['channel']}: {r['status']}", flush=True)
            bad += [r for r in res["results"]
                    if str(r["status"]).startswith(("FAILED", "SKIPPED"))]
        print(f"\n{'⚠' if bad else '✓'} notice "
              f"{'previewed' if args.dry_run else 'posted'} to "
              f"{len(orgs)} org(s)", flush=True)
        return 1 if bad else 0

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
                             verbose=True, profile_dir=PROFILE_DIR) as page:
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

    # STILL BEHIND -> REPORTED, NOT SENT (Megan 2026-08-26: "the updated ones are
    # sent and the non updated ones are reported in the slack channel and NOT
    # sent"). The morning run already withholds what the gate held; this is the
    # ~7am catch-up's half, which until now posted them regardless as the "last
    # stop" — so a board nobody had refreshed still reached every channel, just
    # later. Deliberately NOT removed from post_pages: the board keeps its header
    # line and its "Tableau hasn't updated this one yet" note, because being told
    # a number is missing is the entire point. An explicit --only still wins.
    if still_behind and not args.only:
        selected = withhold_still_behind(selected, still_behind)
        _alert_not_sent(today, still_behind, dry_run=args.dry_run)

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
                                 verbose=True, profile_dir=PROFILE_DIR) as page:
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

    # What the RENDERED boards are showing vs the day they should cover. Watches
    # only — see _report_rendered_dates for why nothing is held on it yet.
    _rendered_suspect = _report_rendered_dates(today, captures,
                                               dry_run=args.dry_run)
    for spec, newest in _rendered_suspect:
        print(f"  ⚠ {spec['title']}: board's newest date is {newest.isoformat()} "
              f"— expected {today - dt.timedelta(days=1)} or newer (posted "
              f"anyway; this check is watching, not holding)", flush=True)

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

    if not captures and still_behind and not failed:
        # Nothing left to send because everything this run could post is STILL
        # behind. That is not a failure — it is the gate working — but the
        # channel must hear it, so update the header in place and post nothing.
        # Same path --notice uses, so there is one implementation of "tell the
        # channel without sending a board".
        print(f"\n⛔ nothing sent: {len(still_behind)} board(s) still behind "
              f"({', '.join(still_behind)}) — reporting in-channel", flush=True)
        for org in orgs:
            with _org_slack_token(org, sp.ORG_LABEL[org]) as missing_tok:
                if missing_tok:
                    print(f"  [{org}] SKIPPED — {missing_tok}", flush=True)
                    continue
                res = sp.annotate_today(post_pages, today, org=org,
                                        dry_run=args.dry_run)
            for r in res.get("results", []):
                print(f"  [{org}] {r['channel']}: {r['status']}", flush=True)
        run_manifest.write_manifest(
            report_id, ok=False, failed=[], kind="tracker", retry_args=[],
            note="nothing sent — %d board(s) still behind: %s"
                 % (len(still_behind), ", ".join(still_behind)),
            dry_run=args.dry_run)
        return 0

    if not captures:
        run_manifest.write_manifest(
            report_id, ok=False, failed=failed, kind="tracker",
            retry_args=["--only", ",".join(failed)] if failed else [],
            note="no trackers captured", dry_run=args.dry_run)
        print("\n❌ Captured nothing. See errors above.", flush=True)
        return 1

    # Preview-DM mode: DM the captured thread to reviewers, post nothing to
    # the channels.
    if args.preview_dm:
        users = [u.strip() for u in args.preview_dm.split(",") if u.strip()]
        # Scope the preview to the channel's real feed when a SINGLE org is named
        # (e.g. --orgs domin8), so it DMs exactly what that channel would get.
        preview_org = orgs[0] if len(orgs) == 1 else None
        pv = sp.preview_dm(captures, post_pages, users, today,
                           dry_run=args.dry_run, org=preview_org)
        if args.dry_run:
            print(f"\n✓ DRY-RUN: captured {len(captures)} PNG(s) to {out_dir}; "
                  f"would DM {', '.join(users)} (nothing to channels).", flush=True)
        else:
            print(f"\n✓ PREVIEW DM'd to {', '.join(pv.get('user_ids', users))} "
                  f"(mode={pv.get('mode')}) — {len(captures)} image(s), "
                  f"nothing posted to the channels.", flush=True)
        run_manifest.write_manifest(
            report_id, ok=bool(not failed), failed=failed, kind="tracker",
            note="preview-dm run" + (f"; {len(failed)} failed" if failed else ""),
            dry_run=args.dry_run)
        return 1 if failed else 0

    # Post into each org's own dated thread — ONE capture feeds them all. An org
    # that blows up must NOT take the rest down with it (that's the whole point of
    # posting them from one run but tracking them separately), so each is caught
    # and recorded; the failures come back as the manifest's retry list.
    if args.dry_run:
        for org in orgs:
            result = sp.post_all(captures, post_pages, today, dry_run=True,
                                 replace=args.replace, org=org,
                                 new_thread=args.new_thread,
                                 note=args.header_note or auto_note,
                                 updated=args.updated)
            print(f"\n  [{org}] would post to {', '.join(result['channels'])} as "
                  f"{sp.header_title(today)}", flush=True)
        print(f"\n✓ DRY-RUN: captured {len(captures)} PNG(s) to {out_dir}; "
              f"posted NOTHING.", flush=True)
        if args.text_trackers:
            _queue_tracker_texts({spec["id"] for spec, _ in captures},
                                 posted_somewhere=True, dry_run=True)
        run_manifest.write_manifest(
            report_id, ok=bool(not failed), failed=failed, kind="tracker",
            note="dry run" + (f"; {len(held)} board(s) held for a stale extract: "
                              f"{', '.join(held)}" if held else ""),
            dry_run=True)
        return 1 if failed else 0

    posted_ok, posted_bad, status_rows = [], [], []
    # Orgs whose ONLY problem was an unreadable channel — conversations.history /
    # .replies failed, so we couldn't tell "already posted" from "not posted yet"
    # and deliberately posted nothing rather than duplicate today's thread
    # (slack_post.DedupReadUnavailable). SOFT: ok=False + the manifest alert, but
    # exit 0. A single unreadable channel must never hard-fail a run that
    # delivered every other org — 2026-08-13, #precisionmanagement-nds-sales
    # sank a Box catch-up that had already posted 14/15.
    posted_soft: list = []
    # Orgs this run owed NOTHING (their ORG_TRACKERS subset excludes every board
    # captured — e.g. #domin8-b2b-sales on the Box-only catch-up). They're `ok`,
    # but they did NOT post, so they're tracked separately: a ✅ next to a channel
    # that received nothing reads as a lie, and "POSTED 10/10" would be one.
    noop_orgs: list = []
    # Which selected boards are actually PRESENT in the channels after this run —
    # unioned across every channel we didn't outright fail on. A tracker that
    # failed to CAPTURE this run isn't a real gap if a prior run already delivered
    # it (all channels then skip and report it in `present_ids`); it's only a gap
    # if it's genuinely absent from a channel.
    present_everywhere: set = set()
    present_seen = False
    for org in orgs:
        label = sp.ORG_LABEL[org]
        # Cross-workspace org (e.g. trang -> FRESH SUCCESS): its channel lives in
        # a non-AO Slack workspace, so post with that workspace's own bot token
        # instead of the default AO 'Lucy' token. slack_post posts via
        # smp._client(), which reads SLACK_USER_TOKEN first — set it here for this
        # org, restore after so the next org uses its own. Same routing
        # office_metrics.runner uses. [[project_trang_fresh_success]]
        _saved_tok, _routed = os.environ.get("SLACK_USER_TOKEN"), False
        try:
            from automations.office_metrics.offices import CROSS_WS_TOKEN_FILES
            _tok_file = CROSS_WS_TOKEN_FILES.get(org)
        except Exception:                             # noqa: BLE001
            _tok_file = None
        _missing_tok = ""
        if _tok_file:
            _tok_path = Path.home() / ".config" / "recruiting-report" / _tok_file
            if _tok_path.exists():
                os.environ["SLACK_USER_TOKEN"] = _tok_path.read_text(
                    encoding="utf-8-sig").strip()
                _routed = True
            else:
                _missing_tok = _cross_ws_token_missing(org, label, _tok_file)
        if _missing_tok:
            # DON'T fall through to the AO token. It cannot see a channel in
            # another workspace, so the run would go pull every board, try to
            # read the day's thread, get channel_not_found, and report
            # "#freshsuccess-all-leaders (channel unreadable)" — which reads as a
            # membership problem in OUR workspace and is why that same alert came
            # back on 8/19 and 8/23 with nobody able to act on it. Skip SOFT
            # (nothing posted, re-runnable) and name the actual missing file.
            print(f"⚠ [{org}] SKIPPED — {_missing_tok}", flush=True)
            result = {"ok": False, "no_op": False,
                      "channels": [{"channel": label, "ok": False, "soft": True,
                                    "error": _missing_tok}]}
        else:
            try:
                result = sp.post_all(captures, post_pages, today,
                                     replace=args.replace, org=org,
                                     new_thread=args.new_thread,
                                     note=args.header_note or auto_note,
                                     updated=args.updated)
            except Exception as e:                    # noqa: BLE001
                result = {"ok": False, "channels": [],
                          "error": f"{type(e).__name__}: {str(e)[:120]}"}
            finally:
                if _routed:                           # restore AO token for next org
                    if _saved_tok is None:
                        os.environ.pop("SLACK_USER_TOKEN", None)
                    else:
                        os.environ["SLACK_USER_TOKEN"] = _saved_tok
        for c in result.get("channels", []):
            if c.get("skipped"):
                print(f"↷ [{org}] {c['channel']} already had today's images — "
                      f"left alone", flush=True)
            elif c.get("ok"):
                rm = c.get("removed") or 0
                print(f"✓ [{org}] posted {len(c.get('posted', []))} image(s) to "
                      f"{c['channel']} thread {c.get('thread_ts')}"
                      + (f", replaced {rm} old" if rm else ""), flush=True)
            elif c.get("soft"):
                # lucy's action id uses underscores; report_id is the hyphenated
                # manifest id, so translate rather than hardcode a second name.
                _lucy_id = report_id.replace("-", "_")
                _late = " --late-only" if args.late_only else ""
                print(f"⚠ [{org}] {c['channel']} SKIPPED — {c.get('error')}. "
                      f"Re-run once the channel reads again: "
                      f"lucy rerun {_lucy_id}{_late} --orgs {org}", flush=True)
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
        if result.get("no_op"):
            noop_orgs.append(org)
            print(f"↷ [{org}] no board in this run belongs to {label} — nothing "
                  f"owed, nothing posted", flush=True)
        # THREE outcomes, not two. An org whose only misses are SOFT (a channel we
        # couldn't read, so we posted nothing rather than duplicate) is neither a
        # success nor a hard failure: it's INCOMPLETE. Hard-failing it would take
        # the exit code — and every other org's clean post — down with it.
        _chans = result.get("channels", [])
        _soft_miss = [c for c in _chans if not c.get("ok") and c.get("soft")]
        _hard_miss = [c for c in _chans if not c.get("ok") and not c.get("soft")]
        if result.get("ok"):
            posted_ok.append(org)
        elif _soft_miss and not _hard_miss and not result.get("error"):
            posted_soft.append(org)
        else:
            posted_bad.append(org)
        status_rows.append({
            "org": org, "label": label, "ok": bool(result.get("ok")),
            "no_op": bool(result.get("no_op")),
            "soft": org in posted_soft,
            "channels": [{"channel": c.get("channel"), "ok": bool(c.get("ok")),
                          "soft": bool(c.get("soft")),
                          "thread_ts": c.get("thread_ts"),
                          "error": c.get("error")}
                         for c in result.get("channels", [])],
            "error": result.get("error"),
        })
    # Boards deliberately omitted this run because their source wasn't in yet
    # (an email tracker's .xlsx hasn't landed) — recorded by TITLE so the card and
    # the run summary can name exactly what's missing, not just a count.
    omitted_boards = [(pages_mod.by_id(i) or {}).get("title") or i for i in gated_out]
    _write_status(out_dir, status_rows, today, status_file, omitted=omitted_boards)

    # Count only the orgs this run actually OWED a post — a no-op org is neither a
    # success nor a failure, so it's out of both the numerator and denominator and
    # gets its own ↷ marker rather than a ✅ it didn't earn.
    n_noop = len(noop_orgs)
    print(f"\n=== POSTED: {len(posted_ok) - n_noop}/{len(orgs) - n_noop} org(s)"
          + (f" ({n_noop} not owed this run)" if n_noop else ""), flush=True)
    for org in orgs:
        if org in noop_orgs:
            mark, why = "↷", " (nothing owed)"
        elif org in posted_ok:
            mark, why = "✅", ""
        elif org in posted_soft:
            mark, why = "⚠", " (channel unreadable — nothing posted, re-runnable)"
        else:
            mark, why = "❌", ""
        print(f"  {mark} {sp.ORG_LABEL[org]}{why}", flush=True)

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
    # A board OMITTED because its source wasn't in yet is NOT a failure (the run
    # succeeded at everything it could) — it does NOT flip `ok` or the exit code,
    # so it never pages. But it MUST be visible: the note names it and the count,
    # so "posted 7 of 8 — VZ+FTR source not in yet" surfaces in the run summary /
    # Hub detail instead of a silent "all 8".
    # Count against the boards the morning run is PERMANENTLY responsible for —
    # `p.get("late")`, not pages_mod.is_late(), which also counts boards held for
    # a stale extract today. Using is_late() here would shrink the denominator to
    # match what we posted and print a clean "7 of 7" over a board we deliberately
    # held: exactly the silent pass that let 7/29's stale thread go out.
    total_morning = len([p for p in pages_mod.PAGES if not p.get("late")])
    held_titles = [(pages_mod.by_id(i) or {}).get("title") or i for i in held]
    # A held board makes the run INCOMPLETE, never FAILED: ok=False + exit 0 is
    # the soft path (Hub flags it, reconcile can self-heal, no 4:31am page), and
    # the data really is missing from today's thread until the catch-up posts it.
    # A SOFT channel miss counts exactly like a held board: ok=False (Hub flags it
    # orange, section_drop_alert fires from write_manifest) but exit 0 below.
    ok = ((not missing_trackers) and not posted_bad and not posted_soft
          and not held)
    parts = ([sp.ORG_LABEL[o] for o in posted_bad]
             + [f"{sp.ORG_LABEL[o]} (channel unreadable)" for o in posted_soft]
             + [f"tracker:{f}" for f in missing_trackers]
             + [f"stale:{i}" for i in held])
    # A channel miss re-posts exactly the missed channels; a lone capture gap
    # re-captures just that tracker (self-heals a transient Tableau flake; a board
    # whose SOURCE isn't in yet — e.g. an email tracker — stays flagged, softly).
    if posted_bad or posted_soft:
        # --replace only where something may have half-landed (a hard miss). A
        # soft-missed channel got NOTHING, and --replace would just start with the
        # very read that failed — plain find-or-create is both correct and cheaper.
        retry_args = (["--late-only"] if args.late_only else []) + \
                     ["--orgs", ",".join(posted_bad + posted_soft)] + \
                     (["--replace"] if posted_bad else [])
    elif missing_trackers:
        # --late-only and --only are mutually exclusive (a late run already selects
        # exactly the late trackers), so re-run the late catch-up as-is; a normal
        # run re-captures just the missing tracker(s).
        retry_args = (["--late-only"] if args.late_only
                      else ["--only", ",".join(missing_trackers)])
    else:
        retry_args = []
    # The omitted clause renders even on an ok=True run (a clean run that simply
    # couldn't include an email board whose source wasn't in yet) — that's the
    # whole point: say what actually posted.
    soft_errs = "; ".join(
        f"{sp.ORG_LABEL[o]}: " + (next(
            (c.get("error") for r in status_rows if r["org"] == o
             for c in r["channels"] if c.get("soft")), "read failed"))
        for o in posted_soft)
    note = "; ".join(filter(None, [
        f"{len(posted_bad)} channel(s) missed: "
        f"{', '.join(sp.ORG_LABEL[o] for o in posted_bad)}" if posted_bad else "",
        f"{len(posted_soft)} channel(s) SKIPPED — couldn't read what's already "
        f"posted there, so nothing was posted (no duplicate thread): "
        f"{soft_errs}. Everything else posted; re-run scoped to that org once "
        f"the channel reads again" if posted_soft else "",
        f"{len(missing_trackers)} tracker(s) missing from the thread: "
        f"{', '.join(missing_trackers)}" if missing_trackers else "",
        f"posted {total_morning - len(gated_out)} of {total_morning} boards — "
        f"{', '.join(omitted_boards)} omitted (source .xlsx not in yet; reposts "
        f"once it lands)" if gated_out else "",
        f"{len(held)} board(s) HELD — Tableau extract not refreshed: "
        + "; ".join(f"{t} ({held[i]})" for i, t in zip(held, held_titles))
        + " — listed in the header as still coming, posted by the ~7am catch-up"
        if held else "",
    ]))
    run_manifest.write_manifest(
        report_id, ok=bool(ok), failed=parts, kind="channel",
        # No-op orgs are excluded: the Hub's checklist should say a channel
        # RECEIVED the boards, and one that was owed nothing didn't.
        succeeded=[sp.ORG_LABEL[o] for o in posted_ok if o not in noop_orgs],
        retry_args=retry_args,
        note=note, dry_run=args.dry_run)

    # Carlos 2026-08-09: mirror the B2B AT&T / B2B Box boards to their iMessage
    # groups, right after they land in Slack. Off unless --text-trackers is passed.
    if args.text_trackers:
        captured_ids = {spec["id"] for spec, _ in captures}
        posted_somewhere = (len(posted_ok) - n_noop) > 0
        _queue_tracker_texts(captured_ids, posted_somewhere, dry_run=False)

    # EXIT CODE — hard failure ONLY when a channel genuinely failed to post (a
    # real "some org didn't get images" error): the orchestrator treats non-zero
    # as FAILED and fires the immediate failure email, so that path must mean a
    # human is actually needed. A capture GAP is NOT hard-failed here: exit 0 lets
    # the manifest flow through reconcile, which marks it soft INCOMPLETE (Hub
    # checklist + a bounded self-heal retry), instead of a hard 4:31am page for a
    # single board — while "everything already posted, nothing to re-post" stays a
    # clean exit 0. (A total capture failure still returns 1 above.)
    #
    # A SOFT channel miss is likewise exit 0 (2026-08-13): the channel's dedup read
    # failed, so we posted nothing there to avoid duplicating today's thread — but
    # every other org DID get its images. Exiting 1 would (a) page as if the whole
    # run broke, and (b) make the orchestrator retry all ~15 orgs three times over
    # one unreadable channel. The manifest carries ok=False + the loud alert +
    # a scoped retry, which is the right amount of noise for "14 of 15 landed".
    if posted_bad:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
