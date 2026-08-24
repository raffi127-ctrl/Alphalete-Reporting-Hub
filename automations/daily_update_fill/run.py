"""Daily Update fill — automates the VA's New DU runbook (Carlos 2026-08-23).

For each office, reads ApplicantStream's Retention Details and fills the
board's Daily Update tab exactly the way the VA does it by hand:

  APPEND (per interview day): one row per NEW second-round candidate —
    A Status · I Name · J Email · K Phone · L 2nd-round date · M 1st Round ·
    N 2nd Round · O Showed/No Show · P Offered Y/N (blank for no-shows) ·
    Q BOB Status · R Orientation Date · S Job Ad.
  CLASSROOM RETENTION (col T, Carlos 2026-08-23): the same report's
    'Total Training' / 'Training Showed Up' rows say who had their first day
    (new starts) and who showed — existing rows get 'Showed To CR' /
    'CR No Show' filled in when column T is blank. A candidate we append who
    later shows to training also gets R = that training date and
    A = '2 - Showed to classroom'.

Offices: Carlos's own (11580 -> Vantura 'New DU') and the 11 captainship
owners (funnel_board roster ids -> their boards' 'Daily Update').

DEDUP by name per tab — re-runs and VA overlap are safe. DRY-RUN by default.

    python -m automations.daily_update_fill.run                       # today, all
    python -m automations.daily_update_fill.run --offices vantura
    python -m automations.daily_update_fill.run --start 2026-07-27 \\
        --end 2026-08-23 --offices captainship --write               # backfill

Calendar-only nuances (nightly runs only, calendar shows today): follow-up
wording LM/Letting us know/Declined, and orientation dates for people who
have not reached training yet.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from zoneinfo import ZoneInfo

from automations.applicant_tracker.applicantstream import session
from automations.applicant_tracker.run import (
    L_2ND_ROSTER, L_2ND_SHOWED, L_OFFERED, L_BOB, L_TRAINING,
    L_TRAINING_SHOWED, N_2R_COLS, date_header_for)
from automations.captainship_boards.config import OWNERS as BOARD_IDS

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

CENTRAL = ZoneInfo("America/Chicago")
VANTURA = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"

# name -> (appstream office id, sheet id, tab)
OFFICES = {"Carlos Hidalgo": ("11580", VANTURA, "New DU")}
_ROSTER_OIDS = {
    "Atef Choudhury": "23467", "Jamis Garay": "19592", "Jackie LeRoy": "22358",
    "Jeff Starr": "15031", "Kinsey Guenther": "11906", "Vincent Smith": "23318",
    "George Hipolito": "11296", "Justin Wood": "22192",
    "Joshua Murphy": "21770", "Joey Ramirez": "23206", "Dhyey Patel": "22767",
}
for _n_, _oid in _ROSTER_OIDS.items():
    OFFICES[_n_] = (_oid, BOARD_IDS[_n_][1], "Daily Update")

NAME_COL_IDX = 9                          # column I
Q_DIDNT_OFFER = "Didn't offer them "      # trailing space = the dropdown value
# Simplified lifecycle (Carlos 2026-08-23): terminated -> Not Active; any
# sale -> Active; showed to classroom/orientation -> Showed to Classroom;
# Admin is manual and never touched. The old numbered ladder is retired.
STATUS_ACTIVE = "Active"
STATUS_CR = "Showed to Classroom"
STATUS_NOT_ACTIVE = "Not Active"
STATUS_ADMIN = "Admin"
# Vantura master (Carlos, 2026-08-24): terminations and classroom flips ONLY —
# no sale=>Active automation of ANY flavor there (the WeekData-history variant
# inflated his Actives to 162). Actives on the master are set by hand. The
# captainship boards keep the full lifecycle.
NO_SALE_ACTIVE = {"Carlos Hidalgo"}
# The master also keeps its orientation->Roll Call flow MANUAL; the daily
# rollcall_sync below is for the 11 owner boards only (Carlos 8/24).
NO_ROLLCALL_SYNC = {"Carlos Hidalgo"}
OLD_LADDER_ACTIVE = ("3", "4", "5", "6", "7")   # '3 - In Training'.. prefixes
CR_SHOW, CR_NOSHOW = "Showed To CR", "CR No Show"


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _n(s) -> str:
    return " ".join(str(s or "").split()).strip()


def pick_sunday(d: dt.date) -> dt.date:
    """The week-anchor Sunday whose picked week (Sun..Sat) contains d."""
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def ensure_week(app, sun: dt.date) -> bool:
    """Drive the report to the Sun-Sat week starting `sun` (the datepicker
    only accepts Sundays; the Get Report button reloads the grid)."""
    probe = date_header_for(sun)
    try:
        if app.page.evaluate("(h) => document.body.innerText.includes(h)", probe):
            return True
        app.page.click("#weekStart", timeout=15000)
        app.page.wait_for_timeout(1000)
        app.page.evaluate(
            """(t) => {
                const d = document.getElementById('ui-datepicker-div');
                if (!d) return;
                const mSel = d.querySelector('.ui-datepicker-month');
                const ySel = d.querySelector('.ui-datepicker-year');
                if (mSel && +mSel.value !== t.m) {
                    mSel.value = String(t.m);
                    mSel.dispatchEvent(new Event('change', {bubbles: true}));
                }
                if (ySel && +ySel.value !== t.y) {
                    ySel.value = String(t.y);
                    ySel.dispatchEvent(new Event('change', {bubbles: true}));
                }
                const a = [...d.querySelectorAll('a')]
                    .find(x => x.textContent.trim() === String(t.d));
                if (!a) return;
                a.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                a.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                a.click();
            }""", {"m": sun.month - 1, "y": sun.year, "d": sun.day})
        app.page.wait_for_timeout(1200)
        app.page.click("text=Get Report", timeout=10000)
        app.page.wait_for_load_state("domcontentloaded", timeout=60000)
        app.page.wait_for_timeout(4000)
        ok = app.page.evaluate(
            "(h) => document.body.innerText.includes(h)", probe)
        if not ok:
            log(f"  !! week picker did not land on week of {sun}")
        return bool(ok)
    except Exception as e:  # noqa: BLE001
        log(f"  !! ensure_week failed ({type(e).__name__}: {e})")
        return False


def scrape_calendar_details(app) -> dict:
    """Best-effort {name_lower: {'follow','bob_date'}} from the shown day."""
    try:
        pairs = app.page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('tr').forEach(tr => {
                    const t = tr.innerText || '';
                    if (!/Phone:/i.test(t)) return;
                    let name = '';
                    for (const td of tr.children) {
                        const x = td.innerText || '';
                        if (/Phone:/i.test(x)) {
                            name = x.split('\\n').map(s => s.trim())
                                    .filter(Boolean)[0];
                            break;
                        }
                    }
                    if (!name) return;
                    const bob = t.match(/Brought on Board\\s*\\(([^)]+)\\)/i);
                    let follow = '';
                    tr.querySelectorAll('select').forEach(sel => {
                        const v = sel.options[sel.selectedIndex]
                                  ? sel.options[sel.selectedIndex].text : '';
                        if (/bob|declin|waiting|called|sms/i.test(v)) follow = v;
                    });
                    if (!follow) {
                        const m = t.match(/(BOB[^\\n]*|Declined next round[^\\n]*)/i);
                        if (m) follow = m[1];
                    }
                    out.push([name, follow, bob ? bob[1].trim() : '']);
                });
                return out;
            }""")
        return {n.strip().lower(): {"follow": f, "bob_date": b}
                for n, f, b in pairs}
    except Exception:  # noqa: BLE001
        return {}


