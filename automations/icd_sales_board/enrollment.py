"""What every office is enrolled in, and when each thing runs.

Megan 2026-10-05: a link anyone can open showing "what everyone is enrolled in
and on what schedule". Nobody could answer that without opening five
registries, so it was answered five different ways.

ASSEMBLED, NEVER RE-KEYED. Every column reads the registry that already
decides it, so this page cannot drift from what actually runs:

  Sara+ Alerts        'Office Channels' tab, Alerts Approved
  Text Scoreboard     same tab, Texts Approved
  Knock & Dispo       same tab, Knocks Approved
  Resume Pushing      applicant_push.OFFICES
  Metrics thread      office_metrics.OFFICES + its schedule_config entry
  Trackers            office_metrics (a metrics office gets the tracker set)
  Dispo alerts        gap_alerts.config.OFFICES
  Own board           board_access — WHETHER they have a code, never the code

A CELL IS THE SCHEDULE, NOT A TICK. "Yes" tells an owner nothing they wanted;
"9pm local" answers the actual question. Blank means not enrolled.

NOTHING SENSITIVE. This is built to be served WITHOUT an access code, so it
carries no board codes, no money, no phone numbers, no channel ids — names,
what runs, and when. `SAFE_COLUMNS` is the whole contract and a test pins it.
"""
from __future__ import annotations

import re
import time

# The columns this page may ever show. Anything not here is a leak, and the
# test that checks it is the point of the list existing.
SAFE_COLUMNS = ["ICD", "Campaigns", "LucyECO", "Sara+ Alerts",
                "Text Scoreboard", "Call-outs", "Knock & Dispo Boards",
                "Weather Report", "Ad Photo Threads", "Resume Pushing",
                "Metrics Thread", "Trackers", "Dispo Alerts", "Posts to"]

# A feature an office does NOT have says so (Megan 2026-10-05: "not just
# blank - should be light red"). A blank cell is ambiguous between "no" and
# "we did not check".
NOT_ON = "Not Enrolled"

# Schedules that are the same wherever the feature is switched on. Each is
# read off the module that enforces it rather than retyped from memory; where
# that module holds the hours as config, the comment says which.
# Sara+ alerts and the text scoreboard run noon to midnight with a 2am
# catch-up, which is near enough round the clock that printing the window was
# noise in a column people scan for "do they have it?" (Megan 2026-10-05: "it
# should just say active since it's pretty much 24/7"). The hours still live
# in icd_alerts.config SALES_* — this is how they READ, not what they are.
ALWAYS_ON = "Active"
# The knocks poster is hour-gated 8–23 in its wrapper; what differs per office
# is the cadence and the rooms, which come off that office's own approved
# destinations (Megan 2026-10-05: "a time start-end and every 15 min or
# whatever they enrolled in and where at - text / slack").
def _ampm(hm) -> str:
    """(20, 30) or '20:30' as '8:30pm'. Built from ints, never %-I — that
    strftime flag is Mac-only and these have to run on Windows too."""
    if isinstance(hm, str):
        try:
            h, m = (int(x) for x in hm.split(":")[:2])
        except ValueError:
            return hm
    else:
        h, m = hm
    ap = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{ap}" if m else f"{h12}{ap}"


def _window(office, cut=None, sat_cut=None) -> str:
    """'11:30am-8:30pm M-F' / '11am-5pm Sat', one per line.

    TWO SHORT LINES, NOT ONE LONG ONE (Megan 2026-10-05, with a mock-up). The
    day label goes AFTER the hours so the times line up down the column and
    the eye reads the numbers, not the labels; a column of
    '11:30am–8:30pm · Sat 11am–5pm' was most of the table's width."""
    def end(val, wall):
        hm = tuple(int(x) for x in str(val).split(":")[:2])
        return min(hm, wall) if wall else hm
    try:
        lines = [f"{_ampm(office.day_start)}-"
                 f"{_ampm(end(office.day_end, cut))} M-F"]
        if getattr(office, "saturday", True):
            lines.append(f"{_ampm(office.sat_start)}-"
                         f"{_ampm(end(office.sat_end, sat_cut))} Sat")
        else:
            lines.append("no Sat")
        return "\n".join(lines)
    except Exception:   # noqa: BLE001
        return ""
