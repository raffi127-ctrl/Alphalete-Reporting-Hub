"""Rebuild the Funnel Board tabs from a pulled dataset.

Reads FUNNEL_DATA (json) and writes the five tabs into FUNNEL_SSID.
Only ever touches its own five tabs — see the OURS guard.
"""
import datetime as dt
import os
import json
import statistics
import sys
from pathlib import Path

# run.py launches this as a plain script, so only its own directory lands on
# sys.path — put the repo root there too, or the `automations.` import below
# can't resolve.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from automations.funnel_board.auth import session as _auth_session  # noqa: E402
from automations.funnel_board.roster import (  # noqa: E402
    CAMPAIGN_ONLY, CAPTAINSHIP_NAMES, ORG_NAMES,
    BOARD_TITLE as CAP_BOARD_TITLE, TREND_TITLE as CAP_TREND_TITLE)
from automations.org_campaign_metrics.layout import (  # noqa: E402
    N_SLOTS as CAMP_SLOTS, ZONE_START as CAMP_ZONE_START)

SSID = os.environ.get("FUNNEL_SSID", "1Y3RxPbWhJrpV_hyK53zwswIcPQAGanU2EY17MVUSbtU")
API = "https://sheets.googleapis.com/v4/spreadsheets/" + SSID
DATA = os.environ.get("FUNNEL_DATA") or str(
    Path(__file__).resolve().parent / "state" / "funnel_data.json")

S = _auth_session(verbose=True)


def call(path, payload, method="post"):
    r = getattr(S, method)(API + path, json=payload)
    if r.status_code != 200:
        raise SystemExit("%s %s -> %s\n%s" % (method.upper(), path, r.status_code, r.text[:2000]))
    return r.json()


def batch(rq):
    return call(":batchUpdate", {"requests": rq})


def rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


# High-contrast palette. The previous one leaned on pale greys that vanished at
# small sizes; secondary text is now dark enough to read, and rules are dark
# enough to actually separate things.
INK, INK_2, INK_3 = "#0B1220", "#334155", "#475569"
LINE, LINE_HARD, SURF_2, SUNKEN = "#C2CCD6", "#64748B", "#F1F5F9", "#DDE4EC"
ACCENT, ACCENT_BG = "#1E293B", "#E6ECF3"          # derived cells: weight, not hue
PICK, PICK_BG = "#92400E", "#FEF3C7"              # editable pickers read as inputs
EDIT, EDIT_BG = "#5B21B6", "#EDE9FE"              # editable GOAL cells — violet on purpose:
                                                  # the old amber (#FEF3C7) was one shade off
                                                  # the WARN band (#FDF0C8) and read as "close
                                                  # to goal" instead of "type here" (Carlos,
                                                  # 2026-08-22)
GOOD, GOOD_BG = "#14532D", "#D6F5DF"
WARN, WARN_BG = "#854D0E", "#FDF0C8"
BAD, BAD_BG = "#991B1B", "#FBDDDD"
# One hue per funnel stage — far easier to find your place than a single ramp.
STAGE = ["#475569", "#0F766E", "#1D4ED8", "#7E22CE", "#B45309"]
FONT, FONT_UI = "Roboto Mono", "Inter"


def txt(c=INK, b=False, s=11, f=FONT_UI):
    return {"foregroundColor": rgb(c), "bold": b, "fontSize": s, "fontFamily": f}


def bd(c=LINE, style="SOLID"):
    return {"style": style, "color": rgb(c)}


def bdm(c=LINE_HARD):
    return {"style": "SOLID_MEDIUM", "color": rgb(c)}


def bdt(c=INK):
    return {"style": "SOLID_THICK", "color": rgb(c)}