def map_bob_status(offered: bool, follow: str, in_bob: bool) -> str:
    if not offered:
        return Q_DIDNT_OFFER
    f = (follow or "").lower()
    if "booked" in f or f.strip() == "bob":
        return "BOB"
    if "called" in f or "sms" in f:
        return "LM"
    if "waiting" in f:
        return "Letting us know"
    if "declined" in f:
        return "Declined"
    return "BOB" if in_bob else ""


def harvest_office(app, oid: str, days: list, use_calendar: bool):
    """One office: navigate week by week, collect per-day hrefs from each
    single report load, then visit them. Returns (candidates, cr_map)."""
    owner = app.select_office(oid)
    log(f"  office {oid}: {owner}")
    per_day = {}
    for sun in sorted({pick_sunday(d) for d in days}):
        app.open_retention_details()
        if not ensure_week(app, sun):
            continue
        for d in days:
            if pick_sunday(d) != sun:
                continue
            h = date_header_for(d)
            per_day[d] = {lbl: app.detail_href(lbl, h) for lbl in (
                L_2ND_ROSTER, L_2ND_SHOWED, L_OFFERED, L_BOB,
                L_TRAINING, L_TRAINING_SHOWED)}
    cands, cr_map = [], {}
    for d in sorted(per_day):
        hs = per_day[d]
        rows = (app.scrape_at(hs[L_2ND_ROSTER], N_2R_COLS)
                if hs[L_2ND_ROSTER] else [])
        showed = {n.strip().lower() for n in (
            app.names_at(hs[L_2ND_SHOWED]) if hs[L_2ND_SHOWED] else [])}
        offered = {n.strip().lower() for n in (
            app.names_at(hs[L_OFFERED]) if hs[L_OFFERED] else [])}
        bob = {n.strip().lower() for n in (
            app.names_at(hs[L_BOB]) if hs[L_BOB] else [])}
        train = [_n(x) for x in (
            app.names_at(hs[L_TRAINING]) if hs[L_TRAINING] else [])]
        tshow = {n.strip().lower() for n in (
            app.names_at(hs[L_TRAINING_SHOWED]) if hs[L_TRAINING_SHOWED]
            else [])}
        for name in train:
            cr_map[name.lower()] = (d, name.lower() in tshow)
        cal = {}
        if use_calendar and rows and d == dt.datetime.now(CENTRAL).date():
            if app.open_calendar_for(d):
                cal = scrape_calendar_details(app)
        for r in rows:
            r = list(r) + [""] * (10 - len(r))
            name = f"{_n(r[0])} {_n(r[1])}".strip()
            key = name.lower()
            info = cal.get(key, {})
            off, did_show = key in offered, key in showed
            cands.append({
                "day": d, "name": name, "email": _n(r[2]), "phone": _n(r[3]),
                "first_round": _n(r[5]), "second_round": _n(r[6]),
                "ad": _n(r[9]),
                "show": "Showed" if did_show else "No Show",
                "offered": ("Y" if off else "N") if did_show else "",
                "bob_status": (map_bob_status(off, info.get("follow", ""),
                                              key in bob) if did_show else ""),
                "orientation": _n(info.get("bob_date", "")),
            })
        if rows or train:
            log(f"    {d}: interviews={len(rows)} showed={len(showed)} "
                f"offered={len(offered)} bob={len(bob)} "
                f"training={len(train)} tshowed={len(tshow)}")
    return cands, cr_map


