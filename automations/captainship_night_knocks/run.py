"""The night send itself — one tick, whatever that tick owes.

    python -m automations.captainship_night_knocks.run --tick            # dry
    python -m automations.captainship_night_knocks.run --tick --send --sample
    python -m automations.captainship_night_knocks.run --notice-test --sample

WHAT A TICK IS. The agent wakes every 5 minutes and asks `schedule.due()` what
is owed right now; ~170 of the ~175 nightly passes have nothing and exit in a
second. The times are NOT in the plist — they are 9 PM in each office's own
zone, which is a moment no calendar-based launchd entry can express. Same shape
as knocks_intraday, and for the same reason.

WHAT IT SENDS. Per wave: the captainship's DAILY KNOCKS SUMMARY board, then one
DAILY TOTAL KNOCKS board per ICD in that wave — the same boards the captainship
report's daily section carries, drawn by the same functions
(`knock_dispo_images`), so the night mail can never disagree with the morning
one. The first wave of a night opens the thread; later waves reply into it.

WHY IT RUNS ON LUCY 3. It impersonates ICDs in ownerville, which needs a live
session, and the captainship gate + the intraday boards already live there.
That last part is also the one collision worth knowing about: the 9 PM eod
slot of `knocks_intraday` fires on the SAME instant on the SAME machine. The
guard below skips a tick while that job is running and picks the wave up on a
later pass, which is why `schedule.GRACE_MIN` is an hour and not fifteen
minutes — a wave that goes out at 9:20 is late, a wave that never goes out is
a bug.

THE SAMPLE WEEKEND (Eve, 2026-09-11). The first run of this is unattended, over
a weekend, off zones a scraper harvested on the Friday night. Three things make
that safe, and all three are load-bearing:

  · `--sample` pins the recipients to Raf and Eve (mail.SAMPLE_RECIPIENTS) and
    raises rather than mail anybody else. No ICD, no captain, no distro.
  · `--sample` is also the only mode that trusts `zones.enable_harvested()`.
    `--live` refuses to, so a zone nobody confirmed can never decide when a
    real captainship gets its board.
  · If ANYTHING fails — no zones, no session, no rows, SMTP down — the same
    two people get a plain message at 00:45 Central saying why nothing arrived
    (`--notice`, run off the same tick). Eve's explicit ask: never leave them
    wondering whether it was sent and lost.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — Windows console, best effort
    pass

from automations.captainship_night_knocks import (
    ingest, mail, schedule as S, state as ST, zones as Z,
)

CT = ZoneInfo("America/Chicago")

# The captainship the sample runs for. Raf asked for his own
# ("can we start this process for my captainship?", #l10-alphalete 2026-09-11).
SAMPLE_CAPTAIN = "rafael"

OUT_DIR = Path("output") / "night_knocks"
# Our OWN Chrome profile: one browser per profile dir, and this runs in the
# same evening as the intraday boards and the captainship gate.
PROFILE_DIR = (Path(__file__).resolve().parents[1] / "uploaded" / "_shared"
               / ".browser_profile_night_knocks")

# Jobs that hold the machine's ownerville session. A tick that lands while one
# of these is running steps aside and tries again on the next pass.
BUSY_PATTERNS = ("automations.knocks_intraday.run",
                 "automations.captainship_drafts.run",
                 # The address harvest holds the session for ~45 minutes and it
                 # is the thing this whole module is waiting on — a wave that
                 # elbows into it costs the zones every later night needs.
                 "automations.captainship_night_knocks.harvest_zones")

# THE FIRST NIGHT THE SAMPLE MAY GO OUT. The harvest that places Raf's offices
# runs the night of Friday 2026-09-11 at 10 PM Central; before it lands, only
# two of his thirteen ICDs have a zone at all, and a first email showing two
# offices would read as a broken report rather than an unfinished one. So the
# sample starts on the Saturday, with the zones in. Live mode has no such gate.
SAMPLE_FIRST_NIGHT = dt.date(2026, 9, 12)

# THE HARVEST THIS MODULE IS WAITING ON — and why the AGENT owns it rather
# than a person's terminal. The address harvest was first queued by hand from
# Eve's Windows box, which meant the whole weekend depended on that window
# staying open until 10 PM. It does not any more: after 10 PM Central, a tick
# that finds no harvest on disk runs it itself, stands aside for whatever else
# holds the session, and tries again on a later tick. That also makes it a
# RETRY — a harvest that dies at 10 PM Friday is re-attempted Saturday night
# instead of leaving the sample with no zones and nobody awake to notice.
#
# 10 PM: the 9 PM boards (knocks_intraday, same machine) are done by then and
# the 4 AM wave is six hours away.
HARVEST_HOUR = 22

# WHEN THE FAILURE NOTICE GOES OUT: 00:45 Central, about the night that just
# ended. Late enough that the last wave a night can have (9 PM Pacific = 11 PM
# Central, plus the hour of grace) has either gone out or failed; early enough
# that the two people who asked for it read it with the morning.
NOTICE_HOUR, NOTICE_MIN = 0, 45


# ---------------------------------------------------------------------------
# rosters
# ---------------------------------------------------------------------------

def _roster_cache(night: dt.date) -> Path:
    return OUT_DIR / ("roster_%s.json" % night.isoformat())


def rosters_for(captain_keys: Sequence[str], *, night: Optional[dt.date] = None,
                logfn=print) -> Dict[str, List[str]]:
    """{captain_key: [ICD, …]} off the Org Sales Board — the Sheet is truth.

    Shares `harvest_zones.captain_rosters`, so the people we mail about are
    exactly the people the harvest went looking for.

    CACHED FOR THE NIGHT, and that is not an optimisation, it is a quota rule.
    This is called from a job that wakes every 5 minutes; reading the board on
    every tick would be ~60 Sheets reads across one evening's waves, on top of
    everything else the machine does. §1 of the captainship report has already
    been killed once by that quota (2026-08-23). A captainship roster does not
    change between 8 PM and midnight, so the first tick of a night reads it and
    the rest read the file — and a read that fails falls back to the cache
    rather than cancelling the night.
    """
    from automations.captainship_night_knocks import harvest_zones as HZ
    night = night or dt.datetime.now(dt.timezone.utc).astimezone(CT).date()
    cache = _roster_cache(night)
    try:
        import json
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if all(k in cached for k in captain_keys):
            return {k: list(v) for k, v in cached.items()}
    except Exception:  # noqa: BLE001 — first tick of the night
        cached = {}

    out: Dict[str, List[str]] = {}
    for key in captain_keys:
        try:
            got = HZ.captain_rosters(key)
        except Exception as exc:  # noqa: BLE001
            logfn("[night-knocks] roster lookup failed for %s (%s: %s)"
                  % (key, type(exc).__name__, exc))
            if key in (cached or {}):
                logfn("[night-knocks] using tonight's cached roster for %s" % key)
                out[key] = list(cached[key])
            continue
        out.update({k: list(v) for k, v in (got or {}).items()})
    if out:
        try:
            import json
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out, indent=2, sort_keys=True),
                             encoding="utf-8")
        except Exception:  # noqa: BLE001 — a cache that won't write is not a failure
            pass
    return out


def any_zone_in_window(now_utc: dt.datetime) -> bool:
    """Could ANY wave be owed right now? Pure clock arithmetic, no Sheet.

    The gate in front of everything else: ~170 of a night's ~288 ticks are
    outside every zone's window, and those must cost nothing at all — no Sheets
    read, no log line, no file. See rosters_for for why that matters.
    """
    return any(S._zone_is_due(z, now_utc) for z in Z.ZONE_LABEL)


def captain_display(key: str) -> str:
    """'Raf's Captainship' — what the subject line calls this captainship."""
    try:
        from automations.captainship_drafts import config
        for cap in config.CAPTAINS:
            if cap.key == key:
                name = getattr(cap, "name", None) or key.title()
                return "%s's Captainship" % ("Raf" if key == "rafael" else name)
    except Exception:  # noqa: BLE001 — a display name is not worth a failure
        pass
    return "%s's Captainship" % key.title()