def a1(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


# ---- agreed percentage thresholds (Carlos, 2026-08-07). {v} is the cell ref.
# Anything not listed here is deliberately left uncoloured until thresholds exist,
# rather than falling back to a goal-relative rule that would mean something else.
# ONE grading rule for everything: how far off goal are you?
#   within 5%  -> green      5-10% off -> yellow      10%+ off -> red
# Judged on shortfall, so beating the goal stays green. Removal % inverts (being
# UNDER the removal goal is good). Counts are measured against goal x pace-to-date
# so a Wednesday number is judged on run rate, not on the full week's target.
BAND_OK, BAND_WARN = 0.95, 0.90
GRADE = {  # board header -> (goal key, kind).  ONLY the metrics typed on Goals.
           # all NINE typed goals grade here — NS Shw % was missed originally.
    "Removal %":    ("rmvpct", "rate_low"),   # lower than goal is good
    "Sent to CL":   ("sent", "count"),
    "Ret to CL %":  ("ret2cl", "rate"),
    "1st Shw %":    ("sh1pct", "rate"),
    "2nd Booked %": ("bk2pct", "rate"),
    "2nd Shw %":    ("sh2pct", "rate"),
    "Offer %":      ("offpct", "rate"),
    "BOB Conv %":   ("bobconv", "rate"),
    "NS Shw %":     ("nspct", "rate"),
}   # every derived count stays black — colouring an output as well as the input
    # behind it just says the same thing twice
MIRROR_KEY = {h: k for h, (k, _) in GRADE.items()}
TREND_PCT_GOAL = {"Removal %": "rmvpct", "Retention to Call List": "ret2cl",
                  "1st Show %": "sh1pct", "2nd Booked % of 1st showed": "bk2pct",
                  "2nd Show %": "sh2pct", "Offer % of 2nd showed": "offpct",
                  "BOB Conversion": "bobconv",
                  "New Start Show %": "nspct"}
LEGEND = [   # the band label carries its own colour, so no COLOUR column needed
    ("Within 5% of goal",        "on target"),
    ("5% - 10% off goal",        "slipping"),
    ("More than 10% off goal",   "off target"),
]
LEGEND2 = [
    ("Counts", "graded against goal x share of the week normally done by today"),
    ("Rates",  "graded against the goal directly - a rate does not accumulate"),
]


# ------------------------------------------------------------------ data
raw = json.load(open(DATA))
OFF = raw["offices"]
MEAS = ["applies", "sent", "removed", "processed", "retb", "b1", "s1", "b2",
        "s2", "off", "bob", "nss", "nsh"]

# Board order: New Starts Showed desc, then Applies desc.
def _fix(v):
    v = dict(v)
    v["sent"] = v["sent"] + v.get("manual", 0) + v.get("scoop_s", 0) + v.get("file_s", 0)
    v["removed"] = v["removed"] + v.get("rm_scoop", 0)
    # Applies is INTAKE — what arrived that day, across every channel. It is NOT
    # sent+removed: those are what got vetted that day, which on a Monday is
    # mostly the weekend's arrivals. Rafael 8/10: 32 arrived, 623 vetted.
    v["applies"] = (v.get("emails_rx", 0) + v.get("scoop_rx", 0)
                    + v.get("file_rx", 0) + v.get("manual", 0))
    v["processed"] = v["sent"] + v["removed"]      # what was vetted that day
    return v


def tot(name, k):
    return sum(_fix(d)[k] for d in OFF[name]["days"].values())


# Everyone the pull covers, best first. Daily Log and Goals span all of them —
# Goals in particular MUST, because every board grades each row against that
# person's own goal row, wherever they appear.
MANAGERS = sorted(OFF, key=lambda m: (-tot(m, "nsh"), -tot(m, "applies")))

# ...but the org board is the ORG. Deriving its rows from "whoever is in the
# data" put all eleven captainship-only offices on the Manager Board the first
# time they were pulled (2026-08-19). The two rosters are named lists precisely
# so that can't happen again.
ORG_ROSTER = [m for m in MANAGERS if m in ORG_NAMES]


def _rank(m):
    """Same order as the org board — but someone with no pull yet sorts last
    rather than landing mid-table on a row of zeros."""
    if m in OFF:
        return (0, -tot(m, "nsh"), -tot(m, "applies"), CAPTAINSHIP_NAMES.index(m))
    return (1, 0, 0, CAPTAINSHIP_NAMES.index(m))


# Carlos's captainship is NOT a subset of the org board — most of it sits
# outside those 17 offices — so it is a roster, not a filter. Names with no
# Daily Log rows yet still get a row; every cell is a SUMIFS, so they read zero
# today and fill themselves in the hour their first pull lands.
CAP_ROSTER = sorted(CAPTAINSHIP_NAMES, key=_rank)
ALL_DATES = sorted({d for m in OFF.values() for d in m["days"]})
WEEK_ENDS = sorted({(dt.date.fromisoformat(d) + dt.timedelta(days=6 - dt.date.fromisoformat(d).weekday()))
                    for d in ALL_DATES})
print("managers=%d (org %d, captainship %d) dates=%d weeks=%s"
      % (len(MANAGERS), len(ORG_ROSTER), len(CAP_ROSTER), len(ALL_DATES), WEEK_ENDS))

# A week still in flight has fewer than 7 days of data. Say so on every tab —
# otherwise a 5-day week sitting beside 7-day weeks reads as a collapse.
_by_week = {}
for iso in ALL_DATES:
    d = dt.date.fromisoformat(iso)
    if d <= dt.date.today():
        _by_week.setdefault(d + dt.timedelta(days=6 - d.weekday()), set()).add(d)
PARTIAL = {w: sorted(ds) for w, ds in _by_week.items() if len(ds) < 7}
NOTE = ""
if PARTIAL:
    w = max(PARTIAL)
    ds = PARTIAL[w]
    NOTE = ("  ·  week ending %s is PARTIAL — %s–%s only (%d of 7 days)"
            % (w.strftime("%-m/%-d"), ds[0].strftime("%a %-m/%-d"),
               ds[-1].strftime("%a %-m/%-d"), len(ds)))
    print("PARTIAL:", NOTE)

AUDIT = ["emails_rx", "scoop_rx", "file_rx", "manual",
         "sent_email", "scoop_s", "file_s", "rm_email", "rm_scoop"]
AUDIT_HEAD = ["· Emails Received", "· Scooper In", "· File Import In", "· Manual Entry",
              "· Email Sent", "· Scooper Sent", "· File Sent",
              "· Removed (Email)", "· Removed (Scooper)"]
DAILY_HEAD = (["Date", "Week Ending", "Manager", "Office"]
              # "Ret Booked" is the numerator implied by AppStream's own Retention
              # Call List %, stored so a stitched week rebuilds the cohort rate.
              + ["Applies", "Sent to Call List", "Removed", "Processed", "Ret Booked",
                 "1st Booked", "1st Showed",
                 "2nd Booked", "2nd Showed", "Job Offered", "BOB",
                 "NS Scheduled", "NS Showed"]
              + AUDIT_HEAD)
# "Sent to Call List" is every intake path, not just email — applicants also
# arrive by manual entry, resume scooper and file import, each with its own line
# on the report. Counting email alone understated the call-list denominator badly
# (Rashad Reed took in more via the scooper than via email). The components are
# kept as audit columns to the right so any total can be traced back.
AUDIT = ["emails_rx", "scoop_rx", "file_rx", "manual",
         "sent_email", "scoop_s", "file_s", "rm_email", "rm_scoop"]
AUDIT_HEAD = ["· Emails Received", "· Scooper In", "· File Import In", "· Manual Entry",
              "· Email Sent", "· Scooper Sent", "· File Sent",
              "· Removed (Email)", "· Removed (Scooper)"]
daily_rows = []
for m in MANAGERS:
    for iso in sorted(OFF[m]["days"]):
        d = dt.date.fromisoformat(iso)
        we = d + dt.timedelta(days=6 - d.weekday())
        v = dict(OFF[m]["days"][iso])
        v["sent_email"], v["rm_email"] = v["sent"], v["removed"]
        v["sent"] = v["sent_email"] + v.get("manual", 0) + v.get("scoop_s", 0) + v.get("file_s", 0)
        v["removed"] = v["rm_email"] + v.get("rm_scoop", 0)
        v["applies"] = (v.get("emails_rx", 0) + v.get("scoop_rx", 0)
                        + v.get("file_rx", 0) + v.get("manual", 0))
        v["processed"] = v["sent"] + v["removed"]
        daily_rows.append([d.strftime("%m/%d/%Y"), we.strftime("%m/%d/%Y"), m, OFF[m]["office_id"]]
                          + [v[k] for k in MEAS] + [v.get(k, 0) for k in AUDIT])

# Provisional goals: the office median per metric, PER WEEK (the board shows one
# week at a time, so a 4-week sum here would read as a 4x goal). Replace with real
# targets when you have them.
NW = max(1, len(WEEK_ENDS))
med = {k: int(statistics.median([tot(m, k) / NW for m in MANAGERS])) for k in MEAS + ["applies"]}

# Goals layout: Removal % sits immediately right of Removed (column E) and is a
# formula, so it tracks whatever targets get typed into C and D.
# Goals is the single control panel: one row per manager. Applies is a typed goal
# of its own (Carlos: "Rafael's applied goal is 2,000") rather than sent+removed.
# Retention to Call List is the typed input; 1st Booked falls OUT of it
# (sent x retention), so the booking target can't drift from the retention target.
# Column-for-column the same funnel as the Manager Board, so a goal always sits
# under the number it grades.
# You type the rates; every count falls out of them. One number per decision, and
# the funnel can never contradict itself.
GOALS_HEAD = ["Office", "Manager",
              "Applies", "Removed", "Removal %", "Sent to Call List",
              "Retention to Call List", "1st Booked", "1st Showed", "1st Show %",
              "2nd Booked %", "2nd Booked", "2nd Showed", "2nd Show %",
              "Offer %", "Job Offered", "BOB", "BOB Conversion",
              "NS Scheduled", "NS Showed", "New Start Show %"]
GOAL_AT = {"applies": 2, "removed": 3, "rmvpct": 4, "sent": 5, "ret2cl": 6,
           "b1": 7, "s1": 8, "sh1pct": 9, "bk2pct": 10, "b2": 11, "s2": 12,
           "sh2pct": 13, "offpct": 14, "off": 15, "bob": 16, "bobconv": 17,
           "nss": 18, "nsh": 19, "nspct": 20}                        # 0-based
GOALS_AMBER = ["rmvpct", "sent", "ret2cl", "sh1pct", "bk2pct",
               "sh2pct", "offpct", "bobconv", "nspct"]
GOALS_COMPUTED = ["Applies", "Removed", "1st Booked", "1st Showed", "2nd Booked", "2nd Showed",
                  "Job Offered", "BOB", "NS Scheduled", "NS Showed"]


def _med_ratio(n, d):
    vals = [tot(m, n) / tot(m, d) for m in MANAGERS if tot(m, d)]
    return round(statistics.median(vals), 4) if vals else 0.0


_r2c, _s1p = _med_ratio("b1", "sent"), _med_ratio("s1", "b1")
_b2p, _s2p = _med_ratio("b2", "s1"), _med_ratio("s2", "b2")
_ofp, _bcv = _med_ratio("off", "s2"), _med_ratio("bob", "off")
_nsp = _med_ratio("nsh", "nss")
_rmp = _med_ratio("removed", "applies")

# ---- Whatever is typed on the Goals tab is the USER'S, and a rebuild must never
# discard it. Read it back BEFORE anything is written, keyed on manager name +
# header text so neither a column re-order nor a row re-sort can misalign it.
PRIOR = {}
try:
    _g = S.get(API + "/values/Goals!A1:Z200",
               params={"valueRenderOption": "UNFORMATTED_VALUE"}).json().get("values", [])
    if _g:
        _hdr = _g[0]
        _mi = _hdr.index("Manager") if "Manager" in _hdr else 0
        for _row in _g[1:]:
            if len(_row) <= _mi or not isinstance(_row[_mi], str) or not _row[_mi].strip():
                continue
            _who = _row[_mi].strip()
            for _i, _h in enumerate(_hdr):
                if _i < len(_row) and isinstance(_row[_i], (int, float)):
                    PRIOR.setdefault(_who, {})[_h] = _row[_i]
    if PRIOR:
        print("preserving typed goals for %d manager(s)" % len(PRIOR))
except Exception as _e:
    print("could not read prior goals (%s)" % type(_e).__name__)

# Belt and braces: a crash BETWEEN the wipe and the rewrite would otherwise lose
# hand-typed goals for good (it already did once). Mirror them to disk and fall
# back to that file whenever the sheet comes back empty.
_BAK = Path(DATA).with_name("goals_backup.json")
if PRIOR:
    _BAK.write_text(json.dumps(PRIOR, indent=1), encoding="utf-8")
elif _BAK.exists():
    PRIOR = json.loads(_BAK.read_text(encoding="utf-8"))
    print("Goals tab was empty — restored typed goals from %s" % _BAK.name)

# Goals stays ONE tab, in two boxes (Carlos, 2026-08-22): the ORG box at the
# top, and a separate CAPTAINSHIP box that starts at row 32 — captainship-only
# people never sit in the org grid. Carlos and Atef are in both rosters and get
# exactly one row, in the org box: two goals rows for one person is how a board
# ends up grading against the wrong one. Every lookup into Goals is a VLOOKUP on
# the name column, so layout is cosmetic to the boards; PRIOR read-back skips
# the spacer/title rows (no numeric cells) and harmlessly records the repeated
# header row. The legend anchors off len(goal_rows), so it follows the second
# box down automatically.
_ORG_PART = [m for m in MANAGERS if m in ORG_NAMES]
_CAP_PART = [m for m in MANAGERS if m not in ORG_NAMES]
_CAP_HEADER_AT = 32            # row where the captainship box header lands
_GOALS_ORDER = (_ORG_PART
                + ["__BLANK__"] * (_CAP_HEADER_AT - 3 - len(_ORG_PART))
                + ["__TITLE__", "__HEADER__"]
                + _CAP_PART)

goal_rows = []
for m in _GOALS_ORDER:
    r = len(goal_rows) + 2
    if m == "__BLANK__":
        goal_rows.append([""] * len(GOALS_HEAD))
        continue
    if m == "__TITLE__":
        goal_rows.append(["", "CAPTAINSHIP — oversight, not in the org"] + [""] * (len(GOALS_HEAD) - 2))
        continue
    if m == "__HEADER__":
        goal_rows.append(list(GOALS_HEAD))
        continue

    def _keep(header, default):
        """A typed goal always wins over the seeded median."""
        return PRIOR.get(m, {}).get(header, default)

    goal_rows.append([
        OFF[m]["office_id"], m,
        '=IFERROR(ROUND(F%d/(1-E%d)),"")' % (r, r),      # Applies     = Sent / (1 - Removal %)
        '=IFERROR(C%d-F%d,"")' % (r, r),                 # Removed     = Applies - Sent
        _keep("Removal %", _rmp),
        _keep("Sent to Call List", med["sent"]),
        _keep("Retention to Call List", _r2c),
        '=IFERROR(ROUND(F%d*G%d),"")' % (r, r),          # 1st Booked  = Sent x Retention
        '=IFERROR(ROUND(H%d*J%d),"")' % (r, r),          # 1st Showed  = 1st Booked x 1st Show %
        _keep("1st Show %", _s1p),
        _keep("2nd Booked %", _b2p),
        '=IFERROR(ROUND(I%d*K%d),"")' % (r, r),          # 2nd Booked  = 1st Showed x 2nd Booked %
        '=IFERROR(ROUND(L%d*N%d),"")' % (r, r),          # 2nd Showed  = 2nd Booked x 2nd Show %
        _keep("2nd Show %", _s2p),
        _keep("Offer %", _ofp),
        '=IFERROR(ROUND(M%d*O%d),"")' % (r, r),          # Job Offered = 2nd Showed x Offer %
        '=IFERROR(ROUND(P%d*R%d),"")' % (r, r),          # BOB         = Job Offered x BOB Conv
        _keep("BOB Conversion", _bcv),
        '=IFERROR(Q%d,"")' % r,                          # NS Scheduled = BOB (measured 99%)
        '=IFERROR(ROUND(S%d*U%d),"")' % (r, r),          # NS Showed   = NS Sched x NS Show %
        _keep("New Start Show %", _nsp)])

# Pace curves, measured from this data rather than assumed. Weekends are NOT idle
# (Sunday alone is ~6% of applies) and the shape differs sharply per metric — New
# Starts are ~82% done on Monday because training starts Monday, while applies
# spread across the week. A single divisor misjudges both.
_full = {w for w, ds in _by_week.items() if len(ds) == 7}
_dow = {k: [0.0] * 7 for k in MEAS + ["applies"]}
for _m, _o in OFF.items():
    for _iso, _v in _o["days"].items():
        _d = dt.date.fromisoformat(_iso)
        if _d + dt.timedelta(days=6 - _d.weekday()) not in _full:
            continue
        _fv = _fix(_v)
        for _k in _dow:
            _dow[_k][_d.weekday()] += _fv[_k]
PACE_CURVE = {}
for _k, _vals in _dow.items():
    _t = sum(_vals)
    _run, _cum = 0.0, []
    for _x in _vals:
        _run += _x
        _cum.append(round(_run / _t, 4) if _t else 1.0)
    PACE_CURVE[_k] = _cum
print("pace curve (cumulative share by Mon..Sun):")
for _k in ["applies", "sent", "b1", "off", "bob", "nss", "nsh"]:
    print("   %-8s %s" % (_k, ["%.0f%%" % (100 * x) for x in PACE_CURVE[_k]]))

COL = dict(zip(MEAS, ["E", "F", "G", "H", "I", "J", "K", "L", "M", "N",
                      "O", "P", "Q"]))
GCOL = {k: a1(i) for k, i in GOAL_AT.items()}

# ------------------------------------------------------------------ sheets
meta = S.get(API).json()
SID = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
# create any of our five tabs that are missing, appended at the far right
# The captainship twins are gone: every view is group-switchable in place
# (F1/E1 pickers). One board, one trend, one matrix.
_want = ["Recruiting Dashboard", "Focus Report", "Manager Matrix", "Daily Log", "Goals"]
_missing = [t for t in _want if t not in SID]
if _missing:
    _res = batch([{"addSheet": {"properties": {
        "title": t, "index": len(meta["sheets"]) + i,
        "gridProperties": {"rowCount": 4000, "columnCount": 60}}}}
        for i, t in enumerate(_missing)])
    for _rp in _res.get("replies", []):
        _pp = _rp["addSheet"]["properties"]
        SID[_pp["title"]] = _pp["sheetId"]
    print("created: %s" % ", ".join(_missing))

if "Manager Matrix" in SID:
    # the helper column sits past the visible grid, so make sure the sheet is wide
    # enough (a year of weeks pushed it beyond the original 30-column default)
    batch([{"updateSheetProperties": {"properties": {
        "sheetId": SID["Manager Matrix"],
        "gridProperties": {"columnCount": max(60, len(WEEK_ENDS) + 8)}},
        "fields": "gridProperties.columnCount"}}])
if "Manager Matrix" not in SID:
    res = batch([{"addSheet": {"properties": {
        "title": "Manager Matrix", "index": len(meta["sheets"]),
        "gridProperties": {"rowCount": 200, "columnCount": 60}}}}])
    SID["Manager Matrix"] = res["replies"][0]["addSheet"]["properties"]["sheetId"]
BOARD, TREND, LOG, GOALS = SID["Recruiting Dashboard"], SID["Focus Report"], SID["Daily Log"], SID["Goals"]
MATRIX = SID["Manager Matrix"]

# The campaign zone's data store. Created here so the zone's formulas never
# dangle on a fresh workbook, but deliberately NOT in OURS below: the hourly
# wipe re-renders the zone's FORMULAS while the DATA (stamped by
# org_campaign_metrics, typed rows synced by the Goal Sync script) lives on.
if "Campaign Log" not in SID:
    _res = batch([{"addSheet": {"properties": {
        "title": "Campaign Log", "hidden": True,
        "gridProperties": {"rowCount": 20000, "columnCount": 20}}}}])
    SID["Campaign Log"] = _res["replies"][0]["addSheet"]["properties"]["sheetId"]
    print("created: Campaign Log")

# A Trend tab is 2 + 8 columns per week and keeps growing; a freshly created
# sheet only has 60, and writing past the grid is a 400, not a resize.
for _t in (TREND,):
    batch([{"updateSheetProperties": {"properties": {
        "sheetId": _t,
        "gridProperties": {"columnCount": max(60, 2 + 8 * len(WEEK_ENDS) + 4)}},
        "fields": "gridProperties.columnCount"}}])

# wipe the illustrative data
batch([{"updateCells": {"range": {"sheetId": s}, "fields": "*"} }
       for s in (BOARD, TREND, LOG, GOALS, MATRIX)]
      + [{"deleteConditionalFormatRule": {"sheetId": s, "index": 0}}
         for s in (BOARD, TREND) for _ in range(0)])
# drop every existing CF rule + column group
info = S.get(API, params={"fields": "sheets(properties.sheetId,conditionalFormats,columnGroups,bandedRanges)"}).json()
clear = []
OURS = {BOARD, TREND, MATRIX, LOG, GOALS}
for s in info["sheets"]:
    sid = s["properties"]["sheetId"]
    if sid not in OURS:
        continue                     # never touch tabs we do not own
    for i in range(len(s.get("conditionalFormats", [])) - 1, -1, -1):
        clear.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": i}})
    for g in s.get("columnGroups", []):
        clear.append({"deleteDimensionGroup": {"range": dict(g["range"], sheetId=sid)}})
    for b in s.get("bandedRanges", []):
        clear.append({"deleteBanding": {"bandedRangeId": b["bandedRangeId"]}})
if clear:
    batch(clear)

# ------------------------------------------------------------------ values
values = [
    {"range": "'Daily Log'!A1", "values": [DAILY_HEAD]},
    {"range": "'Daily Log'!A2", "values": daily_rows},
    {"range": "Goals!A1", "values": [GOALS_HEAD]},
    {"range": "Goals!A2", "values": goal_rows},
]

# ---- Manager Board
BCOLS = [
    ("Applies", "n", "applies"), ("Removed", "n", "removed"),
    ("Removal %", "pctd", ("removed", "processed")), ("Sent to CL", "n", "sent"),
    ("Ret to CL %", "pctd", ("retb", "sent")), ("1st Bkd", "n", "b1"),
    ("1st Shw", "n", "s1"), ("1st Shw %", "pct", ("s1", "b1")),
    ("2nd Booked %", "pct", ("b2", "s1")), ("2nd Bkd", "n", "b2"),
    ("2nd Shw", "n", "s2"), ("2nd Shw %", "pct", ("s2", "b2")),
    ("Offer %", "pct", ("off", "s2")), ("Offered", "n", "off"),
    ("BOB", "n", "bob"), ("BOB Conv %", "pct", ("bob", "off")),
    ("NS Sched", "n", "nss"), ("NS Showed", "n", "nsh"), ("NS Shw %", "pct", ("nsh", "nss")),
]
KEYCOL = {c[2]: i for i, c in enumerate(BCOLS) if isinstance(c[2], str)}
B0, HDR, M0 = 1, 3, 4
WEEK_CELL = "$I$1"


def cell(kind, key, r):
    if kind == "pctd":
        n, d = key
        f = "SUMIFS('Daily Log'!$%s:$%s,'Daily Log'!$C:$C,$A%d,'Daily Log'!$B:$B,%s)"
        return "=IFERROR(%s/%s,\"\")" % (f % (COL[n], COL[n], r, WEEK_CELL),
                                          f % (COL[d], COL[d], r, WEEK_CELL))
    if kind == "derived":
        return "=%s%d+%s%d" % (a1(B0 + KEYCOL["removed"]), r, a1(B0 + KEYCOL["sent"]), r)
    if kind == "n":
        return ("=SUMIFS('Daily Log'!$%s:$%s,'Daily Log'!$C:$C,$A%d,'Daily Log'!$B:$B,%s)"
                % (COL[key], COL[key], r, WEEK_CELL))
    n, d = key
    return "=IFERROR(%s%d/%s%d,\"\")" % (a1(B0 + KEYCOL[n]), r, a1(B0 + KEYCOL[d]), r)
# hidden: per-column pace for the day reached, then the curve table it reads from
PACE_ROW, CURVE0 = 108, 110
PACE_KEY = {h: k for h, (k, kind) in GRADE.items() if kind == "count"}
MIRROR0 = B0 + len(BCOLS) + 1

# ---- Manager Trend
METRICS = [
    ("grp", "SOURCING", 0),
    ("n", "Total Applies", "applies"),
    ("n", "Removed — duplicate / DQ", "removed"),
    ("n", "Sent to Call List", "sent"),
    ("pctd", "Removal %", ("removed", "processed")),
    ("grp", "FIRST ROUND", 1),
    ("n", "1st Booked", "b1"),
    ("pctd", "Retention to Call List", ("retb", "sent")),
    ("n", "1st Showed", "s1"),
    ("pct", "1st Show %", ("s1", "b1")),
    ("grp", "SECOND ROUND", 2),
    ("n", "2nd Booked", "b2"),
    ("pct", "2nd Booked % of 1st showed", ("b2", "s1")),
    ("n", "2nd Showed", "s2"),
    ("pct", "2nd Show %", ("s2", "b2")),
    ("grp", "OFFER", 3),
    ("n", "Job Offered", "off"),
    ("pct", "Offer % of 2nd showed", ("off", "s2")),
    ("n", "BOB", "bob"),
    ("pct", "BOB Conversion", ("bob", "off")),
    ("grp", "NEW STARTS", 4),
    ("n", "New Starts Scheduled", "nss"),
    ("n", "New Starts Showed", "nsh"),
    ("pct", "New Start Show %", ("nsh", "nss")),
]
THDR, TC0, WW = 3, 2, 8
TF = THDR + 1
DAYN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ncols = TC0 + WW * len(WEEK_ENDS)

rowof = {}
for i, (k, lab, key) in enumerate(METRICS):
    if k != "grp":
        rowof[lab] = TF + i
APP_R, REM_R, SENT_R = rowof["Total Applies"], rowof["Removed — duplicate / DQ"], rowof["Sent to Call List"]
KR = {"applies": APP_R, "removed": REM_R, "sent": SENT_R, "b1": rowof["1st Booked"],
      "s1": rowof["1st Showed"], "b2": rowof["2nd Booked"], "s2": rowof["2nd Showed"],
      "off": rowof["Job Offered"], "bob": rowof["BOB"],
      "nss": rowof["New Starts Scheduled"], "nsh": rowof["New Starts Showed"]}
# ---- Manager Matrix: managers down, weeks across, ONE metric at a time.
# A grid has two axes and there are three dimensions, so the metric is the one
# that collapses — into a picker in B1 driven by the hidden definition block.
# Each metric names a numerator column, a denominator column, and how to combine
# them, so a single formula serves counts, sums and ratios alike.
MX_DEFS = [
    ("Total Applies",             "Applies",           "Applies",           "one"),
    ("Removed",                   "Removed",           "Removed",           "one"),
    ("Removal %",                 "Removed",           "Sent to Call List", "pctsum"),
    ("Sent to Call List",         "Sent to Call List", "Sent to Call List", "one"),
    ("1st Booked",                "1st Booked",        "1st Booked",        "one"),
    ("Retention to Call List",    "Ret Booked",        "Sent to Call List", "pct"),
    ("1st Showed",                "1st Showed",        "1st Showed",        "one"),
    ("1st Show %",                "1st Showed",        "1st Booked",        "pct"),
    ("2nd Booked",                "2nd Booked",        "2nd Booked",        "one"),
    ("2nd Booked % of 1st showed","2nd Booked",        "1st Showed",        "pct"),
    ("2nd Showed",                "2nd Showed",        "2nd Showed",        "one"),
    ("2nd Show %",                "2nd Showed",        "2nd Booked",        "pct"),
    ("Job Offered",               "Job Offered",       "Job Offered",       "one"),
    ("Offer % of 2nd showed",     "Job Offered",       "2nd Showed",        "pct"),
    ("BOB",                       "BOB",               "Job Offered",       "one"),
    ("BOB Conversion",            "BOB",               "Job Offered",       "pct"),
    ("New Starts Scheduled",      "NS Scheduled",      "NS Scheduled",      "one"),
    ("New Starts Showed",         "NS Showed",         "NS Showed",         "one"),
    ("New Start Show %",          "NS Showed",         "NS Scheduled",      "pct"),
]
MX_H = "$A$100:$G$%d" % (99 + len(MX_DEFS))
MX_M0 = 4                                        # first manager row
MXN = len(WEEK_ENDS) + 2                         # manager col + weeks + ALL WEEKS
MX_MAXR = 17                                     # the longer roster
MX_TOT = MX_M0 + MX_MAXR


def mx(mgr_ref, week_ref):
    def sumifs(col):
        s = ("SUMIFS(INDEX('Daily Log'!$E:$Q,0,MATCH(VLOOKUP($B$1,%s,%d,FALSE),"
             "'Daily Log'!$E$1:$Q$1,0))" % (MX_H, col))
        # The TOTAL row passes the whole name column ($A$4:$A$20): SUMIFS with a
        # range criterion returns an array, and the SUM around it collapses it —
        # so the total is the sum of the ROSTER ON SCREEN. The old '"<>"'
        # fallback summed every manager in the log, which silently included all
        # eleven captainship offices in the org total the moment the log grew
        # to 28 (2026-08-21).
        s += ",'Daily Log'!$C:$C,%s" % (mgr_ref or '$A$%d:$A$%d' % (MX_M0, MX_M0 + 16))
        if week_ref:
            s += ",'Daily Log'!$B:$B,%s" % week_ref
        return "SUM(" + s + "))"
    return ('=IFERROR(LET(n,' + sumifs(2) + ',d,' + sumifs(3) +
            ',m,VLOOKUP($B$1,' + MX_H + ',4,FALSE),'
            'IFS(m="pct",IF(d=0,"",TEXT(n/d,"0%")),'
            'm="pctsum",IF(n+d=0,"",TEXT(n/(n+d),"0%")),'
            'm="sum",n+d,TRUE,n)),"")')


matrix = [["Manager Matrix", MX_DEFS[6][0]],
          ["Every manager × every week. Pick the metric in B1." + NOTE],
          ["MANAGER"] + [w.strftime("%m/%d/%Y") for w in reversed(WEEK_ENDS)] + ["ALL WEEKS"]]
_MX_SPILL = ('=IF($E$1="Captainship",'
             'FILTER($AA$100:$AA$140,$AA$100:$AA$140<>""),'
             'FILTER($Z$100:$Z$140,$Z$100:$Z$140<>""))')
for i in range(MX_MAXR):
    r = MX_M0 + i
    matrix.append([_MX_SPILL if i == 0 else ""]
                  + ['=IF($A%d="","",%s)' % (r, mx("$A%d" % r, "%s$3" % a1(1 + wi))[1:])
                     for wi in range(len(WEEK_ENDS))]
                  + ['=IF($A%d="","",%s)' % (r, mx("$A%d" % r, None)[1:])])
matrix.append(['=IF($E$1="Captainship","CAPTAINSHIP TOTAL","OFFICE TOTAL")']
              + [mx(None, "%s$3" % a1(1 + wi)) for wi in range(len(WEEK_ENDS))]
              + [mx(None, None)])
values.append({"range": "'Manager Matrix'!A1", "values": matrix})
# both rosters for the column-A spill, parked right of the definition block
values.append({"range": "'Manager Matrix'!Z100", "values":
               [[o if i < len(ORG_NAMES) else "",
                 CAPTAINSHIP_NAMES[i] if i < len(CAPTAINSHIP_NAMES) else ""]
                for i, o in enumerate(
                    ORG_NAMES + [""] * max(0, len(CAPTAINSHIP_NAMES) - len(ORG_NAMES)))]})
try:
    _mg = S.get(API + "/values/'Manager Matrix'!E1").json().get("values", [[""]])
    _mgrp = (_mg[0][0] if _mg and _mg[0] else "").strip()
except Exception:  # noqa: BLE001
    _mgrp = ""
if _mgrp not in ("Org", "Captainship"):
    _mgrp = "Org"
values.append({"range": "'Manager Matrix'!D1", "values": [["GROUP:", _mgrp]]})
MX_GRADE = {"Sent to Call List": ("sent", "count"),
            "Removal %": ("rmvpct", "rate_low"),
            "Retention to Call List": ("ret2cl", "rate"), "1st Show %": ("sh1pct", "rate"),
            "2nd Booked % of 1st showed": ("bk2pct", "rate"), "2nd Show %": ("sh2pct", "rate"),
            "Offer % of 2nd showed": ("offpct", "rate"), "BOB Conversion": ("bobconv", "rate"),
            "New Start Show %": ("nspct", "rate")}
values.append({"range": "'Manager Matrix'!A100", "values": [
    list(d) + [GOAL_AT[MX_GRADE[d[0]][0]] if d[0] in MX_GRADE else 0,
               1 if MX_GRADE.get(d[0], ("", ""))[1] == "rate_low" else 0,
               1 if MX_GRADE.get(d[0], ("", ""))[1] == "count" else 0]
    for d in MX_DEFS]})
# hidden column: the selected metric's goal for each manager, plus two flags.
# Keeping the lookups here rather than inside the rules keeps each conditional
# format formula short enough for the API to accept.
MXG = a1(MXN + 1)
values.append({"range": "'Manager Matrix'!%s1" % MXG, "values":
               [['=IFERROR(VLOOKUP($B$1,%s,6,FALSE),0)' % MX_H],
                ['=IFERROR(VLOOKUP($B$1,%s,7,FALSE),0)' % MX_H]]})
values.append({"range": "'Manager Matrix'!%s%d" % (MXG, MX_M0), "values":
               [['=IFERROR(VLOOKUP($A%d,Goals!$B:$U,VLOOKUP($B$1,%s,5,FALSE),FALSE),0)'
                 % (MX_M0 + i, MX_H)] for i in range(len(ORG_ROSTER))]})


# ------------------------------------------------------------------ format
def gr(s, r0, r1, c0, c1):
    return {"sheetId": s, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def fmt(s, r0, r1, c0, c1, cf, fields):
    return {"repeatCell": {"range": gr(s, r0, r1, c0, c1), "cell": cf, "fields": fields}}


F = []
LEGEND_VALUES = []
# ---- centring + weight, emitted per tab by the builders above.
# Scoped to single fields so they can't disturb the colours, fonts or borders
# set alongside them. Title/subtitle rows stay left-aligned — they overflow
# across columns and centring them inside column A looks broken.
CENTER = {"userEnteredFormat": {"horizontalAlignment": "CENTER"}}
BOLD = {"userEnteredFormat": {"textFormat": {"bold": True}}}
FC, FB = "userEnteredFormat.horizontalAlignment", "userEnteredFormat.textFormat.bold"

# ---- ad budget box, on each board below its totals
#
# Reads each manager's own tracker tab (the IMPORTRANGE mirrors of their Indeed
# sheets), NOT 'Manager View'. Manager View is =INDIRECT on its own B1 picker,
# so it only ever shows one manager — whoever last touched the dropdown. The
# per-manager tabs are the real source and carry the same columns:
#   B = Report Date (a real date serial)   S = Daily Budget (a real number)
#
# Deliberately pure formulas, no scraping. The manager tabs are IMPORTRANGE, so
# Google refreshes them on its own and this box follows automatically — nobody
# has to tell the automation that a tracker was updated. INDIRECT is volatile,
# which is what we want here, and it also lets IFERROR swallow a manager who
# has no tab yet (a literal 'No Such Tab'!B2:B would be a parse error instead).
#
# Whichever rows carry the newest Report Date are the current picture, so the
# box takes MAX(date) per manager and sums Daily Budget on that date only. No
# status filter — every ad on the latest report date counts.
def budget(sid, title, nrows, row0):
    first, last = row0 + 2, row0 + 1 + nrows
    day = ("=IF($A%d=\"\",\"\",IFERROR(LET(d,INDIRECT(\"'\"&$A%d&\"'!$B$2:$B\"),"
           "b,INDIRECT(\"'\"&$A%d&\"'!$S$2:$S\"),"
           "IF(MAX(d)=0,0,SUMIF(d,MAX(d),b))),0))")
    # names mirror the board's column A, so the box follows the GROUP picker;
    # blank slots stay blank instead of rendering $0 rows.
    rows = [["=IF($A%d=\"\",\"\",$A%d)" % (M0 + i, M0 + i),
             day % (r, r, r),
             "=IF($A%d=\"\",\"\",$B%d*7)" % (r, r),
             "=IF($A%d=\"\",\"\",$B%d*DAY(EOMONTH(TODAY(),0)))" % (r, r)]
            for i, r in enumerate(range(first, first + nrows))]
    LEGEND_VALUES.append({"range": "'%s'!A%d" % (title, row0), "values":
                          [["AD BUDGET — latest report date on each manager's tracker tab"],
                           ["MANAGER", "DAILY", "WEEKLY", "MONTHLY"]]
                          + rows
                          + [["TOTAL", "=SUM(B%d:B%d)" % (first, last),
                              "=SUM(C%d:C%d)" % (first, last),
                              "=SUM(D%d:D%d)" % (first, last)]]})
    tot = last + 1
    F.extend([
        # Wipe any fill left behind by whatever previously occupied these rows —
        # the colour key used to live here and its band fills would otherwise
        # show through the new box.
        fmt(sid, row0 - 1, tot + 12, 0, 5, {"userEnteredFormat": {
            "backgroundColor": rgb("#FFFFFF")}}, "userEnteredFormat(backgroundColor)"),
        fmt(sid, row0 - 1, row0, 0, 4, {"userEnteredFormat": {
            "textFormat": txt(INK, True, 12), "horizontalAlignment": "LEFT"}},
            "userEnteredFormat(textFormat,horizontalAlignment)"),
        fmt(sid, row0, row0 + 1, 0, 4, {"userEnteredFormat": {
            "backgroundColor": rgb(INK), "textFormat": txt("#FFFFFF", True, 11),
            "horizontalAlignment": "LEFT"}},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"),
        fmt(sid, first - 1, last, 0, 1, {"userEnteredFormat": {
            "textFormat": txt(INK, False, 11), "horizontalAlignment": "LEFT",
            "borders": {"right": bdm(), "bottom": bd(LINE)}}},
            "userEnteredFormat(textFormat,horizontalAlignment,borders)"),
        # Money reads as money, and right-aligned so the columns line up.
        fmt(sid, first - 1, last, 1, 4, {"userEnteredFormat": {
            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0"},
            "textFormat": txt(INK, False, 11, FONT), "horizontalAlignment": "RIGHT",
            "borders": {"bottom": bd(LINE)}}},
            "userEnteredFormat(numberFormat,textFormat,horizontalAlignment,borders)"),
        fmt(sid, tot - 1, tot, 0, 1, {"userEnteredFormat": {
            "backgroundColor": rgb(SURF_2), "textFormat": txt(INK, True, 11),
            "horizontalAlignment": "LEFT", "borders": {"top": bdm(), "right": bdm()}}},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,borders)"),
        fmt(sid, tot - 1, tot, 1, 4, {"userEnteredFormat": {
            "backgroundColor": rgb(SURF_2),
            "numberFormat": {"type": "CURRENCY", "pattern": "$#,##0"},
            "textFormat": txt(INK, True, 11, FONT), "horizontalAlignment": "RIGHT",
            "borders": {"top": bdm()}}},
            "userEnteredFormat(backgroundColor,numberFormat,textFormat,"
            "horizontalAlignment,borders)"),
    ])
# ---- colour key, repeated on each manager tab below its data
def legend(sid, title, row0):
    n = len(LEGEND)
    LEGEND_VALUES.append({"range": "'%s'!A%d" % (title, row0), "values":
                          [["COLOR KEY — distance from goal"],
                           ["BAND", "MEANING"]]
                          + [list(x) for x in LEGEND]
                          + [["HOW IT'S MEASURED", "", ""]]
                          + [list(x) for x in LEGEND2]
                          + [["Coloured number = a count.  Filled cell = a rate.  "
                              "Removed stays black — it only restates Removal %."]]})
    F.extend([
        fmt(sid, row0 - 1, row0, 0, 3, {"userEnteredFormat": {
            "textFormat": txt(INK, True, 12), "horizontalAlignment": "LEFT"}},
            "userEnteredFormat(textFormat,horizontalAlignment)"),
        fmt(sid, row0, row0 + 1, 0, 2, {"userEnteredFormat": {
            "backgroundColor": rgb(INK), "textFormat": txt("#FFFFFF", True, 11),
            "horizontalAlignment": "LEFT"}},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"),
        fmt(sid, row0 + 1 + n, row0 + 2 + n, 0, 2, {"userEnteredFormat": {
            "backgroundColor": rgb(INK), "textFormat": txt("#FFFFFF", True, 11),
            "horizontalAlignment": "LEFT"}},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"),
        fmt(sid, row0 + 2 + n, row0 + 2 + n + len(LEGEND2), 0, 1, {"userEnteredFormat": {
            "textFormat": txt(INK, True, 11), "horizontalAlignment": "LEFT",
            "borders": {"right": bdm(), "bottom": bd(LINE)}}},
            "userEnteredFormat(textFormat,horizontalAlignment,borders)"),
        fmt(sid, row0 + 2 + n, row0 + 3 + n + len(LEGEND2), 1, 4, {"userEnteredFormat": {
            "textFormat": txt(INK_2, False, 11), "horizontalAlignment": "LEFT",
            "wrapStrategy": "CLIP"}},
            "userEnteredFormat(textFormat,horizontalAlignment,wrapStrategy)"),
        fmt(sid, row0 + 2 + n + len(LEGEND2), row0 + 3 + n + len(LEGEND2), 0, 4,
            {"userEnteredFormat": {"textFormat": txt(INK_2, False, 10),
                                   "horizontalAlignment": "LEFT", "wrapStrategy": "CLIP"}},
            "userEnteredFormat(textFormat,horizontalAlignment,wrapStrategy)"),
    ])
    for j, (fg, bg) in enumerate(((GOOD, GOOD_BG), (WARN, WARN_BG), (BAD, BAD_BG))):
        F.append(fmt(sid, row0 + 1 + j, row0 + 2 + j, 0, 1, {"userEnteredFormat": {
            "backgroundColor": rgb(bg), "textFormat": txt(fg, True, 11),
            "horizontalAlignment": "LEFT",
            "borders": {"right": bdm(), "bottom": bd(LINE)}}},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,borders)"))

def build_board(sid, title, heading, roster, total_label, ad_box=True):
    """One Manager-Board-shaped tab over `roster`.

    Every figure is a SUMIFS against Daily Log keyed on the name in column A, so
    a board is nothing but a row list — which is what lets the same code serve
    the 17-office org board and Carlos's 12-person captainship. A name with no
    rows in the log yet (someone whose AppStream office does not exist) simply
    reads zero and starts filling itself in the hour their first pull lands.
    """
    global F                       # the blocks below build it with `F += [...]`
    # GROUP-SWITCHABLE (Carlos, 2026-08-22): one tab serves both rosters. F1
    # picks Org/Captainship; column A is a FILTER spill off hidden per-tab
    # roster lists (AA/AB from row 100), and every figure was already keyed on
    # the name in column A, so the whole grid follows the picker. Rows are laid
    # out for the longer roster; blank-name rows render empty via guards and
    # contribute nothing to the SUBTOTAL totals.
    MAXR = max(len(ORG_NAMES), len(CAPTAINSHIP_NAMES))
    M1 = M0 + MAXR - 1
    TOTR = M1 + 1
    # Hidden ingredient columns for the TOTAL row's ratios. SUMIFS cannot take a
    # range of names as a criterion — it returns one sum, not an array — so the
    # total row can't work out "Removal % across just these managers" on its own.
    # (The org board used to sidestep this by filtering on the week alone, which
    # totals the WHOLE log; correct while the only board was the whole org, and
    # silently the org's own ratio on any subset.) Each ratio column gets its
    # numerator and denominator per manager, parked out of sight to the right,
    # and the total divides their SUBTOTALs — so it also tracks the filter, the
    # same way the count totals already do.
    PCTD = [i for i, c in enumerate(BCOLS) if c[1] == "pctd"]
    HELP0 = MIRROR0 + len(BCOLS) + 1
    F.append(fmt(sid, 0, 200, 0, 60, {"userEnteredFormat": {
        "textFormat": txt(), "verticalAlignment": "MIDDLE"}},
        "userEnteredFormat(textFormat,verticalAlignment)"))
    F.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0, "endIndex": 60},
        "properties": {"pixelSize": 32}, "fields": "pixelSize"}})

    board = [[heading, "", "", "", "", "", "", "Week ending", WEEK_ENDS[-1].strftime("%m/%d/%Y"),
              "", "Week day reached",
              # 1 = Mon .. 7 = Sun, from the latest day logged for the selected week.
              # A finished week reaches Sunday, so its pace factors are all 1.0 and it
              # compares against the full goal with no special case.
              "=IF($I$1>=TODAY(),WEEKDAY(TODAY(),2),7)"],
             ["Live from ApplicantStream · Retention Details (new)" + NOTE],
             ["MANAGER"] + [c[0] for c in BCOLS]]



    _SPILL = ('=IF($F$1="Captainship",'
              'FILTER($AB$100:$AB$140,$AB$100:$AB$140<>""),'
              'FILTER($AA$100:$AA$140,$AA$100:$AA$140<>""))')
    for mi in range(MAXR):
        r = M0 + mi
        namecell = _SPILL if mi == 0 else ""
        board.append([namecell]
                     + ['=IF($A%d="","",%s)' % (r, cell(k, key, r)[1:])
                        for (_, k, key) in BCOLS])

    trow = ['=IF($F$1="Captainship","CAPTAINSHIP TOTAL","OFFICE TOTAL")'
            if total_label else total_label]
    for i, (h, kind, key) in enumerate(BCOLS):
        c = a1(B0 + i)
        if kind == "pctd":
            nc, dc = a1(HELP0 + 2 * PCTD.index(i)), a1(HELP0 + 2 * PCTD.index(i) + 1)
            trow.append("=IFERROR(SUBTOTAL(109,%s%d:%s%d)/SUBTOTAL(109,%s%d:%s%d),\"\")"
                        % (nc, M0, nc, M1, dc, M0, dc, M1))
        elif kind in ("n", "derived"):
            # SUBTOTAL(109) ignores rows the filter hides, so the total reflects
            # whatever subset is on screen rather than always summing all 14.
            trow.append("=SUBTOTAL(109,%s%d:%s%d)" % (c, M0, c, M1))
        else:
            n, d = key
            trow.append("=IFERROR(%s%d/%s%d,\"\")" % (a1(B0 + KEYCOL[n]), TOTR, a1(B0 + KEYCOL[d]), TOTR))
    board.append(trow)
    values.append({"range": "'%s'!A1" % title, "values": board})
    values.append({"range": "'%s'!A100" % title,
                   "values": [[w.strftime("%m/%d/%Y")] for w in reversed(WEEK_ENDS)]})
    # both rosters, parked in hidden rows far right of the data (AA/AB); the
    # column-A spill FILTERs whichever one F1 names.
    values.append({"range": "'%s'!AA100" % title, "values":
                   [[o if i < len(ORG_NAMES) else "",
                     CAPTAINSHIP_NAMES[i] if i < len(CAPTAINSHIP_NAMES) else ""]
                    for i, o in enumerate(
                        ORG_NAMES + [""] * max(0, len(CAPTAINSHIP_NAMES) - len(ORG_NAMES)))]})
    # The GROUP picker is the USER'S cell: a rebuild must never reset it, or
    # the hourly pass flips whoever is looking at Captainship back to Org.
    # Read what is there and write the same thing back (default Org only when
    # genuinely empty), same philosophy as the typed-Goals preserve.
    try:
        _g = S.get(API + "/values/'%s'!F1" % title).json().get("values", [[""]])
        _grp = (_g[0][0] if _g and _g[0] else "").strip()
    except Exception:  # noqa: BLE001 — an unreadable picker must not kill the build
        _grp = ""
    if _grp not in ("Org", "Captainship"):
        _grp = "Org"
    values.append({"range": "'%s'!E1" % title, "values": [["GROUP:", _grp]]})
    F.append({"setDataValidation": {"range": gr(sid, 0, 1, 5, 6), "rule": {
        "condition": {"type": "ONE_OF_LIST",
                      "values": [{"userEnteredValue": "Org"},
                                 {"userEnteredValue": "Captainship"}]},
        "showCustomUi": True, "strict": True}}})
    F.append(fmt(sid, 0, 1, 4, 6, {"userEnteredFormat": {
        "textFormat": txt(INK, True, 12), "backgroundColor": rgb(WARN_BG)}},
        "userEnteredFormat(textFormat,backgroundColor)"))
    values.append({"range": "'%s'!B%d" % (title, PACE_ROW), "values": [[
        ('=IFERROR(VLOOKUP(%s$%d,$A$%d:$H$%d,$L$1+1,FALSE),1)' % (a1(B0 + i), HDR, CURVE0, CURVE0 + 20)
         if c[0] in PACE_KEY else "") for i, c in enumerate(BCOLS)]]})
    values.append({"range": "'%s'!A%d" % (title, CURVE0), "values":
                   [[h] + PACE_CURVE[k] for h, k in PACE_KEY.items()]})
    # hidden goal-mirror columns: each manager's own goal, looked up by name from Goals.
    # Start the hidden goal mirror AFTER the last data column, with one blank
    # column as a buffer. Hard-coding 19 collided with NS Shw % once the board
    # grew to 19 columns, and silently blanked it on every build.

    mirror = []
    for mi in range(MAXR):
        r = M0 + mi
        mirror.append([('=IF($A%d="","",IFERROR(VLOOKUP($A%d,Goals!$B:$U,%d,FALSE),0))'
                        % (r, r, GOAL_AT[MIRROR_KEY[c[0]]]))
                       if c[0] in MIRROR_KEY else "" for c in BCOLS])
    values.append({"range": "'%s'!%s%d" % (title, a1(MIRROR0), M0), "values": mirror})

    helper = []
    for mi in range(MAXR):
        r = M0 + mi
        row = []
        for i in PCTD:
            n, d = BCOLS[i][2]
            row += ['=IF($A%d="","",%s)' % (r, cell("n", n, r)[1:]),
                    '=IF($A%d="","",%s)' % (r, cell("n", d, r)[1:])]
        helper.append(row)
    values.append({"range": "'%s'!%s%d" % (title, a1(HELP0), M0), "values": helper})

    nb = len(BCOLS)
    F += [
        fmt(sid, 0, 1, 0, 1, {"userEnteredFormat": {"textFormat": txt(INK, True, 20)}}, "userEnteredFormat.textFormat"),
        fmt(sid, 1, 2, 0, 1, {"userEnteredFormat": {"textFormat": txt(INK_2, False, 11)}}, "userEnteredFormat.textFormat"),
        fmt(sid, 0, 1, 7, 8, {"userEnteredFormat": {"textFormat": txt(INK_3, True, 9), "horizontalAlignment": "RIGHT"}},
            "userEnteredFormat(textFormat,horizontalAlignment)"),
        fmt(sid, 0, 1, 8, 9, {"userEnteredFormat": {
            "textFormat": txt(PICK, True, 14), "backgroundColor": rgb(ACCENT_BG),
            "horizontalAlignment": "LEFT", "numberFormat": {"type": "DATE", "pattern": "m/d/yy"},
            "borders": {"top": bd(ACCENT), "bottom": bd(ACCENT), "left": bd(ACCENT), "right": bd(ACCENT)}}},
            "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment,numberFormat,borders)"),
        fmt(sid, HDR - 1, HDR, 0, nb + 1, {"userEnteredFormat": {
            "backgroundColor": rgb(INK), "textFormat": txt("#FFFFFF", True, 11),
            "horizontalAlignment": "RIGHT", "wrapStrategy": "CLIP"}},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,wrapStrategy)"),
        fmt(sid, HDR - 1, HDR, 0, 1, {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
            "userEnteredFormat.horizontalAlignment"),
        fmt(sid, M0 - 1, M1, 0, 1, {"userEnteredFormat": {
            "textFormat": txt(INK, True, 12), "horizontalAlignment": "LEFT",
            "borders": {"right": bdm()}}},
            "userEnteredFormat(textFormat,horizontalAlignment,borders)"),
        fmt(sid, M0 - 1, TOTR, 1, nb + 1, {"userEnteredFormat": {
            "textFormat": txt(INK, False, 12, FONT), "horizontalAlignment": "RIGHT",
            "numberFormat": {"type": "NUMBER", "pattern": "#,##0"}, "borders": {"bottom": bd(LINE)}}},
            "userEnteredFormat(textFormat,horizontalAlignment,numberFormat,borders)"),
        fmt(sid, TOTR - 1, TOTR, 0, nb + 1, {"userEnteredFormat": {
            "textFormat": txt(INK, True, 12, FONT), "backgroundColor": rgb(SURF_2),
            "borders": {"top": bdt(INK)}}},
            "userEnteredFormat(textFormat,backgroundColor,borders)"),
        fmt(sid, TOTR - 1, TOTR, 0, 1, {"userEnteredFormat": {
            "textFormat": txt(INK, True, 12, FONT_UI), "horizontalAlignment": "LEFT"}},
            "userEnteredFormat(textFormat,horizontalAlignment)"),
        fmt(sid, M0 - 1, TOTR, B0, B0 + 1, {"userEnteredFormat": {
            "backgroundColor": rgb(ACCENT_BG), "textFormat": txt(ACCENT, True, 12, FONT)}},
            "userEnteredFormat(backgroundColor,textFormat)"),
    ]
    for i, c in enumerate(BCOLS):
        if c[1] in ("pct", "pctd"):
            F.append(fmt(sid, M0 - 1, TOTR, B0 + i, B0 + i + 1, {"userEnteredFormat": {
                "numberFormat": {"type": "PERCENT", "pattern": "0%"}, "borders": {"left": bdm()}}},
                "userEnteredFormat(numberFormat,borders)"))

    # ---- grade every column that has a goal, on distance from that goal.
    # Counts compare to goal x pace-to-date (so mid-week is judged on run rate) and are
    # shown as coloured LETTERING; rates compare to the goal directly and are FILLED —
    # filling both turns the board into one wash.
    for i, c in enumerate(BCOLS):
        spec = GRADE.get(c[0])
        if not spec:
            continue
        gkey, kind = spec
        col, gcol = a1(B0 + i), a1(MIRROR0 + i)
        base = ("%s%d*%s$%d" % (gcol, M0, col, PACE_ROW)) if kind == "count" else "%s%d" % (gcol, M0)
        guard = 'AND(%s%d>0,ISNUMBER(%s%d),' % (gcol, M0, col, M0)
        v = "%s%d" % (col, M0)
        if kind == "rate_low":                      # under the removal goal is good
            tests = (("%s<=%s*%s" % (v, base, 2 - BAND_OK), GOOD),
                     ("AND(%s<=%s*%s,%s>%s*%s)" % (v, base, 2 - BAND_WARN, v, base, 2 - BAND_OK), WARN),
                     ("%s>%s*%s" % (v, base, 2 - BAND_WARN), BAD))
        else:
            tests = (("%s>=%s*%s" % (v, base, BAND_OK), GOOD),
                     ("AND(%s>=%s*%s,%s<%s*%s)" % (v, base, BAND_WARN, v, base, BAND_OK), WARN),
                     ("%s<%s*%s" % (v, base, BAND_WARN), BAD))
        for expr, fg in tests:
            style = ({"backgroundColor": rgb({GOOD: GOOD_BG, WARN: WARN_BG, BAD: BAD_BG}[fg]),
                      "textFormat": {"foregroundColor": rgb(fg), "bold": True}}
                     if kind != "count" else
                     {"textFormat": {"foregroundColor": rgb(fg), "bold": True}})
            F.append({"addConditionalFormatRule": {"rule": {
                "ranges": [gr(sid, M0 - 1, M1, B0 + i, B0 + i + 1)],
                "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                              "values": [{"userEnteredValue": "=" + guard + expr + ")"}]},
                                "format": style}},
                "index": 0}})

    F += [
        fmt(sid, 0, 1, 10, 11, {"userEnteredFormat": {
            "textFormat": txt(INK_3, True, 11), "horizontalAlignment": "RIGHT"}},
            "userEnteredFormat(textFormat,horizontalAlignment)"),
        fmt(sid, 0, 1, 11, 12, {"userEnteredFormat": {
            "textFormat": txt(INK, True, 13, FONT), "horizontalAlignment": "CENTER",
            "numberFormat": {"type": "NUMBER", "pattern": "0"},
            "backgroundColor": rgb(SUNKEN),
            "borders": {"top": bdm(), "bottom": bdm(), "left": bdm(), "right": bdm()}}},
            "userEnteredFormat(textFormat,horizontalAlignment,numberFormat,backgroundColor,borders)"),
        # Filter spans the Goal row + the 14 managers. Sheets treats the first row of
        # a filter range as its header, so anchoring on row 4 keeps the Goal row out of
        # the sorted data AND leaves the OFFICE TOTAL row outside the range entirely.
        {"setBasicFilter": {"filter": {"range": gr(sid, HDR - 1, M1, 0, len(BCOLS) + 1)}}},
        {"updateSheetProperties": {"properties": {
            "sheetId": sid, "gridProperties": {"frozenRowCount": HDR, "frozenColumnCount": 1}},
            "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 208}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 1, "endIndex": nb + 1},
                                       "properties": {"pixelSize": 88}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 97, "endIndex": 140},
                                       "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                                                 "startIndex": MIRROR0,
                                                 "endIndex": HELP0 + 2 * len(PCTD)},
                                       "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
        {"setDataValidation": {"range": gr(sid, 0, 1, 8, 9), "rule": {
            "condition": {"type": "ONE_OF_RANGE",
                          "values": [{"userEnteredValue": "='%s'!$A$100:$A$%d" % (title, 99 + len(WEEK_ENDS))}]},
            "showCustomUi": True, "strict": True}}},
        fmt(sid, 99, 99 + len(WEEK_ENDS), 0, 1,
            {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "m/d/yyyy"}}},
            "userEnteredFormat.numberFormat"),
    ]

    # banding: long rows are hard to track across without an alternating tint
    F.append({"addBanding": {"bandedRange": {
        "range": gr(sid, M0 - 1, TOTR, 0, len(BCOLS) + 1),
        "rowProperties": {"firstBandColor": rgb("#FFFFFF"),
                          "secondBandColor": rgb("#DCE6F2")}}}})

    # ---- Board: a rule at each funnel-stage boundary so the columns group visually
    for _h in ("Sent to CL", "2nd Bkd", "Offered", "NS Sched"):
        _i = [c[0] for c in BCOLS].index(_h)
        F.append({"updateBorders": {
            "range": gr(sid, HDR - 1, TOTR + 1, B0 + _i, B0 + _i + 1), "left": bdt(INK)}})

    # the ad budget box, then the colour key underneath it
    if ad_box:
        budget(sid, title, MAXR, TOTR + 3)
        legend(sid, title, TOTR + 3 + 2 + MAXR + 3)
    else:
        legend(sid, title, TOTR + 3)
    F.append(fmt(sid, HDR - 1, TOTR + 1, 0, len(BCOLS) + 1, CENTER, FC))
    F.append(fmt(sid, HDR - 1, TOTR + 1, 0, len(BCOLS) + 1, BOLD, FB))


