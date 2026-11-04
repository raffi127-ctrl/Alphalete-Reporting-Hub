"""Hourly resume-push report, posted per office into its recruiting-channel thread (2026-11-02; was a DM to Carlos) (Carlos, 2026-09-24:
"every hour report back to me on how much has been pushed for every and how
resumes are left in the 'one app at a time'" + "cant lucy report to me? even
if its through slack").

Sheets-API + Slack only — no browser, no AppStream login. Reads the per-office
'OAT Walk Diag' tabs on the Mini Control sheet (the walk appends one row per
run: timestamp, 'startQueue -> endQueue', outcome counts) and DMs:

  <office>: N pushed · M left @ H:MM PM

Also flags a machine whose offices have posted NO new diag row for over 2h
inside the 7am-10pm push window — that is the walk being down, not quiet.

Usage: python -m automations.push_report.run [--dry-run]
"""

import datetime as dt
import re
import sys

CONTROL_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
CARLOS = "U046G04P5LG"

EVE = "U088E2KJEV8"
MEGAN = "U04G5HJBGFN"

# WHO the hourly report goes to, as a GROUP DM that Lucy opens herself.
#
# Two dead ends got us here, both worth not repeating:
#   1. --channel C0C4FE2TD1A, an id Carlos pasted from HIS Slack. A Slack
#      conversation id only resolves for a member, so to us it named nothing
#      and every run died on `channel_not_found` — the same error Slack gives
#      for an id that never existed, which is why it read as a permissions bug.
#   2. Pointing at Megan's EXISTING Carlos/Eve/Lucy/Megan chat by its real id.
#      Also channel_not_found from Lucy 2, because the "Lucy" in that chat is
#      the Lucy USER account, and Lucy Reporting (U0BCG8F9B5Z, the app whose
#      token every Lucy box posts with) is not in it — and cannot be, since
#      Slack does not allow adding an app to a DM.
#
# The way out is the one the focus reports already use: Lucy doesn't join a
# chat, she OPENS one. conversations.open(users=…) mints the multi-party DM of
# exactly these people plus the token owner, so Lucy Reporting is a participant
# by construction. Needs mpim:write, which that token has (13 scopes).
#
# Ids, not names — a name lookup would happily resolve the WRONG Lucy.
GROUP = (CARLOS, EVE, MEGAN)

# (diag tab, label, machine). The UNSUFFIXED tab is Carlos's 11580 — his office
# is the default (FILE_SUFFIX "") so its diag tab carries no office id.
OFFICES = [
    # 11580 pushes from CARLOS'S OWN COMPUTER since 2026-10-20, which cannot
    # write the diag tab -- it relays its numbers instead (RELAY_SOURCE below).
    ("relay:carlos:11580",  "Carlos 11580",          "Carlos's computer"),
    # 23467 left Lucy 2 for ATEF'S OWN COMPUTER 2026-10-29 (Megan: "yes take
    # atef live on his computer") -- relayed like Carlos's.
    ("relay:atef:23467",    "Atef 23467",            "Atef's computer"),
    # 11901 from KHALIL'S OWN COMPUTER since 2026-10-29, relayed like Carlos's.
    ("relay:khalil-nds:11901", "Khalil 11901",       "Khalil's computer"),
    # 14733 from COLTEN'S OWN COMPUTER since 2026-11-02.
    ("relay:colten:14733",  "Colten 14733",          "Colten's computer"),
    # Raf's three from RAF'S OWN COMPUTER since 2026-11-03 (they left Lucy 4).
    # One computer, three offices: each relays its own row, told apart by the
    # office number in the summary (resume_push.stats_summary).
    ("relay:raf:11280",     "Raf main 11280",        "Raf's computer"),
    ("relay:raf:23965",     "Raf 2nd funnel 23965",  "Raf's computer"),
    ("relay:raf:24065",     "Raf 24065",             "Raf's computer"),
]

STALE_AFTER_MIN = 120

