"""Rep Knock Breakdown — hourly, Lucy 1 (Raf's OwnerVille login, office 11280).

For every rep who knocked today: pull their knock table, draw it, and reply in
THAT rep's thread for the week in #alphalete-sales-knocking-data. A rep whose
numbers have not moved since the last post is skipped (a rep who stopped at 5pm
would otherwise get four identical pictures). 3+ GPS failures in a row -> one
text to "Knocking Chat A-Players" per streak.

    # preview: pulls + draws PNGs to output/rep_knock_breakdown/<day>/, posts nothing
    python -m automations.rep_knock_breakdown.run --dry-run
    python -m automations.rep_knock_breakdown.run --dry-run --day 2026-10-13 --only "Diego"

    # live (the LaunchAgent)
    python -m automations.rep_knock_breakdown.run --send --text

--send is the only flag that touches Slack; --text the only one that texts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import traceback
from typing import Dict, List, Optional

from automations.rep_knock_breakdown import config as C
from automations.rep_knock_breakdown import streaks as S

try:
    from zoneinfo import ZoneInfo
    CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # noqa: BLE001
    CENTRAL = None


def _log(msg: str) -> None:
    print(msg, flush=True)


def _now() -> dt.datetime:
    return dt.datetime.now(CENTRAL) if CENTRAL else dt.datetime.now()


def _md(d: dt.date) -> str:
    return "%d/%d" % (d.month, d.day)                 # no %-d: Windows


def _clock(t: dt.datetime) -> str:
    return "%d:%02d %s" % (t.hour % 12 or 12, t.minute, "AM" if t.hour < 12 else "PM")


def week_sunday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def in_window(now: dt.datetime) -> bool:
    win = C.WINDOW.get(now.weekday())
    return bool(win) and win[0] <= now.hour <= win[1]


# --- state --------------------------------------------------------------------
def _state() -> Dict:
    try:
        return json.loads(C.STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(data: Dict, today: dt.date) -> None:
    # Keep three weeks; older threads are never posted into again.
    cutoff = (week_sunday(today) - dt.timedelta(days=21)).isoformat()
    for k in ("threads", "last_sig", "texted"):
        data[k] = {key: v for key, v in (data.get(k) or {}).items()
                   if key.split("|", 1)[0] >= cutoff}
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    C.STATE_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")


def signature(rep: Dict) -> str:
    """What has to change for a new post to be worth it."""
    s = S.summary(rep["rows"])
    return "%d|%d|%s" % (s["knocks"], s["gps_fails"], s["last"])


# --- OwnerVille ---------------------------------------------------------------
def _assert_master(page) -> None:
    """Raf's reps only. Same check gap_alerts makes: an impersonation another
    job left behind would otherwise publish someone else's office as Raf's."""
    from automations.rashad_metrics.knocks_pull import (MASTER_OFFICE_ID,
                                                        logged_in_office)
    head, office_id = logged_in_office(page)
    if office_id and office_id != MASTER_OFFICE_ID:
        raise RuntimeError("OwnerVille session is on office %s, not Raf's %s "
                           "(header %r)" % (office_id, MASTER_OFFICE_ID, head[:100]))


def pull(day: dt.date, only: str = "") -> List[Dict]:
    from automations.b2b_dispositions import capture as cap
    from automations.gap_alerts import config as GA
    from automations.rep_knock_breakdown import pull as P
    from automations.shared.tableau_patchright import ownerville_session
    with ownerville_session(headless=True, verbose=False,
                            profile_dir=GA.PROFILE_DIR,
                            session_wait_s=GA.OWNERVILLE_SESSION_WAIT_S,
                            priority="scheduled") as page:
        rqst = cap.capture_rqst(page)
        try:
            from automations.focus_office_att.run_all_owners import _exit_impersonation
            _exit_impersonation(page)
            rqst = cap.capture_rqst(page) or rqst
        except Exception:  # noqa: BLE001 — _assert_master is the real guard
            pass
        _assert_master(page)
        P.pin_campaign(page, rqst)
        return P.pull_day(page, rqst, day, only=only)


# --- Slack --------------------------------------------------------------------
def _client():
    from automations.shared import slack_metrics_post as smp
    return smp._client()


def thread_ts(state: Dict, rep: Dict, day: dt.date, send: bool) -> str:
    sun = week_sunday(day)
    key = "%s|%s" % (sun.isoformat(), rep["pid"])
    ts = (state.get("threads") or {}).get(key)
    if ts:
        return ts
    text = "*%s* — knocking data · week of Sun %s" % (rep["name"], _md(sun))
    if not send:
        _log("  PREVIEW would open thread: %s" % text)
        return ""
    ts = _client().chat_postMessage(channel=C.SLACK_CHANNEL, text=text)["ts"]
    state.setdefault("threads", {})[key] = ts
    return ts


def post_rep(rep: Dict, pngs, ts: str, caption: str, send: bool) -> None:
    if not send:
        _log("  PREVIEW reply (%d image(s)): %s" % (len(pngs), caption))
        return
    _client().files_upload_v2(
        channel=C.SLACK_CHANNEL, thread_ts=ts, initial_comment=caption,
        file_uploads=[{"file": str(p), "filename": p.name} for p in pngs])


def _permalink(ts: str) -> str:
    try:
        return _client().chat_getPermalink(channel=C.SLACK_CHANNEL,
                                           message_ts=ts)["permalink"]
    except Exception:  # noqa: BLE001
        return ""


# --- the text -----------------------------------------------------------------
def streak_texts(rep: Dict, day: dt.date) -> List[Dict]:
    """[{key, body}] — one per 3+ GPS-failure streak today."""
    seq = S.chronological(rep["rows"])
    out = []
    for s, e in S.fail_streaks(rep["rows"], C.FAIL_STREAK):
        run = seq[s:e + 1]
        dists = [S.distance_text(r.get("gps", "")) for r in run]
        dists = [x for x in dists if x]
        body = ("GPS alert: %s has %d knocks in a row that failed GPS "
                "(%s to %s%s)."
                % (rep["name"], len(run), run[0].get("time", ""),
                   run[-1].get("time", ""),
                   ", " + " / ".join(dists[:5]) + " from the door" if dists else ""))
        out.append({"key": S.streak_key(day, rep["pid"], run[0]), "body": body})
    return out


def send_text(body: str, text: bool) -> Dict:
    from automations.b2b_dispositions import text_post as tp
    from automations.gap_alerts import config as GA
    if text and not GA.can_text():
        raise RuntimeError("this machine can't text (not in TEXTING_MACHINES)")
    return tp.send_text_to_group(C.TEXT_GROUP, body, dry_run=not text)


# --- main ---------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="post to Slack")
    ap.add_argument("--text", action="store_true", help="text the A-Players room")
    ap.add_argument("--dry-run", action="store_true", help="(default) post nothing")
    ap.add_argument("--day", help="YYYY-MM-DD (default today, Central)")
    ap.add_argument("--only", default="", help="one rep, by name fragment")
    ap.add_argument("--force", action="store_true",
                    help="ignore the selling-hours window and the no-change skip")
    a = ap.parse_args(argv)
    send = a.send and not a.dry_run
    text = a.text and not a.dry_run

    now = _now()
    day = dt.date.fromisoformat(a.day) if a.day else now.date()
    if not a.day and not a.force and not in_window(now):
        _log("outside the selling-hours window (%s) — nothing to do" % _clock(now))
        return 0

    _log("Rep Knock Breakdown %s · %s · %s"
         % (day.isoformat(), _clock(now), "LIVE" if send else "preview"))
    reps = pull(day, only=a.only)
    _log("%d rep(s) knocked on %s" % (len(reps), day.isoformat()))

    from automations.rep_knock_breakdown import render as R
    state = _state()
    out_dir = C.OUT_DIR / day.isoformat() / now.strftime("%H%M")
    day_label = "%s %s" % (day.strftime("%a"), _md(day))
    asof = _clock(now) if day == now.date() else "end of day"
    errors = []
    posted = skipped = 0
    for rep in sorted(reps, key=lambda r: r["name"].lower()):
        try:
            sig_key = "%s|%s" % (day.isoformat(), rep["pid"])
            sig = signature(rep)
            if not a.force and (state.get("last_sig") or {}).get(sig_key) == sig:
                skipped += 1
                continue
            summ = S.summary(rep["rows"])
            pngs = R.render(rep, day_label, asof, out_dir)
            caption = "*%s · %s* — %d knocks · %s" % (
                day_label, asof, summ["knocks"],
                ("%d GPS fail%s" % (summ["gps_fails"], "" if summ["gps_fails"] == 1 else "s"))
                if summ["gps_fails"] else "no GPS fails")
            if summ["longest_fail_run"] >= C.FAIL_STREAK:
                caption += " · :rotating_light: %d in a row" % summ["longest_fail_run"]
            _log("- %s: %s" % (rep["name"], caption))
            ts = thread_ts(state, rep, day, send)
            post_rep(rep, pngs, ts, caption, send)
            if send:
                state.setdefault("last_sig", {})[sig_key] = sig
            posted += 1

            for alert in streak_texts(rep, day):
                if (state.get("texted") or {}).get(alert["key"]):
                    continue
                body = alert["body"]
                link = _permalink(ts) if (send and ts) else ""
                if link:
                    body += "\n" + link
                res = send_text(body, text)
                _log("  %s -> %s: %s" % ("TEXT" if text else "PREVIEW text",
                                         C.TEXT_GROUP, body.replace("\n", " ")))
                if text and res.get("ok"):
                    state.setdefault("texted", {})[alert["key"]] = now.isoformat()
        except Exception as e:  # noqa: BLE001 — one rep, not the pass
            errors.append("%s: %s: %s" % (rep["name"], type(e).__name__, e))
            traceback.print_exc()
        finally:
            if send or text:
                _save_state(state, day)

    _log("done: %d posted, %d unchanged, %d failed" % (posted, skipped, len(errors)))
    for e in errors:
        _log("  FAILED " + e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
