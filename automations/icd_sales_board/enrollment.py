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
                "Metrics Thread", "Tableau Trackers", "Gap Alerts"]

# Separates the columns inside one cell. The page splits on it to build a
# small aligned table; anything reading these as plain text still gets a
# sensible line.
FIELD = " \u00b7 "

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

# gap_alerts' own wrapper gate. Named Gap Alerts on the page, not 'Dispo
# Alerts': it is the reps-over-a-15-minute-gap card, and sitting next to
# 'Knock & Dispo Boards' the old name read like the same thing twice.
DISPO_WINDOW = "every 15 min, Mon–Sat"
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
UNCOLOURED = ("ICD", "Campaigns")

# Everything downstream of the office's own machine. A channel can be
# approved while nothing is coming through it — Eveliz and Rashad are both
# signed up with rooms set up and have never relayed, and the page called
# their alerts Active (Megan 2026-10-05: "doesn't have an active sara+ yet so
# it should say pending"). Approved is not flowing, so when the office has
# never reported these read Pending rather than Active. The ones WE run off
# our own scrape — metrics, trackers — are unaffected.
RELAY_FED = ("Sara+ Alerts", "Text Scoreboard", "Call-outs",
             "Knock & Dispo Boards")


# WHAT EACH COLUMN MEANS, and a picture where we have one. The screenshots
# are the Hub's own card images, so they are the real thing rather than a
# mock-up. A feature with no shot yet gets the words only — better than a
# broken image, and dropping a PNG in `resources/report-screenshots/` under
# the name below is all it takes to give it one.
EXPLAINS = {
    "Sara+ Alerts": ("Every sale and credit check off the office's own "
                     "SaraPlus, posted to their room as it happens.",
                     "sara-plus-alerts.png"),
    "Text Scoreboard": ("The running scoreboard texted to the office's "
                        "iMessage group through the day.",
                        "text-scoreboard.png"),
    "Call-outs": ("Lucy calling out a rep who has gone quiet, and praising "
                  "a good pace, in the office's room.",
                  "sara-plus-callouts.png"),
    "Knock & Dispo Boards": ("The knocks and dispositions board, posted on "
                             "the office's own cadence.", "total-knocks.png"),
    "Weather Report": ("The morning forecast for that office's city.",
                       "weather-report.png"),
    "Ad Photo Threads": ("Eve's daily 1st-round screenshots, one Slack "
                         "thread per Indeed ad, with the ad's % removed and "
                         "average star rating.",
                         "ad-photo-threads.png"),
    "Resume Pushing": ("Pulling resumes out of ApplicantStream and sending "
                       "them to the AI.", "resume-pushing.png"),
    "Metrics Thread": ("The office's daily metrics thread in Slack.",
                       "office-metrics-thread.png"),
    "Tableau Trackers": ("The universal tracker boards, drawn from Tableau "
                         "and posted to the office's room.",
                         "tableau-trackers.png"),
    "Gap Alerts": ("The KNOCKS & DISPOSITIONS card — reps over a 15 "
                     "minute gap — texted through the day.",
                     "gap-alerts-card.png"),
}


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


def _with_where(schedule: str, names) -> str:
    """'1pm-8:30pm M-F' / '11am-5pm Sat' / '#everforward-sales'."""
    if not schedule:
        return ""
    lines = [schedule] + [n for n in (names or []) if n]
    return "\n".join(lines)


def _room_name(channel_id: str) -> str:
    """A Slack room's name from its id, out of the registries that hold both.
    '' when nothing knows it — the caller then says 'Slack' and no more."""
    cid = (channel_id or "").strip()
    if not cid:
        return ""
    key = ("rooms", "byid")
    import time as _t
    now = _t.time()
    if key in _CACHE and now - _CACHE[key][0] < _TTL:
        return _CACHE[key][1].get(cid, "")
    byid = {}
    try:
        from automations.office_metrics import offices as OM
        for o in OM.OFFICES.values():
            if getattr(o, "channel_id", "") and getattr(o, "channel_name", ""):
                byid[o.channel_id] = o.channel_name
    except Exception:   # noqa: BLE001
        pass
    try:
        from automations.icd_alerts import post as AP3
        for chans in (AP3.approved_channels() or {}).values():
            for c in chans:
                cid2 = (getattr(c, "id", "") or "").strip()
                nm = (getattr(c, "name", "") or "").strip()
                if cid2 and nm:
                    byid[cid2] = nm
    except Exception:   # noqa: BLE001
        pass
    _CACHE[key] = (now, byid)
    return byid.get(cid, "")


def _gap_rooms(me: str, gap_dests: dict) -> list:
    """Where this office's gap card goes. Its registry keys by short name."""
    for key, names in (gap_dests or {}).items():
        if key == me or (len(key) >= 5 and me.startswith(key)):
            return names
    return []


