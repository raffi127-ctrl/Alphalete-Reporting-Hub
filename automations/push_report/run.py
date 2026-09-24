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


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    text = build_report()
    print(text)
    if "--dry-run" in args:
        return 0
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    ch = client.conversations_open(users=CARLOS)["channel"]["id"]
    client.chat_postMessage(channel=ch, text=text)
    print("[push_report] DM'd Carlos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
