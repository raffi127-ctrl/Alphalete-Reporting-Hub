
"""Steak on the Line — Texas de Brazil monthly competition.
Builds the flyer+standings PDF; with --send, posts to Slack
(#alphalete-sales + #alphalete-lvl1-chat) + iMessage as Lucy on Lucy 1.
Month auto-derived. Comment-light for the 50K cell limit; full src in repo."""

import os, re, sys, html, glob, shutil, subprocess, tempfile, unicodedata, datetime, importlib, json, calendar, argparse
from collections import defaultdict

def _ensure(pkg):
    """Import a package, pip-installing it on first run if missing (no terminal needed)."""
    try:
        return importlib.import_module(pkg)
    except ImportError:
        print(f"Installing {pkg} (one-time)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", pkg], check=True)
        return importlib.import_module(pkg)

_ensure("openpyxl")
_ensure("pypdf")
import openpyxl
from pypdf import PdfWriter

SALES_SHEET_ID   = "1MC9pfKryQrRtcMthUBL2hOciDCaa83U059pz0N2CmHc"
RECRUIT_SHEET_ID = "1Ez-mbROADd5aCWbLak6kQkNapb-BEk9W81n2ln6DVB4"
SALES_GLOB   = os.path.expanduser("~/Downloads/Alphalete SALES BOARD 2025*.xlsx")
RECRUIT_GLOB = os.path.expanduser("~/Downloads/All in One Local Office - Raf*.xlsx")
RECRUIT_TAB  = "2nd rds %s"
ESTIMATED_MINUTES = 2

_anchor    = datetime.date.today() - datetime.timedelta(days=1)
COMP_YEAR  = int(os.environ.get("TDB_COMP_YEAR")  or _anchor.year)
COMP_MONTH = int(os.environ.get("TDB_COMP_MONTH") or _anchor.month)
MONTH_NAME = datetime.date(COMP_YEAR, COMP_MONTH, 1).strftime("%B")
MONTH_UP   = MONTH_NAME.upper()
MONTH_LAST = calendar.monthrange(COMP_YEAR, COMP_MONTH)[1]
WIN        = 10

OUTPUT_PDF = os.path.expanduser(f"~/Downloads/Steak on the Line - {MONTH_NAME}.pdf")

MANUAL_INPUTS = os.path.expanduser("~/recruiting-report/output/texas_de_brazil_manual.json")

DINNER_DAY_DEFAULT  = "TO BE DETERMINED"
DINNER_TIME_DEFAULT = ""

LEADERS_STATE = os.path.expanduser("~/recruiting-report/output/texas_de_brazil_leaders_state.json")

EXCLUDE      = {"Rafael Hidalgo"}
ALIAS        = {"Andrew Sanborn Roadtrip": "Andrew Sanborn", "Randy Amoo": "Randy Amoa",
                "Sebastian Guerrero": "SABASTIN GUERRERO",

                "Drew": "Andrew Sanborn", "D": "Deavion Allen", "Zoey": "Zoria Johnson",
                "Al": "Algemar Kennel"}

PROMOTIONS_BY_MONTH = {
    "2026-07": [
        ("Willie Henderson", "Jessie Gomez"),
        ("Willie Henderson", "Jordan Ruiz"),
        ("Safiya Mahmoud", "Abel Mireles"),
    ],
}
SOLO_LEADERS_BY_MONTH = {
}
CAR_RIDE_LEADERS_BY_MONTH = {
    "2026-07": [
        "Jordan Ruiz",
        "Kaleb Muvunyi",
    ],
}

ADJUSTMENTS = {
    "Algemar Kennel": 15,
}

EXCLUDE_NEW_LEADERS = {"Giselle Loredo"}   # dropped everywhere even if a machine's state auto-detected it

POS_HERE = {"Here", "H+DC", "RT", "H+LM"}
LATE_PEN = {"Late"}
OFF_PEN  = {"Off", "STF", "O-NA"}
REMOVE   = {"T"}

HERE_PTS      = 3
SHOW_PTS      = 10
ENERGY_PTS    = 1
ENERGY5_BONUS = 10
CARRIDE_PTS   = 10

INT_OFF    = 6
DTV_OFF    = 4
NL_OFF     = 3
ENERGY_OFF = 2
DAY_OFF    = 7

def norm(name):
    n = re.sub(r"\([^)]*\)", " ", str(name))
    n = unicodedata.normalize("NFKD", n)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", n).strip()

def resolve_roster(name, rized):
    """Match a name/nickname to a full roster key: exact (after ALIAS), else a
    unique first-name prefix (last-initial narrowed). None if ambiguous."""
    if not name:
        return None
    n = norm(ALIAS.get(str(name).strip(), str(name).strip()))
    if not n:
        return None
    if n in rized:
        return n
    toks = n.lower().split()
    first = toks[0]
    cands = []
    for k in rized:
        kt = k.lower().split()
        if not kt:
            continue
        if kt[0].startswith(first) or first.startswith(kt[0]):
            cands.append(k)
    if len(toks) >= 2 and len(cands) > 1:
        nar = [k for k in cands if len(k.lower().split()) >= 2
               and k.lower().split()[1].startswith(toks[1])]
        if nar:
            cands = nar
    cands = list(dict.fromkeys(cands))
    return cands[0] if len(cands) == 1 else None

def numv(x):
    return float(x) if isinstance(x, (int, float)) else 0.0