def apply_to_sheet(name_label, sheet_id, tab, cands, cr_map, write):
    from automations.recruiting_report.fill import _retry, open_by_key
    sh = _retry(lambda: open_by_key(sheet_id))
    ws = sh.worksheet(tab)
    col_i = [_n(c) for c in ws.col_values(NAME_COL_IDX)]
    col_t = [_n(c) for c in ws.col_values(20)]           # T
    n_before = len(col_i)
    existing = {}
    for idx, nm in enumerate(col_i):
        if nm:
            existing[nm.lower()] = idx + 1               # last wins
    data, appended = [], 0
    next_row = max(n_before + 1, 3)                      # data starts row 2/3
    for c in cands:
        key = c["name"].lower()
        if not key or key in existing:
            continue
        cr = cr_map.get(key)
        orientation = c["orientation"]
        status = STATUS_NOT_ACTIVE
        t_val = ""
        if cr:
            t_val = CR_SHOW if cr[1] else CR_NOSHOW
            if not orientation:
                orientation = f"{cr[0].month}/{cr[0].day}"
            if cr[1]:
                status = STATUS_CR
            # reaching the training roster proves they were offered + BOB'd,
            # even when the interview-day Offered detail missed them
            c["offered"] = "Y"
            if c["bob_status"] in ("", Q_DIDNT_OFFER):
                c["bob_status"] = "BOB"
        row = next_row
        next_row += 1
        existing[key] = row
        ldate = f"{c['day'].month}/{c['day'].day}"
        data.append({"range": f"'{tab}'!A{row}", "values": [[status]]})
        # Campaign (col F) — the owner boards are single-campaign, so stamp it
        # (Carlos 8/24). The Vantura master runs B2B AND BOX; the VA sorts it.
        if name_label not in NO_ROLLCALL_SYNC:
            data.append({"range": f"'{tab}'!F{row}", "values": [["AT&T B2B"]]})
        data.append({"range": f"'{tab}'!I{row}:S{row}", "values": [[
            c["name"], c["email"], c["phone"], ldate, c["first_round"],
            c["second_round"], c["show"], c["offered"], c["bob_status"],
            orientation, c["ad"]]]})
        if t_val:
            data.append({"range": f"'{tab}'!T{row}", "values": [[t_val]]})
        appended += 1
    cr_updates = 0
    for key, (d, shown) in cr_map.items():
        row = existing.get(key)
        if not row or row > n_before:                    # only pre-existing rows
            continue
        cur_t = col_t[row - 1] if row <= len(col_t) else ""
        if cur_t:
            continue
        data.append({"range": f"'{tab}'!T{row}",
                     "values": [[CR_SHOW if shown else CR_NOSHOW]]})
        cr_updates += 1
    log(f"  {name_label:<17} append={appended} cr-updates={cr_updates}"
        + ("" if write else "  (dry-run)"))
    if write and data:
        sh.values_batch_update(body={"valueInputOption": "RAW", "data": data})
    return appended, cr_updates