# ---- campaign zone: per-campaign sales metrics below the funnel (2026-08-23).
# Geometry and formatting live here; WHAT the rows say lives on the hidden
# 'Campaign Log' tab (stamped by automations/org_campaign_metrics/) — band
# headers, labels and values are all INDEX/MATCH lookups keyed on the A1
# picker, so one generic block serves every campaign (B2B / BOX / NDS / limbo)
# and a manager with no campaign mapping renders nothing at all. Values are
# display TEXT ("288", "6.4", "79%"): one slot is a count where another
# campaign's is a rate, and a cell holds only one number format — grading CF
# compares VALUE() of the text instead.
CAMP_Z0 = TF + len(METRICS) + 2            # first zone row, 1-based
if CAMP_Z0 != CAMP_ZONE_START:
    # The installed goal_sync.gs hardcodes ZONE_START; a funnel-length change
    # moves the zone and the script would write typed goals to WRONG slots.
    # Warn loudly but keep building — this runs AFTER the wipe, and dying here
    # would leave every tab blank until someone intervened.
    print("!! CAMPAIGN ZONE MOVED: CAMP_Z0=%d but layout.ZONE_START=%d — "
          "update org_campaign_metrics/layout.py AND the installed "
          "goal_sync.gs together, or typed goals will land on wrong rows"
          % (CAMP_Z0, CAMP_ZONE_START))


