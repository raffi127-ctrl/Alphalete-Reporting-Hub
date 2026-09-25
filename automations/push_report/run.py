"""Hourly resume-push report, DM'd to Carlos on Slack (Carlos, 2026-09-24:
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
    ("OAT Walk Diag",       "Carlos 11580",          "Lucy 2"),
    ("OAT Walk Diag 23467", "Atef 23467",            "Lucy 2"),
    ("OAT Walk Diag 11901", "Khalil 11901",          "Lucy 2"),
    ("OAT Walk Diag 11280", "Raf main 11280",        "Lucy 4"),
    ("OAT Walk Diag 23965", "Raf 2nd funnel 23965",  "Lucy 4"),
    ("OAT Walk Diag 24065", "Raf 24065",             "Lucy 4"),
]

STALE_AFTER_MIN = 120
WINDOW = (7, 22)  # push window, hours local


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
    """'OAT Walk Diag 23965' -> '23965'. The UNSUFFIXED tab is Carlos's 11580
    (FILE_SUFFIX ""), same convention OFFICES documents above."""
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


def build_report() -> str:
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET)
    now = dt.datetime.now()
    today = now.date().isoformat()
    lines = []
    paused = _paused_offices()
    machine_last: dict[str, dt.datetime] = {}
    for tab, label, machine in OFFICES:
        try:
            vals = sh.worksheet(tab).get_all_values()
        except Exception as e:  # noqa: BLE001
            lines.append("%s: diag tab unreadable (%s)" % (label, type(e).__name__))
            continue
        rows = [r for r in vals if r and r[0].startswith(today)]
        sent = 0
        for r in rows:
            m = re.search(r"\bsent=(\d+)", r[4] if len(r) > 4 else "")
            if m:
                sent += int(m.group(1))
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
        lines.append("%s: %s · %s left @ %s"
                     % (label, "paused" if is_paused else "%d pushed" % sent,
                        left, at))
        try:
            ts = dt.datetime.strptime(rows[-1][0], "%Y-%m-%d %H:%M:%S")
            if machine not in machine_last or ts > machine_last[machine]:
                machine_last[machine] = ts
        except Exception:  # noqa: BLE001
            pass
    if WINDOW[0] <= now.hour < WINDOW[1]:
        for machine, last in sorted(machine_last.items()):
            if (now - last).total_seconds() / 60 > STALE_AFTER_MIN:
                lines.append(":warning: %s has posted nothing since %s — the "
                             "walk may be down"
                             % (machine, _hm12(last.strftime("%H:%M"))))
        # A machine whose WHOLE rotation is paused has posted no runs on purpose.
        # Lucy 4 was in exactly that state for four minutes on 2026-09-25
        # (ROTATION_BY_MACHINE["Lucy 4"] == [] between f9da93b and 42a8b78), and
        # this line would have paged about a box that was switched off by hand.
        for machine in ("Lucy 2", "Lucy 4"):
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


def _shots_dirs():
    import glob
    import os
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    today = dt.date.today().isoformat()
    return sorted(glob.glob(str(root / "output" / ("oat-shots-%s*" % today))))


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    text = build_report()
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
    elif "--group" in args:
        ch = client.conversations_open(users=",".join(GROUP))["channel"]["id"]
    if not ch:
        ch = client.conversations_open(users=CARLOS)["channel"]["id"]
    client.chat_postMessage(channel=ch, text=text)
    print("[push_report] posted to %s" % ch)
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
