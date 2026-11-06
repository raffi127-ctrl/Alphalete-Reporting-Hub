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
from typing import Dict, List, Optional, Tuple

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
    start, stop = (C.SATURDAY_START, C.SATURDAY_STOP) if wd == 5 else (C.WEEKDAY_START, C.WEEKDAY_STOP)
    start = getattr(C, "START_OVERRIDES", {}).get(now.date().isoformat(), start)
    return start, stop


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
    return _board_slot(last_at) != _board_slot(now)


def _board_slot(t: dt.datetime):
    """The board slot `t` falls in: every BOARD_EVERY_MIN of the clock (:00
    and :30), or the named slots of an hour that has them (Saturday 10:15 /
    10:30 / 10:45). One board per slot, however late the tick runs."""
    extras = [m for (h, m) in (C.SAT_EXTRA_BOARD_SLOTS if _wd(t) == 5
                               else C.EXTRA_BOARD_SLOTS) if h == t.hour]
    if extras:                       # an hour with its own named slots
        sub = sum(1 for m in extras if t.minute >= m)
    else:                            # otherwise one board per BOARD_EVERY_MIN
        sub = t.minute // C.BOARD_EVERY_MIN
    return (t.date(), t.hour, sub)


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


def _parse_at(text: str) -> Optional[dt.datetime]:
    """'2026-11-03T14:31:00' (Lucy Knocks) or '11/6/2026 10:14:45' (ICD)."""
    text = (text or "").strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _borrow_sources(today: dt.date) -> Dict[str, Tuple[List[Dict], Optional[dt.datetime], str]]:
    """{borrow key: (renderer rows, when shared, where from)} for today.

    Two places, newest wins: the 'Lucy Knocks' row a Lucy's gap_alerts
    shares (how Raf's rows arrived until 2026-11-03) and the 'ICD Knocks'
    relay his own office Mac writes now (C.BORROWED_ICD_OFFICES), read the
    way the owners' hourly board reads every office. Never raises."""
    want = getattr(C, "BORROWED_ROWS", None) or {}
    out: Dict[str, Tuple[List[Dict], Optional[dt.datetime], str]] = {}
    if not want:
        return out
    from automations.owner_knocks_hourly import share as S
    try:
        book = S._book()
    except Exception as e:  # noqa: BLE001
        _log("borrowed: relay workbook unavailable (%s) -- board without them" % type(e).__name__)
        return out
    try:
        ws = S._tab(book)
        lines = ws.get_all_values()[1:] if ws is not None else []
    except Exception as e:  # noqa: BLE001
        _log("borrowed: 'Lucy Knocks' tab unavailable (%s)" % type(e).__name__)
        lines = []
    for r in lines:
        r = list(r) + [""] * (len(S.HEADER) - len(r))
        key = r[S.K_KEY].strip().lower()
        if key not in want or r[S.K_DAY].strip() != today.isoformat():
            continue
        try:
            src = json.loads(r[S.K_ROWS] or "[]")
        except ValueError:
            src = []
        out[key] = (src, _parse_at(r[S.K_AT]), "Lucy Knocks")

    icd = getattr(C, "BORROWED_ICD_OFFICES", None) or {}
    by_office = {str(o).strip().lower(): k for k, o in icd.items() if k in want}
    if not by_office:
        return out
    try:
        from automations.icd_alerts import knocks_map as KM, knocks_post as KP
        from automations.icd_alerts import post as P
        klines = book.worksheet(KP.KNOCKS_TAB).get_all_values()[1:]
    except Exception as e:  # noqa: BLE001
        _log("borrowed: 'ICD Knocks' tab unavailable (%s)" % type(e).__name__)
        return out
    try:
        from automations.icd_alerts import offices as O
        offices = O.all_offices()
    except Exception:  # noqa: BLE001
        offices = {}
    for row in klines:
        row = list(row) + [""] * (KP.KN_POSTED + 1 - len(row))
        okey = (row[KP.KN_OFFICE] or "").strip().lower()
        key = by_office.get(okey)
        if not key:
            continue
        try:
            day_key = P._day_key(row[KP.KN_DAY])
        except Exception:  # noqa: BLE001
            day_key = (row[KP.KN_DAY] or "").strip()
        if day_key != today.isoformat():
            continue
        try:
            raw = json.loads(row[KP.KN_ROWS] or "[]")
            tracker = json.loads(row[KP.KN_TRACKER] or "[]")
        except ValueError:
            _log("borrowed: ICD Knocks row for %s unreadable" % okey)
            continue
        try:
            raw, tracker = KP.shift_ov_clock(offices.get(okey), raw, tracker)
        except Exception:  # noqa: BLE001
            pass
        try:
            rows = KM.to_rows(raw, tracker)
        except Exception as e:  # noqa: BLE001
            _log("borrowed: ICD Knocks rows for %s did not map (%s)" % (okey, type(e).__name__))
            continue
        at = _parse_at(row[KP.KN_RECEIVED])
        prev = out.get(key)
        newer = prev is None or (at is not None and (prev[1] is None or at > prev[1]))
        # An empty relay row still counts: his Mac has reported and nobody
        # has knocked yet, which is "0 rows on raf's relay", not "no relay".
        if newer:
            out[key] = (rows, at, "ICD Knocks office %s" % okey)
    return out