def campaign_zone(sid, title):
    hc = ncols + 1                          # hidden helper column: kind per row
    hcL = a1(hc)
    CL = "'Campaign Log'"
    # the picked manager's campaign key, parked in the hidden helper column
    values.append({"range": "'%s'!%s1" % (title, hcL), "values": [[
        '=IFERROR(VLOOKUP($A$1,%s!$A:$B,2,FALSE),"")' % CL]]})
    kind_rows, grid = [], []
    for s in range(1, CAMP_SLOTS + 1):
        kind_rows.append(['=IFERROR(INDEX(%s!$G:$G,MATCH($%s$1&"|"&%d,%s!$D:$D,0)),"")'
                          % (CL, hcL, s, CL)])
        row = [None] * ncols
        row[0] = ('=IFERROR(INDEX(%s!$H:$H,MATCH($%s$1&"|"&%d,%s!$D:$D,0)),"")'
                  % (CL, hcL, s, CL))
        row[1] = ('=IFERROR(INDEX(%s!$R:$R,MATCH($A$1&"|"&%d,%s!$P:$P,0)),"")'
                  % (CL, s, CL))
        for wi in range(len(WEEK_ENDS)):
            c = a1(TC0 + wi * WW)
            # WK columns only; day cells stay empty (every campaign source is
            # weekly or rolling — day granularity can come later, data-only)
            row[TC0 + wi * WW] = (
                '=IFERROR(INDEX(%s!$N:$N,MATCH($A$1&"|"&TEXT(%s$2,"yyyy-mm-dd")'
                '&"|"&%d,%s!$J:$J,0)),"")' % (CL, c, s, CL))
        grid.append(row)
    values.append({"range": "'%s'!%s%d" % (title, hcL, CAMP_Z0), "values": kind_rows})
    values.append({"range": "'%s'!A%d" % (title, CAMP_Z0), "values": grid})

    z0, z1 = CAMP_Z0 - 1, CAMP_Z0 - 1 + CAMP_SLOTS
    F.extend([
        fmt(sid, z0, z1, 0, ncols, {"userEnteredFormat": {
            "textFormat": txt(INK, False, 12, FONT), "horizontalAlignment": "CENTER",
            "numberFormat": {"type": "TEXT"}, "borders": {"bottom": bd(LINE)}}},
            "userEnteredFormat(textFormat,horizontalAlignment,numberFormat,borders)"),
        fmt(sid, z0, z1, 0, 1, {"userEnteredFormat": {
            "textFormat": txt(INK, False, 12, FONT_UI), "horizontalAlignment": "LEFT"}},
            "userEnteredFormat(textFormat,horizontalAlignment)"),
        fmt(sid, z0, z1, 1, 2, {"userEnteredFormat": {
            "backgroundColor": rgb(SURF_2), "textFormat": txt(INK_2, False, 12, FONT),
            "borders": {"right": bdm(), "bottom": bd(LINE)}}},
            "userEnteredFormat(backgroundColor,textFormat,borders)"),
    ])
    for wi in range(len(WEEK_ENDS)):
        b = TC0 + wi * WW
        F.append(fmt(sid, z0, z1, b, b + 1, {"userEnteredFormat": {
            "textFormat": {"bold": True}, "borders": {"left": bdm(), "right": bdm()}}},
            "userEnteredFormat(textFormat,borders)"))
        F.append(fmt(sid, z0, z1, b + 6, b + 8, {"userEnteredFormat": {
            "textFormat": {"foregroundColor": rgb(INK_3)}, "backgroundColor": rgb(SURF_2)}},
            "userEnteredFormat(textFormat,backgroundColor)"))
        F.append({"updateBorders": {"range": gr(sid, z0, z1, b, b + WW),
                                    "left": bdt(INK)}})
    # band + header rows paint themselves via CF keyed on the hidden kind column
    kref = "$%s%d" % (hcL, CAMP_Z0)
    for kind, colr in [("hdr", INK)] + [("band%d" % i, STAGE[i]) for i in range(5)]:
        F.append({"addConditionalFormatRule": {"rule": {
            "ranges": [gr(sid, z0, z1, 0, ncols)],
            "booleanRule": {"condition": {
                "type": "CUSTOM_FORMULA",
                "values": [{"userEnteredValue": '=%s="%s"' % (kref, kind)}]},
                "format": {"backgroundColor": rgb(colr),
                           "textFormat": {"foregroundColor": rgb("#FFFFFF"),
                                          "bold": True}}}},
            "index": 0}})
    # violet goal cells on the rows that carry one (Head Count / units / SPR)
    F.append({"addConditionalFormatRule": {"rule": {
        "ranges": [gr(sid, z0, z1, 1, 2)],
        "booleanRule": {"condition": {
            "type": "CUSTOM_FORMULA",
            "values": [{"userEnteredValue": '=OR(%s="mg",%s="g")' % (kref, kref)}]},
            "format": {"backgroundColor": rgb(EDIT_BG),
                       "textFormat": {"foregroundColor": rgb(EDIT), "bold": True}}}},
        "index": 0}})
    # grading chips, counts convention (coloured number, no fill), mg/g rows only
    v = "IFERROR(VALUE(%s%d),-1)" % (a1(TC0), CAMP_Z0)
    g = "IFERROR(VALUE($B%d),0)" % CAMP_Z0
    graded = 'OR(%s="mg",%s="g")' % (kref, kref)
    for expr, fg in (
            ("%s>=%s*%s" % (v, g, BAND_OK), GOOD),
            ("AND(%s>=%s*%s,%s<%s*%s)" % (v, g, BAND_WARN, v, g, BAND_OK), WARN),
            ("AND(%s>=0,%s<%s*%s)" % (v, v, g, BAND_WARN), BAD)):
        F.append({"addConditionalFormatRule": {"rule": {
            "ranges": [gr(sid, z0, z1, TC0, ncols)],
            "booleanRule": {"condition": {
                "type": "CUSTOM_FORMULA",
                "values": [{"userEnteredValue": "=AND(%s,%s>0,%s)" % (graded, g, expr)}]},
                "format": {"textFormat": {"foregroundColor": rgb(fg), "bold": True}}}},
            "index": 0}})
    F.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "COLUMNS",
                  "startIndex": ncols, "endIndex": hc + 1},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})


