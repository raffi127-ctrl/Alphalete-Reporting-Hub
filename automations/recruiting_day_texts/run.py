"""Recruiting day texts -- good-morning schedule + 4pm new-start retention.

    python -m automations.recruiting_day_texts.run --mode morning --office raf   # DRY RUN
    python -m automations.recruiting_day_texts.run --mode showed --office raf
    python -m automations.recruiting_day_texts.run --mode morning --due --send   # what the clock runs

HOW A MORNING RUNS (Megan 2026-11-13: "running on the correct lucy (lightest
one) each morning"):

  1. Lucy 1's Report Library card fires `dispatch` at each zone's trigger.
  2. dispatch queues `rerun recruiting_day_texts --due --send` with NO machine,
     so mini_control's routing hands it to the least-loaded Lucy that has
     AppStream (day_orchestrator/routing.py).
  3. That Lucy reads every due office's Retention Details (+ the last 4
     same weekdays, for the red alert).
  4. The SEND always leaves from Lucy 1: Lucy 3's iMessages miss some phones
     ([[reference_lucy3_imessage_partial_delivery]]) and Lucy 1 is the number in
     the office groups. The reader queues `rerun recruiting_day_texts
     --deliver <data>` on Lucy 1, which draws the picture and sends it. If the
     reader IS Lucy 1 it just sends.

--send only ever texts offices whose config `mode` is "live"; everything else
is read and logged. Once per office per day per mode (--force resends).
Exit 0 clean · 1 an office failed · 2 bad arguments. Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import sys
import zlib
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from automations.recruiting_day_texts import config as C
from automations.recruiting_day_texts import render as R
from automations.recruiting_day_texts import texts as T

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output" / "recruiting_day_texts"
STATE = Path.home() / ".config" / "recruiting-report" / "recruiting_day_texts.json"
SENDER = "Lucy 1"
REPORT_ID = "recruiting_day_texts"


def _log(m: str) -> None:
    print("[day-texts] " + m, flush=True)


# ------------------------------------------------------------------ clock --

def local_now(o: C.Office, now: Optional[dt.datetime] = None) -> dt.datetime:
    now = now or dt.datetime.now(dt.timezone.utc).astimezone()
    return now.astimezone(ZoneInfo(o.tz))


def is_due(o: C.Office, mode: str, now: Optional[dt.datetime] = None) -> bool:
    """True when this office's own clock is in its trigger window."""
    loc = local_now(o, now)
    h, m = C.MORNING_LOCAL if mode == "morning" else C.SHOWED_LOCAL
    start = loc.replace(hour=h, minute=m, second=0, microsecond=0)
    mins = (loc - start).total_seconds() / 60.0
    return 0 <= mins < C.DUE_WINDOW_MIN and loc.weekday() != 6   # never Sunday


def due_offices(mode: str, now: Optional[dt.datetime] = None,
                live_only: bool = True) -> List[C.Office]:
    return [o for o in C.OFFICES.values()
            if o.mode != "hold" and (o.mode == "live" or not live_only)
            and is_due(o, mode, now)]


# ------------------------------------------------------------------ state --

def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _key(o: C.Office, mode: str, day: dt.date) -> str:
    return "%s|%s|%s" % (o.key, mode, day.isoformat())


def _remember(k: str) -> None:
    s = _state()
    s[k] = dt.datetime.now().isoformat(timespec="seconds")
    cut = (dt.date.today() - dt.timedelta(days=14)).isoformat()
    s = {a: b for a, b in s.items() if a.rsplit("|", 1)[-1] >= cut}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")


# -------------------------------------------------------------- payloads --

def encode(p: dict) -> str:
    """URL-safe text that survives a queue Args cell + shlex (no quotes,
    commas or spaces -- names like O'Brien would break a plain JSON arg)."""
    raw = zlib.compress(json.dumps(p, ensure_ascii=True).encode("utf-8"), 9)
    return "b64:" + base64.urlsafe_b64encode(raw).decode("ascii")


def decode(s: str) -> dict:
    if not s.startswith("b64:"):
        raise ValueError("not a recruiting_day_texts payload")
    return json.loads(zlib.decompress(base64.urlsafe_b64decode(s[4:].encode("ascii"))))


# ------------------------------------------------------------------ send ---

def dest_for(o: C.Office) -> dict:
    """The ONE approved group this ICD chose, off the relay's Office Channels
    tab (found by its pinned people, not its name)."""
    from automations.icd_alerts import post as P
    dests = P.approved_texts().get(o.key) or []
    hit = [d for d in dests if d.get("group") == o.group] if o.group else dests[:1]
    if not hit:
        raise RuntimeError("%s: group %r is not an approved text destination on "
                           "Office Channels (has: %s)"
                           % (o.key, o.group, [d.get("group") for d in dests]))
    d = hit[0]
    return {k: d[k] for k in ("group", "chat_guid", "require_handles") if d.get(k)}