# AN OFFICE'S OWN COMPUTER (LucyECO) relays one quiet stats row per office per
# day to the ICD relay workbook: stage probe-push-stats, Detail = the newest
# run's numbers as JSON, Last At = when it last ran. Written by
# automations/icd_alerts/resume_push.py (_file_stats). Read with the same
# Google account as the diag tabs (Lucy 2 and Lucy 4 share it).
RELAY_BOOK = "1_5YGHhZ0gCYVZzHl7TPnP-6_75xaI0kcjPinQdVTlKg"
RELAY_FAULTS_TAB = "ICD Faults"
RELAY_STATS_STAGE = "probe-push-stats"
# It runs every 10 minutes, so 45 quiet minutes means it is not running --
# Megan 2026-10-21: "We need to know it's working!"
RELAY_STALE_AFTER_MIN = 45
WINDOW = (7, 22)  # push window, hours local
BACKLOG_FLAG_OVER = 10  # more than this many left -> red X on the line


def _hm12(text: str) -> str:
    """'20:33' -> '8:33 PM'. Built by hand, not strftime: the no-pad hour flag
    is glibc/BSD-only (report_validation._chk_windows rejects it on sight) and
    plain %I pads to '08:33'. Same 6-liner as hub_cards._icd_hm12 /
    disposition_signup._ampm."""
    try:
        h, m = [int(x) for x in str(text).split(":")[:2]]
    except Exception:  # noqa: BLE001
        return str(text)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def _office_id(tab: str) -> str:
    """'OAT Walk Diag 23965' -> '23965'; 'relay:carlos:11580' -> '11580'. The
    UNSUFFIXED tab is Carlos's 11580 (FILE_SUFFIX ""), the old convention."""
    if tab.startswith("relay:"):
        return tab.split(":")[2]
    tail = tab[len("OAT Walk Diag"):].strip()
    return tail or "11580"


def _paused_offices() -> set:
    """Offices no machine is pushing right now, DERIVED — never a list here.

    Carlos flipped this set twice on 2026-09-25 alone (f9da93b pulled 11580 and
    all three of Raf's, 42a8b78 put 11580 + 11280 back four minutes later). A
    hardcoded "paused" list in this file would have been wrong within the hour,
    and a wrong label is worse than none: it explains away a zero.

    The truth is `applicant_push.offices.ROTATION_BY_MACHINE` — what each box
    actually walks. NOT `run.PUSH_ALLOWED`, which is the same fact but lives in
    a module that imports patchright at import time; this report is Sheets +
    Slack only and must not grow a browser dependency to print a label.

    Best-effort by design: on any failure this returns empty, so every office
    reports exactly as it did before. Never the other way round — guessing
    "paused" for a live office would hide a real outage.
    """
    try:
        from automations.applicant_push.offices import ROTATION_BY_MACHINE
    except Exception:  # noqa: BLE001
        return set()
    out = set()
    for tab, _label, machine in OFFICES:
        walked = ROTATION_BY_MACHINE.get(machine)
        if walked is None:          # machine absent = unknown, not paused
            continue
        if _office_id(tab) not in walked:
            out.add(_office_id(tab))
    return out


def _relay_stats(book, office_key: str, today: str, office: str = ""):
    """(numbers dict, last-run datetime) from the office computer's newest
    stats row today, or (None, None). Never raises. A computer with several
    offices (Raf's) files one row per office, "push stats <office>"; only
    that office's row -- or a plain "push stats" row naming it -- counts."""
    import json
    try:
        rows = book.worksheet(RELAY_FAULTS_TAB).get_all_values()
    except Exception:  # noqa: BLE001
        return None, None
    best = None
    for r in rows[1:]:
        if len(r) < 8 or r[2] != RELAY_STATS_STAGE:
            continue
        if (r[0] or "").strip().lower() != office_key:
            continue
        summ = (r[3] or "").strip()
        if office and summ not in ("push stats", "push stats %s" % office):
            continue
        day = str(r[1]).strip()
        if day != today and not day.startswith(today):
            continue
        try:
            last = dt.datetime.strptime(r[7].strip(), "%m/%d/%Y %H:%M:%S")
        except Exception:  # noqa: BLE001
            last = None
        try:
            stats = json.loads(r[4] or "{}")
        except Exception:  # noqa: BLE001
            stats = {}
        if office and str(stats.get("office") or office) != office:
            continue
        if best is None or (last and (best[1] is None or last > best[1])):
            best = (stats, last)
    return best if best else (None, None)