# Call-outs ride the alert rooms and stop at a wall on the office's own clock:
# 8:30pm Mon–Fri, 5pm Saturday, nothing on Sunday (icd_alerts.gap_callouts).
# Call-outs stop at a wall on the office's own clock — 8:30pm Mon–Fri, 5pm
# Saturday — but they only START when that office's field does, and every
# office carries its own window (Cyrus 11:30–21:15, the default 13:30–20:30).
# So the cell is built per office rather than from one constant.
CALLOUT_CUT = (20, 30)
CALLOUT_SAT_CUT = (17, 0)

DISPO_WINDOW = "every 15 min, Mon–Sat"         # gap_alerts wrapper gate
# "daily" told nobody anything — every one of these runs daily, so the column
# was a wall of the same word (Megan 2026-10-05: "instead of daily it should
# say Enrolled and be in green"). The ones with a real time keep it; these
# three just say whether the office has them.
ENROLLED = "Enrolled"
BOARD_WHEN = ENROLLED

# HOW LucyECO READS ON THIS PAGE (Megan 2026-10-05: "it should be active /
# not on / or partial/pending"). The rollout list keeps its five states
# because chasing an install needs to tell 'on an old agent' from 'laptop has
# been shut for two days'. A page anyone can open needs four words:
#
#   Active   reporting, on the current agent
#   Partial  enrolled and HAS reported, but something is off — an old agent,
#            or nothing heard for two days. On, not working properly.
#   Pending  enrolled and has never reported. Waiting on the install.
#   Not on   no feed at all
ECO_STATE = {
    "Live": "Active",
    "Needs update": "Partial",
    "Gone quiet": "Partial",
    "Signed up — not reporting": "Pending",
    "Not on LucyECO": "Not on",
}


# The two words that mean "this office has it". Everything else a feature
# column can hold is also a yes — a window, a cadence — so the colour rule is
# by MEANING, not by matching words: green for anything that says they have
# it, red for the one phrase that says they do not, amber for the two states
# that mean "on, but not working yet".
GOOD_WORDS = (ALWAYS_ON, ENROLLED)
BAD_WORDS = (NOT_ON, "Not on")
WAIT_WORDS = ("Pending", "Partial")
# Columns that are a fact about the office rather than a yes/no, so they are
# never coloured: a green name tells you nothing.
UNCOLOURED = ("ICD", "Campaigns", "Posts to")


def cell_tone(column: str, value) -> str:
    """'good' | 'bad' | 'wait' | '' for one cell."""
    v = str(value or "").strip()
    if column in UNCOLOURED or not v:
        return ""
    if v in BAD_WORDS:
        return "bad"
    if v in WAIT_WORDS:
        return "wait"
    return "good"


def _first_office(feeds, alert_office):
    """The alert-office record behind this ICD's first live feed, or None."""
    for f in feeds:
        o = alert_office.get(f.key)
        if o is not None:
            return o
    return None


def _rooms(feeds, chan, approved_rooms) -> str:
    """Every room and group this office's feeds post into, by NAME."""
    names = []
    for f in feeds:
        for c in (approved_rooms.get(f.key) or []):
            nm = (getattr(c, "name", "") or "").strip()
            if nm and nm not in names:
                names.append(nm)
        for nm in (chan.get(f.key, {}).get("knock_names") or []):
            if nm not in names:
                names.append(nm)
    return ", ".join(names)


def eco_state(status: str) -> str:
    """One of Active / Partial / Pending / Not on."""
    return ECO_STATE.get((status or "").strip(), "Not on")

_CACHE: dict = {}
_TTL = 600