# ---------------------------------------------------------------------------
# capture
# ---------------------------------------------------------------------------

def _busy() -> Optional[str]:
    """The ownerville-holding job running right now, or None. macOS/Linux only;
    on Windows there is no such job to collide with (nothing schedules there)."""
    import subprocess
    for pat in BUSY_PATTERNS:
        try:
            hit = subprocess.run(["pgrep", "-f", pat], capture_output=True,
                                 timeout=20)
        except Exception:  # noqa: BLE001 — no pgrep (Windows): nothing to guard
            return None
        if hit.returncode == 0 and (hit.stdout or b"").strip():
            return pat
    return None


def capture(due: S.Due, *, logfn=print) -> Tuple[List[Tuple[str, Optional[Path]]],
                                                 List[str]]:
    """(boards, notes) for one wave — summary board first, then one per ICD.

    Every board is drawn by `knock_dispo_images`, the captainship report's own
    daily section, so this mail and that report can never disagree about a
    number. An ICD that raises costs its own board and nothing else: the wave
    still goes out, with the reason in `notes`, because a captain reading four
    of five offices is better served than one reading none.
    """
    from automations.captainship_drafts import knock_dispo_images as KD
    from automations.focus_office_att.aliases import load_aliases
    from automations.shared.tableau_patchright import ownerville_session
    from automations.total_knocks import render as knocks_render

    root = OUT_DIR / due.local_date.isoformat() / due.captain_key
    boards: List[Tuple[str, Optional[Path]]] = []
    notes: List[str] = []
    captured: List[Tuple[str, dict, list, Optional[int]]] = []

    aliases_raw = load_aliases()
    pairs = KD.owner_cfgs(list(due.icds), aliases_raw)

    with ownerville_session(verbose=True, profile_dir=PROFILE_DIR) as page:
        for display, cfg in pairs:
            try:
                rows = KD._daily_rows_for_owner(page, cfg, aliases_raw,
                                                due.local_date)
            except Exception as exc:  # noqa: BLE001 — one ICD ≠ the wave
                logfn("[night-knocks]   x %s: %s: %s"
                      % (display, type(exc).__name__, str(exc)[:160]))
                boards.append((display, None))
                notes.append("%s — board unavailable (%s)"
                             % (display, type(exc).__name__))
                continue
            if not rows:
                # Visible absence, never a blank board (standing rule).
                logfn("[night-knocks]   · %s: no knocks recorded" % display)
                boards.append((display, None))
                continue
            # apps=None on purpose: the Total Apps column comes off a Tableau
            # crosstab the morning build downloads, and a night send is not
            # worth waking that pipeline. The knock columns are the ask.
            board_rows, apps_by_rep, apps_n = KD.daily_apps_for_board(rows, None)
            png = knocks_render.render_total_knocks(
                due.local_date, rows=board_rows,
                out_dir=root / KD._slug(display),
                title_suffix=display, title_prefix="DAILY ",
                apps=apps_by_rep)
            boards.append((display, png))
            captured.append((display, cfg, rows, apps_n))
            logfn("[night-knocks]   ✓ %s: %d rep(s) → %s"
                  % (display, len(rows), png.name))

    if captured:
        try:
            summary = KD.render_daily_summary(
                captured, due.local_date, root / "summary",
                roster_n=len(due.icds), n_covered=len(captured))
            boards.insert(0, ("Daily Summary — %s %d"
                              % (due.local_date.strftime("%b"),
                                 due.local_date.day), summary))
        except Exception as exc:  # noqa: BLE001 — summary ≠ the wave
            logfn("[night-knocks]   x summary: %s: %s"
                  % (type(exc).__name__, str(exc)[:160]))
            notes.append("summary board unavailable (%s)" % type(exc).__name__)
    return boards, notes


