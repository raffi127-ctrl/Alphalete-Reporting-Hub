"""DM Megan when an office's apps stop going out (Megan 2026-11-25: "I need
alerted when apps aren't getting pushed" ... "I wasn't notified at all that the
human check needed cleared out").

WHY A SECOND ALERT. The Indeed DM (icd_alerts/post.py SYSTEMS["indeed"]) is
once a day, reaches Slack when the fault poster next runs (11/25: block at
5:38, DM at 8:02), says "good to go" on a one-run clear, and only knows about
Indeed. On 11/25 Raf's 24065 then pushed nothing for hours -- re-blocked, then
two runs that could not open One App at a time -- and nobody heard.

This one does not care WHY. Every hour, with the push report (Lucy 2), for each
office computer that pushes:
  * no finished run in STALE_MIN while that computer says it is in its push
    hours and wants to run (or a run has held the lock for half an hour), or
  * WAITING_FLOOR+ applicants left and nothing sent since the last check.
One message when an office stalls, one when it moves again, in the
office's own group DM -- owner, helpers, Megan, Eve, the same chat the Indeed
alert uses (Megan: "it should DM in the group for Raf right"). Never in the
weekend pause or outside 6am-10pm.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

STALE_MIN = 60
STUCK_LOCK_MIN = 30
WAITING_FLOOR = 5
STATS_STAGE = "probe-push-stats"
HEALTH_STAGE = "probe-push-health"


def _when(s: str) -> Optional[dt.datetime]:
    try:
        return dt.datetime.strptime((s or "").strip(), "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None


def collect(rows: List[list], today: str) -> Tuple[dict, dict]:
    """(stats, health) from the relay's ICD Faults rows for `today`.
    stats[(key, office)] = {last, sent, end, walled}; health[key] = {...}."""
    stats, health = {}, {}
    for r in rows[1:]:
        if len(r) < 8 or str(r[1]).strip() != today:
            continue
        key = (r[0] or "").strip().lower()
        try:
            d = json.loads(r[4] or "{}")
        except ValueError:
            continue
        if r[2] == STATS_STAGE:
            office = str(d.get("office") or "")
            stats[(key, office)] = {
                "last": _when(r[7]), "sent": int(d.get("sent_today") or 0),
                "end": d.get("end"), "walled": bool(d.get("walled"))}
        elif r[2] == HEALTH_STAGE:
            health[key] = {"at": _when(r[7]), "due": bool(d.get("due")),
                           "in_window": bool(d.get("in_window")),
                           "lock_min": d.get("lock_min"),
                           "last_result": d.get("last_result")}
    return stats, health


def in_hours(now: dt.datetime) -> bool:
    try:
        from automations.applicant_push.window import quiet_window
        if quiet_window(now):
            return False
    except Exception:  # noqa: BLE001 -- no window module = no weekend rule
        pass
    return 6 <= now.hour < 22


def check(now: dt.datetime, offices: List[Tuple[str, str, str]],
          stats: dict, health: dict, state: dict) -> List[Tuple[str, str]]:
    """(relay key, message) to send now. `offices` = [(key, office id, label)].
    Updates `state` in place (per-office last sent count + alerted flag)."""
    out = []
    if not in_hours(now):
        return out
    for key, office, label in offices:
        h = health.get(key)
        st = state.setdefault(office, {})
        if not h or not h.get("in_window"):
            continue
        s = stats.get((key, office))
        why = ""
        last = s and s.get("last")
        lock = h.get("lock_min") or 0
        if (not last or (now - last) > dt.timedelta(minutes=STALE_MIN)) and (
                h.get("due") or lock >= STUCK_LOCK_MIN):
            why = ("no push run has finished today" if not last else
                   "no push run has finished in %d min"
                   % ((now - last).total_seconds() // 60))
            if h.get("last_result") and h["last_result"] != "ok":
                why += " (last result: %s)" % h["last_result"]
        elif s and isinstance(s.get("end"), int) and s["end"] >= WAITING_FLOOR:
            prev = st.get("sent")
            if prev is not None and s["sent"] <= prev and st.get("day") == now.date().isoformat():
                why = "%d waiting, nothing sent in the last hour%s" % (
                    s["end"], " -- Indeed's check is up" if s.get("walled") else "")
        if s:
            st["sent"], st["day"] = s["sent"], now.date().isoformat()
        if why and not st.get("alerted"):
            out.append((key, ":rotating_light: *%s* -- apps aren't going out: %s."
                        % (label, why)))
            st["alerted"] = True
        elif not why and st.get("alerted"):
            out.append((key, ":white_check_mark: *%s* -- pushing again (%d sent today)."
                        % (label, s["sent"] if s else 0)))
            st["alerted"] = False
    return out


def state_path() -> Path:
    root = Path(__file__).resolve().parents[2] / "output"
    root.mkdir(parents=True, exist_ok=True)
    return root / "push-stall-state.json"


def run(client, megan: str, offices, book, now: Optional[dt.datetime] = None,
        log=print) -> int:
    """Read the relay, DM Megan what changed. Returns messages sent. Never
    raises -- the push report must still post if this cannot."""
    now = now or dt.datetime.now()
    try:
        from automations.push_report import run as PR
        rows = book.worksheet(PR.RELAY_FAULTS_TAB).get_all_values()
        stats, health = collect(rows, now.date().isoformat())
        try:
            state = json.loads(state_path().read_text())
        except Exception:  # noqa: BLE001
            state = {}
        msgs = check(now, offices, stats, health, state)
        state_path().write_text(json.dumps(state, indent=2))
        if not msgs:
            return 0
        by_key: Dict[str, List[str]] = {}
        for key, m in msgs:
            by_key.setdefault(key, []).append(m)
        from automations.icd_alerts import post as P
        for key, lines in by_key.items():
            text = "\n".join(lines)
            try:
                P.dm_office_people(key, text, log=log)   # owner+helpers+Megan+Eve
            except Exception as e:  # noqa: BLE001 -- never lose the alert
                log("[stall] group DM for %s failed (%s) -- DMing Megan"
                    % (key, type(e).__name__))
                ch = client.conversations_open(users=megan)["channel"]["id"]
                client.chat_postMessage(channel=ch, text=text)
            log("[stall] %s: %s" % (key, text))
        return len(msgs)
    except Exception as e:  # noqa: BLE001
        log("[stall] check skipped: %s: %s" % (type(e).__name__, str(e)[:120]))
        return 0