def _letters(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _knock_names(raw: str) -> list:
    """The rooms an office's knock boards land in, by name."""
    import json
    try:
        dests = json.loads(raw or "[]")
    except ValueError:
        return []
    out = []
    for d in dests:
        nm = str((d or {}).get("channel_name") or "").strip()
        if nm and nm not in out:
            out.append(nm)
    return out


def _knock_detail(raw: str) -> str:
    """'Slack + Text, every 30–60m' out of an office's approved destinations.

    WHERE AND HOW OFTEN, because that is what an owner is actually asking.
    A destination whose channel id carries the imessage: prefix is a text
    group, anything else is a Slack room (icd_alerts.post.is_text_dest)."""
    import json
    try:
        dests = json.loads(raw or "[]")
    except ValueError:
        return ""
    if not dests:
        return ""
    from automations.icd_alerts import post as P
    kinds, mins = [], []
    _names = []
    for d in dests:
        if not isinstance(d, dict):
            continue
        where = ("Text" if P.is_text_dest(str(d.get("channel_id") or ""))
                 else "Slack")
        if where not in kinds:
            kinds.append(where)
        nm = str(d.get("channel_name") or "").strip()
        if nm and nm not in _names:
            _names.append(nm)
        try:
            m = int(d.get("cadence_min") or 0)
        except (TypeError, ValueError):
            m = 0
        if m:
            mins.append(m)
    if not kinds:
        return ""
    how = ""
    if mins:
        lo, hi = min(mins), max(mins)
        how = (f", every {lo}m" if lo == hi else f", every {lo}–{hi}m")
    return " + ".join(kinds) + how


def _channels() -> dict:
    """{office key: {alerts, knocks, texts, knock_detail}} off Office Channels."""
    key = "channels"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1]
    out: dict = {}
    try:
        from automations.icd_alerts import post as P
        from automations.recruiting_report.fill import open_by_key, _retry
        grid = _retry(open_by_key(P.RELAY_SPREADSHEET_ID)
                      .worksheet(P.CHANNELS_TAB).get_all_values)

        def yes(row, i):
            return (len(row) > i
                    and str(row[i]).strip().upper() in ("TRUE", "YES", "Y"))

        for r in grid[1:]:
            k = (r[P.CH_OFFICE] or "").strip().lower() if r else ""
            if not k:
                continue
            out[k] = {
                "alerts": yes(r, P.CH_APPROVED),
                "knocks": yes(r, P.CH_KN_APPROVED),
                "texts": yes(r, P.CH_TX_APPROVED),
                "knock_names": _knock_names(
                    (r[P.CH_KN_APPROVED_JSON]
                     if len(r) > P.CH_KN_APPROVED_JSON else "")
                    or (r[P.CH_KN_JSON] if len(r) > P.CH_KN_JSON else "")),
                "knock_detail": _knock_detail(
                    (r[P.CH_KN_APPROVED_JSON]
                     if len(r) > P.CH_KN_APPROVED_JSON else "")
                    or (r[P.CH_KN_JSON] if len(r) > P.CH_KN_JSON else "")),
            }
    except Exception:   # noqa: BLE001 — the page shows what it can read
        out = {}
    _CACHE[key] = (now, out)
    return out


def _metrics_schedule() -> dict:
    """{office key: 'daily 4am on Lucy 4'} from the scheduler's own entries."""
    out: dict = {}
    try:
        import json
        from pathlib import Path
        here = Path(__file__).resolve().parents[1] / "day_orchestrator"
        reps = json.loads((here / "schedule_config.json").read_text())["reports"]
        for rid, v in reps.items():
            if not rid.endswith("_metrics") or not v.get("on_scheduler"):
                continue
            days = (v.get("cadence") or {}).get("weekdays") or []
            when = ("daily" if len(days) == 7 else
                    "weekdays" if days == [0, 1, 2, 3, 4] else
                    f"{len(days)} day(s)" if days else "")
            at = (v.get("cadence") or {}).get("not_before")
            out[rid[: -len("_metrics")]] = " ".join(
                p for p in (when, f"from {at}" if at else "") if p)
    except Exception:   # noqa: BLE001
        pass
    return out