def build(o: C.Office, mode: str, d, avg: dict):
    """(text, [png]) -- or (None, []) when there is nothing to say."""
    if mode == "morning":
        text = T.morning(o, d)
        if not text:
            return None, []
        from automations.recruiting_day_texts.read import low_flags
        low = low_flags(d, avg)
        return text, [R.morning_png(d, OUT / ("%s-%s-morning.png" % (d.day, o.key)), low)]
    text = T.showed(o, d)
    if not text:
        return None, []
    return text, [R.showed_png(d, OUT / ("%s-%s-showed.png" % (d.day, o.key)))]


def deliver(payload: dict, force: bool = False) -> None:
    """On Lucy 1: draw the picture and text it to the office group."""
    from automations.recruiting_day_texts.read import from_payload
    o, mode, d, avg = from_payload(payload)
    if o.mode != "live":
        _log("%s: mode=%s -- not texting" % (o.owner, o.mode))
        return
    k = _key(o, mode, d.day)
    if k in _state() and not force:
        _log("%s: already texted %s today -- skipping" % (o.owner, mode))
        return
    text, images = build(o, mode, d, avg)
    if not text:
        _log("%s: nothing to send" % o.owner)
        return
    from automations.b2b_dispositions import text_post as tp
    dest = dest_for(o)
    res = tp.send_to_group(dest["group"], text, images, dry_run=False, dest=dest)
    _remember(k)
    _log("%s: texted %r (%s participants) + %d picture(s)"
         % (o.owner, res.get("resolved_name"), res.get("participants"), len(images)))


def _this_machine() -> str:
    try:
        from automations.gap_alerts import config as gc
        return gc.this_machine()
    except Exception:  # noqa: BLE001
        return ""


def hand_off(payload: dict) -> None:
    if _this_machine() == SENDER:
        deliver(payload)
        return
    from automations.day_orchestrator import mini_control as mc
    mc.enqueue("rerun", "%s --deliver %s" % (REPORT_ID, encode(payload)),
               by="recruiting_day_texts", machine=SENDER, auto=True)
    _log("%s: queued on %s to send" % (payload["owner"], SENDER))


# ------------------------------------------------------------------ read ---

def one(app, o: C.Office, mode: str, day: dt.date, send: bool) -> None:
    from automations.recruiting_day_texts import read as RD
    labels = C.LABELS if mode == "morning" else (C.L_NS_SCHED, C.L_NS_SHOWED)
    d = RD.read_day(app, o, day, labels=labels, log=_log)
    avg = {}
    if mode == "morning" and d.ns_scheduled:
        try:
            d.ns_times = RD.new_start_times(app, o, day, log=_log)
        except Exception as e:  # noqa: BLE001 -- names without times, never guessed
            _log("  new-start times unreadable (%s) -- names only" % e)
    if mode == "morning" and T.has_anything(d):
        try:
            avg = RD.usual(app, o, day, log=_log)
        except Exception as e:  # noqa: BLE001 -- no alert beats a wrong alert
            _log("  usual numbers unreadable (%s) -- picture goes without an alert" % e)
    text, images = build(o, mode, d, avg)
    if not text:
        _log("%s: nothing to send (%s)" % (o.owner, "empty calendar" if
             mode == "morning" else "no new starts scheduled today"))
        return
    print("    " + text.replace("\n", "\n    "))
    for p in images:
        _log("picture: %s" % p)
    if not send or o.mode != "live":
        _log("%s: DRY (%s)" % (o.owner, "no --send" if not send else "mode=%s" % o.mode))
        return
    hand_off(RD.to_payload(o, mode, d, avg))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("morning", "showed"))
    ap.add_argument("--office", action="append",
                    help="office key or AppStream id (repeatable)")
    ap.add_argument("--due", action="store_true",
                    help="only offices whose own clock is at this mode's trigger")
    ap.add_argument("--all", action="store_true", help="every office (dry checks)")
    ap.add_argument("--date", help="YYYY-MM-DD (default today; must be this week)")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--deliver", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    if a.deliver:
        try:
            deliver(decode(a.deliver), force=a.force)
            return 0
        except Exception as e:  # noqa: BLE001
            _log("deliver FAILED -- %s" % e)
            return 1
    if not a.mode:
        print("--mode is required", file=sys.stderr)
        return 2
    try:
        day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
        if a.office:
            offices = [C.office(k) for k in a.office]
        elif a.due:
            offices = due_offices(a.mode, live_only=a.send)
        elif a.all:
            offices = [o for o in C.OFFICES.values() if o.mode != "hold"]
        else:
            print("say which offices: --office, --due or --all", file=sys.stderr)
            return 2
    except (ValueError, KeyError) as e:
        print(e, file=sys.stderr)
        return 2
    if not offices:
        _log("no offices due for %s right now" % a.mode)
        return 0
    from automations.applicant_tracker.applicantstream import session
    failed = []
    with session() as app:
        for o in offices:
            _log("%s (%s) %s %s" % (o.owner, o.appstream_id, a.mode, day))
            try:
                one(app, o, a.mode, day, a.send)
            except Exception as e:  # noqa: BLE001 -- one office never stops the rest
                _log("%s: FAILED -- %s" % (o.owner, e))
                failed.append(o.key)
    if failed:
        _log("failed: %s" % ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