def maybe_harvest(now_utc: dt.datetime, *, run_it: bool = True,
                  logfn=print) -> bool:
    """Run the address harvest if it has never landed. True if it ran.

    Deliberately ONE attempt per tick and none at all once the file exists:
    ~44 impersonations single-file is a 45-minute job, and the wrapper's own
    guard keeps a second tick from starting while it runs.
    """
    if ingest.IN_JSON.exists():
        return False
    local = now_utc.astimezone(CT)
    if not (HARVEST_HOUR <= local.hour < 23):
        return False
    busy = _busy()
    if busy:
        logfn("[night-knocks] harvest owed but %s is running — later tick" % busy)
        return False
    if not run_it:
        logfn("[night-knocks] harvest owed (no %s yet)" % ingest.IN_JSON)
        return False
    import subprocess
    logfn("[night-knocks] no addresses on disk — running the harvest now "
          "(~45 min, read-only)")
    cmd = [sys.executable, "-u", "-m",
           "automations.captainship_night_knocks.harvest_zones"]
    try:
        proc = subprocess.run(cmd, timeout=75 * 60, capture_output=True,
                              text=True)
    except Exception as exc:  # noqa: BLE001 — a dead harvest is not a dead tick
        logfn("[night-knocks] harvest failed to start: %s: %s"
              % (type(exc).__name__, str(exc)[:200]))
        return False
    tail = "\n".join((proc.stdout or "").splitlines()[-25:])
    logfn("[night-knocks] harvest rc=%d\n%s" % (proc.returncode, tail))
    if proc.returncode == 0:
        ingest.run(logfn=logfn)
    return True


