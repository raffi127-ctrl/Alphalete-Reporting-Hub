"""Applicant Push session-wedge alarm (Lucy 2).

Covers EVERY office the push works (Carlos 11580, Atef 23467 — see
automations/applicant_push/offices.py). Each office writes its own daily log
`applicant-push[-<office>]-<date>.log`, all of which this scans; the alert names
the office the signature actually came from, read off that log's filename, so
nobody clears Cloudflare on the wrong office.

WHY: when an office's Cloudflare clearance goes stale, BOTH the primary sender
(resume_pushing extractor) AND the OAT leftovers processing freeze at once — new
Indeed applications pile into the "Process Emails" queue and nobody is told, so it
silently climbs (Megan watched it reach 90). The automated browser can't clear
that Cloudflare itself; it needs a one-time headed clear on the mini. The whole
point of this watcher is to catch the wedge the moment it happens so it gets
cleared in minutes instead of stacking for a day.

HOW: runs cheaply (piggybacked on the OAT 5-min wrapper) — it only READS logs and
posts Slack, so it works even while the AppStream session is wedged. It scans the
newest resume_pushing + oat_processing logs for the wedge signature and, on a
fresh wedge, posts ONE alert to the corrections channel. Debounced: one alert per
episode, re-pinged at most every RE_ALERT_HOURS; the alert self-clears (posts an
"all clear") when a healthy run is seen again.

Run on the mini:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.session_wedge_watch
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
LOG_DIR = REPO_ROOT / "output" / "logs"
STATE = REPO_ROOT / "output" / ".oat_session_wedge_state"
# #claudecorrections-and-requests, the same id every other alert uses
# (incident_thread.CHANNEL). This USED to come only from the sidecar cache below,
# which is gitignored and was never written on Lucy 2 — so from the day it shipped
# this alarm printed "NO CHANNEL — would post:" and went nowhere. On 2026-08-26 it
# did that 252 times in one day while the batch stage sat wedged (Megan). A siren
# nobody can hear is worse than no siren: it reads as quiet.
CHANNEL = "C0BK5PRG259"
# Still honoured when present, so a machine that resolves the channel by name (the
# orchestrator's notify.py writes this sidecar) can override the constant.
CHANNEL_CACHE = REPO_ROOT / "output" / ".corrections_channel_id"
# One thread per wedge episode, the convention this channel runs on: repeats reply
# under the open post instead of adding a near-identical message, and the ✅ goes on
# automatically when a healthy walk is seen.
# Per-office, so Carlos wedging and Atef wedging are two separate threads (and
# one clearing does not ✅ the other). 11580 keeps the ORIGINAL key so an
# episode already open on the day this ships is still found and closed.
INCIDENT_KEY = "failure-oat-session-wedge"


def _incident_key(office: str) -> str:
    return INCIDENT_KEY if office == "11580" else "%s-%s" % (INCIDENT_KEY, office)


def _state_path(office: str):
    return STATE if office == "11580" else pathlib.Path(str(STATE) + "-" + office)

# Only consider logs touched in the last window — an old stalled run isn't a live
# wedge. Long enough to span the 5-min OAT cadence + a resume_pushing cycle.
LOOKBACK_MIN = 90
# Don't re-ping more than this often while a wedge stays open.
RE_ALERT_HOURS = 3

# The exact signatures both reports already log when the office-11580 session is
# wedged on Cloudflare (see resume_pushing.run.ExtractionStalled + oat open_oat).
# HARD: only ever printed when the session really is frozen. These stand on their
# own — if one shows up, the run is stuck no matter what else the log says.
HARD_WEDGE_SIGS = [
    "stale cloudflare clearance on office",
    "extractor stalled",
]
# WEAK: a real failure, but not necessarily a frozen session. Only counts when
# NOTHING in the recent logs shows work getting done.
WEAK_WEDGE_SIGS = [
    "no rqst token in url",         # oat couldn't even direct-nav to the queue
]

# NOT SIGNATURES AT ALL — two lines that were on this list and should never have
# been. Both print during ORDINARY operation, so they made the alarm cry wolf:
#
#   "no next-pager control found"  run.py:321 says it outright — "treating as end
#       of queue". Every walk that reaches the last applicant logs it. The 8/26 log
#       had 252 of them next to 74 "✅ SENT to AI" lines.
#   "menu click miss N/3"          run.py:103 — one attempt of a 3-attempt retry.
#       A miss that succeeds on the next attempt still logs it.
#
# Gating them behind "only if nothing looks healthy" was NOT enough, and this is
# the lesson: on a quiet evening the queue is empty, so there are no sends to look
# healthy WITH — the pager line prints, nothing counters it, and the alarm fires.
# It did exactly that on 2026-08-26 and paged the channel with "both pipelines are
# stalled" while the flow was fine. A signature that appears on a healthy run is
# not a signature. Do not re-add these.
# Kept as the union for any caller that imported the old name.
WEDGE_SIGS = HARD_WEDGE_SIGS + WEAK_WEDGE_SIGS
# Signs a recent run processed cleanly (used to CLOSE an open wedge episode).
HEALTHY_SIGS = [
    "✅ sent to ai",
    "sent via overwrite",
    "ready for extraction at start: 0",
    re.compile(r"fill-nophone-from-tab: sent [1-9]"),
    re.compile(r"extract.*cycle.*→.*drop"),
]

# Which logs to scan (bare-name substrings under output/logs). Includes the merged
# applicant-push log (Resume Pushing + OAT combined) so the wedge signature is
# caught whether the office-11580 push runs as the two old agents or the unified one.
LOG_PATTERNS = ("oat-processing-", "oat_processing", "resume-pushing-",
                "resume_pushing", "applicant-push-", "applicant_push")


def _recent_logs() -> list[pathlib.Path]:
    if not LOG_DIR.exists():
        return []
    cutoff = dt.datetime.now().timestamp() - LOOKBACK_MIN * 60
    out = []
    for p in LOG_DIR.iterdir():
        if not p.is_file():
            continue
        if not any(pat in p.name for pat in LOG_PATTERNS):
            continue
        try:
            if p.stat().st_mtime >= cutoff:
                out.append(p)
        except OSError:
            continue
    return out


def _tail(p: pathlib.Path, n: int = 400) -> str:
    """The last n lines, lowercased, MINUS this watcher's own output.

    The watcher runs from the same wrapper that writes this log, and it prints its
    verdict INTO it: `[wedge-watch] state=wedged evidence='no next-pager control
    found'`. That line contains the very signature it matches on, so once the alarm
    fired it kept re-detecting its own echo — the wedge could never clear, because
    the evidence was a line the watcher wrote itself. Drop those lines before
    matching and it only ever judges what the REPORT logged."""
    try:
        lines = p.read_text(errors="ignore").splitlines()[-n:]
    except OSError:
        return ""
    return "\n".join(l for l in lines if "[wedge-watch]" not in l).lower()


def _match(text: str, sigs) -> str | None:
    for s in sigs:
        if isinstance(s, str):
            if s in text:
                return s
        else:  # compiled regex
            m = s.search(text)
            if m:
                return m.group(0)
    return None


def assess() -> tuple[str, str, str]:
    """Return (state, evidence, source_log). state ∈ {'wedged','healthy','quiet'}."""
    logs = _recent_logs()
    if not logs:
        return "quiet", "", ""
    hard_hit = ("", "")
    weak_hit = ("", "")
    healthy_hit = ("", "")
    for p in sorted(logs, key=lambda x: x.stat().st_mtime, reverse=True):
        text = _tail(p)
        hard = _match(text, HARD_WEDGE_SIGS)
        if hard and not hard_hit[0]:
            hard_hit = (hard, p.name)
        weak = _match(text, WEAK_WEDGE_SIGS)
        if weak and not weak_hit[0]:
            weak_hit = (weak, p.name)
        h = _match(text, HEALTHY_SIGS)
        if h and not healthy_hit[0]:
            healthy_hit = (h, p.name)
    # A hard signature is authoritative — the session is frozen even if an older
    # line in the same tail shows a send that landed before it froze.
    if hard_hit[0]:
        return "wedged", hard_hit[0], hard_hit[1]
    # Work is visibly getting done, so whatever the weak signature meant, it isn't
    # "nothing can run". Healthy WINS over weak — this is the check that keeps the
    # alarm off a normal day (see WEAK_WEDGE_SIGS).
    if healthy_hit[0]:
        return "healthy", healthy_hit[0], healthy_hit[1]
    if weak_hit[0]:
        return "wedged", weak_hit[0], weak_hit[1]
    return "quiet", "", ""


def _office_of(log_name: str) -> str:
    """Which office a log belongs to, from its filename. The per-office logs are
    `applicant-push-<office>-<date>.log`; the unsuffixed `applicant-push-<date>.log`
    (and the two retired single-office logs) are Carlos's 11580."""
    # The office segment is followed by the DATE, so anchor on the date — without
    # it, `applicant-push-2026-08-26.log` (Carlos's, no office segment) matched the
    # YEAR and blamed a wedge on "office 2026".
    m = re.search(r"applicant[-_]push-(\d{4,6})-\d{4}-\d{2}-\d{2}", log_name or "")
    return m.group(1) if m else "11580"


