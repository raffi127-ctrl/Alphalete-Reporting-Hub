"""NDS (RES AT&T OOF) -- knocks board, 15-min gaps, call-outs, for Carlos's crew.

    python -m automations.nds_oof.run                 # dry run: pull, render, print
    python -m automations.nds_oof.run --send          # post + queue the texts
    python -m automations.nds_oof.run --send --force  # ignore the clock (hand run)
    python -m automations.nds_oof.run --board         # force the board this tick

ONE TICK, EVERY 15 MINUTES (the LaunchAgent). Each tick opens ONE Ownerville
session as Carlos (this machine's login), pins the RES AT&T OOF campaign,
reads the Time Tracker feed for the gaps, and -- once an hour -- the
Disposition by Rep grid for the board. Then:

  * NDS 15 min gaps (typed, longest-dark first) -> the day's "NDS 15 Min
    Gaps" thread in #alphalete-gp-sales + a text to NEW A Players and
    ATT B2B Leaders. Never an empty list [[feedback_never_post_blank]].
  * NDS Knocks Board (picture, the same renderer every knocks board uses)
    -> the day's "NDS Knocks Board" thread + the same two texts. Hourly.
  * NDS call-out -> loose in #alphalete-gp-sales, once an hour: reps over
    the line whose SaraPlus credit-check count has not moved (the relay's
    records for carlos-b2batt), through icd_alerts.gap_callouts' own lines.

TEXTS ARE HANDED TO THE POLLER (text_dispositions manifests), exactly as the
Box gaps are: this job's identity has no Messages consent, the poller's does.

Replaces the Fiber reports off Raf's login (Carlos 2026-10-19). Raf's own
rooms are not touched by anything here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from automations.nds_oof import config as C
from automations.shared.day_override import weekday as _wd

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "nds_oof"


def _log(msg: str = "") -> None:
    print("[nds] " + msg, flush=True)


# --- clock -------------------------------------------------------------------
def _window(now: dt.datetime):
    wd = _wd(now)
    if wd == 6:
        return None
    return (C.SATURDAY_START, C.SATURDAY_STOP) if wd == 5 else (C.WEEKDAY_START, C.WEEKDAY_STOP)


def in_window(now: dt.datetime) -> bool:
    win = _window(now)
    if not win:
        return False
    (sh, sm), (eh, em) = win
    return (sh, sm) <= (now.hour, now.minute) <= (eh, em)


def _clock(now: dt.datetime) -> str:
    hour = now.hour % 12 or 12
    return "%d:%02d %s" % (hour, now.minute, "AM" if now.hour < 12 else "PM")


def _state() -> Dict:
    try:
        return json.loads(C.STATE_PATH.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save(state: Dict) -> None:
    C.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = C.STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True))
    tmp.replace(C.STATE_PATH)


def _due(state: Dict, key: str, every_min: int, now: dt.datetime) -> bool:
    last = state.get(key)
    if not last:
        return True
    try:
        last_at = dt.datetime.fromisoformat(last)
    except ValueError:
        return True
    # A minute of slack so a 15-minute tick that fires at :14:30 still counts.
    return (now - last_at) >= dt.timedelta(minutes=every_min - 1)


def _board_due(state: Dict, now: dt.datetime) -> bool:
    """ONE BOARD PER CLOCK HOUR, not one per 60 elapsed minutes. The first
    board on 2026-10-21 went at 2:02, every later one at :02, and the 9:00
    pass saw '58 minutes since the last board' and skipped -- 9:15 was past
    the window, so the day's last board was 8:02 (Carlos: 'this is the last
    one i got texted'). Keyed on the hour, the 9:00 pass always draws."""
    last = state.get("board_at")
    if not last:
        return True
    try:
        last_at = dt.datetime.fromisoformat(last)
    except ValueError:
        return True
    return (last_at.date(), last_at.hour) != (now.date(), now.hour)


# --- text --------------------------------------------------------------------
def gaps_text(over: List[Dict], now: dt.datetime) -> str:
    """'NDS 15 min gaps — 3:15 PM' + 'Name - N min', longest first."""
    from automations.b2b_dispositions import capture as cap
    lines = []
    for r in sorted(over, key=lambda r: (-cap._int(r.get("minutesSinceLastKnock")),
                                         (r.get("name") or "").strip().lower())):
        name = (r.get("name") or "").strip()
        if name:
            lines.append("%s - %d min" % (name, cap._int(r.get("minutesSinceLastKnock"))))
    if not lines:
        return ""
    return "%s 15 min gaps — %s\n\n%s" % (C.TEAM, _clock(now).replace(":00", ""), "\n".join(lines))


