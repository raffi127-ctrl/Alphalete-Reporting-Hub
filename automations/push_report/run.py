"""Hourly resume-push report, DM'd to Carlos on Slack (Carlos, 2026-09-24:
"every hour report back to me on how much has been pushed for every and how
resumes are left in the 'one app at a time'" + "cant lucy report to me? even
if its through slack").

Sheets-API + Slack only — no browser, no AppStream login. Reads the per-office
'OAT Walk Diag' tabs on the Mini Control sheet (the walk appends one row per
run: timestamp, 'startQueue -> endQueue', outcome counts) and DMs:

  <office>: N pushed today | M left in OAT (as of HH:MM)

Also flags a machine whose offices have posted NO new diag row for over 2h
inside the 7am-10pm push window — that is the walk being down, not quiet.

Usage: python -m automations.push_report.run [--dry-run]
"""

import datetime as dt
import re
import sys

CONTROL_SHEET = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
CARLOS = "U046G04P5LG"

# The Carlos/Eve/Lucy/Megan group chat (Megan's own Copy-link, 2026-09-24).
#
# The first cut shipped --channel C0C4FE2TD1A and every run died on
# `channel_not_found`. That id was copied from CARLOS's screen, and a Slack
# conversation id is only resolvable by a member: to anyone outside the chat it
# does not name anything, which is the same answer Slack gives for an id that
# never existed. So the error looked like a permission problem and was really a
# wrong id — the chat's actual id is the one below.
#
# These reports post with MEGAN's user token (they only DISPLAY as Lucy), and
# she is in this chat, so this id is valid for the sender. If the chat's
# membership is ever changed, Slack mints a NEW id for the same people and this
# goes stale — re-copy the link from the chat rather than editing anything else.
GROUP_CHANNEL = "C0BJX9LJSJD"

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


def build_report() -> str:
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(CONTROL_SHEET)
    now = dt.datetime.now()
    today = now.date().isoformat()
    lines = []
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
        if not rows:
            lines.append("%s: no runs yet today" % label)
            continue
        m2 = re.search(r"->\s*(\d+)", rows[-1][1] if len(rows[-1]) > 1 else "")
        left = m2.group(1) if m2 else "?"
        at = rows[-1][0][11:16]
        lines.append("%s: %d pushed today | %s left in OAT (as of %s)"
                     % (label, sent, left, at))
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
                             "walk may be down" % (machine, last.strftime("%H:%M")))
        for machine in ("Lucy 2", "Lucy 4"):
            if machine not in machine_last:
                lines.append(":warning: %s has posted NO runs today" % machine)
    return ("*Push report %s*\n" % now.strftime("%-I:%M %p")) + "\n".join(lines)


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
        ch = GROUP_CHANNEL
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