def _shared_at(today: dt.date) -> Dict[str, dt.datetime]:
    """{key: when it was shared} for today's borrowed rows, whichever tab."""
    return {k: at for k, (_rows, at, _src) in _borrow_sources(today).items() if at}


def wait_for_fresh_share(now: dt.datetime, *, shared_at, sleep=None,
                         max_wait_min: Optional[int] = None) -> bool:
    """Hold the board until every borrowed key has been shared since this
    slot began (the :00/:30 boundary), or max_wait_min is up. `shared_at()`
    returns {key: datetime}; `sleep(seconds)` is injectable for tests.
    True = fresh, False = gave up (the board still draws)."""
    import time as _time
    want = getattr(C, "BORROWED_ROWS", None) or {}
    if not want:
        return True
    max_wait = C.BORROWED_FRESH_WAIT_MIN if max_wait_min is None else max_wait_min
    sleep = sleep or _time.sleep
    slot_start = now.replace(minute=(now.minute // C.BOARD_EVERY_MIN) * C.BOARD_EVERY_MIN,
                             second=0, microsecond=0)
    # Off the real clock, like the check below: `now` is the slot's
    # reference time, not necessarily this instant (the tests pass a fixed
    # one, and a deadline built from it had already passed).
    deadline = dt.datetime.now() + dt.timedelta(minutes=max_wait)
    waited = False
    while True:
        at = shared_at()
        stale = [k for k in want if not at.get(k) or at[k] < slot_start]
        if not stale:
            if waited:
                _log("borrowed: fresh share arrived (%s)" % ", ".join(
                    "%s %s" % (k, at[k].strftime("%H:%M:%S")) for k in want))
            return True
        if dt.datetime.now() >= deadline:
            _log("borrowed: no share since %s for %s after %d min -- drawing with what is there"
                 % (slot_start.strftime("%H:%M"), ", ".join(stale), max_wait))
            return False
        if not waited:
            _log("borrowed: waiting for %s's share (last %s, slot %s)"
                 % (", ".join(stale),
                    ", ".join((at[k].strftime("%H:%M:%S") if at.get(k) else "none") for k in stale),
                    slot_start.strftime("%H:%M")))
        waited = True
        sleep(30)


def borrowed_rows(today: dt.date, own: List[Dict]) -> List[Dict]:
    """Rows for C.BORROWED_ROWS off today's shared/relayed rows (_borrow_sources),
    matched like total_knocks.guests. A name already on `own` is left off, a
    name with no row today is logged. Never raises: the board matters more
    than the borrowed names."""
    want = getattr(C, "BORROWED_ROWS", None) or {}
    if not want:
        return []
    from automations.total_knocks import guests as G
    have = {G._norm(G._rep(r)) for r in own}
    keep = set(own[0].keys()) if own else None
    out: List[Dict] = []
    sources = _borrow_sources(today)
    seen = set()
    for key, (src, at, where) in sources.items():
        seen.add(key)
        at_text = at.isoformat(timespec="seconds") if at else "?"
        claimed, missing = G.match_rows(src, want[key])
        for i, name in sorted(claimed.items()):
            row = src[i]
            if G._norm(G._rep(row)) in have:
                _log("borrowed: %s is already on our own rows -- not doubled" % name)
                continue
            if keep:
                row = {k: v for k, v in row.items() if k in keep}
            out.append(row)
            _log("borrowed: %s off %s (shared %s, %s)" % (G._rep(src[i]), key, at_text, where))
        for name in missing:
            # Close spellings, so a roster typo is fixable from the log alone
            # (Carlos: "i may have slight mispelling"): any row sharing a
            # token (a last name, usually) with the wanted name.
            toks = set(G._plain(name).split())
            close = [G._rep(x) for x in src
                     if toks & set(G._plain(G._rep(x)).split())]
            _log("borrowed: %s not on %s's rows today%s"
                 % (name, key, (" (close: %s)" % ", ".join(close)) if close else
                    " (%d rows: %s)" % (len(src), ", ".join(G._rep(x) for x in src)[:400])))
    for key in want:
        if key not in seen:
            _log("borrowed: no 'Lucy Knocks' row and no 'ICD Knocks' relay for %s today" % key)
    return out


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
    """The day's NDS METRICS thread first (Carlos 2026-10-22: 'remove the
    NDS knocks board and NDS 15 min gaps thread and just post that stuff
    into the NDS metrics thread' — the Box pattern). nds_metrics runs on
    THIS machine, so its state file is the authority; the old named thread
    is the fallback when the metrics thread hasn't opened yet (pre-7:30)."""
    import json
    from pathlib import Path
    state = (Path(__file__).resolve().parents[2] / "output" / "nds_metrics"
             / f"thread_{today.isoformat()}.json")
    try:
        ts = json.loads(state.read_text()).get("ts")
        if ts:
            return ts
    except Exception:  # noqa: BLE001 — no metrics thread yet
        pass
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
    (the identity with Messages consent) via the local text outbox. TEXT_ROUTES
    in b2b config route (CAMPAIGN_LABEL, kind) to Carlos's two groups."""
    from automations.b2b_dispositions import text_post as tp
    from automations.b2b_dispositions import run as bd_run
    from automations.day_orchestrator import text_outbox as tob
    spec = {"kind": kind, "title": title, "text": text,
            "by_campaign": {C.CAMPAIGN_LABEL: [str(p) for p in paths]}}
    if not tp.spec_has_routes(spec):
        _log("text: no route for %s -- not queued" % kind)
        return
    out_dir = bd_run.OUTPUT_DIR / today.strftime("%Y-%m-%d")
    mp = tp.write_manifest(spec, out_dir, "%s-%s" % (kind, _clock(now)))
    # Local outbox, NOT the Mini Control sheet: on 2026-10-26 the sheet stopped
    # answering and each enqueue hung ~9 min, so the boards posted 20-40 min
    # late and the texts never left. The poller drains the outbox every loop.
    tob.drop(mp, by="nds_oof", day=today.isoformat())
    _log("text: outbox %s" % mp.name)


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


# --- the Saturday Mon–Sat board ---------------------------------------------
def _week_due(state: Dict, now: dt.datetime) -> bool:
    if _wd(now) != 5 or (now.hour, now.minute) < C.WEEK_AFTER:
        return False
    return state.get("week_at") != now.date().isoformat()


def _week_monday_due(state: Dict, now: dt.datetime) -> bool:
    """Monday at/after WEEK_MONDAY_AFTER, once: last week's board into today's
    NDS Metrics thread. Real Monday only (never a day_override Saturday)."""
    if now.weekday() != 0 or (now.hour, now.minute) < C.WEEK_MONDAY_AFTER:
        return False
    return state.get("week_monday_at") != now.date().isoformat()


def weekly_board(saturday: dt.date, *, send: bool,
                 thread_prefix: str = "") -> int:
    """Run weekly_knock_dispositions for the NDS row (it posts the picture
    into Saturday's "NDS Knocks Board" thread), then text the same picture to
    the two chats. Dry by default: renders, posts nothing.

    `thread_prefix` (a hand run, Carlos 2026-10-26: "have last weeks totals
    post on the nds metrics tab. just today"): render only, then put the
    picture as a reply under TODAY's thread whose text starts with that
    prefix (e.g. "NDS Metrics —"). No texts."""
    from automations.weekly_knock_dispositions import run as W
    argv = ["--office", C.WEEK_ROW_KEY, saturday.isoformat()]
    argv += ["--live"] if (send and not thread_prefix) else ["--dry-run"]
    _log("weekly board: weekly_knock_dispositions %s" % " ".join(argv))
    rc = W.main(argv)
    if rc:
        _log("weekly board: module returned %s" % rc)
        return rc
    png = (Path(W.OUT_DIR) / W._slug(C.WEEK_ROW_KEY)
           / ("weekly_knock_dispositions_%s.png" % saturday.isoformat()))
    if not png.exists():
        _log("weekly board: no picture at %s" % png)
        return 1
    monday = saturday - dt.timedelta(days=5)
    title = "%s Knocks Board — Mon–Sat %s–%s" % (
        C.TEAM, monday.strftime("%-m/%-d"), saturday.strftime("%-m/%-d"))
    if thread_prefix:
        from automations.shared import slack_metrics_post as smp
        client = smp._client()
        today = dt.date.today()
        oldest = dt.datetime.combine(today, dt.time.min).timestamp()
        hist = client.conversations_history(channel=C.SLACK_CHANNEL, oldest=str(oldest), limit=300)
        ts = next((m.get("thread_ts") or m.get("ts") for m in hist.get("messages", [])
                   if (m.get("text") or "").replace("*", "").startswith(thread_prefix)), None)
        if not ts:
            _log("no thread today starting with %r" % thread_prefix)
            return 1
        # Already there (a hand run and the Monday tick on the same day, or a
        # rerun): one copy per thread, never two.
        try:
            reps = client.conversations_replies(channel=C.SLACK_CHANNEL, ts=ts, limit=200)
            if any((m.get("text") or "").replace("*", "").startswith(title)
                   for m in reps.get("messages", [])[1:]):
                _log("%s is already in today's %r thread -- not posting again" % (title, thread_prefix))
                return 0
        except Exception as e:  # noqa: BLE001
            _log("reply check failed (%s) -- posting anyway" % type(e).__name__)
        if not send:
            _log("DRY RUN -- would post %s into thread %s (%r)" % (png, ts, thread_prefix))
            return 0
        client.files_upload_v2(channel=C.SLACK_CHANNEL, file=str(png), filename=png.name,
                               initial_comment="*%s*" % title, thread_ts=ts)
        _log("posted %s into today's %r thread" % (title, thread_prefix))
        return 0
    if send:
        _queue_text(C.KIND_WEEK, title, saturday, dt.datetime.now(), paths=[png])
    else:
        _log("DRY RUN -- would text %s: %s" % (title, png))
    return 0


# --- tick --------------------------------------------------------------------
# ---------------------------------------------------------------- no dispos --

def no_dispo_slot(now: dt.datetime) -> Optional[str]:
    """'HH:MM' of the NO_DISPO_SLOTS slot `now` sits in (within the grace), on
    a NO_DISPO_WEEKDAYS day; None otherwise."""
    if now.weekday() not in C.NO_DISPO_WEEKDAYS:
        return None
    for h, m in C.NO_DISPO_SLOTS:
        slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if 0 <= (now - slot).total_seconds() < C.NO_DISPO_SLOT_GRACE_MIN * 60:
            return slot.strftime("%H:%M")
    return None


def station_names(values: List[List[str]]) -> List[str]:
    """The names in the car-ride grid, left to right then down, blanks out,
    first appearance wins."""
    out: List[str] = []
    seen = set()
    for row in values or []:
        for cell in row or []:
            name = " ".join(str(cell or "").split())
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append(name)
    return out


def _read_station_names() -> List[str]:
    from automations.recruiting_report import fill as _fill
    ws = _fill.open_by_key(C.NO_DISPO_SHEET_ID).worksheet(C.NO_DISPO_TAB)
    return station_names(ws.get(C.NO_DISPO_RANGE))


def _knocks(row: Dict) -> int:
    for k in ("Total Knocks", "Knocks", "Total"):
        v = row.get(k)
        if v not in (None, ""):
            try:
                return int(str(v).replace(",", "").strip() or 0)
            except ValueError:
                return 0
    return 0


def no_dispo_names(names: List[str], rows: List[Dict]) -> List[str]:
    """Roster names with no dispositions on `rows`: no row at all, or a row
    with zero knocks. Matched like total_knocks.guests (exact -> plain ->
    first+last -> tokens), so a middle name on one side does not count as
    absent."""
    from automations.total_knocks import guests as G
    rows = list(rows or [])
    claimed, missing = G.match_rows(rows, names)
    has = {name for i, name in claimed.items() if _knocks(rows[i]) > 0}
    return [n for n in names if n not in has]


def no_dispo_text(missing: List[str], slot: str) -> str:
    """Carlos's wording: 'No dispositions from,' then the names."""
    hh, mm = slot.split(":")
    h = int(hh)
    clock = "%d:%s %s" % (h % 12 or 12, mm, "PM" if h >= 12 else "AM")
    return "No dispositions from (%s): %s" % (clock, ", ".join(missing))


def _no_dispo_message(today: dt.date, now: dt.datetime, rows: List[Dict],
                      state: Dict, *, send: bool) -> str:
    """The message for this slot, or ''. Never raises: a sheet hiccup costs
    this slot's message, not the tick."""
    slot = no_dispo_slot(now)
    if not slot:
        return ""
    key = "%s %s" % (today.isoformat(), slot)
    if state.get("no_dispo_slot") == key:
        return ""
    try:
        names = _read_station_names()
    except Exception as e:  # noqa: BLE001
        _log("no-dispo: Stations %s unreadable (%s) -- skipped this slot"
             % (C.NO_DISPO_RANGE, type(e).__name__))
        return ""
    if not names:
        _log("no-dispo: no names in Stations %s -- nothing to check" % C.NO_DISPO_RANGE)
        return ""
    everyone = rows + borrowed_rows(today, rows)
    missing = no_dispo_names(names, everyone)
    _log("no-dispo %s: %d on the car-ride grid, %d without dispositions%s"
         % (slot, len(names), len(missing), (": " + ", ".join(missing)) if missing else ""))
    if send:
        state["no_dispo_slot"] = key
    return no_dispo_text(missing, slot) if missing else ""


def tick(*, send: bool, force: bool, board: bool, headless: bool = True,
         no_gaps: bool = False) -> int:
    now = dt.datetime.now()
    today = now.date()
    state = _state()
    if _week_due(state, now):
        # After the 5:30 board on a Saturday: the Mon–Sat combined board. Done
        # here, before the window check, so a missed 5:30 tick still gets it
        # on the next one. Marked only on a real send.
        rc = weekly_board(today, send=send)
        if send and rc == 0:
            state["week_at"] = today.isoformat()
            _save(state)
    if _week_monday_due(state, now):
        # Monday morning: last week's Mon–Sat board as a reply in today's NDS
        # Metrics thread (Carlos 2026-11-02). Slack only; marked on a real post.
        last_sat = today - dt.timedelta(days=2)
        rc = weekly_board(last_sat, send=send, thread_prefix=C.WEEK_MONDAY_THREAD)
        if send and rc == 0:
            state["week_monday_at"] = today.isoformat()
            _save(state)
    if C.CAMPAIGN_ID == "__FILL__":
        _log("CAMPAIGN_ID not set -- run `rerun b2b_dispositions --probe-campaigns` and fill config.py")
        return 1
    if not force and not in_window(now):
        _log("outside the window (%s) -- nothing to do" % now.strftime("%a %H:%M"))
        return 0
    want_board = board or force or _board_due(state, now)
    want_gaps = (not no_gaps) and (force or _due(state, "gaps_at", C.GAPS_EVERY_MIN, now))
    if not want_board and not want_gaps:
        _log("nothing due at %s" % _clock(now))
        return 0
    out_dir = OUTPUT_DIR / today.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    if want_board and not force:
        # Raf's numbers for the borrowed reps land ~4 min into the slot; our
        # own pull happens AFTER so both halves of the board are fresh.
        wait_for_fresh_share(now, shared_at=lambda: _shared_at(today))
    over, rows = pull(today, want_board=want_board, headless=headless)
    # Cinthya + Nathaly, knocking on Raf's Ownerville (config.BORROWED_ROWS):
    # on OUR board picture only. `rows` (our own) is what goes to the owners'
    # board share below -- Raf's row there already carries them.
    board_rows = (rows + borrowed_rows(today, rows)) if want_board else rows
    if send and want_board and rows:
        # Carlos's NDS crew on the owners' hourly knocks board (Eve
        # 2026-10-29) -- that board runs on Lucy 1 and cannot see this disk.
        from automations.owner_knocks_hourly import config as OK, share
        share.share(OK.CARLOS_NDS_KEY, OK.CARLOS_NAME, today, rows, log=_log)

    body = gaps_text(over, now) if want_gaps else ""
    pngs = render_board(board_rows, today, now, out_dir) if (want_board and board_rows) else []
    if want_board and not board_rows:
        _log("board: no rows on the grid -- not drawn (never post blank)")
    callout = "" if no_gaps else _callout(over, today, now, send=send)
    no_dispo = _no_dispo_message(today, now, rows, state, send=send and C.NO_DISPO_SEND)

    if not send:
        _log("DRY RUN -- would post:")
        _log("  board: %s" % (", ".join(p.name for p in pngs) or "(none)"))
        _log("  gaps:\n%s" % (body or "(nobody over 15 min)"))
        _log("  call-out: %s" % (callout or "(none)"))
        _log("  no-dispo: %s" % (no_dispo or "(none)"))
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
    if no_dispo:
        if C.NO_DISPO_SEND:
            P._slack(C.SLACK_CHANNEL, no_dispo)
            _queue_text(C.KIND_NO_DISPO, no_dispo.split(":")[0], today, now, text=no_dispo)
            _log("slack: no-dispo posted")
        else:
            _log("no-dispo (NO_DISPO_SEND off, not posted): %s" % no_dispo)
    _save(state)
    return 0


def _share_dump() -> int:
    """Diagnostic: what is on the relay workbook's 'Lucy Knocks' tab right
    now, as Lucy 2 sees it (the mini cannot read that workbook)."""
    import json as _json
    from automations.owner_knocks_hourly import share as S
    from automations.total_knocks import guests as G
    want = [n for ns in (getattr(C, "BORROWED_ROWS", {}) or {}).values() for n in ns]
    try:
        ws = S._tab(S._book())
        lines = ws.get_all_values() if ws is not None else []
    except Exception as e:  # noqa: BLE001
        _log("share-dump: tab unavailable: %s: %s" % (type(e).__name__, str(e)[:160]))
        return 1
    _log("share-dump: %d row(s) incl. header; header=%s" % (len(lines), lines[:1]))
    for r in lines[1:]:
        r = list(r) + [""] * (len(S.HEADER) - len(r))
        try:
            rows = _json.loads(r[S.K_ROWS] or "[]")
        except ValueError:
            rows = None
        hits = []
        if rows:
            try:
                hit_map, _missing = G.match_rows(rows, want)
                hits = [G._rep(rows[i]) for i in hit_map]
            except Exception as e:  # noqa: BLE001
                hits = ["(match failed: %s)" % type(e).__name__]
        _log("share-dump: key=%r owner=%r day=%r at=%r rows=%s hits=%s"
             % (r[S.K_KEY], r[S.K_OWNER], r[S.K_DAY], r[S.K_AT],
                "bad-json" if rows is None else len(rows), hits))
    # The office Macs' own relay ('ICD Knocks') -- where Raf's rows live
    # since his board left Lucy 1 (2026-11-03).
    try:
        from automations.icd_alerts import knocks_map as KM, knocks_post as KP
        kws = S._book().worksheet(KP.KNOCKS_TAB)
        klines = kws.get_all_values()
    except Exception as e:  # noqa: BLE001
        _log("share-dump: '%s' unavailable: %s: %s"
             % ("ICD Knocks", type(e).__name__, str(e)[:160]))
        return 0
    _log("share-dump: ICD Knocks %d row(s); header=%s" % (len(klines), klines[:1]))
    for row in klines[1:]:
        row = list(row) + [""] * (KP.KN_POSTED + 1 - len(row))
        try:
            raw = _json.loads(row[KP.KN_ROWS] or "[]")
            tracker = _json.loads(row[KP.KN_TRACKER] or "[]")
            rows = KM.to_rows(raw, tracker)
        except Exception as e:  # noqa: BLE001
            rows = None
            err = type(e).__name__
        hits = []
        if rows:
            try:
                hit_map, _m = G.match_rows(rows, want)
                hits = [G._rep(rows[i]) for i in hit_map]
            except Exception as e:  # noqa: BLE001
                hits = ["(match failed: %s)" % type(e).__name__]
        _log("share-dump: ICD office=%r day=%r received=%r rows=%s keys=%s hits=%s"
             % (row[KP.KN_OFFICE], row[KP.KN_DAY], row[KP.KN_RECEIVED],
                ("bad: " + err) if rows is None else len(rows),
                sorted(rows[0].keys())[:8] if rows else [], hits))
        okey = (row[KP.KN_OFFICE] or "").strip().lower()
        if okey in {str(o).lower() for o in (getattr(C, "BORROWED_ICD_OFFICES", {}) or {}).values()}:
            # Every name, raw grid and mapped, to the control sheet (logtail
            # truncates): is a borrowed rep missing from the relay itself,
            # or dropped by the map?
            try:
                raw = _json.loads(row[KP.KN_ROWS] or "[]")
                tracker = _json.loads(row[KP.KN_TRACKER] or "[]")
            except ValueError:
                raw, tracker = [], []
            lines = ["raw grid rows: %d; tracker rows: %d; mapped rows: %s"
                     % (len(raw), len(tracker), len(rows) if rows else 0)]
            if raw:
                lines.append("raw keys: " + ", ".join(sorted(raw[0].keys())))
            lines += ["raw: " + " | ".join(str(v) for v in x.values())[:300] for x in raw]
            lines += ["tracker: " + " | ".join(str(v) for v in x.values())[:200] for x in tracker]
            lines += ["mapped: " + G._rep(x) for x in (rows or [])]
            from automations.nds_tnc_check.run import _probe_dump
            _probe_dump("ICD Knocks office %s %s" % (okey, row[KP.KN_DAY]), lines, log=_log)
    return 0


# --- the week recap (one thread, all the pictures) ---------------------------
def recap_days(saturday: dt.date) -> List[dt.date]:
    """Mon..Sat of the week that ends on `saturday`."""
    monday = saturday - dt.timedelta(days=5)
    return [monday + dt.timedelta(days=i) for i in range(6)]


def _last_board_from_slack(day: dt.date, client):
    """A day with no board on disk: pull the LAST '*NDS Knocks Board — H:MM*'
    reply (with its picture) back out of that day's NDS Metrics thread in
    #alphalete-gp-sales. -> (downloaded paths, clock text)."""
    import requests
    state = (Path(__file__).resolve().parents[2] / "output" / "nds_metrics"
             / f"thread_{day.isoformat()}.json")
    try:
        ts = json.loads(state.read_text()).get("ts")
    except Exception:  # noqa: BLE001
        ts = None
    if not ts:
        _log("%s: no NDS Metrics thread state on this box" % day)
        return [], ""
    reps = client.conversations_replies(channel=C.SLACK_CHANNEL, ts=ts, limit=500)
    prefix = "%s Knocks Board — " % C.TEAM
    hits = [m for m in reps.get("messages", [])[1:]
            if (m.get("text") or "").replace("*", "").startswith(prefix)
            and "Mon–Sat" not in (m.get("text") or "") and m.get("files")]
    if not hits:
        _log("%s: no board reply in the NDS Metrics thread" % day)
        return [], ""
    last = max(hits, key=lambda m: float(m.get("ts") or 0))
    clock = (last.get("text") or "").replace("*", "").split("— ", 1)[-1].strip()
    out_dir = OUTPUT_DIR / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in last.get("files", []):
        url = f.get("url_private_download") or f.get("url_private")
        if not url:
            continue
        r = requests.get(url, headers={"Authorization": "Bearer %s" % client.token},
                         timeout=60)
        if r.status_code != 200 or len(r.content) < 1000:
            _log("%s: download of %s failed (%s)" % (day, f.get("name"), r.status_code))
            continue
        dest = out_dir / ("slack_%s" % (f.get("name") or "board.png"))
        dest.write_bytes(r.content)
        paths.append(dest)
    return paths, clock


def recap_week(saturday: dt.date, *, channel: str, send: bool) -> int:
    """Carlos 2026-11-06: "send me the weekly knocks board for last week and
    each individual end of day knocks for last week. Create a thread on the a
    players slack and post them all on there." ONE new thread in `channel`
    (config.RECAP_CHANNEL = #a-players-b2b): the Mon–Sat combined board
    first, then each day's LAST board of the day. output/nds_oof/<date>/
    holds one board per day that every tick overwrites, so the file on disk
    IS the end-of-day picture; a day with nothing on disk is fetched back
    from that day's NDS Metrics thread. Dry by default: lists the plan."""
    from automations.weekly_knock_dispositions import run as W
    days = recap_days(saturday)
    monday = days[0]
    png = (Path(W.OUT_DIR) / W._slug(C.WEEK_ROW_KEY)
           / ("weekly_knock_dispositions_%s.png" % saturday.isoformat()))
    if not png.exists():
        _log("weekly board: not on disk -- rendering it (dry) with weekly_knock_dispositions")
        W.main(["--office", C.WEEK_ROW_KEY, saturday.isoformat(), "--dry-run"])
    if not png.exists():
        _log("weekly board: still no picture at %s" % png)
        return 1
    span = "%s–%s" % (monday.strftime("%-m/%-d"), saturday.strftime("%-m/%-d"))
    items = [(png, "*%s Knocks Board — Mon–Sat %s*" % (C.TEAM, span))]
    _log("weekly: %s" % png)
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    for d in days:
        ddir = OUTPUT_DIR / d.isoformat()
        pngs = (sorted((p for p in ddir.glob("*.png") if not p.name.startswith("slack_")),
                       key=lambda p: p.stat().st_mtime) if ddir.exists() else [])
        src = "disk"
        if pngs:
            newest = pngs[-1].stat().st_mtime
            pngs = [p for p in pngs if newest - p.stat().st_mtime < 120]   # the last tick's set
            when = dt.datetime.fromtimestamp(newest).strftime("%-I:%M %p")
        else:
            src = "slack"
            pngs, when = _last_board_from_slack(d, client)
        if not pngs:
            _log("%s: no end-of-day board anywhere -- skipped" % d)
            continue
        label = "*%s Knocks Board — %s %s, end of day (%s)*" % (
            C.TEAM, d.strftime("%a"), d.strftime("%-m/%-d"), when)
        for i, p in enumerate(pngs):
            items.append((p, label if i == 0 else None))
        _log("%s: %s (%s, %s)" % (d, ", ".join(p.name for p in pngs), src, when))
    head = ("*%s Knocks — week of Mon %s – Sat %s*\nThe Mon–Sat board, then each "
            "day's end-of-day board, in this thread." % (
                C.TEAM, monday.strftime("%-m/%-d"), saturday.strftime("%-m/%-d")))
    # Never twice (2026-11-06: the queue re-ran a --send row and the room
    # got the thread two times): a parent with this exact text today = done.
    oldest = dt.datetime.combine(dt.date.today(), dt.time.min).timestamp()
    try:
        hist = client.conversations_history(channel=channel, oldest=str(oldest), limit=200)
        dup = next((m for m in hist.get("messages", [])
                    if (m.get("text") or "").strip() == head.strip()), None)
    except Exception as e:  # noqa: BLE001
        _log("history check failed (%s) -- going ahead" % type(e).__name__)
        dup = None
    if dup:
        _log("already in %s today (parent %s) -- not posting again" % (channel, dup.get("ts")))
        return 0
    if not send:
        _log("DRY RUN -- would open a thread in %s:\n%s\nand post %d picture(s)"
             % (channel, head, len(items)))
        return 0
    parent = client.chat_postMessage(channel=channel, text=head)
    ts = parent["ts"]
    for p, comment in items:
        client.files_upload_v2(channel=channel, file=str(p), filename=p.name,
                               initial_comment=comment, thread_ts=ts)
    _log("posted %d picture(s) in a new thread (%s) in %s" % (len(items), ts, channel))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--send", action="store_true", help="post to Slack and queue the texts")
    ap.add_argument("--force", action="store_true", help="ignore the window and the cadences")
    ap.add_argument("--board", action="store_true", help="draw the board this tick")
    ap.add_argument("--week", metavar="SATURDAY",
                    help="run the Mon–Sat combined board for that Saturday "
                         "(YYYY-MM-DD) and exit; --send posts and texts it")
    ap.add_argument("--week-thread", metavar="PREFIX", default="",
                    help="with --week: post the picture into TODAY's thread whose "
                         "text starts with PREFIX, Slack only (no texts)")
    ap.add_argument("--compare", metavar="SATURDAY",
                    help="week-over-week board (that week vs the one before), "
                         "every rep and stat, into today's --week-thread thread; "
                         "--send posts it (Slack only)")
    ap.add_argument("--no-gaps", action="store_true",
                    help="board only: no gap list, no call-out (a hand run after hours)")
    ap.add_argument("--recap-week", metavar="SATURDAY",
                    help="one new thread with that week's Mon–Sat board + every "
                         "day's end-of-day board (YYYY-MM-DD); --send posts it")
    ap.add_argument("--recap-channel", default=C.RECAP_CHANNEL,
                    help="where --recap-week opens its thread (default #a-players-b2b)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--share-dump", action="store_true",
                    help="print every 'Lucy Knocks' row (key/owner/day/at/"
                         "rows + the borrowed names found) and exit")
    args = ap.parse_args(argv)
    if args.share_dump:
        return _share_dump()
    if args.recap_week:
        return recap_week(dt.date.fromisoformat(args.recap_week),
                          channel=args.recap_channel, send=args.send)
    if args.compare:
        from automations.nds_oof import week_compare as WC
        return WC.post(dt.date.fromisoformat(args.compare),
                       thread_prefix=args.week_thread or C.WEEK_MONDAY_THREAD,
                       send=args.send)
    if args.week:
        return weekly_board(dt.date.fromisoformat(args.week), send=args.send,
                            thread_prefix=args.week_thread)
    return tick(send=args.send, force=args.force, board=args.board,
                headless=not args.headed, no_gaps=args.no_gaps)


if __name__ == "__main__":
    sys.exit(main())