# --- pull --------------------------------------------------------------------
def pull(today: dt.date, *, want_board: bool, headless: bool = True):
    """ONE session: campaign pinned, gaps feed, and (hourly) the board rows."""
    from automations.shared.tableau_patchright import ownerville_session
    from automations.total_knocks import pull as knocks
    from automations.rashad_metrics import knocks_pull as KP
    from automations.b2b_dispositions import capture as cap
    mdy = today.strftime("%m/%d/%Y")
    rows: List[Dict] = []
    with ownerville_session(headless=headless, profile_dir=str(C.PROFILE_DIR)) as page:
        rqst = knocks._capture_rqst(page)
        if not rqst:
            raise RuntimeError("couldn't capture the ownerville rqst token")
        KP._pin_campaign(page, rqst, C.CAMPAIGN_ID, verbose=True)
        raw = cap.fetch_time_tracking(page, rqst, mdy)
        over = [r for r in raw
                if cap._int(r.get("minutesSinceLastKnock")) > C.GAP_THRESHOLD_MIN]
        if want_board:
            rows = KP._scrape_day_on_page(page, rqst, today, verbose=True)
    _log("gaps feed: %d rep(s), %d over %d min%s"
         % (len(raw), len(over), C.GAP_THRESHOLD_MIN,
            ("; board rows: %d" % len(rows)) if want_board else ""))
    return over, rows


def board_kpis() -> Dict:
    """Raf's KPI scales with THIS crew's First Knock (2:00 start, see config)."""
    from automations.shared import knock_kpis
    (gh, gm), (rh, rm) = C.FIRST_KNOCK_GREEN_AT, C.FIRST_KNOCK_RED_AT
    return {**knock_kpis.load(logfn=_log),
            "first_knock": knock_kpis.Scale(gh * 60 + gm, rh * 60 + rm)}


def render_board(rows: List[Dict], today: dt.date, now: dt.datetime, out_dir: Path) -> List[Path]:
    from automations.total_knocks import render as knocks_render
    pngs, shape = knocks_render.render_knocks_boards(
        today, rows=rows, out_dir=out_dir,
        title_suffix="%s — Carlos" % C.TEAM,
        date_text="%s — %s" % (today.strftime("%a %m/%d"), _clock(now)),
        rate_columns=True, sort_by="knocks", kpis=board_kpis())
    _log("board: %s (%s)" % (", ".join(p.name for p in pngs), shape))
    return list(pngs)


# --- post --------------------------------------------------------------------
def _thread_ts(title: str, today: dt.date) -> Optional[str]:
    from automations.shared import slack_metrics_post as smp
    return smp.ensure_named_thread(title, today, channel_id=C.SLACK_CHANNEL).get("thread_ts")


def _post_board(pngs: List[Path], today: dt.date, now: dt.datetime) -> None:
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    ts = _thread_ts(C.THREAD_BOARD, today)
    for i, p in enumerate(pngs):
        client.files_upload_v2(channel=C.SLACK_CHANNEL, file=str(p), filename=p.name,
                               initial_comment=("*%s Knocks Board — %s*" % (C.TEAM, _clock(now))) if i == 0 else None,
                               thread_ts=ts)
    _log("slack: board -> %s thread" % C.THREAD_BOARD)


def _post_gaps(body: str, today: dt.date) -> None:
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    ts = _thread_ts(C.THREAD_GAPS, today)
    client.chat_postMessage(channel=C.SLACK_CHANNEL, text=body, thread_ts=ts)
    _log("slack: gaps -> %s thread" % C.THREAD_GAPS)


def _queue_text(kind: str, title: str, today: dt.date, now: dt.datetime, *,
                paths: List[Path] = (), text: str = "") -> None:
    """Hand the text to the poller through the b2b_dispositions manifest path
    (the identity with Messages consent). TEXT_ROUTES in b2b config route
    (CAMPAIGN_LABEL, kind) to Carlos's two groups."""
    from automations.b2b_dispositions import text_post as tp
    from automations.b2b_dispositions import run as bd_run
    from automations.day_orchestrator import mini_control as mc
    spec = {"kind": kind, "title": title, "text": text,
            "by_campaign": {C.CAMPAIGN_LABEL: [str(p) for p in paths]}}
    if not tp.spec_has_routes(spec):
        _log("text: no route for %s -- not queued" % kind)
        return
    out_dir = bd_run.OUTPUT_DIR / today.strftime("%Y-%m-%d")
    mp = tp.write_manifest(spec, out_dir, "%s-%s" % (kind, _clock(now)))
    mc.enqueue("text_dispositions", mp.name, by="nds_oof")
    _log("text: queued %s" % mp.name)