def _office_label(office: str) -> str:
    try:
        from automations.applicant_push import offices
        o = offices.OFFICES.get(office)
        if o:
            return "office %s (%s)" % (o["office_id"], o["owner"])
    except Exception:  # noqa: BLE001
        pass
    return "office %s" % office


def _load_state(office: str = "11580") -> dict:
    try:
        return json.loads(_state_path(office).read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save_state(d: dict, office: str = "11580") -> None:
    try:
        _state_path(office).write_text(json.dumps(d))
    except OSError:
        pass


def _channel() -> str:
    """The sidecar wins when a machine has resolved the channel by name; otherwise
    the constant. Never empty — an unresolvable channel used to silence the alarm."""
    try:
        cached = CHANNEL_CACHE.read_text().strip()
        if cached:
            return cached
    except OSError:
        pass
    return CHANNEL


def _post(title: str, body_lines: list[str], dry_run: bool,
          office: str = "11580", key: str | None = None,
          channel_line: str | None = None) -> bool:
    """Open (or follow up in) the wedge incident thread in #claudecorrections.

    Channel gets ONE emoji-free line, the detail goes in the thread — the standing
    format for this channel (Megan 2026-08-18); incident_thread does that split.
    Falls back to a plain threaded post if the incident helper is unavailable, so a
    wedge is never swallowed just because the thread bookkeeping failed."""
    text = "\n".join([title] + body_lines)
    if dry_run:
        print(f"[wedge-watch] DRY-RUN — would post to {_channel()}:\n{text}\n")
        return True
    ch = _channel()
    try:
        from automations.shared.slack_metrics_post import _client
        client = _client()
    except Exception as e:  # noqa: BLE001
        print(f"[wedge-watch] no Slack client: {type(e).__name__}: {e}")
        return False
    try:
        from automations.shared import incident_thread as _inc
        posted = _inc.open_or_followup(
            key=key or _incident_key(office), title=title, body=body_lines,
            channel_line=channel_line or (
                "*Applicant Push* — %s session wedged on Lucy 2"
                % _office_label(office)),
            channel=ch, client=client)
        if posted:
            return True
        print("[wedge-watch] incident thread declined — posting standalone")
    except Exception as e:  # noqa: BLE001
        print(f"[wedge-watch] incident thread unavailable "
              f"({type(e).__name__}: {str(e)[:80]}) — posting standalone")
    try:
        client.chat_postMessage(channel=ch, text=text,
                                unfurl_links=False, unfurl_media=False)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[wedge-watch] post failed: {type(e).__name__}: {e}")
        return False


def run(dry_run: bool = False, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now()
    state, evidence, source = assess()
    # The alert has to name the office that ACTUALLY wedged — the fix is "clear
    # Cloudflare on office N by hand", and sending someone to the wrong office
    # is worse than no alert. The source log's filename is the office.
    office = _office_of(source)
    label = _office_label(office)
    print(f"[wedge-watch] state={state} evidence={evidence!r} source={source} "
          f"office={office}")
    st = _load_state(office)

    if state == "wedged":
        last = st.get("alerted_at")
        recent = False
        if last:
            try:
                recent = (now - dt.datetime.fromisoformat(last)).total_seconds() < RE_ALERT_HOURS * 3600
            except ValueError:
                recent = False
        if recent:
            print("[wedge-watch] wedge still open, alerted recently — no re-ping")
            return 0
        title = (":rotating_light: *%s session wedged — Lucy 2*"
                 % (label[:1].upper() + label[1:]))
        body = [
            "Cloudflare clearance went stale, so the automated browser is frozen "
            "on %s — *both* pipelines are stalled:" % label,
            "• *Resume Pushing* extractor — applications not getting auto-sent",
            "• *OAT 'One App at a time'* leftovers — not draining",
            "New Indeed apps keep arriving, so the Process Emails queue is climbing.",
            f"_signature:_ `{evidence}`  ({source})",
            "",
            "*Fix (~1 min, one-time):* on the mini, open AppStream for %s "
            "in a headed window and clear the 'verify you are human' box once. "
            "Both reports resume and drain on their own." % label,
            "_This alarm auto-clears once a healthy run is seen._",
        ]
        if _post(title, body, dry_run, office=office):
            st["alerted_at"] = now.isoformat()
            st["episode_evidence"] = evidence
            _save_state(st, office)
            print("[wedge-watch] ALERT posted")
        return 0

    if state == "healthy":
        if st.get("alerted_at"):
            # Close the THREAD — ✅ on the parent and the marker flipped to
            # `resolved` — rather than posting a loose all-clear the channel has
            # to match up with the alert by eye. ensure_closed asks the CHANNEL,
            # not this machine's incident index, and — the part that actually
            # bit us — a close it cannot complete is NOT paved over with a
            # message. On 2026-08-26 the 18:21 episode was closed by hand from a
            # laptop, so Lucy 2's index still said open at 19:12; resolve()
            # correctly found the thread already closed and returned False, and
            # the old fallback below turned that False into a fresh post. It
            # went out through _post(), which stamps the WEDGE headline and an
            # `open` marker on whatever it is handed — so the all-clear opened a
            # brand-new incident reading "office 11580 session wedged" with
            # "session recovered" 246ms under it and no ✅ on either. Megan: "if
            # this corrected it should have a green check."
            closed = False
            try:
                from automations.shared import incident_thread as _inc
                closed = _inc.ensure_closed(
                    _incident_key(office),
                    what="*Applicant Push* — the %s session" % label,
                    detail="A healthy walk just processed cleanly; the queue is "
                           "draining again.",
                    channel=_channel(), dry_run=dry_run)
            except Exception as e:  # noqa: BLE001
                print(f"[wedge-watch] couldn't close the thread "
                      f"({type(e).__name__}: {str(e)[:80]})")
            # NO FALLBACK POST HERE, ON PURPOSE. The old one replied "session
            # recovered" with no ✅ and no marker flip, which reads as fixed to a
            # person and as still-open to every machine — worse than silence,
            # because it also hid the failure. Losing one all-clear is cheap: we
            # run again in five minutes. So on failure we KEEP the episode and
            # retry, and only forget it once the thread really is closed.
            if not closed:
                print("[wedge-watch] couldn't close the incident thread — "
                      "keeping the episode open, retrying next pass")
                return 0
            print("[wedge-watch] episode closed (✅ on the incident thread)")
            if dry_run:
                return 0
        _save_state({}, office)
        return 0

    # quiet: no recent activity to judge — leave any open episode as-is.
    print("[wedge-watch] no recent Applicant Push activity — nothing to assess")
    return 0


# ---------------------------------------------------------------------------
# Indeed's resume check (Megan, 2026-09-22: "whenever that issue recurs I need
# alerted in the slack channel to clear it")
# ---------------------------------------------------------------------------
# A SECOND, narrower alarm. The wedge alarm above watches the AppStream session;
# this one watches the one gate a machine genuinely cannot open by itself —
# Indeed's "Verify you are human" box on the resume viewer. It clears itself most
# of the time, so the walk waits it out (_CF_FIRST_READ_POLLS); when it doesn't,
# every resume read in that tick is walled and the walk logs ONE line saying so.
#
# Why it needs its own alarm: on 2026-09-22 the AppStream session was perfectly
# healthy all day — sends, removes, re-texts all working — while every office on
# two machines filled ZERO phone numbers, because only the Indeed reads were
# blocked. The wedge watcher looked at that day and correctly said "healthy", so
# nobody was told, and ~150 applicants a day landed on the manual to-do list
# saying "need a number" when the number was on the resume all along.
CF_WALL_SIG = "cloudflare wall"
# A fill proves the gate is open again — the all-clear for this alarm.
CF_OPEN_SIGS = ("resume phone ", "attachment phone ")
# One walled tick is normal (the check is random); this many in the window is a
# machine that is not getting in on its own and wants a human to tick the box.
CF_WALL_TICKS = 3
CF_WALL_WINDOW_MIN = 30
CF_INCIDENT_KEY = "failure-indeed-resume-check"


def _cf_incident_key(office: str) -> str:
    return "%s-%s" % (CF_INCIDENT_KEY, office)


def _cf_state_path(office: str):
    return pathlib.Path(str(STATE) + "-cf-" + office)


def _machine() -> str:
    try:
        from automations.shared.hub_identity import machine_name
        return machine_name()
    except Exception:  # noqa: BLE001
        import socket
        return socket.gethostname()


def assess_resume_check(now: dt.datetime | None = None) -> dict:
    """Per office: how many recent ticks were walled by Indeed's check, and whether
    any number has been read since. Returns {office: (walls, fills, log_name)}."""
    now = now or dt.datetime.now()
    cutoff = now.timestamp() - CF_WALL_WINDOW_MIN * 60
    out: dict = {}
    for p in _recent_logs():
        try:
            if p.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        office = _office_of(p.name)
        text = _tail(p, n=1200)
        walls = text.count(CF_WALL_SIG)
        fills = sum(text.count(s) for s in CF_OPEN_SIGS)
        if walls or fills:
            w, f, _ = out.get(office, (0, 0, p.name))
            out[office] = (w + walls, f + fills, p.name)
    return out


def run_resume_check(dry_run: bool = False, now: dt.datetime | None = None) -> int:
    """ONE alert per MACHINE when Indeed's check is shutting the resume reads out,
    and ✅ as soon as numbers are being read again.

    Per OFFICE was wrong (2026-09-22 -> 23): the check goes stubborn across a whole
    machine at once, so Megan woke up to five near-identical tickets naming five
    offices and one fix. The offices belong in ONE ticket, as a list.
    """
    now = now or dt.datetime.now()
    seen = assess_resume_check(now)
    if not seen:
        return 0
    machine = _machine()
    blocked = sorted(o for o, (w, f, _s) in seen.items()
                     if f == 0 and w >= CF_WALL_TICKS)
    reading = sorted(o for o, (_w, f, _s) in seen.items() if f)
    for office, (walls, fills, source) in sorted(seen.items()):
        print(f"[cf-watch] {_office_label(office)}: walled_ticks={walls} "
              f"numbers_read={fills} ({source})")

    path = _cf_state_path(machine.replace(" ", "_"))
    try:
        st = json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        st = {}

    if not blocked:
        if st.get("alerted_at"):
            try:
                from automations.shared import incident_thread as _inc
                closed = _inc.ensure_closed(
                    _cf_incident_key(machine.replace(" ", "_")),
                    what="*Applicant Push* — Indeed's resume check on %s" % machine,
                    detail="Numbers are being read off resumes again on %s; "
                           "nothing to clear." % (", ".join(reading) or machine),
                    channel=_channel(), dry_run=dry_run)
            except Exception as e:  # noqa: BLE001
                print(f"[cf-watch] couldn't close the thread "
                      f"({type(e).__name__}: {str(e)[:80]})")
                closed = False
            if closed and not dry_run:
                path.write_text("{}")
                print("[cf-watch] episode closed (✅)")
        return 0

    last = st.get("alerted_at")
    if last:
        try:
            if (now - dt.datetime.fromisoformat(last)).total_seconds() \
                    < RE_ALERT_HOURS * 3600:
                print("[cf-watch] still blocked, alerted recently — no re-ping")
                return 0
        except ValueError:
            pass

    names = ", ".join("%s (%s)" % (o, seen[o][0]) for o in blocked)
    title = (":rotating_light: *Indeed is asking to verify a human — %s*" % machine)
    body = [
        "Indeed's *\u201cVerify you are human\u201d* box is not clearing by itself "
        "on %s, so the walk opens a resume and gets the check instead of the "
        "number." % machine,
        "*Offices shut out* (walled ticks): %s" % names,
        ("*Still reading numbers:* %s" % ", ".join(reading)) if reading
        else "*No office on this machine is reading numbers right now.*",
        "Nobody is written off — these applicants stay in the queue and the walk "
        "keeps trying; it gets in by itself a good share of the time.",
        "",
        "*If you want them now (~1 min, on %s):* run this, tick the box once in "
        "the window that opens, and it drains that office's queue in the same "
        "window." % machine,
        "```cd ~/recruiting-report && PYTHONPATH=. .venv/bin/python -m "
        "automations.oat_processing.cf_clear_window --all```",
        "",
        "_Auto-clears here as soon as a number is read again._",
    ]
    if _post(title, body, dry_run, office=blocked[0],
             key=_cf_incident_key(machine.replace(" ", "_")),
             channel_line="*Applicant Push* — Indeed is asking to verify a human "
                          "on %s; %d office(s) are not reading numbers"
                          % (machine, len(blocked))):
        if not dry_run:
            path.write_text(json.dumps(
                {"alerted_at": now.isoformat(), "offices": blocked}))
        print("[cf-watch] ALERT posted")
    return 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Applicant Push session-wedge alarm")
    ap.add_argument("--dry-run", action="store_true",
                    help="assess + print the alert, post nothing")
    ap.add_argument("--resume-check-only", action="store_true",
                    help="only run the Indeed 'verify you are human' alarm")
    args = ap.parse_args(argv)
    rc = 0 if args.resume_check_only else run(dry_run=args.dry_run)
    rc2 = run_resume_check(dry_run=args.dry_run)
    return rc or rc2


if __name__ == "__main__":
    import sys
    sys.exit(main())