def _relay_line(label: str, stats: dict, last) -> str:
    """'Carlos 11580 (his computer): 12 pushed · 4 left @ 3:40 PM'."""
    end = stats.get("end")
    left = str(end) if isinstance(end, int) else "?"
    flag = ":x: " if isinstance(end, int) and end > BACKLOG_FLAG_OVER else ""
    pushed = ("%d pushed" % int(stats.get("sent_today") or 0)
              if stats.get("live") else "test run, nothing sent")
    at = _hm12(last.strftime("%H:%M")) if last else _hm12(stats.get("at", ""))
    extra = " · Indeed check up" if stats.get("walled") else ""
    if int(stats.get("unconfirmed") or 0):
        extra += " · :warning: %d didn't stick" % int(stats["unconfirmed"])
    return "%s%s (his computer): %s · %s left @ %s%s" % (
        flag, label, pushed, left, at, extra)


def build_report(unreadable=None) -> str:
    """The DM text. `unreadable`, when given, collects the offices whose diag
    tab could not be read — their line says so, but the numbers are missing."""
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET)
    now = dt.datetime.now()
    today = now.date().isoformat()
    lines = []
    paused = _paused_offices()
    machine_last: dict[str, dt.datetime] = {}
    relay_book = None
    for tab, label, machine in OFFICES:
        if tab.startswith("relay:"):
            if relay_book is None:
                try:
                    relay_book = _fill._client().open_by_key(RELAY_BOOK)
                except Exception as e:  # noqa: BLE001
                    relay_book = False
                    print("relay workbook unreadable: %s" % type(e).__name__)
            stats, last = (_relay_stats(relay_book, tab.split(":")[1], today,
                                        _office_id(tab))
                           if relay_book else (None, None))
            if stats is None:
                if relay_book is False and unreadable is not None:
                    unreadable.append(label)
                lines.append("%s (his computer): %s" % (
                    label, "relay unreadable" if relay_book is False
                    else "no runs yet today"))
                continue
            lines.append(_relay_line(label, stats, last))
            if last:
                machine_last[machine] = last
            continue
        try:
            vals = sh.worksheet(tab).get_all_values()
        except Exception as e:  # noqa: BLE001
            lines.append("%s: diag tab unreadable (%s)" % (label, type(e).__name__))
            if unreadable is not None:
                unreadable.append(label)
            continue
        rows = [r for r in vals if r and r[0].startswith(today)]
        sent = 0
        stuck = 0
        for r in rows:
            m = re.search(r"\bsent=(\d+)", r[4] if len(r) > 4 else "")
            if m:
                sent += int(m.group(1))
        # A click AppStream never saved (10/25: Atef's 45 / 86 / 75 queues sat
        # still while every run said "sent"). The LATEST run's count: the same
        # person retries every run, so a day's sum would repeat them.
        m3 = re.search(r"\bsend_unconfirmed=(\d+)",
                       rows[-1][4] if rows and len(rows[-1]) > 4 else "")
        if m3:
            stuck = int(m3.group(1))
        is_paused = _office_id(tab) in paused
        if not rows:
            # "no runs yet today" is a WORRY line — it means the walk should have
            # run and hasn't. For a paused office it is merely true and entirely
            # expected, and reading it as a fault is how someone goes looking for
            # a broken agent that was switched off on purpose.
            lines.append("%s: paused" % label if is_paused
                         else "%s: no runs yet today" % label)
            continue
        m2 = re.search(r"->\s*(\d+)", rows[-1][1] if len(rows[-1]) > 1 else "")
        left = m2.group(1) if m2 else "?"
        # Raf, 2026-09-25: "this dm needs to not be military time and shortened
        # up". The as-of is a RAW SLICE of the diag tab's timestamp cell
        # ('2026-09-24 20:33:12'), which is why it read as military — it was
        # never a datetime, so nothing ever formatted it. _hm12 does now.
        at = _hm12(rows[-1][0][11:16])
        # A paused office says "paused" where the count would go, rather than
        # "0 pushed" — the zero is true but reads as a failure, and the queue
        # count still matters (it keeps growing while nobody works it).
        # Raf, 2026-09-28: a red X in front of any office with MORE than 10
        # still waiting, so the backed-up queues jump out of the list. Paused
        # offices get it too — their queue keeps growing while nobody works it.
        flag = ":x: " if left.isdigit() and int(left) > BACKLOG_FLAG_OVER else ""
        lines.append("%s%s: %s · %s left @ %s%s"
                     % (flag, label,
                        "paused" if is_paused else "%d pushed" % sent,
                        left, at,
                        (" · :warning: %d didn't stick" % stuck) if stuck else ""))
        try:
            ts = dt.datetime.strptime(rows[-1][0], "%Y-%m-%d %H:%M:%S")
            if machine not in machine_last or ts > machine_last[machine]:
                machine_last[machine] = ts
        except Exception:  # noqa: BLE001
            pass
    if WINDOW[0] <= now.hour < WINDOW[1]:
        relay_machines = {m for t, _l, m in OFFICES if t.startswith("relay:")}
        for machine, last in sorted(machine_last.items()):
            stale = (RELAY_STALE_AFTER_MIN if machine in relay_machines
                     else STALE_AFTER_MIN)
            if (now - last).total_seconds() / 60 > stale:
                lines.append(":warning: %s has posted nothing since %s — the "
                             "walk may be down"
                             % (machine, _hm12(last.strftime("%H:%M"))))
        # A machine whose WHOLE rotation is paused has posted no runs on purpose.
        # Lucy 4 was in exactly that state for four minutes on 2026-09-25
        # (ROTATION_BY_MACHINE["Lucy 4"] == [] between f9da93b and 42a8b78), and
        # this line would have paged about a box that was switched off by hand.
        # Derived from OFFICES, never typed: a hand-kept machine list is
        # invisible when it goes stale, and the box that stops being named is
        # the box nobody gets paged about. Put a push office on another Lucy
        # and it is covered here with no edit. (automations/shared/test_fleet
        # guards this repo-wide.)
        for machine in sorted({m for _t, _l, m in OFFICES}):
            if machine in machine_last:
                continue
            mine = {_office_id(t) for t, _l, m in OFFICES if m == machine}
            if mine and mine <= paused:
                lines.append("%s: all offices paused" % machine)
            else:
                lines.append(":warning: %s has posted NO runs today" % machine)
    # Header unchanged in LOOK ('Push report 8:37 PM') — but no longer via the
    # no-pad hour flag, which is glibc/BSD-only and fails the validation gate.
    return ("*Push report %s*\n" % _hm12(now.strftime("%H:%M"))) + "\n".join(lines)