def _by_owner(pairs) -> dict:
    """{letters-only owner: value} — the only join that survives spellings."""
    return {_letters(o): v for o, v in pairs if _letters(o)}


def rows(icds=None) -> list:
    """One row per ICD, every cell a schedule or blank. Never raises."""
    out = []
    try:
        from automations.icd_sales_board import eco_feeds as E
        from automations.icd_sales_board import profiles as P
        from automations.icd_sales_board import rollout as RO
        names = sorted(icds if icds is not None else P.load())
        chan = _channels()
        sched = _metrics_schedule()

        # METRICS BY ALIAS, not raw letters: that registry calls him 'Hammad
        # Haque' and the board calls him 'Muhammad Haque', so a letters-only
        # join said he had no metrics thread when he does (Megan 2026-10-05).
        try:
            from automations.office_metrics import offices as OM
            metrics = _by_owner((o.owner, k) for k, o in OM.OFFICES.items())
            try:
                from automations.focus_office_att import aliases as _AL
                _raw = _AL.load_aliases()
                for _icd in names:
                    if _letters(_icd) in metrics:
                        continue
                    for _cand in _AL.get_search_candidates(_icd, _raw):
                        if _letters(_cand) in metrics:
                            metrics[_letters(_icd)] = metrics[_letters(_cand)]
                            break
            except Exception:   # noqa: BLE001
                pass
        except Exception:   # noqa: BLE001
            metrics = {}
        # RESUME PUSHING: CONFIGURED IS NOT RUNNING. applicant_push lists 11
        # offices, and every one of its schedule entries is on_scheduler
        # False — it has only just launched and is live for nobody (Megan
        # 2026-10-05). Reading the config list called all 11 enrolled, which
        # is the page confidently stating something untrue.
        try:
            import json as _json
            from pathlib import Path as _Path
            _sc = _Path(__file__).resolve().parents[1] / "day_orchestrator"
            _reps = _json.loads(
                (_sc / "schedule_config.json").read_text())["reports"]
            _on = any(v.get("on_scheduler")
                      and (v.get("cadence") or {}).get("weekdays")
                      for k, v in _reps.items()
                      if k.startswith(("applicant_push", "resume_pushing"))
                      and not k.startswith(("install_", "disable_")))
            from automations.applicant_push import offices as AP
            resume = (_by_owner((o.get("owner"), o.get("office_id"))
                                for o in AP.OFFICES.values()) if _on else {})
        except Exception:   # noqa: BLE001
            resume = {}
        # GAP ALERTS KEY BY SHORT NAME, not by owner: its offices are 'rafael',
        # 'calvin', 'jay_att'. Several carry no owner at all, so an owner join
        # matched nobody and the column read zero for everyone — including Raf,
        # whose office is the one it was built for.
        try:
            from automations.gap_alerts import config as GC
            dispo = set()
            for o in GC.OFFICES:
                for attr in ("owner", "key"):
                    v = (getattr(o, attr, None)
                         if not isinstance(o, dict) else o.get(attr))
                    if v:
                        dispo.add(_letters(v))
        except Exception:   # noqa: BLE001
            dispo = set()
        try:
            # Eve's ad photo threads — the daily 1st-round screenshots, one
            # Slack thread per Indeed ad. Only the offices switched on.
            from automations.ad_photo_threads import config as APC
            ads = {o.get("key") for o in APC.OFFICES if o.get("live")}
        except Exception:   # noqa: BLE001
            ads = set()
        try:
            from automations.icd_alerts import offices as AO
            alert_office = {k: AO.get(k) for k in chan}
        except Exception:   # noqa: BLE001
            alert_office = {}
        try:
            from automations.icd_alerts import post as AP2
            approved_rooms = AP2.approved_channels()
        except Exception:   # noqa: BLE001
            approved_rooms = {}
        try:
            # POSITIONALLY, not by unpacking a fixed width: office_posts()
            # documents a 3-tuple and its metrics half appends 4-tuples, so
            # `for k, city, chans in ...` raised and the whole column read
            # empty for every office — a silent blank, not an error.
            from automations.weather_alert import run as WX
            weather = {row[0] for row in WX.office_posts()
                       if len(row) > 2 and row[2]}
        except Exception:   # noqa: BLE001
            weather = set()
        try:
            from automations.icd_alerts import gap_callouts as GCO
            opted_out = {str(k).lower() for k in GCO.CALLOUT_OPT_OUT}
        except Exception:   # noqa: BLE001
            opted_out = set()
        try:
            from automations.icd_sales_board import board_access as BA
            boards = {_letters(i) for i in BA.codes().values()}
        except Exception:   # noqa: BLE001
            boards = set()

        status = {r["ICD"]: r for r in RO.status_rows(light=True)}

        for icd in names:
            me = _letters(icd)
            feeds = E.for_icd(icd)
            # An office's ECO switches are per FEED key, and one owner can run
            # two. Enrolled in either is enrolled.
            mine = [chan.get(f.key, {}) for f in feeds]
            on = lambda w: any(m.get(w) for m in mine)   # noqa: E731
            mkey = metrics.get(me, "")
            st = status.get(icd, {})
            out.append({
                "ICD": icd,
                "Campaigns": st.get("Campaign", ""),
                "LucyECO": eco_state(st.get("Status", "")),
                "Sara+ Alerts": ALWAYS_ON if on("alerts") else "",
                "Text Scoreboard": ALWAYS_ON if on("texts") else "",
                # Call-outs ride the alert rooms, so an office with alerts
                # has them unless it opted out (Colten did, 2026-09-29). The
                # window is this office's own field hours, stopped at the wall.
                "Call-outs": (
                    _window(_first_office(feeds, alert_office),
                            CALLOUT_CUT, CALLOUT_SAT_CUT)
                    if on("alerts") and not any(
                        f.key.lower() in opted_out for f in feeds) else ""),
                # Approved with no destinations parsed still means they get
                # it — show the window rather than a blank that reads as 'not
                # enrolled' (Drew and Jairo are approved with none listed).
                "Knock & Dispo Boards": (
                    "\n".join(x for x in (
                        next((d for d in (chan.get(f.key, {}).get("knock_detail")
                                          for f in feeds) if d), ""),
                        _window(_first_office(feeds, alert_office))) if x)
                    if on("knocks") else ""),
                "Weather Report": ENROLLED if any(
                    f.key in weather for f in feeds) else "",
                "Ad Photo Threads": ENROLLED if any(
                    f.key in ads for f in feeds) else "",
                "Resume Pushing": ENROLLED if me in resume else "",
                "Metrics Thread": ENROLLED if mkey else "",
                "Trackers": ENROLLED if mkey else "",
                # A short key is a PREFIX of the full name ('rafael' ->
                # 'rafaelhidalgo'), which is how that registry names an office.
                "Dispo Alerts": DISPO_WINDOW if any(
                    d == me or (len(d) >= 5 and me.startswith(d))
                    for d in dispo) else "",
                # WHERE IT ALL LANDS, by name (Megan 2026-10-05: "the name of
                # the slack and imessage chat names on there so they know
                # where they are"). Names only — never the channel ids, which
                # this page has no business carrying.
                "Posts to": _rooms(feeds, chan, approved_rooms),
            })
        # A blank reads as "we did not check"; say no out loud.
        skip = {"ICD", "Campaigns", "LucyECO", "Posts to"}
        for r in out:
            for c in SAFE_COLUMNS:
                if c not in skip and not r.get(c):
                    r[c] = NOT_ON
    except Exception:   # noqa: BLE001
        return out
    return out


def counts(rows_: list) -> dict:
    """{column: how many offices have it} for the columns that are features."""
    feats = [c for c in SAFE_COLUMNS if c not in ("ICD", "Campaigns", "LucyECO")]
    return {c: sum(1 for r in rows_ if r.get(c)) for c in feats}