# ---------------------------------------------------------------------------
# one tick
# ---------------------------------------------------------------------------

def footer_lines(icds: Sequence[str], *, sample: bool) -> List[str]:
    """What the reader needs to know about the zones this wave trusted.

    Every ICD placed by the harvest rather than by a person is named here. That
    is the difference between "this is where the office is" and "this is where
    a page said the office is", and on Monday it is the list somebody walks.
    """
    out: List[str] = []
    harvested = [i for i in icds if Z.provenance(i) == "harvested"]
    if harvested:
        out.append("Timezone read automatically (not yet confirmed by a "
                   "person): " + ", ".join(sorted(harvested)) + ".")
    if sample:
        out.append("SAMPLE — this went to Raf and Eve only. No captainship "
                   "and no ICD received it.")
    return out


def tick(now_utc: dt.datetime, *, send: bool, sample: bool,
         captain_keys: Sequence[str], plan: bool = False, logfn=print) -> int:
    """Send whatever is owed at `now_utc`. Returns the number of waves sent.

    `plan=True` stops before the browser: it says what is owed and to whom and
    opens nothing. That mode exists for EVE'S WINDOWS BOX, where a dry run is
    not harmless — opening ownerville there steals the session out from under
    the Lucy machines (the one-session rule). A rehearsal that touches the
    browser belongs on Lucy 3, with --tick and no --send.
    """
    if not (plan or any_zone_in_window(now_utc)):
        return 0          # the quiet 170 ticks: nothing owed, nothing touched

    if plan:
        # THE CREDENTIAL CHECK BELONGS IN THE REHEARSAL, not in the 9 PM wave.
        # This job was built on Eve's Windows box and installed on Lucy 3, and
        # the Gmail app password is a per-machine file — a machine without it
        # builds every board correctly and then fails on the last line, at 9
        # PM, with nobody watching. Never prints the secret: present or not.
        try:
            from automations.scheduled_6_days_out.email_send import app_password
            app_password()
            logfn("[night-knocks] SMTP credential: present on this machine")
        except Exception as exc:  # noqa: BLE001
            logfn("[night-knocks] SMTP credential: MISSING (%s) — this machine "
                  "cannot mail anything" % type(exc).__name__)

    if sample:
        # Fold in whatever the harvest left on disk BEFORE looking at zones.
        # The harvest runs at 10 PM on a Friday and nobody is at a keyboard to
        # paste its output, so the tick that needs those zones is the tick that
        # loads them. Cheap and idempotent: it rewrites one small JSON.
        try:
            ingest.run(logfn=lambda *_a, **_k: None)
        except Exception as exc:  # noqa: BLE001 — no harvest is a state
            logfn("[night-knocks] ingest skipped (%s)" % type(exc).__name__)
        n = Z.enable_harvested()
        logfn("[night-knocks] harvested zones: %d ICD(s) from %s"
              % (n, Z.harvested_source()))

    rosters = rosters_for(captain_keys, logfn=logfn)
    if not rosters:
        logfn("[night-knocks] no roster — nothing can be scheduled")
        return 0

    for key, icds in sorted(rosters.items()):
        missing = Z.unconfirmed(icds)
        logfn("[night-knocks] %s: %d ICD(s), %d placed, %d with no zone"
              % (key, len(icds), len(icds) - len(missing), len(missing)))
        if missing:
            logfn("[night-knocks]   no zone (left out): " + ", ".join(missing))

    # `done` is per night, and a night is a local date — read the state of
    # every date any wave could belong to, not just the runner's today.
    today_ct = now_utc.astimezone(CT).date()
    nights = {today_ct, today_ct - dt.timedelta(days=1)}
    done = set()
    for night in nights:
        done |= ST.markers(ST.load(night))

    owed = S.due(now_utc, rosters, done=done)
    if not owed:
        return 0

    busy = None if plan else _busy()
    if busy:
        logfn("[night-knocks] %d wave(s) owed but %s is running — standing by "
              "for the next tick (grace is %d min)"
              % (len(owed), busy, S.GRACE_MIN))
        return 0

    sent = 0
    for d in owed:
        if sample and d.local_date < SAMPLE_FIRST_NIGHT:
            logfn("[night-knocks] %s wave for %s skipped — the sample starts %s"
                  % (d.label, d.local_date, SAMPLE_FIRST_NIGHT))
            continue
        data = ST.load(d.local_date)
        subject_base = mail.subject_for(captain_display(d.captain_key),
                                        d.local_date, sample=sample)
        thread = mail.Thread.from_json(ST.thread_for(data, d.captain_key),
                                       subject_base)
        first = thread.message_id is None
        logfn("[night-knocks] %s / %s wave / %s — %d ICD(s)%s"
              % (d.captain_key, d.label, d.local_date, len(d.icds),
                 "" if first else " (reply into tonight's thread)"))
        if plan:
            logfn("[night-knocks] PLAN — would mail %r to %s; ICDs: %s"
                  % (thread.subject_for_next(),
                     ", ".join(mail.SAMPLE_RECIPIENTS if sample
                               else recipients_for(d.captain_key)),
                     ", ".join(d.icds)))
            continue
        try:
            boards, notes = capture(d, logfn=logfn)
        except Exception as exc:  # noqa: BLE001 — a dead session ≠ a silent night
            reason = "%s: %s" % (type(exc).__name__, str(exc)[:400])
            logfn("[night-knocks] ✗ capture failed: " + reason)
            logfn(traceback.format_exc()[-1200:])
            ST.save(d.local_date, ST.record_failure(
                data, captain_key=d.captain_key, label=d.label, reason=reason))
            continue

        to_addrs = mail.assert_allowed(
            mail.SAMPLE_RECIPIENTS if sample else recipients_for(d.captain_key),
            sample=sample)
        msg = mail.build(subject=thread.subject_for_next(), label=d.label,
                         icds=d.icds, fire_local=d.fire_local, boards=boards,
                         notes=notes, footer=footer_lines(d.icds, sample=sample),
                         first=first, to_addrs=to_addrs,
                         extra_headers=thread.headers_for_next())
        if not send:
            logfn("[night-knocks] DRY-RUN — would send %r to %s (%d board(s))"
                  % (msg["Subject"], ", ".join(to_addrs), len(boards)))
            continue
        try:
            mid = mail.send(msg, to_addrs, logfn=logfn)
        except Exception as exc:  # noqa: BLE001
            reason = "%s: %s" % (type(exc).__name__, str(exc)[:400])
            logfn("[night-knocks] ✗ send failed: " + reason)
            ST.save(d.local_date, ST.record_failure(
                data, captain_key=d.captain_key, label=d.label, reason=reason))
            continue
        thread.remember(mid)
        ST.save(d.local_date, ST.record_sent(data, d.marker, mid,
                                             d.captain_key, thread.to_json()))
        sent += 1
    return sent