# ONE THREAD PER OFFICE CHANNEL PER DAY (Megan 2026-11-02: "move this alert
# of the push report to be in each of their recruiting channels" + "1 header
# thread named something like Lucy Processed resumes for Monday Nov 2nd -
# ##(total number)... in the thread it should give the hourly update... The
# total number in the header should update each time"). Each office's lines go
# to ITS OWN recruiting channel (applicant_push.offices post_channel); Raf's
# three share his. The header is edited in place with the day's total pushed,
# and an hourly reply is added only when that channel's lines changed.
THREADS_STATE = "push-report-threads.json"


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "%dth" % n
    return "%d%s" % (n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def header_text(day: dt.date, total: int) -> str:
    """'Lucy Processed Resumes for Monday Nov 2nd - 70'."""
    return "*Lucy Processed Resumes for %s %s %s - %d*" % (
        day.strftime("%A"), day.strftime("%b"), _ordinal(day.day), total)


# Raf's accounts each have their OWN recruiting channel for this report
# (Megan 2026-11-02: "Each of Raf's accounts has their own slack channel"),
# while his to-do posts still share #rafs-office-recruiting-11280.
#   23965 -> #raf-hidalgo-recruiting-23965-tiffani
#   24065 -> #full-ai-test-rafael-hidalgo-25065-maria-q (the "25065" in the
#            name is a typo; its "24065 Recruiters" tab is this office)
# Colten's 14733 -> #colten-wrights-office-recruiting-14733 (his existing
# channel, shown by Megan 2026-11-02; Lucy is in it).
REPORT_CHANNEL = {"23965": "C0CAV0P4RRS", "24065": "C0CBEDBFXM2",
                  "14733": "C0AUAPMEF37"}


def channel_of_label() -> dict:
    """{'Carlos 11580': 'C09L…', …} from each office's own post_channel."""
    from automations.applicant_push import offices as _o
    out = {}
    for tab, label, _m in OFFICES:
        oid = _office_id(tab)
        ch = REPORT_CHANNEL.get(oid) or (_o.OFFICES.get(oid) or {}).get("post_channel") or ""
        if ch:
            out[label] = ch
    return out


def split_by_channel(text: str) -> dict:
    """{channel: (stamp, [lines], total_pushed)} out of build_report's text.
    A channel whose offices have nothing yet today (no runs, paused) and no
    warning is left out: never post a blank board."""
    rows = text.split("\n")
    stamp = rows[0].strip("*").replace("Push report ", "")
    chans = channel_of_label()
    machine_of = {label: m for _t, label, m in OFFICES}
    out: dict = {}
    real: dict = {}
    for line in rows[1:]:
        bare = line[4:] if line.startswith(":x: ") else line
        label = next((l for l in chans if bare.startswith(l + ":")
                      or bare.startswith(l + " (")), None)
        targets = []
        if label:
            targets = [chans[label]]
        else:
            for l, m in machine_of.items():
                if l in chans and (line.startswith(":warning: %s " % m)
                                   or line.startswith("%s: " % m)):
                    targets.append(chans[l])
        for ch in dict.fromkeys(targets):
            entry = out.setdefault(ch, [stamp, [], 0])
            entry[1].append(line)
            m = re.search(r"(\d+) pushed", line)
            if label and m:
                entry[2] += int(m.group(1))
            if label and not re.search(r": (no runs yet today|paused)$", bare):
                real[ch] = True
            # A "posted NO runs today" warning alone is not news for an office
            # that has never pushed (Colten 11/2, before his setup: a "- 0"
            # header). A warning still counts once the office has numbers.
            if not label and "posted NO runs today" not in line:
                real[ch] = True
    return {ch: tuple(v) for ch, v in out.items() if real.get(ch)}


def post_threads(client, text: str, today: dt.date = None, state_dir=None) -> list:
    """Post/edit each channel's header + hourly reply. Returns the channels
    Slack accepted. State (header ts + last reply) lives beside the logs."""
    import json
    from pathlib import Path
    if today is None:
        # Nothing pushes Fri 1pm -> Sun 1pm, so nothing to report: without this
        # every channel would get a Saturday "posted NO runs today" warning.
        from automations.applicant_push.window import quiet_window
        if quiet_window(dt.datetime.now()):
            print("[push_report] weekend quiet window -- no thread posts")
            return []
    today = today or dt.date.today()
    d = Path(state_dir) if state_dir else (
        Path(__file__).resolve().parents[2] / "output")
    d.mkdir(parents=True, exist_ok=True)
    path = d / THREADS_STATE
    try:
        state = json.loads(path.read_text())
    except Exception:  # noqa: BLE001 -- no state = a fresh day
        state = {}
    day = state.setdefault(today.isoformat(), {})
    ok = []
    for ch, (stamp, lines, total) in split_by_channel(text).items():
        cur = day.setdefault(ch, {})
        body = "*%s*\n%s" % (stamp, "\n".join(lines))
        head = header_text(today, total)
        try:
            if not cur.get("ts"):
                r = client.chat_postMessage(channel=ch, text=head)
                if r is None or r.get("ok") is False:
                    print("[push_report] %s refused the header: %s"
                          % (ch, (r or {}).get("error")))
                    continue
                cur["ts"], cur["head"] = r["ts"], head
            elif cur.get("head") != head:
                client.chat_update(channel=ch, ts=cur["ts"], text=head)
                cur["head"] = head
            # Only a CHANGED update gets a new reply -- an evening of
            # identical hourly lines is noise in an owner's channel.
            same = "\n".join(lines) == cur.get("last")
            if not same:
                r = client.chat_postMessage(channel=ch, thread_ts=cur["ts"],
                                            text=body)
                if r is not None and r.get("ok") is False:
                    print("[push_report] %s refused the reply: %s"
                          % (ch, r.get("error")))
                    continue
                cur["last"] = "\n".join(lines)
            ok.append(ch)
        except Exception as e:  # noqa: BLE001 -- one channel never stops the rest
            print("[push_report] %s: %s: %s" % (ch, type(e).__name__, str(e)[:120]))
    for k in [k for k in state if k < (today - dt.timedelta(days=7)).isoformat()]:
        state.pop(k, None)
    path.write_text(json.dumps(state, indent=1))
    return ok


REPORT_ID = "push_hourly_report"


def record_delivery(unreadable, ch):
    """Today's run manifest — the proof a clean send closes its ticket with.

    2026-10-07: open since 9/24 as "ran clean, but nothing can confirm it
    DELIVERED". Eve: an exit-0 rule isn't enough, runs often leave info
    unfilled. So it is written only AFTER Slack confirmed the post, and an
    office whose diag tab couldn't be read is a named failed part — the DM
    went out without its numbers. A walk that is down or an office with no
    runs is NOT a failure here: the report said so, which is its job.
    Never raises."""
    try:
        from automations.shared import run_manifest
        done = [l for _t, l, _m in OFFICES if l not in unreadable]
        run_manifest.write_manifest(
            REPORT_ID, succeeded=done,
            failed=["%s: diag tab unreadable" % l for l in unreadable],
            note="posted to %s; %d office(s) reported, %d unreadable"
                 % (ch, len(done), len(unreadable)))
    except Exception as e:  # noqa: BLE001
        print("[push_report] couldn't write the run manifest (%s: %s) — the "
              "DM is sent, but the ticket won't close itself"
              % (type(e).__name__, e))


def _shots_dirs():
    import glob
    import os
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    today = dt.date.today().isoformat()
    return sorted(glob.glob(str(root / "output" / ("oat-shots-%s*" % today))))


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    unreadable = []
    text = build_report(unreadable)
    print(text)
    if "--dry-run" in args:
        return 0
    from automations.shared import slack_metrics_post as smp
    # WHO THIS POSTS AS IS THE MACHINE, NOT THE CODE (2026-09-24). _client()
    # reads ~/.config/recruiting-report/slack-user-token on whatever box runs
    # it: on every Lucy that file is Lucy Reporting, on Megan's laptop it is
    # MEGAN. So the 8:11pm verification post — run from the laptop — arrived
    # under Megan's name and photo, which is a laptop artefact and not a bug in
    # here. Do NOT "fix" it by switching to _bot_client(): that token is the
    # DM-only Lucy app (chat:write + files:write + im:write, no mpim:write) and
    # the file does not exist on the Lucy boxes at all. Verify a change to this
    # send by running it ON a Lucy, never here.
    client = smp._client()
    # WHERE THIS GOES. --group posts in the Carlos/Eve/Lucy/Megan chat;
    # --channel <id> is the escape hatch for any other destination; with
    # neither, it DMs Carlos, which is how this shipped and still works.
    # --with-shots also uploads today's failure screenshots from THIS machine's
    # output/oat-shots-<date>*/.
    ch = ""
    if "--channel" in args:
        ch = args[args.index("--channel") + 1]
    elif "--group" in args or "--threads" in args:
        # --group (what the LaunchAgent passes) now means the per-office
        # channel threads (Megan 2026-11-02: "move this alert ... to be in each
        # of their recruiting channels"); the Carlos/Eve/Megan DM stops.
        ok = post_threads(client, text)
        print("[push_report] posted to %d channel thread(s): %s"
              % (len(ok), ", ".join(ok)))
        if ok:
            record_delivery(unreadable, "office threads")
        return 0
    if not ch:
        ch = client.conversations_open(users=CARLOS)["channel"]["id"]
    resp = client.chat_postMessage(channel=ch, text=text)
    print("[push_report] posted to %s" % ch)
    if resp is not None and resp.get("ok") is False:
        print("[push_report] Slack did NOT accept the post: %s"
              % resp.get("error"))
        return 1
    record_delivery(unreadable, ch)
    if "--with-shots" in args:
        import glob
        import os
        n = 0
        for d in _shots_dirs():
            for f in sorted(glob.glob(os.path.join(d, "*.png")))[:10]:
                try:
                    client.files_upload_v2(channel=ch, file=f,
                                           title=os.path.basename(d) + "/"
                                           + os.path.basename(f))
                    n += 1
                except Exception as e:  # noqa: BLE001
                    print("[push_report] upload failed %s: %s"
                          % (f, type(e).__name__))
        print("[push_report] uploaded %d screenshot(s)" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