def build_trend(sid, title, heading, roster):
    """One Manager-Trend-shaped tab, its picker limited to `roster`."""
    global F
    F.append(fmt(sid, 0, 200, 0, 60, {"userEnteredFormat": {
        "textFormat": txt(), "verticalAlignment": "MIDDLE"}},
        "userEnteredFormat(textFormat,verticalAlignment)"))
    F.append({"updateDimensionProperties": {
        "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": 0,
                  "endIndex": max(90, CAMP_Z0 + CAMP_SLOTS + 14)},
        "properties": {"pixelSize": 32}, "fields": "pixelSize"}})

    trend = [[None] * ncols for _ in range(THDR + len(METRICS))]
    # Pickers live in A1 (manager) and B1 (group): columns A/B are frozen and
    # the only ones a collapsed week group can never swallow — the old E1
    # group dropdown sat inside the first week's group, so selecting a view
    # meant expanding a week first (Carlos, 2026-08-22). No heading cell; the
    # tab name already says what this is. Keep whoever is currently picked —
    # an hourly rebuild that resets the pickers would silently flip a
    # captainship view mid-morning. Read A1:E1 so the values also survive the
    # one-time move from the old B1/E1 layout.
    _names = set(ORG_NAMES) | set(CAPTAINSHIP_NAMES) | set(CAMPAIGN_ONLY)
    _cur = _grp = ""
    try:
        _r1 = S.get(API + "/values/'%s'!A1:E1" % title).json().get("values", [[]])
        _r1 = [str(v).strip() for v in (_r1[0] if _r1 else [])]
        _cur = next((v for v in _r1 if v in _names), "")
        _grp = next((v for v in _r1 if v in ("Org", "Captainship")), "")
    except Exception:  # noqa: BLE001
        pass
    trend[0][0] = _cur or roster[0]
    trend[0][1] = _grp or "Org"
    trend[0][3] = ""                     # old "GROUP:" label — wiped
    trend[0][4] = ""                     # old E1 group dropdown — wiped
    trend[1][0] = "Click + above a week to open Mon–Sun" + NOTE
    trend[THDR - 1][0] = "METRIC"
    trend[THDR - 1][1] = "GOAL"
    # Each week block is [WK total][Mon..Sun], NOT [Mon..Sun][WK total]. Sheets draws
    # a collapsed group's +/- toggle on the column immediately BEFORE the group, so
    # putting the total first is what makes the + for a week sit above that week's own
    # header instead of above the previous week's.
    for wi, we in enumerate(reversed(WEEK_ENDS)):        # newest week first
        b = TC0 + wi * WW
        trend[THDR - 1][b] = "WK " + we.strftime("%-m/%-d")
        trend[THDR - 2][b] = we.strftime("%m/%d/%Y")
        for di in range(7):
            d = we - dt.timedelta(days=6 - di)
            trend[THDR - 1][b + 1 + di] = DAYN[di]
            trend[THDR - 2][b + 1 + di] = d.strftime("%m/%d/%Y")

    for i, (kind, lab, key) in enumerate(METRICS):
        r = TF + i
        trend[r - 1][0] = lab
        if kind == "grp":
            continue
        if kind == "pctd":
            trend[r - 1][1] = ('=IFERROR(VLOOKUP($A$1,Goals!$B:$U,%d,FALSE),"")'
                               % (GOAL_AT[TREND_PCT_GOAL[lab]]))
        elif kind == "derived":
            trend[r - 1][1] = ('=IFERROR(VLOOKUP($A$1,Goals!$B:$U,%d,FALSE),"")'
                               % (GOAL_AT["applies"]))
        elif kind == "n":
            trend[r - 1][1] = ("=IFERROR(VLOOKUP($A$1,Goals!$B:$U,%d,FALSE),\"\")"
                               % (GOAL_AT[key]))
        elif lab in TREND_PCT_GOAL:
            trend[r - 1][1] = ('=IFERROR(VLOOKUP($A$1,Goals!$B:$U,%d,FALSE),"")'
                               % GOAL_AT[TREND_PCT_GOAL[lab]])
        else:
            n, d = key
            trend[r - 1][1] = "=IFERROR(B%d/B%d,\"\")" % (KR[n], KR[d])
        for wi in range(len(WEEK_ENDS)):
            b = TC0 + wi * WW
            for di in range(8):
                c = a1(b + di)
                if kind == "pctd":
                    n, d = key
                    col_c = ("SUMIFS('Daily Log'!$%s:$%s,'Daily Log'!$C:$C,$A$1,"
                             "'Daily Log'!$%s:$%s,%s$2)")
                    ax = "A" if di > 0 else "B"        # day cells match the date, WK the week
                    f = "=IFERROR(%s/%s,\"\")" % (
                        col_c % (COL[n], COL[n], ax, ax, c), col_c % (COL[d], COL[d], ax, ax, c))
                elif kind == "derived":
                    f = "=%s%d+%s%d" % (c, REM_R, c, SENT_R)
                elif kind == "n":
                    f = ("=SUM(%s%d:%s%d)" % (a1(b + 1), r, a1(b + 7), r) if di == 0 else
                         "=SUMIFS('Daily Log'!$%s:$%s,'Daily Log'!$C:$C,$A$1,'Daily Log'!$A:$A,%s$2)"
                         % (COL[key], COL[key], c))
                else:
                    n, d = key
                    f = "=IFERROR(%s%d/%s%d,\"\")" % (c, KR[n], c, KR[d])
                trend[r - 1][b + di] = f

    values.append({"range": "'%s'!A1" % title, "values": trend})
    # A100 is the picker's source list; it FILTERs whichever roster the
    # preserved GROUP cell (B1) names, from the two hidden lists in D100/E100.
    values.append({"range": "'%s'!A100" % title, "values": [[
        '=IF($B$1="Captainship",FILTER($E$100:$E$140,$E$100:$E$140<>""),'
        'FILTER($D$100:$D$140,$D$100:$D$140<>""))']]})
    # the Org picker list carries the campaign-only people too (MJ, Akib):
    # they have no org funnel data, but their campaign block below needs a
    # picker entry to render on
    _pick = ORG_NAMES + CAMPAIGN_ONLY
    values.append({"range": "'%s'!D100" % title, "values":
                   [[_pick[i] if i < len(_pick) else "",
                     CAPTAINSHIP_NAMES[i] if i < len(CAPTAINSHIP_NAMES) else ""]
                    for i in range(max(len(_pick), len(CAPTAINSHIP_NAMES)))]})
    F.append({"setDataValidation": {"range": gr(sid, 0, 1, 1, 2), "rule": {
        "condition": {"type": "ONE_OF_LIST",
                      "values": [{"userEnteredValue": "Org"},
                                 {"userEnteredValue": "Captainship"}]},
        "showCustomUi": True, "strict": True}}})
    # the group dropdown used to be E1 — clear its rule and paint so a stale
    # chip doesn't linger inside the first collapsed week group
    F.append({"setDataValidation": {"range": gr(sid, 0, 1, 3, 5)}})
    F.append(fmt(sid, 0, 1, 3, 5, {"userEnteredFormat": {
        "backgroundColor": rgb("#FFFFFF"), "textFormat": txt()}},
        "userEnteredFormat(backgroundColor,textFormat)"))

    # ---- Trend formatting
    F += [
        fmt(sid, 0, 1, 0, 1, {"userEnteredFormat": {
            "textFormat": txt(PICK, True, 14), "backgroundColor": rgb(ACCENT_BG), "horizontalAlignment": "LEFT",
            "borders": {"top": bd(ACCENT), "bottom": bd(ACCENT), "left": bd(ACCENT), "right": bd(ACCENT)}}},
            "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment,borders)"),
        fmt(sid, 0, 1, 1, 2, {"userEnteredFormat": {
            "textFormat": txt(INK, True, 12), "backgroundColor": rgb(WARN_BG), "horizontalAlignment": "CENTER"}},
            "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment)"),
        fmt(sid, 1, 2, 0, 1, {"userEnteredFormat": {"textFormat": txt(INK_2, False, 11)}}, "userEnteredFormat.textFormat"),
        fmt(sid, 1, 2, TC0, ncols, {"userEnteredFormat": {
            "textFormat": txt(INK_2, False, 10, FONT), "horizontalAlignment": "CENTER",
            "numberFormat": {"type": "DATE", "pattern": "m/d"}, "backgroundColor": rgb(SURF_2)}},
            "userEnteredFormat(textFormat,horizontalAlignment,numberFormat,backgroundColor)"),
        fmt(sid, THDR - 1, THDR, 0, ncols, {"userEnteredFormat": {
            "backgroundColor": rgb(INK), "textFormat": txt("#FFFFFF", True, 11), "horizontalAlignment": "RIGHT"}},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"),
        fmt(sid, THDR - 1, THDR, 0, 1, {"userEnteredFormat": {"horizontalAlignment": "LEFT"}},
            "userEnteredFormat.horizontalAlignment"),
        fmt(sid, TF - 1, TF + len(METRICS) - 1, 0, ncols, {"userEnteredFormat": {
            "textFormat": txt(INK, False, 12, FONT), "horizontalAlignment": "RIGHT",
            "numberFormat": {"type": "NUMBER", "pattern": "#,##0"}, "borders": {"bottom": bd(LINE)}}},
            "userEnteredFormat(textFormat,horizontalAlignment,numberFormat,borders)"),
        fmt(sid, TF - 1, TF + len(METRICS) - 1, 0, 1, {"userEnteredFormat": {
            "textFormat": txt(INK, False, 12, FONT_UI), "horizontalAlignment": "LEFT",
            "borders": {"bottom": bd(LINE)}}},
            "userEnteredFormat(textFormat,horizontalAlignment,borders)"),
        fmt(sid, TF - 1, TF + len(METRICS) - 1, 1, 2, {"userEnteredFormat": {
            "backgroundColor": rgb(SURF_2), "textFormat": txt(INK_2, False, 12, FONT),
            "borders": {"right": bdm(), "bottom": bd(LINE)}}},
            "userEnteredFormat(backgroundColor,textFormat,borders)"),
    ]
    # GOAL cells whose Goals-tab source is amber (typed, gradable) get the same
    # amber here — Carlos edits these; grey ones are computed (2026-08-22).
    for i, (kind, lab, key) in enumerate(METRICS):
        amber = ((kind == "n" and key in GOALS_AMBER)
                 or kind == "pctd"
                 or (kind == "pct" and lab in TREND_PCT_GOAL))
        if amber:
            F.append(fmt(sid, TF + i - 1, TF + i, 1, 2, {"userEnteredFormat": {
                "backgroundColor": rgb(EDIT_BG), "textFormat": txt(EDIT, True, 12, FONT),
                "borders": {"left": bdm(EDIT), "right": bdm(EDIT)}}},
                "userEnteredFormat(backgroundColor,textFormat,borders)"))

    for wi in range(len(WEEK_ENDS)):
        b = TC0 + wi * WW
        # week total is now the FIRST column of the block
        F.append(fmt(sid, THDR - 1, TF + len(METRICS) - 1, b, b + 1, {"userEnteredFormat": {
            "textFormat": {"bold": True}, "borders": {"left": bdm(), "right": bdm()}}},
            "userEnteredFormat(textFormat,borders)"))
        # Sat + Sun (day slots 6 and 7 within the block) read back
        F.append(fmt(sid, TF - 1, TF + len(METRICS) - 1, b + 6, b + 8, {"userEnteredFormat": {
            "textFormat": {"foregroundColor": rgb(INK_3)}, "backgroundColor": rgb(SURF_2)}},
            "userEnteredFormat(textFormat,backgroundColor)"))
        F.append({"addDimensionGroup": {"range": {
            "sheetId": sid, "dimension": "COLUMNS", "startIndex": b + 1, "endIndex": b + 8}}})

    LOWER_BETTER = {"Removal %"}
    for i, (kind, lab, key) in enumerate(METRICS):
        r = TF + i
        if kind == "grp":
            F.append(fmt(sid, r - 1, r, 0, ncols, {"userEnteredFormat": {
                "backgroundColor": rgb(STAGE[key]), "textFormat": txt("#FFFFFF", True, 10),
                "horizontalAlignment": "LEFT", "borders": {}}},
                "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,borders)"))
            F.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS", "startIndex": r - 1, "endIndex": r},
                "properties": {"pixelSize": 28}, "fields": "pixelSize"}})
        elif kind == "derived":
            F.append(fmt(sid, r - 1, r, 0, ncols, {"userEnteredFormat": {
                "backgroundColor": rgb(ACCENT_BG), "textFormat": txt(ACCENT, True, 12, FONT)}},
                "userEnteredFormat(backgroundColor,textFormat)"))
            F.append(fmt(sid, r - 1, r, 0, 1, {"userEnteredFormat": {
                "textFormat": txt(ACCENT, True, 12, FONT_UI)}}, "userEnteredFormat.textFormat"))
        elif kind in ("pct", "pctd"):
            F.append(fmt(sid, r - 1, r, 1, ncols, {"userEnteredFormat": {
                "numberFormat": {"type": "PERCENT", "pattern": "0%"}, "textFormat": txt(INK_2, False, 11, FONT)}},
                "userEnteredFormat(numberFormat,textFormat)"))
            F.append(fmt(sid, r - 1, r, 0, 1, {"userEnteredFormat": {
                "textFormat": txt(INK_2, False, 11, FONT_UI)}}, "userEnteredFormat.textFormat"))
            if lab not in TREND_PCT_GOAL:
                continue                      # no goal behind it — leave it uncoloured
            # A rate does not accumulate, so every cell (each day and the week total)
            # is comparable to the goal in column B as-is.
            low = lab == "Removal %"
            v, g = "C%d" % r, "$B%d" % r
            tests = (((("%s<=%s*%s" % (v, g, 2 - BAND_OK), GOOD, GOOD_BG),
                       ("AND(%s<=%s*%s,%s>%s*%s)" % (v, g, 2 - BAND_WARN, v, g, 2 - BAND_OK), WARN, WARN_BG),
                       ("%s>%s*%s" % (v, g, 2 - BAND_WARN), BAD, BAD_BG)) if low else
                      (("%s>=%s*%s" % (v, g, BAND_OK), GOOD, GOOD_BG),
                       ("AND(%s>=%s*%s,%s<%s*%s)" % (v, g, BAND_WARN, v, g, BAND_OK), WARN, WARN_BG),
                       ("%s<%s*%s" % (v, g, BAND_WARN), BAD, BAD_BG))))
            for expr, fg, bg in tests:
                f = '=AND(ISNUMBER(%s),%s>0,%s)' % (v, g, expr)
                F.append({"addConditionalFormatRule": {"rule": {
                    "ranges": [gr(sid, r - 1, r, TC0, ncols)],
                    "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                                  "values": [{"userEnteredValue": f}]},
                                    "format": {"backgroundColor": rgb(bg),
                                               "textFormat": {"foregroundColor": rgb(fg), "bold": True}}}},
                    "index": 0}})
        elif kind == "n" and key in set(GRADE[h][0] for h in GRADE if GRADE[h][1] == "count"):
            # Counts accumulate, so only the WEEK-TOTAL columns are comparable to a
            # weekly goal; a single day against a week's target means nothing.
            for wi in range(len(WEEK_ENDS)):
                wcol = a1(TC0 + wi * WW)
                v, g = "%s%d" % (wcol, r), "$B%d" % r
                for expr, fg in (("%s>=%s*%s" % (v, g, BAND_OK), GOOD),
                                 ("AND(%s>=%s*%s,%s<%s*%s)" % (v, g, BAND_WARN, v, g, BAND_OK), WARN),
                                 ("%s<%s*%s" % (v, g, BAND_WARN), BAD)):
                    f = '=AND(ISNUMBER(%s),%s>0,%s)' % (v, g, expr)
                    F.append({"addConditionalFormatRule": {"rule": {
                        "ranges": [gr(sid, r - 1, r, TC0 + wi * WW, TC0 + wi * WW + 1)],
                        "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                                      "values": [{"userEnteredValue": f}]},
                                        "format": {"textFormat": {"foregroundColor": rgb(fg),
                                                                  "bold": True}}}},
                        "index": 0}})

    F += [
        {"updateSheetProperties": {"properties": {
            "sheetId": sid, "gridProperties": {"frozenRowCount": THDR, "frozenColumnCount": 2}},
            "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 250}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 1, "endIndex": ncols},
                                       "properties": {"pixelSize": 80}, "fields": "pixelSize"}},
        # The picker reads this tab's OWN hidden name list (row 100 down), not a
        # slice of Goals. Goals is ordered by the org board, so a captainship — a
        # scattered subset of those rows — cannot be expressed as a range there.
        {"setDataValidation": {"range": gr(sid, 0, 1, 0, 1), "rule": {
            "condition": {"type": "ONE_OF_RANGE",
                          "values": [{"userEnteredValue": "='%s'!$A$100:$A$%d"
                                      % (title, 99 + max(len(ORG_NAMES) + len(CAMPAIGN_ONLY),
                                                         len(CAPTAINSHIP_NAMES)))}]},
            "showCustomUi": True, "strict": True}}},
        {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                 "startIndex": 97, "endIndex": 140},
                                       "properties": {"hiddenByUser": True},
                                       "fields": "hiddenByUser"}},
    ]

    # ---- vertical rules so each week block reads as one unit
    for wi in range(len(WEEK_ENDS)):
        b = TC0 + wi * WW
        F.append({"updateBorders": {
            "range": gr(sid, THDR - 1, TF + len(METRICS) - 1, b, b + WW),
            "left": bdt(INK)}})

    campaign_zone(sid, title)
    legend(sid, title, CAMP_Z0 + CAMP_SLOTS + 2)
    F.append(fmt(sid, THDR - 2, TF + len(METRICS) - 1, 0, ncols, CENTER, FC))
    # On the Trend the counts are the story and the rates are support, so bold
    # the count rows only — bolding both flattens that back out.
    for i, (kind, lab, key) in enumerate(METRICS):
        if kind in ("n", "derived"):
            F.append(fmt(sid, TF + i - 1, TF + i, 0, ncols, BOLD, FB))
    F.append(fmt(sid, THDR - 1, THDR, 0, ncols, BOLD, FB))


