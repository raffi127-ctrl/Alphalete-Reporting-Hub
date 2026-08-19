"""Daily refresh of the Recruiting Funnel Board.

Pulls AppStream's "Retention - Details (new)" (p=783) for every tracked manager
and rewrites the five Funnel Board tabs.

WHAT IT REFRESHES (Carlos's restatement rule, 2026-08-07)
--------------------------------------------------------
Managers backfill late — Monday's numbers routinely change on Tuesday — so this
never pulls "yesterday only". Every run re-pulls the ENTIRE current Mon-Sun week
and overwrites it. On Mondays it also re-pulls the PRIOR week one final time and
then leaves it alone forever. At most two weeks are ever in play.

WHERE HISTORY LIVES
-------------------
In the Daily Log tab, not in this repo. The run reads the existing log back,
replaces only the rows for the weeks it refreshed, and writes the whole thing
out again. That keeps a daily-changing data file out of git (Lucy 2 pulls with
--ff-only and a tracked data file would eventually conflict).

USAGE
    python -m automations.funnel_board.run                # live
    python -m automations.funnel_board.run --dry-run      # pull + report, no write
    python -m automations.funnel_board.run --weeks 4      # backfill N weeks
"""
import argparse
import atexit
import datetime as dt
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from automations.funnel_board import guard
from automations.funnel_board.roster import CAPTAINSHIP
from automations.funnel_board.auth import identity as _auth_identity
from automations.funnel_board.auth import session as _auth_session
from automations.shared.tableau_patchright import (
    appstream_direct_session, APPSTREAM_PROFILE_DIR,
)
from automations.recruiting_report import fetch_office
from automations.funnel_board.fetch import report_week

HERE = Path(__file__).resolve().parent
SSID = os.environ.get("FUNNEL_SSID", "1nOuJ5kGtEf25XIgKE-_iu8-tUHA8kZ6hyDaJnaJNmVo")
API = "https://sheets.googleapis.com/v4/spreadsheets/" + SSID
# Sheets credentials live in auth.py — shared with build.py, service account
# first. See the note there on why the personal token is only a fallback.

# name -> (office id, the owner string AppStream's switcher matches on)
OFFICES = [
    ("Atef Choudhury",    "23467", "Atef Choudhury"),
    ("Aya Al-Khafaji",    "22992", "Aya Al-Khafaji"),
    ("Carlos Hidalgo",    "11580", "CARLOS HIDALGO"),
    ("Cody Cannon",       "21151", "Cody Cannon"),
    ("Cyrus Wade",        "22815", "Cyrus Wade"),
    ("Dhyey Patel",       "22767", "Dhyey Patel"),
    ("Drew Tepper",       "22583", "Drew Tepper"),
    ("George Hipolito",   "11296", "George Hipolito"),
    ("Haytham Nagi",      "22524", "Haytham Nagi"),
    ("Isaiah Revelle",    "19717", "Isaiah Revelle"),
    ("Jackie LeRoy",      "22358", "Jackie LeRoy"),
    ("Jacob Dover",       "23607", "Jacob Dover"),
    ("Jamis Garay",       "19592", "Jamis Garay"),
    ("Jeff Starr",        "15031", "Jeffrey Starr"),
    ("Joey Ramirez",      "23206", "Joey Ramirez"),
    ("Joshua Murphy",     "21770", "Joshua Murphy"),
    ("Justin Wood",       "22192", "Justin Wood"),
    ("Kash Rai",          "22177", "Akashdeep Rai"),
    ("Khalil Mansour",    "11901", "KHALIL MANSOUR"),
    ("Kinsey Guenther",   "11906", "Kinsey Guenther"),
    ("Maxamad-Amin Aden", "23066", "Maxamad Aden"),
    ("Noah Dubale",       "23356", "Noah Dubale"),
    ("Rafael Hidalgo",    "11280", "Rafael Hidalgo"),
    ("Rashad Reed",       "23411", "Rashad Reed"),
    ("Roshan Amin",       "19833", "Roshan Amin Ahmad"),
    ("Ryan McSpadden",    "22820", "Ryan McSpadden"),
    ("Salik Mallick",     "21328", "Muhammad UI Haque"),
    ("Vincent Smith",     "23318", "Vincent Smith"),
]
# Carlos's captainship is a SECOND cut of the same report — see roster.py. Most
# of it lives outside the 17 offices above, so those people have to be pulled
# too or the Captainship Board is a grid of zeros. Anyone already on the org
# list is pulled once and shows up on both boards.
RESOLVED = HERE / "state" / "resolved_offices.json"
NEW_OFFICE_WEEKS = 4      # how far back to reach the first time an office appears