def _first_office(feeds, alert_office):
    """The alert-office record behind this ICD's first live feed, or None."""
    for f in feeds:
        o = alert_office.get(f.key)
        if o is not None:
            return o
    return None


def _names_of(feeds, chan, field) -> list:
    """Every line across this office's feeds, grouped by where it lands.

    An owner with two campaigns posts into the same rooms on two clocks —
    Carlos's Box feed hourly and his B2B feed every 30 minutes, both into
    #alphalete-gp-sales. Both lines are true and both belong; sorting by the
    ROOM keeps the pair together instead of interleaving four rooms."""
    seen = {}
    order = []
    for f in feeds:
        for ln in (chan.get(f.key, {}).get(field) or []):
            when, _, where = ln.partition(FIELD)
            if where not in seen:
                seen[where] = []
                order.append(where)
            if when not in seen[where]:
                seen[where].append(when)
    # ONE ROW PER ROOM. An owner running two campaigns into the same room
    # produced that room twice, once per cadence — Carlos had four lines for
    # two rooms. The cadences merge onto the room's own row instead.
    out = []
    for where in sorted(order):
        whens = seen[where]
        def _n(w):
            digits = "".join(c for c in w if c.isdigit())
            return int(digits) if digits else 999
        merged = " & ".join(w.replace("Every ", "").replace(" Min", "")
                            for w in sorted(whens, key=_n))
        label = (f"Every {merged} Min" if all(w.startswith("Every ")
                                              for w in whens)
                 else " & ".join(whens))
        out.append(f"{label}{FIELD}{where}" if where else label)
    return out


def _rooms_for(feeds, approved_rooms) -> list:
    """The alert rooms, each said to be Slack — same reason as _knock_lines."""
    out = []
    for f in feeds:
        for c in (approved_rooms.get(f.key) or []):
            nm = (getattr(c, "name", "") or "").strip()
            if nm:
                nm = nm if nm.lower().startswith(("slack", "imessage")) \
                    else "Slack " + nm
                if nm not in out:
                    out.append(nm)
    return out


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


def _label_dest(name: str, cid: str) -> str:
    """'Slack #room' or 'iMessage Group' — never a bare name."""
    from automations.icd_alerts import post as P
    if P.is_text_dest(cid or ""):
        return "iMessage " + (name or P.text_group_of(cid or ""))
    return ("Slack " + name) if name else ""


def _dest_names(raw: str) -> list:
    """The rooms or groups in an approved-destinations blob, by NAME.

    THE NAME GOES IN THE CELL WITH THE SCHEDULE (Megan 2026-10-05, with a
    mock-up: the hours and '#slackchannel' side by side). Knowing an office
    gets call-outs is half an answer; the other half is where they land."""
    import json
    try:
        dests = json.loads(raw or "[]")
    except ValueError:
        return []
    out = []
    for d in dests:
        if not isinstance(d, dict):
            continue
        nm = _label_dest(
            str(d.get("channel_name") or d.get("name") or "").strip(),
            str(d.get("channel_id") or ""))
        if nm and nm not in out:
            out.append(nm)
    return out


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