def fv(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0

def newest(pattern):
    fs = glob.glob(pattern)
    return max(fs, key=os.path.getmtime) if fs else None

def find_chrome():
    """Locate Chrome/Chromium on macOS, Windows, or Linux."""
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    cands = []
    if sys.platform == "darwin":
        cands += [os.path.join(os.sep, "Applications", "Google Chrome.app", "Contents", "MacOS", "Google Chrome"),
                  os.path.join(os.sep, "Applications", "Chromium.app", "Contents", "MacOS", "Chromium")]
    elif sys.platform.startswith("win"):
        for base in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")):
            if base:
                cands.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    else:
        cands += ["/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium",
                  "/snap/bin/chromium"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    sys.exit("ERROR: Google Chrome not found. Install Chrome, then re-run.")

def sales_week_tabs(wb):
    tabs = [n for n in wb.sheetnames if re.match(r"Sales Board WE \d", n)]
    def k(n):
        m = re.search(r"WE\s+(\d{1,2})\.(\d{1,2})", n)
        return (int(m.group(1)), int(m.group(2))) if m else (99, 99)
    return sorted(tabs, key=k)

def tab_week_dates(tabname):
    """The 7 calendar dates (chronological) for the week ENDING on the WE date."""
    m = re.search(r"WE\s+(\d{1,2})\.(\d{1,2})", tabname)
    if not m:
        raise ValueError("no WE date in tab name")
    mo, dy = int(m.group(1)), int(m.group(2))
    end = datetime.date(COMP_YEAR, mo, dy)
    return [end - datetime.timedelta(days=6 - i) for i in range(7)]

def read_sales(sales_file):
    wb = openpyxl.load_workbook(sales_file, read_only=True, data_only=True)
    sales = defaultdict(lambda: {"int": 0.0, "dtv": 0.0, "nl": 0.0, "energy": 0.0,
                                 "here": 0, "late": 0, "off": 0, "int3": 0, "energy5": 0})
    removed = {}
    through = None
    today = datetime.date.today()
    for tab in sales_week_tabs(wb):
        try:
            dates = tab_week_dates(tab)
        except ValueError:
            continue
        if not any(d.month == COMP_MONTH and d.year == COMP_YEAR for d in dates):
            continue
        ws = wb[tab]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        try:
            shr = next(i for i, r in enumerate(rows)
                       if any(isinstance(c, str) and c.strip() == "Roll Call" for c in r))
        except StopIteration:
            continue
        rc_cols = [j for j, c in enumerate(rows[shr]) if isinstance(c, str) and c.strip() == "Roll Call"]
        daterow = rows[shr - 1]
        label2date = {d.day: d for d in dates}

        rc_date = {}
        for i, rc in enumerate(rc_cols):
            lbl = daterow[rc - DAY_OFF] if rc - DAY_OFF >= 0 else None
            dt = None
            if lbl is not None:
                try:
                    dt = label2date.get(int(lbl))
                except (TypeError, ValueError):
                    dt = None
            if dt is None and i < len(dates):
                dt = dates[i]
            rc_date[rc] = dt
        for r in rows[shr + 1:]:
            raw = r[2] if len(r) > 2 else None
            if not (isinstance(raw, str) and raw.strip()):
                break
            name = norm(raw); rec = sales[name]
            for rc in rc_cols:
                dt = rc_date.get(rc)
                if dt is None or dt.month != COMP_MONTH or dt.year != COMP_YEAR:
                    continue
                if dt >= today:
                    continue
                is_sun = dt.weekday() == 6
                dayint = numv(r[rc - INT_OFF]); dayeng = numv(r[rc - ENERGY_OFF])
                rec["int"] += dayint; rec["dtv"] += numv(r[rc - DTV_OFF]); rec["nl"] += numv(r[rc - NL_OFF])
                rec["energy"] += dayeng
                if dayint >= 3:
                    rec["int3"] += 1
                if dayeng >= 3:
                    rec["energy5"] += 1
                got = dayint > 0 or dayeng > 0
                v = r[rc]
                if isinstance(v, str) and v.strip():
                    got = True
                    v = v.strip()
                    if v in REMOVE: removed[name] = v
                    elif v in POS_HERE: rec["here"] += 1
                    elif v in LATE_PEN:
                        if not is_sun: rec["late"] += 1
                    elif v in OFF_PEN:
                        if not is_sun: rec["off"] += 1
                if got and (through is None or dt > through):
                    through = dt
    wb.close()
    return sales, removed, through

def read_recruiting(recruit_file):
    wb = openpyxl.load_workbook(recruit_file, read_only=True, data_only=True)
    ws = wb[RECRUIT_TAB]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    june = {}
    for r in rows[2:]:
        nm = r[0] if len(r) > 0 else None
        if not (isinstance(nm, str) and nm.strip()):
            break
        june[nm.strip()] = (fv(r[3] if len(r) > 3 else 0),
                            fv(r[6] if len(r) > 6 else 0))
    wb.close()
    return june

def read_leadership(sales_file):
    """From the latest weekly tab, read each rep's Leadership Status (CJ),
    Trainer (CD) and Best Car Ride Leader (CK). Columns are located by HEADER
    TEXT (not fixed letters) so it survives layout shifts. Returns
    {norm_name: {"status": str, "trainer": raw str, "best": bool}}."""
    wb = openpyxl.load_workbook(sales_file, read_only=True, data_only=True)
    out = {}
    for tab in reversed(sales_week_tabs(wb)):
        ws = wb[tab]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        try:
            shr = next(i for i, r in enumerate(rows)
                       if any(isinstance(c, str) and c.strip() == "Roll Call" for c in r))
        except StopIteration:
            continue

        def find_col(label):
            for r in rows[:shr + 1]:
                for j, c in enumerate(r):
                    if isinstance(c, str) and c.strip().lower() == label:
                        return j
            return None
        c_status = find_col("leadership status")
        c_train = find_col("trainer")
        c_best = find_col("best car ride leader")
        if c_status is None:
            continue
        for r in rows[shr + 1:]:
            raw = r[2] if len(r) > 2 else None
            if not (isinstance(raw, str) and raw.strip()):
                break
            name = norm(raw)
            status = r[c_status] if c_status < len(r) else None
            trainer = r[c_train] if (c_train is not None and c_train < len(r)) else None
            best = r[c_best] if (c_best is not None and c_best < len(r)) else None
            out[name] = {
                "status": status.strip() if isinstance(status, str) else "",
                "trainer": trainer.strip() if isinstance(trainer, str) else "",
                "best": isinstance(best, str) and best.strip().upper() == "BEST",
            }
        break
    wb.close()
    return out

def update_leaders_state(leadership):
    """Baseline each rep's Leadership Status; accumulate NEW LEADERS (moved UP to
    'Level 1' after first sighting; Trainer gets Break-a-Leader too) + CAR-RIDE
    ('BEST'). First sighting only seeds baseline. Returns (promotions, car)."""
    try:
        state = json.loads(open(LEADERS_STATE).read())
    except Exception:
        state = {}

    if (state.get("period") or _current_period()) != _current_period():
        state = {}
    baseline = state.get("baseline") or {}
    promos = state.get("new_leaders") or []
    cars = state.get("car_ride") or []
    first_run = not baseline
    detected = {p[1] for p in promos}
    car_set = set(cars)
    for nm, d in leadership.items():
        if nm not in baseline:
            baseline[nm] = d["status"]
        elif d["status"] == "Level 1" and baseline[nm] != "Level 1" and nm not in detected:
            promos.append([d["trainer"], nm]); detected.add(nm)
        if d.get("best") and nm not in car_set:
            cars.append(nm); car_set.add(nm)
    try:
        os.makedirs(os.path.dirname(LEADERS_STATE), exist_ok=True)
        with open(LEADERS_STATE, "w") as fh:
            json.dump({"period": _current_period(), "baseline": baseline,
                       "new_leaders": promos, "car_ride": cars}, fh, indent=2)
    except Exception as e:
        print(f"(couldn't save leaders state: {e})")
    if first_run:
        print(f"Leaders baseline set for {len(baseline)} reps (no detections on first run)")
    return promos, cars

def load_leaders_state():
    """Read-only view of the accumulated auto-detected leaders for display
    (the flyer). Returns (promotions, car_names)."""
    try:
        state = json.loads(open(LEADERS_STATE).read())
    except Exception:
        return [], []
    if (state.get("period") or _current_period()) != _current_period():
        return [], []
    return state.get("new_leaders") or [], state.get("car_ride") or []

def load_manual_inputs():
    """Read the Hub-typed weekly additions (accumulating for the month) and
    return (promotions, solo_leaders, car_ride). Each 'new leaders' line is
    'Promoter > New Leader' (a promotion pair) or just 'New Leader' (solo).
    Any parse trouble or missing file -> empty lists (never crashes the run)."""
    prom, solo, car = [], [], []
    try:
        data = json.loads(open(MANUAL_INPUTS).read())
    except Exception:
        return prom, solo, car
    for line in str(data.get("new_leaders_text", "") or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if ">" in line:
            a, b = line.split(">", 1)
            a, b = a.strip(), b.strip()
            if a and b:
                prom.append((a, b))
            elif b:
                solo.append(b)
        else:
            solo.append(line)
    for line in str(data.get("car_ride_text", "") or "").splitlines():
        line = line.strip()
        if line:
            car.append(line)
    return prom, solo, car

def load_dinner():
    """Look up THIS competition month's dinner date from the Hub-typed schedule
    (manual inputs -> dinner_schedule["YYYY-MM"] = {"day":..,"time":..}). Falls back
    to the legacy single dinner_day/dinner_time, then to DINNER_*_DEFAULT
    ("TO BE DETERMINED"). Maud sets dates 2 months ahead on the card, so the flyer
    should always have the real date."""
    day, time = DINNER_DAY_DEFAULT, DINNER_TIME_DEFAULT
    try:
        data = json.loads(open(MANUAL_INPUTS).read())
    except Exception:
        return day, time
    entry = (data.get("dinner_schedule") or {}).get(_current_period()) or {}
    d = str(entry.get("day", "") or "").strip() or str(data.get("dinner_day", "") or "").strip()
    t = str(entry.get("time", "") or "").strip() or str(data.get("dinner_time", "") or "").strip()
    return (d or day), (t or time)

def _current_period():
    """The competition period key ('YYYY-MM') used to auto-reset month state."""
    return f"{COMP_YEAR}-{COMP_MONTH:02d}"

def build_board(sales_file, recruit_file):
    sales, removed, through = read_sales(sales_file)
    recruit = read_recruiting(recruit_file)
    m_prom, m_solo, m_car = load_manual_inputs()
    a_prom, a_car = update_leaders_state(read_leadership(sales_file))
    _mp = _current_period()
    _excl = {norm(x) for x in EXCLUDE_NEW_LEADERS}
    promotions   = [(p, q) for (p, q) in dict.fromkeys(PROMOTIONS_BY_MONTH.get(_mp, []) + m_prom + [tuple(p) for p in a_prom]) if norm(q) not in _excl]
    solo_leaders = [q for q in dict.fromkeys(SOLO_LEADERS_BY_MONTH.get(_mp, []) + m_solo) if norm(q) not in _excl]
    car_leaders  = list(dict.fromkeys(CAR_RIDE_LEADERS_BY_MONTH.get(_mp, []) + m_car + a_car))
    if a_prom or a_car:
        print(f"Auto-detected: {len(a_prom)} new leaders, {len(a_car)} car-ride")
    if m_prom or m_solo or m_car:
        print(f"Manual overrides: {len(m_prom)} promotions, {len(m_solo)} solo, {len(m_car)} car-ride")

    rized = {}
    for name, s in sales.items():
        if name in EXCLUDE or name in removed:
            continue
        rized[name] = {
            "name": name, "int_p": s["int"] * 2, "dtv_p": s["dtv"], "nl_p": s["nl"],
            "eng_p": s["energy"] * ENERGY_PTS,
            "att_p": s["here"] * HERE_PTS - s["late"] * 5 - s["off"] * 10,
            "i3_p": s["int3"] * 10, "e5_p": s["energy5"] * ENERGY5_BONUS,
            "acc": 0.0, "show": 0.0, "acc_p": 0.0, "show_p": 0.0, "brk_p": 0.0, "car_p": 0.0,
            "adj_p": 0.0,
        }
    for rn, (acc, show) in recruit.items():
        key = norm(ALIAS.get(rn, rn))
        if key in EXCLUDE or key not in rized:
            continue
        rized[key]["acc"] += acc; rized[key]["show"] += show
        rized[key]["acc_p"] += acc * 5; rized[key]["show_p"] += show * SHOW_PTS
    unmatched = []
    for promoter, newleader in promotions:
        for nm in (promoter, newleader):
            key = resolve_roster(nm, rized)
            if key:
                rized[key]["brk_p"] += 15
            elif str(nm).strip():
                unmatched.append(nm)
    for nm in solo_leaders:
        key = resolve_roster(nm, rized)
        if key:
            rized[key]["brk_p"] += 15
    for nm in car_leaders:
        key = resolve_roster(nm, rized)
        if key:
            rized[key]["car_p"] += CARRIDE_PTS
        elif str(nm).strip():
            unmatched.append(nm)
    if unmatched:
        print("Unmatched names (no points; check spelling / give me the nickname): "
              + ", ".join(sorted(set(str(u).strip() for u in unmatched))))
    for nm, pts in ADJUSTMENTS.items():
        key = resolve_roster(nm, rized)
        if key:
            rized[key]["adj_p"] += pts

    board = list(rized.values())
    for r in board:
        r["total"] = (r["int_p"] + r["dtv_p"] + r["nl_p"] + r["att_p"] + r["eng_p"]
                      + r["acc_p"] + r["show_p"] + r["brk_p"] + r["i3_p"]
                      + r["e5_p"] + r["car_p"] + r["adj_p"])
    board.sort(key=lambda x: (-x["total"], -x["acc"], x["name"]))
    return board, through

def esc(s): return html.escape(str(s))

BOARD_CSS = """
  @page { size: 12.5in 26in; margin: 0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .poster{ width:1200px; height:2496px; position:relative; overflow:hidden;
    background: radial-gradient(circle at 50% 8%, rgba(212,175,55,.18), transparent 34%),
      linear-gradient(180deg,#120606 0%, #1c0808 26%, #0c0404 100%);
    font-family: Georgia,'Times New Roman',serif; color:#f6efe1; padding-bottom:60px;}
  .ember{ position:absolute; left:0; right:0; top:0; height:200px;
    background:linear-gradient(180deg, rgba(177,18,18,.85), rgba(120,10,10,0)); filter:blur(2px);}
  .kicker{ text-align:center; letter-spacing:13px; font-family:Arial,Helvetica,sans-serif;
    font-weight:700; font-size:24px; color:#e7c878; padding-top:40px; text-transform:uppercase;}
  h1{ text-align:center; font-family:'Arial Black',Impact,sans-serif; font-weight:900;
    font-size:96px; line-height:.92; letter-spacing:2px; margin-top:8px; color:#fff;
    text-shadow:0 4px 0 #7d0d0d,0 10px 26px rgba(0,0,0,.6);}
  h1 .gold{ color:#f0c75e; display:block; font-size:56px;
    text-shadow:0 3px 0 #6a4e0e,0 8px 22px rgba(0,0,0,.5);}
  .month{ text-align:center; font-family:Arial,sans-serif; font-weight:700; letter-spacing:5px;
    font-size:26px; color:#d9b86a; margin-top:14px;}
  .tag{ text-align:center; font-size:22px; color:#caa14a; font-style:italic; margin-top:6px;}
  .gold-rule{ height:5px; width:780px; margin:22px auto;
    background:linear-gradient(90deg,transparent,#d4af37 18%,#f3d98a 50%,#d4af37 82%,transparent); border-radius:3px;}
  .podium{ display:flex; gap:22px; align-items:flex-end; margin:6px 70px 0;}
  .pcard{ flex:1; text-align:center; border-radius:18px; padding:26px 16px 22px;
    background:linear-gradient(180deg,#23100f,#180a0a); border:3px solid #d4af37; box-shadow:0 14px 34px rgba(0,0,0,.5);}
  .pcard.p1{ border-color:#f0c75e; transform:translateY(-22px); padding-top:34px;
    box-shadow:0 0 0 6px rgba(240,199,94,.12),0 18px 40px rgba(0,0,0,.6);}
  .medal{ width:74px; height:74px; border-radius:50%; margin:0 auto 12px; color:#1a0808;
    font-family:'Arial Black',sans-serif; font-size:24px; line-height:74px; box-shadow:0 6px 14px rgba(0,0,0,.45);}
  .pcard.p1 .medal{ width:90px; height:90px; line-height:90px; font-size:28px;}
  .pname{ font-family:'Arial Black',sans-serif; font-size:28px; color:#fff; line-height:1.05;}
  .pcard.p1 .pname{ font-size:34px; color:#f0c75e;}
  .ptot{ font-family:'Arial Black',sans-serif; font-size:54px; color:#f0c75e; margin-top:8px;}
  .pcard.p1 .ptot{ font-size:70px;}
  .ptot span{ font-size:20px; color:#caa14a; margin-left:6px;}
  .pbreak{ font-family:Arial,sans-serif; font-size:14px; color:#d9c89a; margin-top:10px; line-height:1.4;}
  .crown{ text-align:center; font-family:Arial,sans-serif; font-weight:700; letter-spacing:3px;
    font-size:22px; color:#f0c75e; margin:30px 70px 0; text-transform:uppercase;}
  .cols{ display:flex; gap:30px; margin:18px 60px 0;}
  .cols > div{ flex:1;}
  table.board{ width:100%; border-collapse:collapse; font-family:Arial,sans-serif;}
  table.board th{ font-size:13px; letter-spacing:1px; color:#caa14a; text-transform:uppercase;
    padding:8px 3px; border-bottom:2px solid rgba(212,175,55,.5); text-align:right;}
  table.board th:nth-child(2){ text-align:left;}
  table.board td{ font-size:16px; padding:9px 3px; text-align:right;
    border-bottom:1px solid rgba(212,175,55,.16); color:#e7dcc4;}
  td.rk{ color:#caa14a; font-family:'Arial Black',sans-serif; width:28px;}
  td.nm{ text-align:left; color:#fff; font-weight:700; font-size:17px;}
  td.att{ color:#cc9999; }
  td.bkr{ color:#7BE08A; font-family:'Arial Black',sans-serif; }
  td.tot{ font-family:'Arial Black',sans-serif; color:#f0c75e; font-size:19px;}
  tr.win td.nm{ color:#f0c75e;} tr.win td.rk{ color:#f0c75e;} tr.win td{ background:rgba(240,199,94,.07);}
  tr.cut td{ text-align:center; font-family:'Arial Black',sans-serif; letter-spacing:3px;
    font-size:17px; color:#1a0808; text-transform:uppercase; padding:10px 4px;
    background:linear-gradient(90deg,#d4af37,#f3d98a 50%,#d4af37); border:none;}
  .legend{ margin:40px 60px 0; background:linear-gradient(180deg,#1f0a0a,#160707);
    border:3px solid #d4af37; border-radius:16px; padding:22px 30px;}
  .legend h3{ text-align:center; font-family:'Arial Black',sans-serif; font-size:26px;
    color:#f0c75e; letter-spacing:3px; text-transform:uppercase; margin-bottom:14px;}
  .lgrid{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px 40px;}
  .lgrid div{ display:flex; justify-content:space-between; font-family:Arial,sans-serif;
    font-size:18px; padding:6px 2px; border-bottom:1px dashed rgba(212,175,55,.3);}
  .lgrid .p{ font-family:'Arial Black',sans-serif; color:#7BE08A;}
  .lgrid .n{ font-family:'Arial Black',sans-serif; color:#ff6b6b;}
  .foot{ text-align:center; font-family:Arial,sans-serif; letter-spacing:5px; font-size:20px;
    color:#c9a14a; text-transform:uppercase; margin:40px 60px 0;}
  .note{ text-align:center; font-family:Arial,sans-serif; font-size:14px; color:#8a7a52;
    margin:14px 60px 0; font-style:italic;}
"""

LEGEND = ('<div class="legend"><h3>How Points Are Scored</h3><div class="lgrid">'
    '<div><span>New Internet</span><span class="p">+2</span></div>'
    '<div><span>Closing a 2nd Round</span><span class="p">+5</span></div>'
    '<div><span>New Start Showed</span><span class="p">+10</span></div>'
    '<div><span>DTV</span><span class="p">+1</span></div>'
    '<div><span>New Line</span><span class="p">+1</span></div>'
    '<div><span>Here / On Time / Dress Code</span><span class="p">+3</span></div>'
    '<div><span>Energy</span><span class="p">+1</span></div>'
    '<div><span>Break a Leader</span><span class="p">+15</span></div>'
    '<div><span>3 Internet in 1 Day</span><span class="p">+10</span></div>'
    '<div><span>5 Energy in 1 Day</span><span class="p">+10</span></div>'
    '<div><span>Best Car Ride Leader</span><span class="p">+10</span></div>'
    '<div><span>Late</span><span class="n">&minus;5</span></div>'
    '<div><span>Off / STF / No-Answer</span><span class="n">&minus;10</span></div>'
    '</div></div>')
NOTE = ('<div class="note">Sales &amp; attendance month-to-date (no Sunday off-day penalty) &bull; '
    f'recruiting {MONTH_NAME} MTD &bull; ties broken by most 2nd-round closes.<br>'
    'Columns: 2RD=2nd-round closes &bull; NEW=new starts showed &bull; INT=Internet pts &bull; DTV &bull; '
    'NL=New Line &bull; ENG=Energy &bull; ATT=attendance net &bull; BRK=Break-a-Leader &bull; '
    '3IN=3-internet-day &bull; E3=3-energy-day &bull; CAR=Best Car Ride Leader.</div>')

def medal_card(rank, r):
    colors = {1: ("#f0c75e", "#9a7611", "1st"), 2: ("#d9d9e0", "#7d7d86", "2nd"), 3: ("#e0a36b", "#8a5a2b", "3rd")}
    c1, c2, place = colors[rank]
    return (f'<div class="pcard p{rank}"><div class="medal" style="background:linear-gradient(180deg,{c1},{c2});">{place}</div>'
            f'<div class="pname">{esc(r["name"])}</div><div class="ptot">{r["total"]:.0f}<span>pts</span></div>'
            f'<div class="pbreak">2RD {r["acc_p"]:.0f} &bull; NEW {r["show_p"]:.0f} &bull; INT {r["int_p"]:.0f} '
            f'&bull; NL {r["nl_p"]:.0f} &bull; ENG {r["eng_p"]:.0f} &bull; ATT {r["att_p"]:+.0f}'
            + (f' &bull; BRK {r["brk_p"]:.0f}' if r.get("brk_p") else "")
            + (f' &bull; CAR {r["car_p"]:.0f}' if r.get("car_p") else "") + "</div></div>")

def trow(rank, r):
    cls = "win" if rank <= WIN else ""
    brk = f'{r["brk_p"]:.0f}' if r.get("brk_p") else "&middot;"
    i3 = f'{r["i3_p"]:.0f}' if r.get("i3_p") else "&middot;"
    e5 = f'{r["e5_p"]:.0f}' if r.get("e5_p") else "&middot;"
    car = f'{r["car_p"]:.0f}' if r.get("car_p") else "&middot;"
    return (f'<tr class="{cls}"><td class="rk">{rank}</td><td class="nm">{esc(r["name"])}</td>'
            f'<td>{r["acc_p"]:.0f}</td><td>{r["show_p"]:.0f}</td><td>{r["int_p"]:.0f}</td>'
            f'<td>{r["dtv_p"]:.0f}</td><td>{r["nl_p"]:.0f}</td><td>{r["eng_p"]:.0f}</td>'
            f'<td class="att">{r["att_p"]:+.0f}</td>'
            f'<td class="bkr">{brk}</td><td class="bkr">{i3}</td><td class="bkr">{e5}</td>'
            f'<td class="bkr">{car}</td><td class="tot">{r["total"]:.0f}</td></tr>')

def detailed_table(rows, start):
    body = []
    for i, r in enumerate(rows):
        rank = start + i
        body.append(trow(rank, r))
        if rank == WIN:
            body.append('<tr class="cut"><td colspan="14">&#9733; Top 10 &mdash; these eat steak &#9733;</td></tr>')
    return ('<table class="board"><thead><tr><th>#</th><th>Rep</th><th>2RD</th><th>NEW</th>'
            '<th>INT</th><th>DTV</th><th>NL</th><th>ENG</th><th>ATT</th><th>BRK</th><th>3IN</th>'
            '<th>E3</th><th>CAR</th><th>TOT</th>'
            '</tr></thead><tbody>' + "\n".join(body) + "</tbody></table>")

def board_html(board, through):
    half = (len(board) + 1) // 2
    colA, colB = board[:half], board[half:]
    prows = "\n".join(medal_card(i, r) for i, r in enumerate(board[:3], 1))
    dinner_day, dinner_time = load_dinner()
    if through:
        thru = "THROUGH " + through.strftime("%a %b ").upper() + str(through.day)
    else:
        thru = f"{MONTH_UP} &mdash; MONTH TO DATE"
    head = ('<div class="ember"></div><div class="kicker">Alphalete Sales &mdash; Steak on the Line</div>'
            f'<h1>{MONTH_UP} STANDINGS<span class="gold">Texas de Brazil</span></h1>'
            f'<div class="month">{thru} &bull; WINDOW {MONTH_UP} 1&ndash;{MONTH_LAST}</div>'
            '<div class="tag">Top 10 on the board eat on us at the #1 Brazilian steakhouse in Texas</div>'
            '<div class="gold-rule"></div>')
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><style>{BOARD_CSS}</style></head><body>'
            f'<div class="poster">{head}<div class="podium">{prows}</div>'
            f'<div class="crown">&#9733; Top 10 earn their seat at the table &#9733;</div>'
            f'<div class="cols"><div>{detailed_table(colA,1)}</div><div>{detailed_table(colB,half+1)}</div></div>'
            f'<div class="foot">Most points wins &bull; Ranked daily &bull; {esc(dinner_day)}{(" &bull; " + esc(dinner_time)) if str(dinner_time).strip() else ""}</div>'
            f'{NOTE}</div></body></html>')

FLYER_TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><style>
  @page { size: 12.5in 16.667in; margin: 0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html,body{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }
  .poster{ width:1200px; height:1600px; position:relative; overflow:hidden;
    background: radial-gradient(circle at 50% 14%, rgba(212,175,55,.18), transparent 38%),
      linear-gradient(180deg,#120606 0%, #1c0808 30%, #0c0404 100%);
    font-family: Georgia,'Times New Roman',serif; color:#f6efe1; }
  .ember{ position:absolute; left:0; right:0; top:0; height:230px;
    background:linear-gradient(180deg, rgba(177,18,18,.85), rgba(120,10,10,.0)); filter:blur(2px);}
  .flame{ position:absolute; top:36px; left:50%; transform:translateX(-50%); }
  .gold-rule{ height:5px; width:760px; margin:18px auto;
    background:linear-gradient(90deg,transparent,#d4af37 18%,#f3d98a 50%,#d4af37 82%,transparent); border-radius:3px;}
  .kicker{ text-align:center; letter-spacing:14px; font-family:Arial,Helvetica,sans-serif;
    font-weight:700; font-size:25px; color:#e7c878; margin-top:14px; text-transform:uppercase;}
  h1{ text-align:center; font-family:'Arial Black',Impact,sans-serif; font-weight:900;
    font-size:98px; line-height:.92; letter-spacing:2px; margin-top:4px;
    color:#fff; text-shadow:0 4px 0 #7d0d0d, 0 10px 26px rgba(0,0,0,.6);}
  h1 .gold{ color:#f0c75e; display:block; font-size:78px; text-shadow:0 3px 0 #6a4e0e, 0 8px 22px rgba(0,0,0,.5);}
  .sub{ text-align:center; font-size:31px; color:#f1e6cf; margin:22px 44px 0; font-style:italic;}
  .sub b{ color:#f0c75e; font-style:normal;}
  .window{ text-align:center; margin-top:16px; font-family:Arial,sans-serif; font-weight:700;
    letter-spacing:3px; font-size:24px; color:#d9b86a;}
  .panel{ margin:28px 64px 0; background:linear-gradient(180deg,#1f0a0a,#160707);
    border:3px solid #d4af37; border-radius:18px; padding:28px 38px 30px;
    box-shadow:0 0 0 6px rgba(212,175,55,.08), 0 18px 40px rgba(0,0,0,.5);}
  .panel h2{ text-align:center; font-family:'Arial Black',Impact,sans-serif; font-size:36px;
    letter-spacing:4px; color:#f0c75e; text-transform:uppercase; margin-bottom:16px;}
  .grid{ display:grid; grid-template-columns:1fr 1fr; gap:9px 42px;}
  .row{ display:flex; justify-content:space-between; align-items:center;
    border-bottom:1px dashed rgba(212,175,55,.35); padding:11px 4px; font-size:29px;}
  .row .lbl{ color:#f6efe1;}
  .row .pts{ font-family:'Arial Black',sans-serif; font-size:29px; min-width:110px; text-align:right;}
  .pos{ color:#7BE08A;} .neg{ color:#ff6b6b;}
  .bonus{ margin-top:22px; display:flex; flex-wrap:wrap; gap:18px; justify-content:center;}
  .bcard{ flex:1 1 28%; min-width:262px; text-align:center; background:linear-gradient(180deg,#2a0e0e,#1a0808);
    border:2px solid #b11212; border-radius:14px; padding:15px 12px;}
  .bcard .big{ font-family:'Arial Black',sans-serif; font-size:44px; color:#f0c75e;}
  .bcard .cap{ font-size:19px; color:#f1e6cf; margin-top:4px; line-height:1.2;}
  .details{ margin:26px 64px 0; display:flex; gap:24px; align-items:stretch;}
  .when{ flex:1; background:linear-gradient(180deg,#d4af37,#b8902a); color:#1a0808;
    border-radius:18px; padding:22px 24px; text-align:center; box-shadow:0 14px 30px rgba(0,0,0,.45);}
  .when .day{ font-family:'Arial Black',sans-serif; font-size:44px; letter-spacing:1px;}
  .when .time{ font-family:'Arial Black',sans-serif; font-size:54px; margin-top:2px;}
  .when .at{ font-size:22px; font-style:italic; margin-top:6px;}
  .where{ flex:1.2; background:#160707; border:3px solid #d4af37; border-radius:18px;
    padding:22px 24px; text-align:center; display:flex; flex-direction:column; justify-content:center;}
  .where .name{ font-family:'Arial Black',sans-serif; font-size:38px; color:#f0c75e; letter-spacing:1px;}
  .where .addr{ font-size:26px; color:#f6efe1; margin-top:9px; line-height:1.35;}
  .foot2{ margin:30px 40px 26px; text-align:center; white-space:nowrap;
    font-family:Arial,sans-serif; letter-spacing:3px; font-size:21px; color:#c9a14a; text-transform:uppercase;}
  .poster + .poster{ page-break-before:always; }
  .promo-sub{ text-align:center; font-size:29px; color:#f1e6cf; margin:22px 70px 0; font-style:italic;}
  .promo-sub b{ color:#f0c75e; font-style:normal;}
  .plist{ margin:30px 56px 0; display:grid; grid-template-columns:1fr 1fr; gap:13px 24px;}
  .prow{ display:flex; align-items:center; justify-content:space-between;
    background:linear-gradient(180deg,#1f0a0a,#160707); border:2px solid #d4af37; border-radius:12px;
    padding:13px 16px; box-shadow:0 8px 18px rgba(0,0,0,.4);}
  .prow .who{ display:flex; align-items:center; gap:9px; font-size:20px; min-width:0;}
  .prow .pp{ font-family:'Arial Black',sans-serif; color:#fff; white-space:nowrap;}
  .prow .arrow{ color:#f0c75e; font-size:20px;}
  .prow .nl{ font-family:'Arial Black',sans-serif; color:#f0c75e; white-space:nowrap;}
  .prow .pts{ font-family:'Arial Black',sans-serif; color:#7BE08A; font-size:16px; white-space:nowrap; margin-left:10px;}
  .promo-note{ position:absolute; bottom:30px; left:0; right:0; text-align:center;
    font-family:Arial,sans-serif; letter-spacing:4px; font-size:19px; color:#c9a14a; text-transform:uppercase;}
</style></head><body>
<div class="poster">
  <div class="ember"></div>
  <svg class="flame" width="120" height="150" viewBox="0 0 120 150">
    <path d="M60 6 C40 44 16 56 30 96 C38 122 52 132 60 144 C68 132 82 122 90 96 C104 56 80 44 60 6 Z" fill="url(#g1)"/>
    <path d="M60 52 C50 72 40 80 48 104 C53 120 60 128 60 138 C60 128 67 120 72 104 C80 80 70 72 60 52 Z" fill="#f0c75e"/>
    <defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffd35a"/><stop offset="1" stop-color="#b11212"/></linearGradient></defs>
  </svg>
  <div class="kicker">Alphalete Sales Presents</div>
  <h1>STEAK ON<br>THE LINE<span class="gold">TEXAS DE BRAZIL</span></h1>
  <div class="gold-rule"></div>
  <div class="sub">Outsell the floor in <b>__MONTHNAME__</b> &mdash; the <b>Top 10</b> on the board eat on us at the <b>#1 Brazilian steakhouse in Texas.</b></div>
  <div class="window">COMPETITION WINDOW &nbsp;&bull;&nbsp; __WINDOW__</div>
  <div class="panel">
    <h2>How You Score</h2>
    <div class="grid">
      <div class="row"><span class="lbl">New Internet</span><span class="pts pos">+2</span></div>
      <div class="row"><span class="lbl">Closing a 2nd Round</span><span class="pts pos">+5</span></div>
      <div class="row"><span class="lbl">DTV</span><span class="pts pos">+1</span></div>
      <div class="row"><span class="lbl">New Start Showed</span><span class="pts pos">+10</span></div>
      <div class="row"><span class="lbl">New Line</span><span class="pts pos">+1</span></div>
      <div class="row"><span class="lbl">Here / On Time / Dress Code</span><span class="pts pos">+3</span></div>
      <div class="row"><span class="lbl">Energy</span><span class="pts pos">+1</span></div>
      <div class="row"><span class="lbl">Late</span><span class="pts neg">&minus;5</span></div>
    </div>
    <div class="bonus">
      <div class="bcard"><div class="big">+15</div><div class="cap"><b>BREAK A LEADER</b><br>15 pts to you <i>&amp;</i> 15 to the new leader</div></div>
      <div class="bcard"><div class="big">+10</div><div class="cap"><b>3 INTERNET IN A DAY</b><br>hit 3 in one day &mdash; instant bonus</div></div>
      <div class="bcard"><div class="big">+10</div><div class="cap"><b>3 ENERGY IN A DAY</b><br>hit 3 in one day &mdash; instant bonus</div></div>
      <div class="bcard"><div class="big">+10</div><div class="cap"><b>BEST CAR RIDE LEADER</b><br>top car-ride leader earns the bonus</div></div>
      <div class="bcard"><div class="big">&minus;10</div><div class="cap"><b>OFF / STF / NO-ANSWER</b><br>points come off the board</div></div>
    </div>
  </div>
  <div class="details">
    <div class="when"><div class="day">__DINNER_DAY__</div><div class="time">__DINNER_TIME__</div><div class="at">Dinner is served</div></div>
    <div class="where"><div class="name">TEXAS DE BRAZIL</div><div class="addr">15101 Addison Rd<br>Addison, TX 75001</div></div>
  </div>
  <div class="foot2">Most points wins &bull; Ranked daily &bull; Earn your seat at the table</div>
</div>
<div class="poster">
  <div class="ember"></div>
  <div class="kicker">Alphalete Sales Presents</div>
  <h1 style="font-size:72px; margin-top:20px;">LEADERSHIP<span class="gold" style="font-size:50px;">PROMOTIONS &middot; __MONTH_UP__</span></h1>
  <div class="gold-rule"></div>
  <div class="promo-sub">Break a leader, you both eat. <b>+15 to the leader who promoted &amp; +15 to the new leader.</b></div>
  <div class="plist">
__PROMO_ROWS__
  </div>
  <div class="gold-rule" style="margin-top:40px;"></div>
  <h1 style="font-size:72px; margin-top:16px;">BEST CAR RIDE<span class="gold" style="font-size:50px;">LEADER &middot; __MONTH_UP__</span></h1>
  <div class="promo-sub">Top car-ride leader of the week &mdash; <b>+10 points.</b></div>
  <div class="plist">
__CARRIDE_ROWS__
  </div>
  <div class="promo-note">Confirmed manually &bull; updated weekly</div>
</div>
</body></html>"""

def flyer_html():
    m_prom, m_solo, m_car = load_manual_inputs()
    a_prom, a_car = load_leaders_state()
    _mp = _current_period()
    _excl = {norm(x) for x in EXCLUDE_NEW_LEADERS}
    promotions = [(p, q) for (p, q) in dict.fromkeys(PROMOTIONS_BY_MONTH.get(_mp, []) + m_prom + [tuple(p) for p in a_prom]) if norm(q) not in _excl]
    solos = [q for q in dict.fromkeys(SOLO_LEADERS_BY_MONTH.get(_mp, []) + m_solo) if norm(q) not in _excl]
    cars = list(dict.fromkeys(CAR_RIDE_LEADERS_BY_MONTH.get(_mp, []) + m_car + a_car))
    prom_rows = [
        f'    <div class="prow"><div class="who"><span class="pp">{esc(p)}</span>'
        f'<span class="arrow">&rarr;</span><span class="nl">{esc(q)}</span></div>'
        f'<span class="pts">+15&nbsp;/&nbsp;+15</span></div>'
        for p, q in promotions]
    prom_rows += [
        f'    <div class="prow"><div class="who"><span class="nl">{esc(nm)}</span></div>'
        f'<span class="pts">+15</span></div>'
        for nm in solos]
    car_rows = [
        f'    <div class="prow"><div class="who"><span class="nl">{esc(nm)}</span></div>'
        f'<span class="pts">+10</span></div>'
        for nm in cars]
    dinner_day, dinner_time = load_dinner()
    html_out = FLYER_TEMPLATE.replace("__PROMO_ROWS__", "\n".join(prom_rows))
    html_out = html_out.replace("__CARRIDE_ROWS__", "\n".join(car_rows))
    html_out = html_out.replace("__MONTHNAME__", esc(MONTH_NAME))
    html_out = html_out.replace("__WINDOW__", f"{MONTH_UP} 1 &ndash; {MONTH_UP} {MONTH_LAST}")
    html_out = html_out.replace("__MONTH_UP__", MONTH_UP)
    html_out = html_out.replace("__DINNER_DAY__", esc(dinner_day))
    html_out = html_out.replace("__DINNER_TIME__", esc(dinner_time))
    return html_out

def render_pdf(chrome, html_str, out_pdf, tmpdir):
    html_path = os.path.join(tmpdir, os.path.basename(out_pdf) + ".html")
    with open(html_path, "w") as f:
        f.write(html_str)
    subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={out_pdf}", html_path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def fetch_from_drive(sheet_id, label, workdir):
    """Export a Google Sheet to a temp .xlsx using the Hub's shared login, so no
    manual download is needed. Returns the file path, or None if the Hub login
    isn't importable/authorized (e.g. run standalone) so the caller can fall back
    to Downloads."""
    try:
        from automations.recruiting_report import fill as _fill
    except Exception:
        return None
    try:
        sh = _fill.open_by_key(sheet_id)
        sess = sh.client.session
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
        r = sess.get(url, timeout=120); r.raise_for_status()
        path = os.path.join(workdir, f"{label}.xlsx")
        with open(path, "wb") as fh:
            fh.write(r.content)
        print(f"{label:11}: live from Google Drive")
        return path
    except Exception as e:
        print(f"({label} live fetch unavailable: {type(e).__name__}: {e}; trying Downloads)")
        return None

SLACK_HEADER = "*TEXAS DE BRAZIL COMPETITION STANDINGS*"
SLACK_CHANNELS = [
    ("alphalete-sales",     os.environ.get("TDB_SALES_CHANNEL_ID", "C068PH3RFSM")),

    ("alphalete-lvl1-chat", os.environ.get("TDB_LVL1_CHANNEL_ID", "C09JG28CD27")),
]

IMESSAGE_GROUP   = os.environ.get("TDB_IMESSAGE_GROUP", "Alphalete A-Team Chat🔥🔥")
IMESSAGE_CHAT_ID = os.environ.get("TDB_IMESSAGE_CHAT_ID", "iMessage;+;chat72256665735645227")
IMESSAGE_TO      = [x.strip() for x in os.environ.get("TDB_IMESSAGE_TO", "").split(",") if x.strip()]
IMESSAGE_TEXT  = "🥩 TEXAS DE BRAZIL COMPETITION STANDINGS"

def post_slack(pdf_path, *, dry_run=True):
    """Post the PDF as a top-level message to each configured channel AS Lucy
    (bot token), matching Maud's manual 'PDF' post. Channels with no id are
    skipped (logged). Lucy must be a member of each channel to upload."""
    results = []
    for name, cid in SLACK_CHANNELS:
        if not cid:
            print(f"  Slack #{name}: SKIPPED — no channel id configured yet")
            results.append({"channel": name, "skipped": True}); continue
        if dry_run:
            print(f"  Slack #{name} ({cid}): WOULD post {os.path.basename(pdf_path)} "
                  f"as Lucy — comment {SLACK_HEADER!r}")
            results.append({"channel": name, "dry_run": True}); continue
        try:
            from automations.shared.slack_metrics_post import _client
            resp = _client().files_upload_v2(
                channel=cid, file=pdf_path, filename=os.path.basename(pdf_path),
                initial_comment=SLACK_HEADER)
            print(f"  Slack #{name}: posted (file {(resp.get('file') or {}).get('id')})")
            results.append({"channel": name, "ok": resp.get("ok")})
        except Exception as e:
            print(f"  Slack #{name}: FAILED — {type(e).__name__}: {str(e)[:140]}")
            results.append({"channel": name, "ok": False, "error": str(e)})
    return results

def _osascript(script, timeout=60):
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "osascript non-zero").strip()[:300])

def _ensure_fitz():
    try:
        import fitz; return fitz
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "PyMuPDF"], check=True)
        import fitz; return fitz

def _crop_trailing_black(path, thresh=28, pad=24):
    """Trim the near-black space below the content — the posters are a fixed tall
    print size, so a short board leaves a big black tail. Keeps full width + the
    top; only crops the empty bottom."""
    try:
        from PIL import Image
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "Pillow"], check=True)
        from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    bbox = im.convert("L").point(lambda v: 255 if v > thresh else 0).getbbox()
    if bbox and bbox[3] + pad < h:
        im.crop((0, 0, w, bbox[3] + pad)).save(path)

def pdf_to_pngs(pdf_path, outdir, dpi=100):
    """Render each PDF page to a PNG (trailing black cropped). iMessage transmits
    inline IMAGES to a group reliably, whereas a PDF document attachment often shows
    on the sender but never reaches the other members' phones."""
    fitz = _ensure_fitz()
    doc = fitz.open(pdf_path); out = []
    for i, page in enumerate(doc):
        p = os.path.join(outdir, f"tdb_page{i+1}.png")
        page.get_pixmap(dpi=dpi).save(p)
        _crop_trailing_black(p)
        out.append(p)
    doc.close()
    return out

def send_imessage(image_paths, *, dry_run=True):
    """Text the A-Team group on Lucy 1 (macOS only): the header line + one inline
    PNG per page. Best-effort; failures logged, never fatal. A `delay` after each
    image lets Messages finish UPLOADING to the group before we exit — otherwise
    the image shows on the sender but not the recipients."""
    if sys.platform != "darwin":
        print("  iMessage: SKIPPED — not macOS"); return {"skipped": "not_darwin"}
    if not IMESSAGE_CHAT_ID:
        print("  iMessage: SKIPPED — no group chat id configured")
        return {"skipped": "no_chat_id"}
    msg = IMESSAGE_TEXT.replace('\\', '\\\\').replace('"', '\\"')
    if dry_run:
        print(f"  iMessage: WOULD text header + {len(image_paths)} page image(s) to group {IMESSAGE_GROUP!r}")
        return {"dry_run": True, "group": IMESSAGE_GROUP, "images": len(image_paths)}
    cid = IMESSAGE_CHAT_ID.replace('"', '\\"')
    def _grp(action, timeout=90):
        _osascript(f'tell application "Messages"\n'
                   f'  set theChat to a reference to chat id "{cid}"\n'
                   f'  {action}\nend tell', timeout)
    ok = []
    try:
        _grp(f'send "{msg}" to theChat', 30); print("  iMessage: header text sent")
    except Exception as e:
        print(f"  iMessage text FAILED — {type(e).__name__}: {str(e)[:150]}")
    for idx, img in enumerate(image_paths, 1):
        ip = img.replace('\\', '\\\\').replace('"', '\\"')
        try:
            _grp(f'send (POSIX file "{ip}") to theChat\n  delay 18', 90)
            print(f"  iMessage: page {idx}/{len(image_paths)} image sent"); ok.append(img)
        except Exception as e:
            print(f"  iMessage page {idx} FAILED — {type(e).__name__}: {str(e)[:120]}")
    return {"sent": ok}

def main():
    ap = argparse.ArgumentParser(description="Steak on the Line — Texas de Brazil monthly competition")
    ap.add_argument("--send", action="store_true",
                    help="actually deliver (Slack channels + iMessage). Default: dry-run, no sends.")
    ap.add_argument("--dry-run", action="store_true", help="force dry-run even with --send")
    ap.add_argument("--no-slack", action="store_true", help="skip Slack (iMessage-only test)")
    args, _ = ap.parse_known_args()
    send = args.send and not args.dry_run
    workdir = tempfile.mkdtemp(prefix="tdb_")
    try:
        sales_file = fetch_from_drive(SALES_SHEET_ID, "Sales board", workdir) or newest(SALES_GLOB)
        recruit_file = fetch_from_drive(RECRUIT_SHEET_ID, "Recruiting", workdir) or newest(RECRUIT_GLOB)
        if not sales_file:
            sys.exit(f"ERROR: no sales data (Drive fetch failed and nothing matching:\n  {SALES_GLOB})")
        if not recruit_file:
            sys.exit(f"ERROR: no recruiting data (Drive fetch failed and nothing matching:\n  {RECRUIT_GLOB})")
        print(f"Sales board : {sales_file}")
        print(f"Recruiting  : {recruit_file}")
        chrome = find_chrome()
        board, through = build_board(sales_file, recruit_file)

        pdf_path = os.path.join(workdir, f"Steak on the Line - {MONTH_NAME}.pdf")  # temp; not saved to Downloads
        with tempfile.TemporaryDirectory() as tmp:
            flyer_pdf = os.path.join(tmp, "flyer.pdf")
            board_pdf = os.path.join(tmp, "board.pdf")
            render_pdf(chrome, flyer_html(), flyer_pdf, tmp)
            render_pdf(chrome, board_html(board, through), board_pdf, tmp)
            w = PdfWriter()
            w.append(flyer_pdf)
            w.append(board_pdf)
            with open(pdf_path, "wb") as fh:
                w.write(fh)

        thru = through.isoformat() if through else "n/a"
        print(f"Built {os.path.basename(pdf_path)}  ({len(board)} reps, through {thru})")
        for i, r in enumerate(board[:WIN], 1):
            print(f"  {i:>2} {r['name']:22} {r['total']:.0f}")

        images = pdf_to_pngs(pdf_path, workdir)          # one PNG per page, for iMessage
        print(f"\n--- Delivery {'(LIVE)' if send else '(dry-run — no sends)'} ---")
        if args.no_slack:
            print("  Slack: SKIPPED (--no-slack)")
        else:
            post_slack(pdf_path, dry_run=not send)       # Slack gets the PDF
        send_imessage(images, dry_run=not send)          # iMessage gets the page images
        print("=== done ===")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

if __name__ == "__main__":
    main()