def _is_term(v: str) -> bool:
    v = _n(v).lower()
    return v == "t" or "termin" in v


def terminated_names(sh) -> set:
    """Names marked T/Terminated on this workbook's Sales Board (Field
    Status col or a literal T in a day cell) or Roll Call (Status col or a
    T in the Mon-Sat attendance cells). Carlos 2026-08-23."""
    out = set()
    try:
        tabs = {ws.title: ws for ws in sh.worksheets()}
    except Exception:  # noqa: BLE001
        return out
    if "Sales Board" in tabs:
        rows = tabs["Sales Board"].get_values("A1:P250")
        hdr_i = next((i for i, r in enumerate(rows)
                      if any(_n(c).upper() == "REP" for c in r)), None)
        if hdr_i is not None:
            hdr = [_n(c).lower() for c in rows[hdr_i]]
            rep_c = hdr.index("rep")
            try:
                fs_c = next(i for i, h in enumerate(hdr)
                            if "field status" in h)
            except StopIteration:
                fs_c = None
            day_cs = [i for i, h in enumerate(hdr) if h.startswith(
                ("monday", "tuesday", "wednesday", "thursday", "friday",
                 "saturday", "sunday"))]
            for r in rows[hdr_i + 1:]:
                r += [""] * (16 - len(r))
                name = _n(r[rep_c])
                if not name:
                    continue
                if fs_c is not None and _is_term(r[fs_c]):
                    out.add(name.lower())
                elif any(_n(r[c]).lower() == "t" for c in day_cs):
                    out.add(name.lower())
    if "Roll Call" in tabs:
        rows = tabs["Roll Call"].get_values("A1:L250")
        # Owner boards head the name column "Rep Name"; the Vantura master
        # heads it "Roll Call" (exact match only — the tab TITLE also contains
        # the words "roll call", so containment would grab the title row).
        def _is_name_hdr(h):
            return "rep name" in h or h == "roll call"
        hdr_i = next((i for i, r in enumerate(rows)
                      if any(_is_name_hdr(_n(c).lower()) for c in r)), None)
        if hdr_i is not None:
            hdr = [_n(c).lower() for c in rows[hdr_i]]
            rep_c = next(i for i, h in enumerate(hdr) if _is_name_hdr(h))
            st_c = next((i for i, h in enumerate(hdr) if h == "status"), None)
            att_cs = [i for i, h in enumerate(hdr) if h in (
                "mon", "tue", "wed", "thu", "fri", "sat")]
            for r in rows[hdr_i + 1:]:
                r += [""] * (12 - len(r))
                name = _n(r[rep_c])
                if not name:
                    continue
                if (st_c is not None and _is_term(r[st_c])) or                         any(_n(r[c]).lower() == "t" for c in att_cs):
                    out.add(name.lower())
    return out