def _callout(over: List[Dict], today: dt.date, now: dt.datetime, *, send: bool) -> str:
    """Once an hour: reps over the line with no new credit check. Credit
    checks = the relay's records for carlos-b2batt (his own SaraPlus)."""
    from automations.icd_alerts import gap_callouts as GC
    from automations.icd_alerts import post as P
    key = "nds:carlos"
    st = GC._state().get(key) or {}
    if not GC.due(st, now, C.CALLOUT_EVERY_MIN):
        return ""
    records: Dict[str, int] = {}
    try:
        tab = P._relay_tab()
        for _rownum, row in P._rows_for(today, tab):
            if (row[P.COL_OFFICE] or "").strip().lower() == C.RELAY_OFFICE_KEY:
                records = P._loads(row[P.COL_RECORDS]) or {}
    except Exception as e:  # noqa: BLE001
        _log("call-out: relay records unavailable (%s) -- gaps only" % type(e).__name__)
    prev = (st.get("records") or {}) if st.get("day") == today.isoformat() else dict(records)
    text = GC.line(key, GC.pick_from_gaps(over, records, prev), now)
    if text:
        text = "%s — %s" % (C.TEAM, text)
    if send:
        GC._remember(key, {"day": today.isoformat(),
                           "last_at": now.isoformat(timespec="seconds"),
                           "records": dict(records)})
    return text


# --- tick --------------------------------------------------------------------
def tick(*, send: bool, force: bool, board: bool, headless: bool = True,
         no_gaps: bool = False) -> int:
    now = dt.datetime.now()
    today = now.date()
    if C.CAMPAIGN_ID == "__FILL__":
        _log("CAMPAIGN_ID not set -- run `rerun b2b_dispositions --probe-campaigns` and fill config.py")
        return 1
    if not force and not in_window(now):
        _log("outside the window (%s) -- nothing to do" % now.strftime("%a %H:%M"))
        return 0
    state = _state()
    want_board = board or force or _board_due(state, now)
    want_gaps = (not no_gaps) and (force or _due(state, "gaps_at", C.GAPS_EVERY_MIN, now))
    if not want_board and not want_gaps:
        _log("nothing due at %s" % _clock(now))
        return 0
    out_dir = OUTPUT_DIR / today.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    over, rows = pull(today, want_board=want_board, headless=headless)

    body = gaps_text(over, now) if want_gaps else ""
    pngs = render_board(rows, today, now, out_dir) if (want_board and rows) else []
    if want_board and not rows:
        _log("board: no rows on the grid -- not drawn (never post blank)")
    callout = "" if no_gaps else _callout(over, today, now, send=send)

    if not send:
        _log("DRY RUN -- would post:")
        _log("  board: %s" % (", ".join(p.name for p in pngs) or "(none)"))
        _log("  gaps:\n%s" % (body or "(nobody over 15 min)"))
        _log("  call-out: %s" % (callout or "(none)"))
        return 0

    from automations.icd_alerts import post as P
    if pngs:
        _post_board(pngs, today, now)
        _queue_text(C.KIND_BOARD, "%s Knocks Board — %s" % (C.TEAM, _clock(now)), today, now, paths=pngs)
        state["board_at"] = now.isoformat(timespec="seconds")
    if body:
        _post_gaps(body, today)
        _queue_text(C.KIND_GAPS, body.splitlines()[0], today, now, text=body)
    else:
        _log("gaps: nobody over 15 min -- nothing posted")
    if want_gaps:
        state["gaps_at"] = now.isoformat(timespec="seconds")
    if callout:
        P._slack(C.SLACK_CHANNEL, callout)
        _log("slack: call-out posted")
    _save(state)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true", help="post to Slack and queue the texts")
    ap.add_argument("--force", action="store_true", help="ignore the window and the cadences")
    ap.add_argument("--board", action="store_true", help="draw the board this tick")
    ap.add_argument("--no-gaps", action="store_true",
                    help="board only: no gap list, no call-out (a hand run after hours)")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args(argv)
    return tick(send=args.send, force=args.force, board=args.board,
                headless=not args.headed, no_gaps=args.no_gaps)


if __name__ == "__main__":
    sys.exit(main())
