"""Read a Verizon office's Optix FROM A LUCY and relay it as that office.

    python -m automations.verizon_office.house_feed --office nicolas          # preview
    python -m automations.verizon_office.house_feed --office nicolas --send

THE STOPGAP UNTIL THE OFFICE'S OWN ECO MACHINE ARRIVES. Runs on MEGAN'S
LAPTOP in the background (Megan 2026-11-06: "we need to do it on this laptop
in the background not a lucy") -- so it pauses whenever the laptop sleeps. Same idea as Raf's house feed
(alphalete_sales_board/eco_relay.py): the read happens on our machine, the
relay carries it under the OFFICE's key, and everything downstream -- the knock
board, sale alerts, the iMessage scoreboard -- cannot tell the difference.

ONE READ, BOTH HALVES: knocks (board rows) and sales (Sale Made - Wireless)
go out from the same Optix read, exactly as the ECO agent does it
(icd_alerts.run._optix_knocks).

WHEN HIS ECO MACHINE RELAYS, TURN THIS OFF -- two senders under one key would
be one office reported twice. `python -m automations.day_orchestrator.uninstall_agent verizon-house-feed`.

THE OPTIX SESSION lives in this machine's Lucy profile
(config.OPTIX_PROFILE_DIR), signed in once by a person:
`python -m automations.icd_alerts.optix_signin` at the machine.

NEVER RAISES out of a scheduled tick; a lost session is logged loudly and the
tick exits 2 so the log shows it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time

SOURCE = "verizon_house_feed"
# Office keys this machine reads for. One Optix profile per machine, so ONE
# office per Lucy until the reader takes a profile per office.
HOUSE_FEEDS = {"nicolas": "verizon"}

_KEY_CACHE = {"at": 0.0, "key": "", "office": ""}


def _relay_key(office_key: str) -> str:
    if (_KEY_CACHE["office"] == office_key and _KEY_CACHE["key"]
            and time.time() - float(_KEY_CACHE["at"]) < 600):
        return str(_KEY_CACHE["key"])
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key
    for row in open_by_key(P.RELAY_SPREADSHEET_ID).worksheet("Relay Keys").get_all_values()[1:]:
        if len(row) > 2 and row[0].strip().lower() == office_key:
            if row[2].strip().upper() not in ("TRUE", "YES", "Y"):
                return ""
            _KEY_CACHE.update(at=time.time(), key=row[1].strip(), office=office_key)
            return row[1].strip()
    return ""


def run(office_key: str, *, send: bool, log=print) -> int:
    from automations.icd_alerts import config as C, offices as O, relay as R
    from automations.icd_alerts import optix_read

    if office_key not in HOUSE_FEEDS:
        log("no house feed for %r — known: %s" % (office_key, sorted(HOUSE_FEEDS)))
        return 1
    day = dt.date.today()
    try:
        out = optix_read.read_day(day, headless=True, log=log)
    except optix_read.SignInInProgress:
        return 0
    except optix_read.SignInNeeded as e:
        log("✗ OPTIX SIGNED OUT on this machine — %s Run "
            "`python -m automations.icd_alerts.optix_signin` here." % e)
        return 2
    except Exception as e:  # noqa: BLE001
        log("✗ optix read failed: %s: %s" % (type(e).__name__, e))
        return 1

    rows = [optix_read.board_row(rep, c) for rep, c in sorted(out["reps"].items())]
    sales = {rep: {"Sales": c["Sale"]} for rep, c in out["reps"].items() if c.get("Sale")}
    log("%s: %d rep(s), %d knocks, %d sale(s)%s"
        % (office_key, len(rows), out["totals"]["Knocks"], out["totals"]["Sale"],
           "  ⚠ count mismatch %s" % out["mismatch"] if out.get("mismatch") else ""))
    if not send:
        log("preview — nothing sent")
        return 0
    key = _relay_key(office_key)
    if not key:
        log("✗ no active %r key on Relay Keys — nothing sent" % office_key)
        return 1
    rec = {"office_key": office_key, "relay_key": key, "relay_url": O.RELAY_URL,
           "campaign": HOUSE_FEEDS[office_key]}
    knocks = {"office_key": office_key, "key": key, "day": day.isoformat(),
              "knocks_rows": rows, "knocks_time_tracker": [], "agent": SOURCE,
              "local_time": dt.datetime.now().isoformat(timespec="seconds")}
    R._post(rec["relay_url"], json.dumps(knocks).encode("utf-8"))
    body = R.payload({}, day, rec, sales=sales)
    body["agent"] = SOURCE
    R._post(rec["relay_url"], json.dumps(body).encode("utf-8"))
    log("✓ relayed %d knock row(s) + %d seller(s) as %s" % (len(rows), len(sales), office_key))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default="nicolas")
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args(argv)
    return run(a.office, send=a.send)


if __name__ == "__main__":
    sys.exit(main())