def _resolved():
    try:
        return json.loads(RESOLVED.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing or damaged just means "none yet"
        return {}


def _known():
    """Offices discovered on an earlier pass, {name: office id}."""
    return {k: v["office_id"] for k, v in _resolved().items() if v.get("office_id")}


def _needs_backfill():
    """Found, but no successful deep pull yet."""
    return {k for k, v in _resolved().items() if not v.get("backfilled")}


def _remember(name, oid, backfilled=False):
    cur = _resolved()
    cur[name] = {"office_id": oid, "backfilled": backfilled,
                 "found": cur.get(name, {}).get(
                     "found", dt.datetime.now().isoformat(timespec="seconds"))}
    RESOLVED.parent.mkdir(parents=True, exist_ok=True)
    RESOLVED.write_text(json.dumps(cur, indent=1), encoding="utf-8")


def to_pull(known):
    """Every office this run should visit, org list first, no duplicates."""
    todo = list(OFFICES)
    have = {n for n, _, _ in todo}
    for name, oid, owner in CAPTAINSHIP:
        oid = oid or known.get(name)
        if oid and name not in have:
            todo.append((name, oid, owner))
            have.add(name)
    return todo


def _norm(s):
    return " ".join("".join(c for c in s.lower() if c.isalpha() or c.isspace()).split())


def _same_person(a, b):
    """Timid on purpose: exact match, or same surname with one first name a
    prefix of the other.

    The switcher lists people under their legal name — Jeff/Jeffrey — so exact
    alone is too tight. Same-surname-plus-initial was the first cut and it is
    too loose: it makes Vincent Smith and Victor Smith the same person, and
    pulling the wrong office writes someone else's numbers under this name.
    """
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    pa, pb = a.split(), b.split()
    if len(pa) < 2 or len(pb) < 2 or pa[-1] != pb[-1]:
        return False
    fa, fb = pa[0], pb[0]
    short, long_ = sorted((fa, fb), key=len)
    return len(short) >= 3 and long_.startswith(short)


def discover(page, pending, log):
    """Has AppStream created an office for anyone still waiting for one?

    Four of the twelve are sales-only today and Carlos expects their offices to
    appear. Rather than have somebody remember to come back and edit roster.py,
    every pass with an unresolved name re-reads the office switcher and starts
    pulling the moment one shows up. If two offices could plausibly be the same
    person it resolves NEITHER and says so — pulling the wrong office would
    write somebody else's numbers under this person's name, which is worse than
    another hour of zeros.
    """
    try:
        from automations.recruiting_report.list_all_offices import scrape_offices
        offices = scrape_offices(page, verbose=False)
    except Exception as e:  # noqa: BLE001 — discovery must never fail the pull
        log("office discovery unavailable (%s: %s)" % (type(e).__name__, str(e)[:110]))
        return {}
    log("office switcher lists %d office(s); still waiting on %s"
        % (len(offices), ", ".join(n for n, _ in pending)))
    found = {}
    for name, owner in pending:
        ids = sorted({o.get("office_id") for o in offices
                      if o.get("office_id")
                      and (_same_person(o.get("owner", ""), name)
                           or _same_person(o.get("owner", ""), owner))})
        if len(ids) == 1:
            found[name] = ids[0]
        elif len(ids) > 1:
            log("%-20s could be any of %s — resolving none of them, say which"
                % (name, ", ".join(ids)))
    return found


def announce(msg, log, dry_run=False):
    """A new office turning up is worth a line in Slack; nobody reads a 3am log."""
    if dry_run or os.environ.get("FUNNEL_NO_SLACK"):
        log("(not posting) %s" % msg)
        return
    try:
        from automations.shared import slack_metrics_post as smp
        smp._client().chat_postMessage(channel=guard.SLACK_CHANNEL, text=msg)
    except Exception as e:  # noqa: BLE001
        log("Slack notice didn't post (%s: %s)" % (type(e).__name__, str(e)[:110]))


MEAS = ["applies", "sent", "removed", "processed", "retb", "b1", "s1", "b2",
        "s2", "off", "bob", "nss", "nsh"]
AUDIT = ["emails_rx", "scoop_rx", "file_rx", "manual",
         "sent_email", "scoop_s", "file_s", "rm_email", "rm_scoop"]


def log(m):
    print("%s  %s" % (dt.datetime.now().strftime("%H:%M:%S"), m), flush=True)


def _session():
    return _auth_session(verbose=True)


def read_daily_log(S):
    """Existing history, as {manager: {iso date: metrics}}."""
    # A FAILED READ IS NOT AN EMPTY LOG. This used to be
    #     rows = r.json().get("values", []) if r.status_code == 200 else []
    # so one 429 or 500 turned into "there is no history", and the run then
    # wrote ONLY the days it had just pulled — silently destroying everything
    # else. That is exactly what happened on 2026-08-20: 3,898 day-rows back to
    # December collapsed to 331, and nothing in the log said so. Retry, then
    # refuse to continue; a run that cannot read the log must not write it.
    rows = None
    for attempt in range(3):
        r = S.get(API + "/values/'Daily Log'!A1:U100000",
                  params={"valueRenderOption": "UNFORMATTED_VALUE"})
        if r.status_code == 200:
            rows = r.json().get("values", [])
            break
        log("read of Daily Log failed (HTTP %d), attempt %d/3" % (r.status_code, attempt + 1))
        time.sleep(5 * (attempt + 1))
    if rows is None:
        raise RuntimeError(
            "could not read the existing Daily Log after 3 attempts (last HTTP %d). "
            "Refusing to run: writing now would replace the whole history with "
            "just this run's days." % r.status_code)
    if not rows:
        return {}
    hdr, out = rows[0], {}
    # dates come back as serials; header order is fixed by build.py
    def col(name):
        return hdr.index(name) if name in hdr else None
    ci = {k: col(h) for k, h in zip(
        MEAS, ["Applies", "Sent to Call List", "Removed", "Processed", "Ret Booked",
               "1st Booked", "1st Showed", "2nd Booked", "2nd Showed",
               "Job Offered", "BOB", "NS Scheduled", "NS Showed"])}
    ai = {k: col(h) for k, h in zip(
        AUDIT, ["· Emails Received", "· Scooper In", "· File Import In", "· Manual Entry",
                "· Email Sent", "· Scooper Sent", "· File Sent",
                "· Removed (Email)", "· Removed (Scooper)"])}
    for row in rows[1:]:
        if len(row) < 5 or not isinstance(row[0], (int, float)):
            continue
        d = (dt.date(1899, 12, 30) + dt.timedelta(days=int(row[0]))).isoformat()
        who, office = row[2], str(row[3])
        v = {}
        for k, i in list(ci.items()) + list(ai.items()):
            v[k] = int(row[i]) if i is not None and i < len(row) and isinstance(row[i], (int, float)) else 0
        # The log stores TOTALS in the main columns and the components in the
        # audit columns; build.py re-derives the totals from the components. Only
        # trust a component when it is actually there — blindly taking it wiped
        # Removed to zero for every manager once, and each later run then re-read
        # that zero and wrote it back. If a component is missing or empty while
        # its total is not, back it out of the total instead.
        if ai["rm_email"] is None or (v["removed"] and not v["rm_email"]):
            v["rm_email"] = max(0, v["removed"] - v.get("rm_scoop", 0))
        if ai["sent_email"] is None or (v["sent"] and not v["sent_email"]):
            v["sent_email"] = max(0, v["sent"] - v.get("manual", 0)
                                  - v.get("scoop_s", 0) - v.get("file_s", 0))
        v["sent"] = v.pop("sent_email")
        v["removed"] = v.pop("rm_email")
        v["applies"] = (v.get("emails_rx", 0) + v.get("scoop_rx", 0)
                        + v.get("file_rx", 0) + v.get("manual", 0))
        out.setdefault(who, {"office_id": office, "days": {}})["days"][d] = v
    return out


def target_weeks(today):
    """Current Mon-Sun always; the prior week too, but only on a Monday."""
    monday = today - dt.timedelta(days=today.weekday())
    weeks = [monday]
    if today.weekday() == 0:
        weeks.insert(0, monday - dt.timedelta(days=7))
    return weeks


def pull(page, rqst, weeks, today):
    """Cover every target day, whatever weekday this office's report starts on."""
    days, fetched = {}, set()

    def grab(anchor):
        if anchor in fetched:
            return
        fetched.add(anchor)
        # verbose=True: the one-line "week ... ok" per report submission is the
        # only heartbeat a long backfill has — without it a timeout kill leaves
        # a log that can't say whether the run was slow or stuck (2026-08-20).
        days.update(report_week(page, rqst, anchor, verbose=True))

    got = {}
    for mon in weeks:
        want = [mon + dt.timedelta(days=i) for i in range(7)]
        grab(mon)
        for _ in range(3):
            missing = [d for d in want if d not in days and d <= today]
            if not missing:
                break
            grab(missing[0])
        for d in want:
            # Keep FUTURE days inside the target week. They are not padding:
            # "Total New Starts Scheduled" is filtered on the start date, so a
            # start booked today for Saturday lands on Saturday. Dropping them
            # hid Atef's whole week (all 5 of his starts are dated 8/15).
            if d in days:
                got[d.isoformat()] = days[d]
    return got


def switch(page, oid, hint, rqst):
    """Switch office by URL, not by driving the autocomplete.

    The old path typed the office id into #searchMC and clicked the match. On
    Lucy 2 only the FIRST keystroke registered, so typing "21328" filtered on
    "1" and offered 11296 / 11280 / 11906 — the office asked for was never in
    the list, which is why the same five offices failed every retry while the
    mini happened to get away with it.

    The switcher is really just a query parameter (`&newOfficeId=`), so ask for
    the office directly and confirm by reading it back off the page.
    """
    for attempt in range(3):
        try:
            page.goto("https://applicantstream.com/index.cfm?p=104&rqst=%s&newOfficeId=%s"
                      % (rqst, oid), timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(1800)
            who = page.evaluate(
                "() => (document.body.innerText.match(/Office ID: *(\\d+)/) || [])[1]")
            if who == oid:
                return True
            if attempt == 2:
                # say WHAT came back — an access refusal reads very differently
                # from a slow render, and we can't shell into Lucy 2 to look
                body = page.evaluate("() => (document.body.innerText||'')")
                body = " ".join(body.split())[:220]
                log("   %s: landed on %s | url=%s | body=%s"
                    % (oid, who or "?", page.url[-60:], body))
        except Exception as e:
            if attempt == 2:
                log("   %s: %s: %s" % (oid, type(e).__name__, str(e)[:120]))
        page.wait_for_timeout(1500)
    return False


# ---------------------------------------------------------------- run lock
# Two runs must never write the Daily Log at once. This is not hypothetical:
# a run launched 14s before an earlier one finished writing clobbered Jacob
# Dover's whole column (2026-08-10). At the old once-a-day cadence that took a
# human mistake; at hourly it would happen on its own the first time a run ran
# long, so the lock is a precondition of the hourly agent, not a nicety.
#
# mkdir is atomic on every platform (the repo has to run on Windows too), so no
# fcntl. A lock older than STALE_MIN is assumed to be a crashed run and broken —
# otherwise one hard kill would wedge the report until someone noticed.
LOCK = HERE / "state" / "run.lock"
STALE_MIN = 90


def acquire_lock():
    """True if we own the lock. False means another run holds it — skip, don't queue."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        LOCK.mkdir()
    except FileExistsError:
        try:
            age = (dt.datetime.now().timestamp() - LOCK.stat().st_mtime) / 60.0
        except OSError:
            age = 0.0
        if age < STALE_MIN:
            who = ""
            try:
                who = " (" + (LOCK / "owner").read_text().strip() + ")"
            except OSError:
                pass
            log("another run holds the lock%s, %.0f min old — skipping this pass" % (who, age))
            return False
        log("breaking a stale lock (%.0f min old, limit %d)" % (age, STALE_MIN))
        release_lock()
        try:
            LOCK.mkdir()
        except OSError:
            log("could not take the lock after breaking it — skipping")
            return False
    try:
        (LOCK / "owner").write_text("pid %d on %s at %s"
                                    % (os.getpid(), socket.gethostname(),
                                       dt.datetime.now().isoformat(timespec="seconds")))
    except OSError:
        pass
    return True


def release_lock():
    try:
        for f in LOCK.iterdir():
            f.unlink()
    except OSError:
        pass
    try:
        LOCK.rmdir()
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="pull and report, write nothing")
    ap.add_argument("--weeks", type=int, default=0, help="backfill this many weeks instead")
    ap.add_argument("--today", help="override today (YYYY-MM-DD), for testing")
    ap.add_argument("--only", help="pipe-separated manager names, e.g. 'Rafael Hidalgo|Kash Rai'")
    ap.add_argument("--account", choices=("primary", "alt"), default="primary",
                    help="which AppStream login to use. 'alt' is the second "
                         "account set by set_appstream_alt_creds — needed where "
                         "the primary cannot see every office (Lucy 2 runs as "
                         "CarlosNLR, which is denied 6 of the 28).")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="permit a write that has fewer day-rows than the sheet already holds")
    a = ap.parse_args()

    # --dry-run writes nothing, so it never needs the lock and must never block
    # a real run (or be blocked by one).
    holding = False
    if not a.dry_run:
        if not acquire_lock():
            # SAY SO. This used to `return 0` in silence, which is
            # indistinguishable from a clean run: on 2026-08-20 a killed backfill
            # left the lock behind and six consecutive batches "succeeded" while
            # doing nothing at all. A skip is a non-event, not a success.
            try:
                age = (dt.datetime.now().timestamp() - LOCK.stat().st_mtime) / 60.0
                extra = " (held %.0f min; auto-breaks at %d)" % (age, STALE_MIN)
            except OSError:
                extra = ""
            log("SKIPPED — another run holds %s%s. Nothing was pulled or written."
                % (LOCK, extra))
            return 0
        holding = True
        atexit.register(release_lock)

    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    if a.weeks:
        monday = today - dt.timedelta(days=today.weekday())
        weeks = [monday - dt.timedelta(days=7 * i) for i in range(a.weeks - 1, -1, -1)]
    else:
        weeks = target_weeks(today)
    log("target weeks: %s%s" % (", ".join(str(w) for w in weeks),
                                "  (Monday — closing out last week)" if today.weekday() == 0
                                and not a.weeks else ""))

    S = _session()
    history = read_daily_log(S)
    log("existing log: %d manager(s), %d day-rows"
        % (len(history), sum(len(v["days"]) for v in history.values())))

    # Did anything edit the Daily Log since this report last wrote it? Read-only,
    # and never fatal — a hand backfill is legitimate and the week gets re-pulled
    # and overwritten regardless. It just shouldn't happen silently.
    drift = guard.check(S, API, log)
    if drift:
        guard.ping(drift, log, dry_run=a.dry_run)
    else:
        # Clean — close an open drift thread so the channel says when the
        # hand-editing STOPPED, not only when it started (Eve 2026-08-14).
        guard.resolved(log, dry_run=a.dry_run)

    fresh, failed = {}, []
    # headless=True trips a Cloudflare re-challenge on the rcaptain login;
    # every successful pull has been headed. Lucy 2 runs with a display.
    #
    # OWN PROFILE (2026-08-10). Lucy 2 dropped the SAME five offices on every
    # single run since it went on the scheduler — 19717, 23607, 22177, 23411,
    # 21328 — while Lucy 1 pulled 14/14. Not a timeout: the page body came back
    # "This Office is not assigned to you!", and Eve confirmed by hand that
    # rcaptain DOES have all five. So the run wasn't rcaptain.
    #
    # force_form_login=True is not enough on its own: it only skips the
    # storage_state reuse. The session then loads applicantstream.com and types
    # the login form ONLY IF a password field is there. A persistent profile
    # still holding someone else's live session renders logged-in, no form
    # appears, and the whole pull proceeds silently as that other account.
    # A profile of our own starts empty, so the rcaptain form login actually
    # runs. verbose=True so the log says which path it took — the silent reuse
    # is exactly what made this cost a day to find.
    # --account alt logs in as the SECOND AppStream login (set_appstream_alt_creds)
    # on its own profile, so the two accounts' cookies never mix. Needed where the
    # primary cannot see every office: Lucy 2 runs as CarlosNLR, which is denied 6
    # of the 28, while rcaptain reaches all of them.
    _sess = dict(headless=False, verbose=True, force_form_login=True,
                 profile_dir=(APPSTREAM_PROFILE_DIR.parent
                              / ".appstream_profile_funnel"))
    if getattr(a, "account", "primary") == "alt":
        from automations.shared import creds as _creds
        if not _creds.has_appstream_alt():
            log("--account alt asked for, but no alternate AppStream login is "
                "configured on this machine. Set one with the mini-control action "
                "set_appstream_alt_creds. Refusing to fall back to the primary, "
                "which would silently pull as the wrong account.")
            return 1
        _sess.update(username=_creds.appstream_alt_username(),
                     password=_creds.appstream_alt_password(),
                     profile_dir=(APPSTREAM_PROFILE_DIR.parent
                                  / ".appstream_profile_funnel_alt"))
        log("AppStream account: ALT (%s)" % _creds.appstream_alt_username())
    with appstream_direct_session(**_sess) as page:
        rqst = re.search(r"rqst=([A-Za-z0-9-]+)", page.url).group(1)
        def attempt(todo, wks=None):
            still = []
            for name, oid, hint in todo:
                try:
                    # Say the office is STARTING, not just finished. A --weeks 34
                    # backfill of a slow office can grind for the better part of
                    # an hour, and with no line here a timeout kill reads as a
                    # hang at "only: ..." with no trace of progress (2026-08-20).
                    log("-> %s (office %s)…" % (name, oid))
                    if not switch(page, oid, hint, rqst):
                        raise RuntimeError("office switch failed after retries")
                    days = pull(page, rqst, wks or weeks, today)
                    if not days:
                        raise RuntimeError("no days returned")
                    fresh[name] = {"office_id": oid, "days": days}
                    log("%-20s %d day(s)" % (name, len(days)))
                except Exception as e:
                    still.append((name, oid, hint))
                    log("%-20s failed: %s: %s" % (name, type(e).__name__, e))
            return still

        # Lucy 2 is slower and busier than the mini — her first live dry run
        # dropped 5 of 14 offices where the mini dropped none. Sweep the
        # stragglers again rather than letting a transient render timeout cost a
        # day's numbers for that manager.
        # Anyone from the captainship whose office has appeared since the last
        # pass joins this run — and gets NEW_OFFICE_WEEKS of history rather than
        # just today, so their Trend opens with a shape instead of one column.
        known = _known()
        just_found = {}
        pending = [(n, own) for n, oid, own in CAPTAINSHIP
                   if not oid and n not in known]
        if pending and not a.only:
            just_found = discover(page, pending, log)
            for name, oid in just_found.items():
                known[name] = oid
                if not a.dry_run:
                    _remember(name, oid)
                log("%-20s office %s appeared in AppStream — pulling from now on"
                    % (name, oid))
            if just_found:
                announce("🆕 *Recruiting Funnel Board* — AppStream now has an "
                         "office for %s. Pulling %d week(s) of history now; "
                         "they were sitting at zero on the Captainship Board."
                         % (", ".join("%s (%s)" % (n, o)
                                      for n, o in just_found.items()),
                            NEW_OFFICE_WEEKS),
                         log, dry_run=a.dry_run)

        todo = to_pull(known)
        if a.only:
            names = set(a.only.split("|"))
            todo = [o for o in todo if o[0] in names]
            log("only: %s" % ", ".join(n for n, _, _ in todo))
        log("pulling %d office(s): %d org, %d captainship-only"
            % (len(todo), len(OFFICES), len(todo) - len(OFFICES)))
        # A newly-appeared office is worth reaching back for, and it stays on
        # that list until a pull for it actually SUCCEEDS — otherwise one failed
        # first attempt would quietly cost it its history for good.
        deep = {n for n in set(just_found) | _needs_backfill()
                if n in {t[0] for t in todo}}
        left = attempt([o for o in todo if o[0] not in deep])
        if deep:
            mon = today - dt.timedelta(days=today.weekday())
            back = [mon - dt.timedelta(days=7 * i)
                    for i in range(NEW_OFFICE_WEEKS - 1, -1, -1)]
            log("reaching back %d weeks for %s" % (NEW_OFFICE_WEEKS,
                                                   ", ".join(sorted(deep))))
            left += attempt([o for o in todo if o[0] in deep], back)
            for name in deep:
                if name in fresh and not a.dry_run:
                    _remember(name, fresh[name]["office_id"], backfilled=True)
        for round_no in (2, 3):
            if not left:
                break
            log("retry pass %d for %d office(s): %s"
                % (round_no, len(left), ", ".join(n for n, _, _ in left)))
            left = attempt(left)
        failed = [n for n, _, _ in left]

    if not fresh:
        log("nothing pulled — leaving the sheet untouched")
        return 1

    # merge: refreshed days overwrite, everything else is left alone
    merged = {k: {"office_id": v["office_id"], "days": dict(v["days"])}
              for k, v in history.items()}
    for name, o in fresh.items():
        merged.setdefault(name, {"office_id": o["office_id"], "days": {}})
        merged[name]["office_id"] = o["office_id"]
        merged[name]["days"].update(o["days"])

    # Belt and braces to the read guard above: whatever the cause, a merge that
    # comes out SMALLER than what was already in the sheet means history is
    # being dropped, and the write must not go ahead unsupervised.
    had = sum(len(v["days"]) for v in history.values())
    now_have = sum(len(v["days"]) for v in merged.values())
    if now_have < had and not a.allow_shrink:
        raise RuntimeError(
            "refusing to write: the merged log has %d day-rows but the sheet already "
            "had %d (%d managers -> %d). History would be lost. Investigate, then "
            "re-run with --allow-shrink if the shrink is genuinely intended."
            % (now_have, had, len(history), len(merged)))

    alld = sorted({d for v in merged.values() for d in v["days"]})
    log("merged: %d manager(s), %d day-rows, %s .. %s"
        % (len(merged), sum(len(v["days"]) for v in merged.values()),
           alld[0] if alld else "-", alld[-1] if alld else "-"))
    if failed:
        log("!! %d office(s) failed and kept their previous numbers: %s"
            % (len(failed), ", ".join(failed)))

    if a.dry_run:
        log("dry run — not writing")
        return 0

    all_weeks = sorted({dt.date.fromisoformat(d) - dt.timedelta(days=dt.date.fromisoformat(d).weekday())
                        for d in alld})
    payload = {"weeks": [str(w) for w in all_weeks], "offices": merged, "errors": {}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        tmp = fh.name
    env = dict(os.environ, FUNNEL_DATA=tmp, FUNNEL_SSID=SSID)
    rc = subprocess.call([sys.executable, "-W", "ignore",
                          str(HERE / "build.py")], env=env)
    os.unlink(tmp)
    log("build exited %d" % rc)
    if rc == 0:
        # Stamp AFTER the write — build.py wipes the tab and rewrites it, so a
        # stamp put down any earlier wouldn't survive the run that set it.
        guard.stamp(S, API, _auth_identity(), log)
    return rc or (1 if failed else 0)


if __name__ == "__main__":
    raise SystemExit(main())