def board_sellers_and_roster(sh):
    """(sellers, roster) from this workbook: WeekData when present (any
    positive day => that rep sold), else the Sales Board's numeric cells."""
    sellers, roster = set(), set()
    try:
        tabs = {ws.title for ws in sh.worksheets()}
    except Exception:  # noqa: BLE001
        return sellers, roster
    if "Sales Board" in tabs:
        rows = sh.worksheet("Sales Board").get_values("A1:P250")
        hdr_i = next((i for i, r in enumerate(rows)
                      if any(_n(c).upper() == "REP" for c in r)), None)
        if hdr_i is not None:
            hdr = [_n(c).lower() for c in rows[hdr_i]]
            rep_c = hdr.index("rep")
            num_cs = [i for i, h in enumerate(hdr) if h.startswith(
                ("current week", "last wk", "monday", "tuesday", "wednesday",
                 "thursday", "friday", "saturday", "sunday"))]
            for r in rows[hdr_i + 1:]:
                r += [""] * (16 - len(r))
                name = _n(r[rep_c])
                if not name:
                    continue
                roster.add(name.lower())
                for c in num_cs:
                    v = _n(r[c]).replace(",", "")
                    try:
                        if float(v) > 0:
                            sellers.add(name.lower())
                            break
                    except ValueError:
                        continue
    if "WeekData" in tabs:
        for r in sh.worksheet("WeekData").get_values("A2:H5000"):
            if not r or "|" not in (r[0] or ""):
                continue
            rep = _n(r[0].split("|")[0])
            for v in r[1:8]:
                try:
                    if float(_n(v) or 0) > 0:
                        sellers.add(rep.lower())
                        break
                except ValueError:
                    continue
    return sellers, roster


def _fuzzy_key(name: str):
    parts = _n(name).lower().split()
    if len(parts) < 2:
        return None
    return (parts[-1], parts[0][:3])


def _member(key_name: str, exact: set, fuzzy: set) -> bool:
    if key_name in exact:
        return True
    fk = _fuzzy_key(key_name)
    return fk is not None and fk in fuzzy