def recipients_for(captain_key: str) -> List[str]:
    """A LIVE send's recipients. Deliberately the captainship report's own
    distro (config.Captain.to) rather than a second list nobody maintains —
    and deliberately unused until somebody passes --live."""
    from automations.captainship_drafts import config
    for cap in config.CAPTAINS:
        if cap.key == captain_key:
            return list(getattr(cap, "to", []) or [])
    return []


# ---------------------------------------------------------------------------
# the failure notice
# ---------------------------------------------------------------------------

def notice_due(now_utc: dt.datetime) -> Optional[dt.date]:
    """The night this tick should report on, or None.

    Fires in the window that starts at 00:45 Central and lasts an hour, about
    YESTERDAY — the knocking night that just ended. Sunday nights are not
    reported: nobody knocks, so nothing was owed (schedule.WORKING_WEEKDAYS).
    """
    local = now_utc.astimezone(CT)
    start = local.replace(hour=NOTICE_HOUR, minute=NOTICE_MIN, second=0,
                          microsecond=0)
    if not (start <= local < start + dt.timedelta(hours=1)):
        return None
    night = local.date() - dt.timedelta(days=1)
    if night.weekday() not in S.WORKING_WEEKDAYS:
        return None
    # Nothing was owed before the sample's first night, so there is nothing to
    # explain either — a notice then would be a false alarm.
    return night if night >= SAMPLE_FIRST_NIGHT else None


