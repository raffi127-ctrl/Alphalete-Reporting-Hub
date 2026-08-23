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
STATUS_ORIENT = "1 - Orientation Scheduled"
STATUS_CR = "2 - Showed to classroom"
STATUS_NOT_ACTIVE = "Not Active"
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
        status = STATUS_ORIENT if orientation else STATUS_NOT_ACTIVE
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
        hdr_i = next((i for i, r in enumerate(rows)
                      if any("rep name" in _n(c).lower() for c in r)), None)
        if hdr_i is not None:
            hdr = [_n(c).lower() for c in rows[hdr_i]]
            rep_c = next(i for i, h in enumerate(hdr) if "rep name" in h)
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


def sync_terminated(name_label, sh, tab, write) -> int:
    """Board says terminated => Daily Update Status (A) = Not Active (and
    Secondary Status B = Terminated when blank)."""
    term = terminated_names(sh)
    if not term:
        return 0
    ws = sh.worksheet(tab)
    col_i = [_n(c) for c in ws.col_values(NAME_COL_IDX)]
    col_a = [_n(c) for c in ws.col_values(1)]
    col_b = [_n(c) for c in ws.col_values(2)]
    data, hits = [], 0
    for idx, nm in enumerate(col_i):
        if not nm or nm.lower() not in term:
            continue
        row = idx + 1
        a = col_a[idx] if idx < len(col_a) else ""
        b = col_b[idx] if idx < len(col_b) else ""
        if a != STATUS_NOT_ACTIVE:
            data.append({"range": f"'{tab}'!A{row}",
                         "values": [[STATUS_NOT_ACTIVE]]})
            hits += 1
        if not b:
            data.append({"range": f"'{tab}'!B{row}",
                         "values": [["Terminated"]]})
    log(f"  {name_label:<17} terminated on board={len(term)} "
        f"du-status-flips={hits}" + ("" if write else "  (dry-run)"))
    if write and data:
        sh.values_batch_update(body={"valueInputOption": "RAW", "data": data})
    return hits


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
            sync_terminated(name, sh, tab, args.write)
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name} term-sync: {type(e).__name__}: {e}")
            log(f"  !! {name} term-sync FAILED: {type(e).__name__}: {e}")
    if failures:
        log(f"finished with {len(failures)} FAILURE(S): {failures}")
        return 1
    log("finished clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