# ---- the two cuts of the same data.
# Org first so its formatting lands first; they touch different tabs, so the
# order is only about what a reader sees in the request log.
build_board(BOARD, "Recruiting Dashboard", "Recruiting Dashboard", ORG_ROSTER, "OFFICE TOTAL")
build_trend(TREND, "Focus Report", "Focus Report", ORG_ROSTER)


call("/values:batchUpdate", {"valueInputOption": "USER_ENTERED", "data": values})
print("values written")

# ---- Manager Matrix formatting
F += [
    fmt(MATRIX, 0, 200, 0, 30, {"userEnteredFormat": {
        "textFormat": txt(), "verticalAlignment": "MIDDLE"}},
        "userEnteredFormat(textFormat,verticalAlignment)"),
    {"updateDimensionProperties": {
        "range": {"sheetId": MATRIX, "dimension": "ROWS", "startIndex": 0, "endIndex": 40},
        "properties": {"pixelSize": 32}, "fields": "pixelSize"}},
    fmt(MATRIX, 0, 1, 0, 1, {"userEnteredFormat": {"textFormat": txt(INK, True, 20)}},
        "userEnteredFormat.textFormat"),
    fmt(MATRIX, 0, 1, 1, 2, {"userEnteredFormat": {
        "textFormat": txt(PICK, True, 14), "backgroundColor": rgb(PICK_BG),
        "horizontalAlignment": "LEFT",
        "borders": {"top": bdm(PICK), "bottom": bdm(PICK), "left": bdm(PICK), "right": bdm(PICK)}}},
        "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment,borders)"),
    fmt(MATRIX, 1, 2, 0, 1, {"userEnteredFormat": {"textFormat": txt(INK_2, False, 11)}},
        "userEnteredFormat.textFormat"),
    fmt(MATRIX, 2, 3, 0, MXN, {"userEnteredFormat": {
        "backgroundColor": rgb(INK), "textFormat": txt("#FFFFFF", True, 11),
        "horizontalAlignment": "RIGHT",
        "numberFormat": {"type": "DATE", "pattern": "m/d/yy"}}},
        "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,numberFormat)"),
    fmt(MATRIX, 2, 3, 0, 1, {"userEnteredFormat": {
        "horizontalAlignment": "LEFT", "numberFormat": {"type": "TEXT"}}},
        "userEnteredFormat(horizontalAlignment,numberFormat)"),
    fmt(MATRIX, 2, 3, MXN - 1, MXN, {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
        "userEnteredFormat.numberFormat"),
    fmt(MATRIX, MX_M0 - 1, MX_TOT, 0, 1, {"userEnteredFormat": {
        "textFormat": txt(INK, True, 12), "horizontalAlignment": "LEFT",
        "borders": {"right": bdm()}}},
        "userEnteredFormat(textFormat,horizontalAlignment,borders)"),
    # Ratios come back as text (a column can hold only one number format, and this
    # one flips between counts and percentages with the picker) — align them like
    # numbers so the column still reads as a column.
    fmt(MATRIX, MX_M0 - 1, MX_TOT, 1, MXN, {"userEnteredFormat": {
        "textFormat": txt(INK, False, 12, FONT), "horizontalAlignment": "RIGHT",
        "numberFormat": {"type": "NUMBER", "pattern": "#,##0"},
        "borders": {"bottom": bd(LINE)}}},
        "userEnteredFormat(textFormat,horizontalAlignment,numberFormat,borders)"),
    fmt(MATRIX, MX_M0 - 1, MX_TOT, MXN - 1, MXN, {"userEnteredFormat": {
        "backgroundColor": rgb(ACCENT_BG), "textFormat": txt(ACCENT, True, 12, FONT),
        "borders": {"left": bdm()}}},
        "userEnteredFormat(backgroundColor,textFormat,borders)"),
    fmt(MATRIX, MX_TOT, MX_TOT + 1, 0, MXN, {"userEnteredFormat": {
        "textFormat": txt(INK, True, 12, FONT), "backgroundColor": rgb(SURF_2),
        "horizontalAlignment": "RIGHT",
        "borders": {"top": bdt(INK)}}},
        "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment,borders)"),
    fmt(MATRIX, MX_TOT, MX_TOT + 1, 0, 1, {"userEnteredFormat": {
        "textFormat": txt(INK, True, 12, FONT_UI), "horizontalAlignment": "LEFT"}},
        "userEnteredFormat(textFormat,horizontalAlignment)"),
    {"updateSheetProperties": {"properties": {
        "sheetId": MATRIX, "gridProperties": {"frozenRowCount": 3, "frozenColumnCount": 1}},
        "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
    {"updateDimensionProperties": {
        "range": {"sheetId": MATRIX, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 215}, "fields": "pixelSize"}},
    {"updateDimensionProperties": {
        "range": {"sheetId": MATRIX, "dimension": "COLUMNS", "startIndex": 1, "endIndex": MXN},
        "properties": {"pixelSize": 126}, "fields": "pixelSize"}},
    {"updateDimensionProperties": {
        "range": {"sheetId": MATRIX, "dimension": "ROWS", "startIndex": 97, "endIndex": 140},
        "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
    {"setDataValidation": {"range": gr(MATRIX, 0, 1, 1, 2), "rule": {
        "condition": {"type": "ONE_OF_RANGE",
                      "values": [{"userEnteredValue": "='Manager Matrix'!$A$100:$A$%d"
                                  % (99 + len(MX_DEFS))}]},
        "showCustomUi": True, "strict": True}}},
    {"setDataValidation": {"range": gr(MATRIX, 0, 1, 4, 5), "rule": {
        "condition": {"type": "ONE_OF_LIST",
                      "values": [{"userEnteredValue": "Org"},
                                 {"userEnteredValue": "Captainship"}]},
        "showCustomUi": True, "strict": True}}},
]

# ---- banding: long rows are hard to track across without an alternating tint
F.append({"addBanding": {"bandedRange": {
    "range": gr(MATRIX, MX_M0 - 1, MX_TOT, 0, MXN),
    "rowProperties": {"firstBandColor": rgb("#FFFFFF"),
                      "secondBandColor": rgb("#DCE6F2")}}}})

for wi in range(len(WEEK_ENDS) + 1):
    F.append({"updateBorders": {
        "range": gr(MATRIX, 2, MX_TOT + 1, 1 + wi, 2 + wi), "left": bdm()}})

for s, n in ((LOG, len(DAILY_HEAD)), (GOALS, len(GOALS_HEAD))):
    F += [
        fmt(s, 0, 1, 0, n, {"userEnteredFormat": {
            "backgroundColor": rgb(INK), "textFormat": txt("#FFFFFF", True, 11),
            "horizontalAlignment": "RIGHT", "wrapStrategy": "WRAP"}},
            "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,wrapStrategy)"),
        fmt(s, 1, 900, 0, n, {"userEnteredFormat": {
            "textFormat": txt(INK, False, 11, FONT), "horizontalAlignment": "RIGHT",
            "numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}},
            "userEnteredFormat(textFormat,horizontalAlignment,numberFormat)"),
        {"updateSheetProperties": {"properties": {"sheetId": s, "gridProperties": {"frozenRowCount": 1}},
                                   "fields": "gridProperties.frozenRowCount"}},
        {"updateDimensionProperties": {"range": {"sheetId": s, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 44}, "fields": "pixelSize"}},
    ]
F += [
    fmt(LOG, 1, 900, 0, 2, {"userEnteredFormat": {
        "numberFormat": {"type": "DATE", "pattern": "ddd m/d/yy"}, "horizontalAlignment": "LEFT",
        "textFormat": txt(INK_2, False, 11, FONT)}},
        "userEnteredFormat(numberFormat,horizontalAlignment,textFormat)"),
    fmt(LOG, 1, 900, 2, 4, {"userEnteredFormat": {
        "horizontalAlignment": "LEFT", "textFormat": txt(INK, False, 11, FONT_UI)}},
        "userEnteredFormat(horizontalAlignment,textFormat)"),
    {"updateDimensionProperties": {"range": {"sheetId": LOG, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 3},
                                   "properties": {"pixelSize": 126}, "fields": "pixelSize"}},
    fmt(GOALS, 1, 900, 0, 2, {"userEnteredFormat": {
        "horizontalAlignment": "LEFT", "textFormat": txt(INK, True, 11, FONT_UI)}},
        "userEnteredFormat(horizontalAlignment,textFormat)"),
]
# ---- mark the Goals tab so it is obvious which cells actually drive a colour
NG = len(goal_rows) + 1
for k in GOALS_AMBER:                                   # amber = edit me, I grade
    ci = GOAL_AT[k]
    F.append(fmt(GOALS, 1, NG, ci, ci + 1, {"userEnteredFormat": {
        "backgroundColor": rgb(EDIT_BG), "textFormat": txt(EDIT, True, 12, FONT),
        "borders": {"left": bdm(EDIT), "right": bdm(EDIT)}}},
        "userEnteredFormat(backgroundColor,textFormat,borders)"))
    F.append(fmt(GOALS, 0, 1, ci, ci + 1, {"userEnteredFormat": {
        "backgroundColor": rgb(EDIT), "textFormat": txt("#FFFFFF", True, 11)}},
        "userEnteredFormat(backgroundColor,textFormat)"))
for h in GOALS_COMPUTED:                                 # grey = formula, hands off
    ci = GOALS_HEAD.index(h)
    F.append(fmt(GOALS, 1, NG, ci, ci + 1, {"userEnteredFormat": {
        "backgroundColor": rgb(SUNKEN), "textFormat": txt(INK_3, False, 11, FONT),
        "numberFormat": ({"type": "PERCENT", "pattern": "0%"} if "%" in h
                         else {"type": "NUMBER", "pattern": "#,##0"})}},
        "userEnteredFormat(backgroundColor,textFormat,numberFormat)"))
# the retention goal is a percentage, not a count
for _rc in (GOAL_AT[k] for k in ("rmvpct", "ret2cl", "sh1pct", "bk2pct",
                                 "sh2pct", "offpct", "bobconv", "nspct")):
    F.append(fmt(GOALS, 1, NG, _rc, _rc + 1, {"userEnteredFormat": {
        "numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
        "userEnteredFormat.numberFormat"))

# The colour key sits BETWEEN the two boxes (Carlos, 2026-08-22) — rows 46-54
# under the captainship box were dead scroll. _LG is its top row, inside the
# gap the boxes leave open; the old below-the-box rows are scrubbed each run.
_LG = len(_ORG_PART) + 3
GKEY = 0
F += [
    # clean the gap first: the amber/grey column striping above runs rows 2..NG
    # and would otherwise band straight through the space between the boxes
    fmt(GOALS, len(_ORG_PART) + 1, _CAP_HEADER_AT - 2, 0, len(GOALS_HEAD),
        {"userEnteredFormat": {"backgroundColor": rgb("#FFFFFF"), "borders": {}}},
        "userEnteredFormat(backgroundColor,borders)"),
    fmt(GOALS, _LG - 1, _LG, 1, 6, {"userEnteredFormat": {
        "textFormat": txt(INK, True, 12), "horizontalAlignment": "LEFT"}},
        "userEnteredFormat(textFormat,horizontalAlignment)"),
    fmt(GOALS, _LG, _LG + 1, 1, 6, {"userEnteredFormat": {
        "backgroundColor": rgb(INK), "textFormat": txt("#FFFFFF", True, 11),
        "horizontalAlignment": "LEFT"}},
        "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"),
    fmt(GOALS, _LG + 1, _LG + 2, 1, 2, {"userEnteredFormat": {
        "backgroundColor": rgb(EDIT_BG), "textFormat": txt(EDIT, True, 11, FONT),
        "borders": {"left": bdm(EDIT), "right": bdm(EDIT)}}},
        "userEnteredFormat(backgroundColor,textFormat,borders)"),
    fmt(GOALS, _LG + 2, _LG + 3, 1, 2, {"userEnteredFormat": {
        "backgroundColor": rgb(SUNKEN), "textFormat": txt(INK_3, False, 11, FONT)}},
        "userEnteredFormat(backgroundColor,textFormat)"),
    fmt(GOALS, _LG + 1, _LG + 4, 2, 6, {"userEnteredFormat": {
        "textFormat": txt(INK_2, False, 11), "horizontalAlignment": "LEFT",
        "wrapStrategy": "CLIP"}},
        "userEnteredFormat(textFormat,horizontalAlignment,wrapStrategy)"),
    # scrub the key's old home below the captainship box: values are blanked
    # via LEGEND_VALUES, formats here
    fmt(GOALS, NG + 1, NG + 12, 0, 8, {"userEnteredFormat": {
        "backgroundColor": rgb("#FFFFFF"), "borders": {}}},
        "userEnteredFormat(backgroundColor,borders)"),
]
LEGEND_VALUES.append({"range": "Goals!B%d" % (NG + 3),
                      "values": [[""] * 6 for _ in range(9)]})
LEGEND_VALUES.append({"range": "Goals!B%d" % _LG, "values": [
    ["WHICH CELLS MATTER"],
    ["CELL LOOK", "MEANING"],
    ["violet", "You edit these. They grade the Recruiting Dashboard — each manager against their OWN row. Also editable straight on the Focus Report's GOAL column."],
    ["grey", "Formulas. Removal % = Removed / Applies. 1st Booked = Sent to Call List x Retention to Call List. Don't type over them."],
    ["plain", "You may edit. Shown on the Manager Trend GOAL column, but grades nothing today."],
    [""],
    ["YOU TYPE: " + ", ".join(GOALS_HEAD[GOAL_AT[k]] for k in GOALS_AMBER)],
    ["Counts: value vs (goal x pace to date) — 80%+ green, 60-80% yellow, under 60% red."],
    ["Retention to Call List: actual vs your goal — at/above green, within 90% yellow, below red."],
]})
F += [
    # office id and the intake breakdown are traceability, not things to read
    {"updateDimensionProperties": {"range": {"sheetId": GOALS, "dimension": "COLUMNS",
                                            "startIndex": 0, "endIndex": 1},
                                   "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
    {"updateDimensionProperties": {"range": {"sheetId": LOG, "dimension": "COLUMNS",
                                             "startIndex": len(DAILY_HEAD) - len(AUDIT_HEAD),
                                             "endIndex": len(DAILY_HEAD)},
                                   "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}},
    {"updateDimensionProperties": {"range": {"sheetId": GOALS, "dimension": "COLUMNS", "startIndex": 1, "endIndex": 2},
                                   "properties": {"pixelSize": 208}, "fields": "pixelSize"}},
]

# ---- Goals: draw the two sections as real boxes (Carlos, 2026-08-22) — a
# bordered ORG box, a clean gap, and a bordered CAPTAINSHIP box with its own
# title bar, instead of bare rows separated by empty space. Appended after the
# amber/grey striping so these repaints win where they overlap.
_GN = len(GOALS_HEAD)
_CAP_TITLE_R = _CAP_HEADER_AT - 1          # 1-based title-bar row (31)
F += [
    # captainship title bar
    fmt(GOALS, _CAP_TITLE_R - 1, _CAP_TITLE_R, 1, _GN, {"userEnteredFormat": {
        "backgroundColor": rgb(ACCENT), "textFormat": txt("#FFFFFF", True, 12),
        "horizontalAlignment": "LEFT", "verticalAlignment": "MIDDLE"}},
        "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"),
    {"updateDimensionProperties": {"range": {"sheetId": GOALS, "dimension": "ROWS",
                                             "startIndex": _CAP_TITLE_R - 1,
                                             "endIndex": _CAP_TITLE_R},
                                   "properties": {"pixelSize": 34}, "fields": "pixelSize"}},
    # its header row gets the same dark treatment as the org header in row 1
    fmt(GOALS, _CAP_HEADER_AT - 1, _CAP_HEADER_AT, 1, _GN, {"userEnteredFormat": {
        "backgroundColor": rgb(INK), "textFormat": txt("#FFFFFF", True, 11),
        "horizontalAlignment": "RIGHT", "wrapStrategy": "WRAP"}},
        "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,wrapStrategy)"),
    # a medium border box around each section
    {"updateBorders": {"range": gr(GOALS, 0, len(_ORG_PART) + 1, 1, _GN),
                       "top": bdm(), "bottom": bdm(), "left": bdm(), "right": bdm()}},
    {"updateBorders": {"range": gr(GOALS, _CAP_TITLE_R - 1, NG, 1, _GN),
                       "top": bdm(), "bottom": bdm(), "left": bdm(), "right": bdm()}},
]

# ---- Manager Matrix: the metric is chosen at runtime, so each rule is gated on
# the picker. Values there are TEXT ("54%"), hence VALUE() with an IFERROR guard.
# ---- Manager Matrix: same bands, against each manager's own goal. Rates compare
# on every week; counts skip the in-flight week, whose part-total can't be judged
# against a full week's target.
_g, _v = "$%s%d" % (MXG, MX_M0), 'IFERROR(VALUE(B%d),"")' % MX_M0
for is_count, c0 in ((0, 1), (1, 2)):
    if c0 >= MXN:
        continue
    lo = [("<=%s*%s" % (_g, 2 - BAND_OK), GOOD, GOOD_BG),
          (">%s*%s" % (_g, 2 - BAND_OK), WARN, WARN_BG),
          (">%s*%s" % (_g, 2 - BAND_WARN), BAD, BAD_BG)]
    hi = [(">=%s*%s" % (_g, BAND_OK), GOOD, GOOD_BG),
          ("<%s*%s" % (_g, BAND_OK), WARN, WARN_BG),
          ("<%s*%s" % (_g, BAND_WARN), BAD, BAD_BG)]
    for low_flag, tests in ((1, lo), (0, hi)):
        for expr, fg, bg in tests:
            f = ('=AND($%s$2=%d,$%s$1=%d,%s>0,ISNUMBER(%s),%s%s)'
                 % (MXG, is_count, MXG, low_flag, _g, _v, _v, expr))
            F.append({"addConditionalFormatRule": {"rule": {
                "ranges": [gr(MATRIX, MX_M0 - 1, MX_TOT, c0, MXN)],
                "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                              "values": [{"userEnteredValue": f}]},
                                "format": {"backgroundColor": rgb(bg),
                                           "textFormat": {"foregroundColor": rgb(fg),
                                                          "bold": True}}}},
                "index": 0}})
F.append({"updateDimensionProperties": {
    "range": {"sheetId": MATRIX, "dimension": "COLUMNS",
              "startIndex": MXN + 1, "endIndex": MXN + 2},
    "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})
legend(MATRIX, "Manager Matrix", MX_TOT + 3)

call("/values:batchUpdate", {"valueInputOption": "USER_ENTERED", "data": LEGEND_VALUES})

F.append(fmt(MATRIX, 2, MX_TOT + 1, 0, MXN, CENTER, FC))
F.append(fmt(LOG, 0, 900, 0, len(DAILY_HEAD), CENTER, FC))
F.append(fmt(GOALS, 0, 900, 0, len(GOALS_HEAD), CENTER, FC))
F.append(fmt(MATRIX, 2, MX_TOT + 1, 0, MXN, BOLD, FB))
F.append(fmt(LOG, 0, 1, 0, len(DAILY_HEAD), BOLD, FB))
F.append(fmt(GOALS, 0, 1, 0, len(GOALS_HEAD), BOLD, FB))
F.append(fmt(GOALS, 1, 900, 0, 2, BOLD, FB))

batch(F)
print("formatting applied")
# Collapse EVERY week, the newest included — Carlos wants the tab to open with
# all dailies tucked away (2026-08-22); the week-total columns tell the story
# and any week opens with its + when needed. (This used to leave the newest
# week expanded, which read as the sheet "ungrouping itself" on every open.)
for _tsid in (TREND,):
    batch([{"updateDimensionGroup": {"dimensionGroup": {
        "range": {"sheetId": _tsid, "dimension": "COLUMNS",
                  "startIndex": TC0 + wi * WW + 1, "endIndex": TC0 + wi * WW + 8},
        "depth": 1, "collapsed": True}, "fields": "collapsed"}}
        for wi in range(len(WEEK_ENDS))])
print("done -> https://docs.google.com/spreadsheets/d/%s/edit" % SSID)