def sync_statuses(name_label, sh, tab, write) -> int:
    """Enforce the simplified lifecycle (Active / Not Active / Admin /
    Showed to Classroom) on every Daily Update row.
    Order: terminated -> Not Active; sale seen -> Active; old numbered
    ladder -> Active if still on the board roster else Not Active;
    '1 - Orientation' -> Not Active; '2 - Showed'/fresh CR-shown -> Showed
    to Classroom. 'Not Active' rows are never resurrected except by a sale;
    Admin rows are never touched. Nickname-tolerant matching (will~william)."""
    term = terminated_names(sh)
    sellers, roster = board_sellers_and_roster(sh)
    if name_label in NO_SALE_ACTIVE:
        sellers, roster = set(), set()
    term_f = {k for k in (_fuzzy_key(x) for x in term) if k}
    sellers_f = {k for k in (_fuzzy_key(x) for x in sellers) if k}
    roster_f = {k for k in (_fuzzy_key(x) for x in roster) if k}
    ws = sh.worksheet(tab)
    col_i = [_n(c) for c in ws.col_values(NAME_COL_IDX)]
    col_a = [_n(c) for c in ws.col_values(1)]
    col_b = [_n(c) for c in ws.col_values(2)]
    col_t = [_n(c) for c in ws.col_values(20)]
    data, flips = [], 0
    for idx, nm in enumerate(col_i):
        if not nm:
            continue
        key = nm.lower()
        cur = col_a[idx] if idx < len(col_a) else ""
        if cur == STATUS_ADMIN:
            continue
        t = col_t[idx] if idx < len(col_t) else ""
        cl = cur.lower()
        old_ladder = cur[:1] in OLD_LADDER_ACTIVE and " - " in cur
        if _member(key, term, term_f):
            want = STATUS_NOT_ACTIVE
        elif _member(key, sellers, sellers_f):
            want = STATUS_ACTIVE
        elif old_ladder:
            if _member(key, roster, roster_f):
                want = STATUS_ACTIVE
            elif cur.startswith("3"):        # still in training, no sale yet
                want = STATUS_CR
            else:
                want = STATUS_NOT_ACTIVE
        elif cl.startswith("1 - orientation"):
            want = STATUS_NOT_ACTIVE
        elif cl.startswith("2 - showed") or (not cur and t == CR_SHOW):
            want = STATUS_CR
        else:
            continue                     # Not Active / Active / blank stand
        if cur != want:
            data.append({"range": f"'{tab}'!A{idx + 1}", "values": [[want]]})
            flips += 1
        if _member(key, term, term_f) and                 not (col_b[idx] if idx < len(col_b) else ""):
            data.append({"range": f"'{tab}'!B{idx + 1}",
                         "values": [["Terminated"]]})
    log(f"  {name_label:<17} term={len(term)} sellers={len(sellers)} "
        f"status-flips={flips}" + ("" if write else "  (dry-run)"))
    if write and data:
        sh.values_batch_update(body={"valueInputOption": "RAW", "data": data})
    return flips


