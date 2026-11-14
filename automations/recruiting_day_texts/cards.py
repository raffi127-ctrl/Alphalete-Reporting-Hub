"""The 8 Report Library cards that are this report's clock (all on Lucy 1).

Lucy 1's card_scheduler runs each at its Central time; each just runs
`dispatch`, which decides from every office's own clock who is due. One card
per zone so daylight saving and Arizona stay right without touching these.

    python -m automations.recruiting_day_texts.cards            # show
    python -m automations.recruiting_day_texts.cards --write    # add missing rows

ADD THEM ONLY AFTER `lucy update` HAS PUT THIS MODULE ON LUCY 1 -- a card
whose module is not there fails every day on the Hub.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

LIBRARY = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TAB = "Report Library"
MODULE = "automations.recruiting_day_texts.dispatch"
# (card id suffix, mode, Central time, which zone it is for)
SLOTS = [
    ("morning_et", "morning", "6:00 AM", "Eastern"),
    ("morning_ct", "morning", "7:00 AM", "Central"),
    ("morning_mt", "morning", "8:00 AM", "Mountain"),
    ("morning_pt", "morning", "9:00 AM", "Pacific"),
    ("showed_et", "showed", "2:45 PM", "Eastern"),
    ("showed_ct", "showed", "3:45 PM", "Central"),
    ("showed_mt", "showed", "4:45 PM", "Mountain"),
    ("showed_pt", "showed", "5:45 PM", "Pacific"),
]


def rows():
    out = []
    for sfx, mode, t, zone in SLOTS:
        cid = "recruiting_day_texts_" + sfx
        name = "Recruiting day texts - %s (%s offices)" % (
            "good morning" if mode == "morning" else "new starts 4pm", zone)
        meta = {"id": cid, "name": name, "emoji": "☀️", "color": "#D97706",
                "module": MODULE, "args": ["--mode", mode],
                "assignees": ["Lucy 1"],
                "schedule": {"frequency": "weekly", "weekdays": [0, 1, 2, 3, 4, 5],
                             "time": t, "estimated_minutes": 1,
                             "time_label": "%s CT Mon-Sat" % t},
                "description": "Clock for recruiting_day_texts: queues the %s read for "
                               "%s live offices on the lightest Lucy; Lucy 1 sends."
                               % (mode, zone)}
        out.append([cid, name, MODULE, "Claude",
                    dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    json.dumps(meta), ""])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    want = rows()
    if not a.write:
        for r in want:
            print(r[0], "|", json.loads(r[5])["schedule"]["time_label"])
        return 0
    from automations.recruiting_report import fill
    ws = fill.open_by_key(LIBRARY).worksheet(TAB)
    have = {r[0] for r in ws.get_all_values()[1:] if r}
    new = [r for r in want if r[0] not in have]
    if new:
        ws.append_rows(new, value_input_option="RAW")
    print("added %d, already there %d" % (len(new), len(want) - len(new)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
