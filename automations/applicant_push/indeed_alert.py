"""Indeed's "verify you are human" on a LUCY -> a DM to whoever can tick it.

Megan 2026-11-03: "for raf we need to build the alert and I'm at lucy 4 so I
can clear it". The office computers have had this since 10/21
(icd_alerts.resume_push._note_wall); the Lucys did not, so Lucy 4 walled every
run on Raf's 11280 and 24065 that morning and nobody heard.

Same rules as the office computers: an alert after WALL_RUNS walled pushes in
a row (one often clears by itself), at most once a day per office while it
lasts, and a "good to go" when a push gets through again. Posts as THIS
machine's Slack login (Lucy on a Lucy). Never raises.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

WALL_RUNS = 2
MEGAN, EVE, RAF = "U04G5HJBGFN", "U088E2KJEV8", "U045Z8N0ZQC"
# Who can tick the box, per office. Raf's three: Raf, Megan, Eve.
ALERT_USERS = {"11280": (RAF, MEGAN, EVE), "23965": (RAF, MEGAN, EVE),
               "24065": (RAF, MEGAN, EVE)}
DEFAULT_USERS = (MEGAN, EVE)


def _path(office: str) -> Path:
    root = Path(__file__).resolve().parents[2] / "output"
    root.mkdir(parents=True, exist_ok=True)
    return root / ("indeed-wall-%s.json" % office)


def ask_text(label: str, machine: str) -> str:
    return (":raising_hand: *%s on %s* — Lucy needs a human on *Indeed* "
            "to keep pushing applicants.\nOn %s: click Lucy's Chrome (it shows "
            "Indeed) and tick \"Verify you are human.\"" % (label, machine, machine))


def good_text(label: str, machine: str) -> str:
    return (":white_check_mark: *%s on %s* — good to go on Indeed. Lucy is "
            "pushing applicants again." % (label, machine))


def _dm(office: str, text: str, log=print) -> bool:
    try:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        users = ",".join(ALERT_USERS.get(office, DEFAULT_USERS))
        ch = client.conversations_open(users=users)["channel"]["id"]
        r = client.chat_postMessage(channel=ch, text=text)
        ok = r is None or r.get("ok") is not False
        log("[indeed-alert] DM %s: %s" % ("sent" if ok else "REFUSED", text[:80]))
        return ok
    except Exception as e:  # noqa: BLE001 -- the telling, never the work
        log("[indeed-alert] DM failed: %s: %s" % (type(e).__name__, str(e)[:100]))
        return False


def waiting_on_human(office: str, today: dt.date = None) -> bool:
    """Is this office one walled push away from (or past) its Indeed DM today?
    Then a walled push should leave Indeed's page up for the person the DM
    asks, instead of closing it (Megan 2026-11-03: "there's nothing up on
    lucy 4 to clear out")."""
    today = (today or dt.date.today()).isoformat()
    try:
        st = json.loads(_path(office).read_text())
    except Exception:  # noqa: BLE001
        return False
    return (st.get("alert_day") == today and bool(st.get("alerted"))) or \
        int(st.get("streak") or 0) >= WALL_RUNS - 1


def note(office: str, label: str, machine: str, walled: bool,
         cleared: bool = False, today: dt.date = None, log=print, send=_dm) -> str:
    """Record one push's Indeed outcome. Returns what it did: 'ask', 'good'
    or ''."""
    today = (today or dt.date.today()).isoformat()
    p = _path(office)
    try:
        st = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        st = {}
    did = ""
    if walled:
        st["streak"] = int(st.get("streak") or 0) + 1
        if st["streak"] >= WALL_RUNS and st.get("alert_day") != today:
            if send(office, ask_text(label, machine), log=log):
                st["alert_day"], st["alerted"] = today, True
                did = "ask"
    else:
        if cleared and st.get("alerted"):
            if send(office, good_text(label, machine), log=log):
                st["alerted"] = False
                did = "good"
        st["streak"] = 0
    try:
        p.write_text(json.dumps(st))
    except Exception:  # noqa: BLE001
        pass
    return did