def rollcall_sync(name_label, sh, tab, write) -> int:
    """Owner boards only (Carlos 8/24; the Vantura master keeps its manual
    flow): anyone the Daily Update shows as classroom-shown (T='Showed To
    CR') who has no Roll Call row gets appended as Status='New Start' with
    their week-ending, campaign and 2nd Rounder; once a NEW week starts,
    the previous weeks' 'New Start' rows flip to 'Active'. Blank 'Week
    Ending' / '2nd Rounder' cells on existing rows are backfilled from the
    DU — typed values are never overwritten."""
    if name_label in NO_ROLLCALL_SYNC:
        return 0
    ws = sh.worksheet("Roll Call")
    rc = ws.get_values("A1:N250")
    du = sh.worksheet(tab).get_values("A2:T6000")
    today = dt.datetime.now(CENTRAL).date()
    cur_we = today - dt.timedelta(days=today.weekday()) + dt.timedelta(days=6)

    def we_label(d):
        return f"{d.month}.{d.day}"

    def parse_lbl(s):
        m = re.match(r"^(\d{1,2})[./](\d{1,2})$", _n(s))
        if not m:
            return None
        try:
            return dt.date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None

    def orient_we(orient):
        m = re.match(r"^(\d{1,2})/(\d{1,2})", _n(orient))
        if m:
            try:
                d = dt.date(today.year, int(m.group(1)), int(m.group(2)))
                return we_label(d - dt.timedelta(days=d.weekday())
                                + dt.timedelta(days=6))
            except ValueError:
                pass
        return we_label(cur_we)

    by_name = {}
    for row in du:
        row = list(row) + [""] * 20
        nm = _n(row[8])
        if not nm:
            continue
        e = {"n2": _n(row[13]), "orient": _n(row[17]), "cr": _n(row[19])}
        by_name[nm.lower()] = e
        fk = _fuzzy_key(nm)
        if fk:
            by_name.setdefault(fk, e)

    rc_names, campaigns, first_empty = {}, [], None
    for i, row in enumerate(rc[2:], 3):
        row = list(row) + [""] * 6
        nm = _n(row[3])
        if nm:
            rc_names[nm.lower()] = i
            fk = _fuzzy_key(nm)
            if fk:
                rc_names.setdefault(fk, i)
            if _n(row[2]):
                campaigns.append(_n(row[2]))
        elif first_empty is None:
            first_empty = i
    campaign = (max(set(campaigns), key=campaigns.count)
                if campaigns else "AT&T B2B")
    if first_empty is None:
        first_empty = len(rc) + 1

    data, added, flipped, filled = [], 0, 0, 0
    # append classroom-shown people missing from the Roll Call — RECENT ones
    # only (last 14 days by orientation date): the DU carries months of
    # historical CR marks from the backfill, and those people are long gone
    # (first dry-run wanted +53 on Justin). No parseable date = not recent.
    seen_new, skipped_old = set(), 0
    for row in du:
        row = list(row) + [""] * 20
        nm = _n(row[8])
        if not nm or _n(row[19]) != CR_SHOW:
            continue
        key = nm.lower()
        if key in seen_new or _member(key, set(rc_names), set(rc_names)):
            continue
        m = re.match(r"^(\d{1,2})/(\d{1,2})", _n(row[17]))
        try:
            od = dt.date(today.year, int(m.group(1)), int(m.group(2))) if m else None
        except ValueError:
            od = None
        if od is None or not (today - dt.timedelta(days=14) <= od <= today
                              + dt.timedelta(days=7)):
            skipped_old += 1
            continue
        seen_new.add(key)
        r = first_empty + added
        data.append({"range": f"'Roll Call'!A{r}:F{r}",
                     "values": [[orient_we(row[17]), "New Start", campaign,
                                 nm, _n(row[13]), ""]]})
        added += 1
    # week rollover: previous weeks' New Starts become Active; backfills;
    # and the TERMINATION CASCADE (Carlos 8/24: "mark T" must actually do
    # its job) — an attendance-cell T sets Status='Terminated', fills Date
    # Gone with the T'd day, and guarantees a DU row exists to flip.
    du_names = {_n(r[8]).lower() for r in
                (list(x) + [""] * 20 for x in du) if _n(r[8])}
    term_cascaded, term_new_du = 0, []
    for i, row in enumerate(rc[2:], 3):
        row = list(row) + [""] * 14
        nm = _n(row[3])
        if not nm:
            continue
        att_t_idx = next((c for c in range(6, 12)
                          if _n(row[c]).lower() == "t"), None)
        is_term = _is_term(row[1]) or att_t_idx is not None
        if is_term:
            if not _is_term(row[1]):
                data.append({"range": f"'Roll Call'!B{i}",
                             "values": [["Terminated"]]})
                term_cascaded += 1
            if not _n(row[12]) and att_t_idx is not None:
                wed = parse_lbl(row[0]) or cur_we
                gone = wed - dt.timedelta(days=6 - (att_t_idx - 6))
                data.append({"range": f"'Roll Call'!M{i}",
                             "values": [[f"{gone.month}/{gone.day}"]]})
            if nm.lower() not in du_names:
                du_names.add(nm.lower())
                term_new_du.append(nm)
        elif _n(row[1]) == "New Start":
            wed = parse_lbl(row[0])
            if wed is not None and wed < cur_we:
                data.append({"range": f"'Roll Call'!B{i}",
                             "values": [["Active"]]})
                flipped += 1
        e = by_name.get(nm.lower()) or by_name.get(_fuzzy_key(nm))
        if e:
            if not _n(row[4]) and e["n2"]:
                data.append({"range": f"'Roll Call'!E{i}", "values": [[e["n2"]]]})
                filled += 1
            if not _n(row[0]) and e["orient"]:
                data.append({"range": f"'Roll Call'!A{i}",
                             "values": [[orient_we(e["orient"])]]})
                filled += 1
    next_du = len(du) + 2
    for nm in term_new_du:
        data.append({"range": f"'{tab}'!A{next_du}", "values": [["Not Active"]]})
        data.append({"range": f"'{tab}'!B{next_du}", "values": [["Terminated"]]})
        data.append({"range": f"'{tab}'!F{next_du}", "values": [[campaign]]})
        data.append({"range": f"'{tab}'!I{next_du}", "values": [[nm]]})
        next_du += 1
    log(f"  {name_label:<17} rollcall: +{added} new-start, {flipped} -> Active, "
        f"{filled} backfilled, {skipped_old} historical skipped, "
        f"{term_cascaded} T-cascaded, +{len(term_new_du)} DU rows for terms"
        + ("" if write else "  (dry-run)"))
    if write and data:
        sh.values_batch_update(body={"valueInputOption": "RAW", "data": data})
    return added + flipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offices", default="all",
                    choices=["all", "vantura", "captainship"])
    ap.add_argument("--only", default=None, help="one owner name")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--date", default=None, help="single day (default today)")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    today = dt.datetime.now(CENTRAL).date()
    if args.start:
        start = dt.date.fromisoformat(args.start)
        end = dt.date.fromisoformat(args.end) if args.end else today
    else:
        start = end = (dt.date.fromisoformat(args.date) if args.date
                       else today)
    days = [start + dt.timedelta(days=i)
            for i in range((end - start).days + 1)]
    targets = {}
    for name, cfg in OFFICES.items():
        if args.only and name != args.only:
            continue
        if args.offices == "vantura" and name != "Carlos Hidalgo":
            continue
        if args.offices == "captainship" and name == "Carlos Hidalgo":
            continue
        targets[name] = cfg
    log(f"=== daily update fill | {start}..{end} | "
        f"{len(targets)} office(s) | {'WRITE' if args.write else 'DRY-RUN'} ===")

    use_cal = start == end == today
    failures = []
    results = {}
    with session() as app:
        for name, (oid, sheet_id, tab) in targets.items():
            try:
                cands, cr_map = harvest_office(app, oid, days, use_cal)
                results[name] = (sheet_id, tab, cands, cr_map)
            except Exception as e:  # noqa: BLE001
                failures.append(f"{name}: {type(e).__name__}: {e}")
                log(f"  !! {name} harvest FAILED: {type(e).__name__}: {e}")
    from automations.recruiting_report.fill import _retry, open_by_key
    for name, (sheet_id, tab, cands, cr_map) in results.items():
        try:
            apply_to_sheet(name, sheet_id, tab, cands, cr_map, args.write)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name} write: {type(e).__name__}: {e}")
            log(f"  !! {name} write FAILED: {type(e).__name__}: {e}")
        try:
            sh = _retry(lambda sid=sheet_id: open_by_key(sid))
            sync_statuses(name, sh, tab, args.write)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name} term-sync: {type(e).__name__}: {e}")
            log(f"  !! {name} term-sync FAILED: {type(e).__name__}: {e}")
        try:
            rollcall_sync(name, sh, tab, args.write)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name} rollcall: {type(e).__name__}: {e}")
            log(f"  !! {name} rollcall FAILED: {type(e).__name__}: {e}")
    if failures:
        log(f"finished with {len(failures)} FAILURE(S): {failures}")
        return 1
    log("finished clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