def _knock_lines(raw: str) -> list:
    """One line PER DESTINATION: 'Every 30 Min · #palace-sales'.

    AN OFFICE'S BOARDS GO TO SEVERAL PLACES ON DIFFERENT CLOCKS (Megan
    2026-10-05: "Raf has dispo boards in multiple places", with a mock-up of
    a row per destination). Carlos posts hourly into two rooms; Ryan posts
    every 30 minutes into one and every 60 into another. Collapsing that to
    'every 30-60m' and a separate list of names made you pair them up
    yourself and guess which cadence belonged to which room.

    A destination whose id carries the imessage: prefix is a text group, and
    it is labelled as one — '#room' and a group name look alike otherwise.
    """
    import json
    try:
        dests = json.loads(raw or "[]")
    except ValueError:
        return []
    from automations.icd_alerts import post as P
    out = []
    for d in dests:
        if not isinstance(d, dict):
            continue
        cid = str(d.get("channel_id") or "")
        name = str(d.get("channel_name") or d.get("name") or "").strip()
        # SAY WHICH IT IS. A leading '#' is the only thing that marked a
        # Slack room apart from an iMessage group, and nobody should have to
        # know that convention to read the page (Megan 2026-10-05: "this is
        # confusing - should say slack or iMessage"). The label goes in
        # FRONT, so the column reads Slack/Slack/iMessage down its left edge
        # rather than hiding the kind at the end of a long room name.
        if P.is_text_dest(cid):
            name = "iMessage " + (name or P.text_group_of(cid))
        elif name:
            name = "Slack " + name
        try:
            mins = int(d.get("cadence_min") or 0)
        except (TypeError, ValueError):
            mins = 0
        when = f"Every {mins} Min" if mins else "Each slot"
        # TWO FIELDS, not one string: the page lays these out as columns so
        # the cadences line up under each other and the room names line up
        # under each other. Run together with a '·' they wrapped mid-name and
        # read as a wall (Megan 2026-10-05: "this looks so sloppy").
        line = f"{when}{FIELD}{name}" if name else when
        if line not in out:
            out.append(line)
    return out


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
                "text_names": _dest_names(
                    (r[P.CH_TX_APPROVED_JSON]
                     if len(r) > P.CH_TX_APPROVED_JSON else "")
                    or (r[P.CH_TX_JSON] if len(r) > P.CH_TX_JSON else "")),
                "knock_names": _knock_names(
                    (r[P.CH_KN_APPROVED_JSON]
                     if len(r) > P.CH_KN_APPROVED_JSON else "")
                    or (r[P.CH_KN_JSON] if len(r) > P.CH_KN_JSON else "")),
                "knock_lines": _knock_lines(
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
            # Where the gap card actually lands, by name — it was the one
            # feature saying only WHEN (Megan 2026-10-05).
            from automations.gap_alerts import config as GC2
            gap_dests = {}
            for o in GC2.OFFICES:
                key = _letters((o.get("key") if isinstance(o, dict)
                                else getattr(o, "key", "")) or "")
                # NOT `names` — that is the list of ICDs this function is
                # looping over, and reusing it here emptied it: the loop ran
                # zero times and the whole page came back blank with no error
                # to show for it.
                dests = []
                for d in ((o.get("destinations") if isinstance(o, dict)
                           else getattr(o, "destinations", None)) or []):
                    nm = _label_dest(str(d.get("name") or "").strip(),
                                     "imessage:" if d.get("kind") == "imessage"
                                     else "")
                    if d.get("kind") == "slack" and not d.get("name"):
                        # NEVER THE RAW ID. gap_alerts stores this room by id
                        # with no name, and printing 'Slack C09JG28CD27' put
                        # exactly the thing this page promises not to carry on
                        # a link anyone can open. Resolved to a name where we
                        # know one, and just 'Slack' where we do not — the
                        # answer people want is which room, and an id is not
                        # that answer anyway.
                        nm = "Slack " + _room_name(
                            str(d.get("channel_id") or "")) \
                            if _room_name(str(d.get("channel_id") or "")) \
                            else "Slack"
                    if nm and nm not in dests:
                        dests.append(nm)
                if key:
                    gap_dests[key] = dests
        except Exception:   # noqa: BLE001
            gap_dests = {}
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
                "Sara+ Alerts": _with_where(
                    ALWAYS_ON if on("alerts") else "",
                    _rooms_for(feeds, approved_rooms)),
                "Text Scoreboard": _with_where(
                    ALWAYS_ON if on("texts") else "",
                    _names_of(feeds, chan, "text_names")),
                # Call-outs ride the alert rooms, so an office with alerts
                # has them unless it opted out (Colten did, 2026-09-29). The
                # window is this office's own field hours, stopped at the wall.
                "Call-outs": _with_where(
                    _window(_first_office(feeds, alert_office),
                            CALLOUT_CUT, CALLOUT_SAT_CUT)
                    if on("alerts") and not any(
                        f.key.lower() in opted_out for f in feeds) else "",
                    _rooms_for(feeds, approved_rooms)),
                # Approved with no destinations parsed still means they get
                # it — show the window rather than a blank that reads as 'not
                # enrolled' (Drew and Jairo are approved with none listed).
                # The window once, then a line per place it lands.
                "Knock & Dispo Boards": _with_where(
                    _window(_first_office(feeds, alert_office))
                    if on("knocks") else "",
                    _names_of(feeds, chan, "knock_lines")),
                "Weather Report": ENROLLED if any(
                    f.key in weather for f in feeds) else "",
                "Ad Photo Threads": ENROLLED if any(
                    f.key in ads for f in feeds) else "",
                "Resume Pushing": ENROLLED if me in resume else "",
                "Metrics Thread": ENROLLED if mkey else "",
                "Tableau Trackers": ENROLLED if mkey else "",
                # A short key is a PREFIX of the full name ('rafael' ->
                # 'rafaelhidalgo'), which is how that registry names an office.
                "Gap Alerts": _with_where(
                    DISPO_WINDOW if any(
                        d == me or (len(d) >= 5 and me.startswith(d))
                        for d in dispo) else "",
                    _gap_rooms(me, gap_dests)),
                # WHERE IT ALL LANDS, by name (Megan 2026-10-05: "the name of
                # the slack and imessage chat names on there so they know
                # where they are"). Names only — never the channel ids, which
                # this page has no business carrying.
            })
        skip = {"ICD", "Campaigns", "LucyECO", "Posts to"}
        for r in out:
            # Nothing has come through this office's machine yet, so anything
            # that rides it is set up and waiting, not running.
            if r.get("LucyECO") == "Pending":
                for c in RELAY_FED:
                    if r.get(c):
                        r[c] = "Pending"
            # A blank reads as "we did not check"; say no out loud.
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
