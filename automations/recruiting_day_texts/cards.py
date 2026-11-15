"""The ONE Report Library card that is this report's clock (on Lucy 1).

It fires at every zone's trigger -- 8 times a day, Mon-Sat, Central time --
and each time runs `dispatch`, which works out from every office's own clock
who is due for which text. Megan 2026-11-14: "shouldn't it just be one?"
(card_scheduler takes a `times` list for exactly this.)

    python -m automations.recruiting_day_texts.cards            # show
    python -m automations.recruiting_day_texts.cards --write    # add the row

ADD IT ONLY AFTER `lucy update` HAS PUT THIS MODULE ON LUCY 1 -- a card
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
# THE SAME ID AS THE HUB CARD (hub_cards.py "recruiting-day-texts"). The Hub
# drops a library row whose id a built-in card already has, so people see ONE
# card; card_scheduler reads the library directly, so the clock still fires and
# its runs light up that same card.
CARD_ID = "recruiting-day-texts"
# Central times: each zone's 7:00 AM morning read, then its 3:45 PM read.
TIMES = ["6:00 AM", "7:00 AM", "8:00 AM", "9:00 AM",      # ET CT MT PT mornings
         "2:45 PM", "3:45 PM", "4:45 PM", "5:45 PM"]      # ET CT MT PT 4pm texts


def rows():
    meta = {"id": CARD_ID, "name": "Recruiting Day Texts",
            "emoji": "\u2600\ufe0f", "color": "#D97706",
            "module": MODULE, "args": [], "assignees": ["Lucy 1"],
            "schedule": {"frequency": "weekly", "weekdays": [0, 1, 2, 3, 4, 5],
                         "times": TIMES, "time": TIMES[0], "estimated_minutes": 1,
                         "time_label": "Mon-Sat, each office 7:00 AM + 3:45 PM its own time"},
            "description": "Clock for recruiting_day_texts: queues the due offices' read "
                           "on the lightest Lucy; Lucy 1 sends."}
    return [[CARD_ID, meta["name"], MODULE, "Claude",
             dt.datetime.now().strftime("%Y-%m-%d %H:%M"), json.dumps(meta), ""]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    want = rows()
    if not a.write:
        for r in want:
            print(r[0], "|", ", ".join(json.loads(r[5])["schedule"]["times"]))
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