def notice_html(night: dt.date, data: dict, rosters: Dict[str, List[str]],
                *, sample: bool) -> str:
    """Why nothing (or not everything) arrived. Written for a reader who was
    not watching: what was supposed to happen, what did, and what to do."""
    sent = data.get("sent") or {}
    fails = ST.failures(data)
    bits: List[str] = []
    bits.append("<p><b>Nightly knocking sheet — %s</b></p>"
                % night.strftime("%a %m/%d"))
    if sent:
        bits.append("<p>%d wave(s) did go out: %s.</p>"
                    % (len(sent), ", ".join(sorted(sent))))
    else:
        bits.append("<p>No email went out for this night. Here is why.</p>")

    for key, icds in sorted(rosters.items()):
        missing = Z.unconfirmed(icds)
        bits.append(
            "<p style='margin:6px 0'><b>%s</b>: %d office(s), %d with a known "
            "timezone, %d without.%s</p>"
            % (captain_display(key), len(icds), len(icds) - len(missing),
               len(missing),
               ("<br><span style='color:#777'>No timezone, so left out of "
                "every wave: %s</span>" % ", ".join(missing)) if missing else ""))
    if not rosters:
        bits.append("<p style='color:#b00'>The captainship roster could not be "
                    "read from the Org Sales Board, so no wave could even be "
                    "scheduled.</p>")

    if fails:
        bits.append("<p><b>What failed</b></p><ul>")
        for f in fails:
            bits.append("<li>%s — %s wave: %s</li>"
                        % (f.get("captain"), f.get("wave"), f.get("reason")))
        bits.append("</ul>")
    elif not sent:
        bits.append("<p>Nothing raised an error — the schedule simply had "
                    "nothing to send, which means no office in the captainship "
                    "had a confirmed timezone (or the harvest never ran).</p>")

    bits.append("<p style='color:#777;font-size:12px'>Sent automatically "
                "because the sample was expected tonight and %s. Next attempt: "
                "the next knocking night (Mon–Sat), same hours. State file: "
                "output/night_knocks/state_%s.json</p>"
                % ("some of it failed" if sent else "nothing arrived",
                   night.isoformat()))
    if sample:
        bits.append("<p style='color:#999;font-size:12px'>This is the sample "
                    "run — it reaches Raf and Eve only.</p>")
    return "".join(bits)


