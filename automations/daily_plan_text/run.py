"""Daily plan text -- 8:00 AM Mon-Sat to NEW A Players (Carlos 2026-11-11).

    lucy rerun daily_plan_text                 # today, DRY RUN (prints the text)
    lucy rerun daily_plan_text --send          # queue today's text
    lucy rerun daily_plan_text --date 2026-11-12
    lucy rerun daily_plan_text --send --force  # resend even if already sent today

The text goes out the same way the NDS boards do: a b2b_dispositions manifest
dropped in the local text outbox, which the Lucy 2 poller drains and sends
through Messages. Routing: config.TEXT_ROUTES[("DAILY PLAN", "daily_plan")].
Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Optional

from automations.daily_plan_text import config as C


def _log(msg: str) -> None:
    print("[plan] " + msg, flush=True)


# ---------------------------------------------------------------- pure -----

def template_for(day: dt.date) -> Optional[str]:
    """The day's text, or None when the weekday has no template (or is Sunday)."""
    if day.weekday() not in C.WEEKDAYS:
        return None
    return C.TEMPLATES.get(day.weekday())


def _load_state() -> dict:
    try:
        return json.loads(C.STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def already_sent(day: dt.date, state: Optional[dict] = None) -> bool:
    st = _load_state() if state is None else state
    return st.get("sent_day") == day.isoformat()


def remember_sent(day: dt.date, now: dt.datetime) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.STATE_PATH.write_text(json.dumps({
        "sent_day": day.isoformat(),
        "sent_at": now.isoformat(timespec="seconds")}, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- send -----

def queue_text(text: str, day: dt.date, now: dt.datetime) -> bool:
    """Same handoff as nds_oof._queue_text: manifest -> local outbox -> poller."""
    from automations.b2b_dispositions import text_post as tp
    from automations.b2b_dispositions import run as bd_run
    from automations.day_orchestrator import text_outbox as tob
    spec = {"kind": C.KIND, "title": "Daily plan", "text": text,
            "by_campaign": {C.CAMPAIGN_LABEL: []}}
    if not tp.spec_has_routes(spec):
        _log("no route for %s/%s in TEXT_ROUTES -- not queued" % (C.CAMPAIGN_LABEL, C.KIND))
        return False
    out_dir = bd_run.OUTPUT_DIR / day.strftime("%Y-%m-%d")
    mp = tp.write_manifest(spec, out_dir, "%s-%s" % (C.KIND, now.strftime("%H%M")))
    tob.drop(mp, by="daily_plan_text", day=day.isoformat())
    _log("text: outbox %s" % mp.name)
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--send", action="store_true", help="queue the text (default: dry run)")
    ap.add_argument("--force", action="store_true", help="send even if already sent today")
    a = ap.parse_args(argv)

    now = dt.datetime.now()
    day = dt.date.fromisoformat(a.date) if a.date else now.date()
    name = C.DAY_NAMES[day.weekday()]
    text = template_for(day)
    if text is None:
        _log("%s %s: no template yet -- nothing to send" % (name, day.isoformat()))
        return 0
    _log("%s %s: %d chars" % (name, day.isoformat(), len(text)))
    for line in text.splitlines():
        print("    " + line)
    if not a.send:
        _log("dry run -- pass --send to queue it")
        return 0
    if already_sent(day) and not a.force:
        _log("already sent today -- not sending again (use --force)")
        return 0
    if queue_text(text, day, now):
        remember_sent(day, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