def notice(now_utc: dt.datetime, *, send: bool, sample: bool,
           captain_keys: Sequence[str], force_night: Optional[dt.date] = None,
           logfn=print) -> int:
    """Send the 'why it didn't arrive' mail, at most once per night."""
    night = force_night or notice_due(now_utc)
    if not night:
        return 0
    data = ST.load(night)
    if ST.notice_sent(data):
        return 0
    if sample:
        Z.enable_harvested()
    rosters = rosters_for(captain_keys, night=night, logfn=logfn)
    sent = data.get("sent") or {}
    fails = ST.failures(data)
    expected = len(captain_keys)
    if sent and not fails and len(ST.sent_captains(data)) >= expected:
        logfn("[night-knocks] %s: everything owed went out — no notice" % night)
        return 0

    # The notice ALWAYS goes to Raf and Eve, live or sample. It is not the
    # report — it is the answer to "did it go out?", and those two are who
    # asked the question (Eve, 2026-09-11).
    to_addrs = mail.assert_allowed(mail.SAMPLE_RECIPIENTS, sample=True)
    subject = ("%sDaily Knocks — nothing to send for %s"
               % (mail.SUBJECT_TAG if sample else "",
                  night.strftime("%a %m/%d"))) if not sent else (
        "%sDaily Knocks — partial for %s"
        % (mail.SUBJECT_TAG if sample else "", night.strftime("%a %m/%d")))
    html = notice_html(night, data, rosters, sample=sample)
    if not send:
        logfn("[night-knocks] DRY-RUN notice: %r -> %s"
              % (subject, ", ".join(to_addrs)))
        return 0
    mid = mail.send_plain(subject, html, to_addrs, logfn=logfn)
    ST.save(night, ST.record_notice(data, mid))
    return 1


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tick", action="store_true",
                    help="send whatever is owed right now")
    ap.add_argument("--send", action="store_true",
                    help="actually mail it (without this: dry-run)")
    ap.add_argument("--sample", action="store_true",
                    help="recipients pinned to Raf + Eve; trusts harvested zones")
    ap.add_argument("--live", action="store_true",
                    help="real distro (refuses harvested zones)")
    ap.add_argument("--captain", action="append",
                    help="captain key; repeatable (default: the sample captain)")
    ap.add_argument("--plan", action="store_true",
                    help="say what is owed and open nothing (safe on Windows)")
    ap.add_argument("--notice", action="store_true",
                    help="also run the failure notice for the night just ended")
    ap.add_argument("--notice-test", metavar="YYYY-MM-DD", nargs="?",
                    const="today", help="build the notice for that night now")
    args = ap.parse_args(argv)

    if args.live and args.sample:
        print("[night-knocks] --live and --sample are mutually exclusive")
        return 2
    sample = not args.live
    keys = args.captain or [SAMPLE_CAPTAIN]

    now_utc = dt.datetime.now(dt.timezone.utc)
    rc = 0
    if args.tick or args.plan:
        # Before anything else: if the addresses this whole module waits on are
        # still not on disk and it is late enough, go get them. See HARVEST_HOUR.
        maybe_harvest(now_utc, run_it=not args.plan)
    if args.tick or args.plan:
        n = tick(now_utc, send=args.send and not args.plan, sample=sample,
                 captain_keys=keys, plan=args.plan)
        if n:
            print("[night-knocks] tick: sent=%d" % n)
    if args.notice_test:
        night = (now_utc.astimezone(CT).date() if args.notice_test == "today"
                 else dt.date.fromisoformat(args.notice_test))
        notice(now_utc, send=args.send, sample=sample, captain_keys=keys,
               force_night=night)
    elif (args.tick and not args.plan) or args.notice:
        notice(now_utc, send=args.send, sample=sample, captain_keys=keys)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
