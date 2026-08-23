"""Daily Update fill — automates the VA's New DU runbook (Carlos 2026-08-23).

Replaces the manual evening pass ("claude prompts.pdf"): for an office, read
today's second-round interviews from ApplicantStream and append one row per
NEW candidate to the board's Daily Update tab.

Source (per office, one Retention Details load — applicant_tracker driver):
  * Total Second Interviews detail  -> name/email/phone/done-by-1st/
                                       done-by-2nd/ad (the CSV the VA exports)
  * Second Interviews Showed Up     -> 2nd Show / No Show
  * Offered Job From Second Round   -> Offered Y/N
  * Total Daily Bob                 -> BOB status fallback
  * Calendar day view (best-effort) -> follow-up wording (BOB/LM/Letting us
    know/Declined) + 'Brought on Board (<date>)' orientation dates. On warm
    patchright sessions the calendar can't navigate — those fields degrade
    gracefully (logged), everything else still fills.

Row written (columns of the Vantura 'New DU' / the boards' 'Daily Update'):
  A Status ('1 - Orientation Scheduled' when a BOB date exists, else
  'Not Active') · I Name · J Email · K Phone · L 2nd-round date (m/d) ·
  M 1st Round · N 2nd Round · O Showed/No Show · P Y/N · Q BOB Status
  ('BOB'/'LM'/'Letting us know'/'Declined'/"Didn't offer them ") ·
  R Orientation Date · S Job Ad.  B-H and T-V are left for the office.

DEDUP: a candidate whose name is already on the tab is skipped, so re-runs
and VA overlap are safe.  DRY-RUN by default; --write appends.

    python -m automations.daily_update_fill.run                    # dry, today
    python -m automations.daily_update_fill.run --date 2026-08-21  # dry, past
    python -m automations.daily_update_fill.run --write
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from zoneinfo import ZoneInfo

from automations.applicant_tracker.applicantstream import session
from automations.applicant_tracker.run import (
    L_2ND_ROSTER, L_2ND_SHOWED, L_OFFERED, L_BOB, N_2R_COLS, date_header_for)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

CENTRAL = ZoneInfo("America/Chicago")
VANTURA = "1Hltk25zTudsaoYJFKvKqWlpT_4MF5_ZZq734XKVCJKY"
DEFAULT_OFFICE = "11580"          # Carlos Hidalgo
DEFAULT_TAB = "New DU"
NAME_COL = "I"                    # Name column of the DU schema
NAME_COL_IDX = 9

Q_DIDNT_OFFER = "Didn't offer them "     # trailing space matches the dropdown
STATUS_ORIENT = "1 - Orientation Scheduled"
STATUS_NOT_ACTIVE = "Not Active"


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().replace(microsecond=0).isoformat()}] {msg}",
          flush=True)


def _n(s) -> str:
    return " ".join(str(s or "").split()).strip()


def scrape_calendar_details(app) -> dict:
    """Best-effort: {name_lower: {'follow': str, 'bob_date': str}} from the
    currently-shown calendar day (second-interview rows)."""
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
    except Exception as e:  # noqa: BLE001
        log(f"  calendar detail scrape unavailable ({type(e).__name__})")
        return {}


def ensure_week(app, day: dt.date, header: str) -> None:
    """The retention report shows one Sat-Fri week. Its #weekStart datepicker
    only allows SUNDAY picks (the runbook's "select the right Sunday"). If the
    target day's column isn't on the page, click the right Sunday."""
    try:
        if app.page.evaluate(
                "(h) => document.body.innerText.includes(h)", header):
            return
        sat = day - dt.timedelta(days=(day.weekday() - 5) % 7)
        sun = sat + dt.timedelta(days=1)
        app.page.click("#weekStart", timeout=15000)
        app.page.wait_for_timeout(1000)
        ok = app.page.evaluate(
            """(t) => {
                const d = document.getElementById('ui-datepicker-div');
                if (!d) return 'no datepicker';
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
                if (!a) return 'day link not found';
                a.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                a.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                a.click();
                return 'clicked';
            }""", {"m": sun.month - 1, "y": sun.year, "d": sun.day})
        app.page.wait_for_timeout(1200)
        app.page.click("text=Get Report", timeout=10000)
        app.page.wait_for_load_state("domcontentloaded", timeout=60000)
        app.page.wait_for_timeout(4000)
        if not app.page.evaluate(
                "(h) => document.body.innerText.includes(h)", header):
            log(f"  !! week picker did not land on {header} ({ok})")
    except Exception as e:  # noqa: BLE001
        log(f"  !! ensure_week failed ({type(e).__name__}: {e})")


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--office", default=DEFAULT_OFFICE)
    ap.add_argument("--sheet-id", default=VANTURA)
    ap.add_argument("--tab", default=DEFAULT_TAB)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default today CT)")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    day = (dt.date.fromisoformat(args.date) if args.date
           else dt.datetime.now(CENTRAL).date())
    header = date_header_for(day)
    log(f"=== daily update fill | office {args.office} | {header} | "
        f"{'WRITE' if args.write else 'DRY-RUN'} ===")

    with session() as app:
        owner = app.select_office(args.office)
        log(f"  office: {owner}")
        app.open_retention_details()
        ensure_week(app, day, header)
        # collect EVERY detail link from this one report load FIRST —
        # scrape_at/names_at navigate away (the applicant_tracker pattern)
        h_roster = app.detail_href(L_2ND_ROSTER, header)
        h_showed = app.detail_href(L_2ND_SHOWED, header)
        h_offered = app.detail_href(L_OFFERED, header)
        h_bob = app.detail_href(L_BOB, header)
        rows = app.scrape_at(h_roster, N_2R_COLS) if h_roster else []
        if not rows:
            log("  no second interviews today — nothing to fill")
            return 0
        showed = {n.strip().lower()
                  for n in (app.names_at(h_showed) if h_showed else [])}
        offered = {n.strip().lower()
                   for n in (app.names_at(h_offered) if h_offered else [])}
        bob = {n.strip().lower()
               for n in (app.names_at(h_bob) if h_bob else [])}
        cal = {}
        if app.open_calendar_for(day):
            cal = scrape_calendar_details(app)
        log(f"  roster={len(rows)} showed={len(showed)} offered={len(offered)}"
            f" bob={len(bob)} calendar-rows={len(cal)}")

    # rows: First, Last, Email, Phone, Rating, 1STR, 2ND, Job Board, DT, Ad
    cands = []
    for r in rows:
        r = list(r) + [""] * (10 - len(r))
        first, last = _n(r[0]), _n(r[1])
        name = f"{first} {last}".strip()
        key = name.lower()
        info = cal.get(key, {})
        off = key in offered
        did_show = key in showed
        bobdate = _n(info.get("bob_date", ""))
        cands.append({
            "name": name, "email": _n(r[2]), "phone": _n(r[3]),
            "first_round": _n(r[5]), "second_round": _n(r[6]),
            "ad": _n(r[9]),
            "show": "Showed" if did_show else "No Show",
            # VA convention: a no-show's Offered / BOB Status stay blank
            "offered": ("Y" if off else "N") if did_show else "",
            "bob_status": (map_bob_status(off, info.get("follow", ""),
                                          key in bob) if did_show else ""),
            "orientation": bobdate,
            "status": STATUS_ORIENT if bobdate else STATUS_NOT_ACTIVE,
        })

    from automations.recruiting_report.fill import _retry, open_by_key
    sh = _retry(lambda: open_by_key(args.sheet_id))
    ws = sh.worksheet(args.tab)
    existing = {(_n(c)).lower() for c in ws.col_values(NAME_COL_IDX) if _n(c)}
    new = [c for c in cands if c["name"].lower() not in existing]
    for c in cands:
        dup = " (already on sheet — skipped)" \
            if c["name"].lower() in existing else ""
        log(f"  {c['name']:<28} {c['show']:<8} offered={c['offered']} "
            f"bob={c['bob_status']!r:<20} orient={c['orientation'] or '-'}"
            f"{dup}")
    if not new:
        log("  nothing new to append")
        return 0
    if not args.write:
        log(f"  DRY-RUN: would append {len(new)} row(s)")
        return 0

    start = len(ws.col_values(NAME_COL_IDX)) + 1
    ldate = f"{day.month}/{day.day}"
    data = []
    for i, c in enumerate(new):
        row = start + i
        data.append({"range": f"'{args.tab}'!A{row}", "values": [[c["status"]]]})
        data.append({"range": f"'{args.tab}'!I{row}:S{row}", "values": [[
            c["name"], c["email"], c["phone"], ldate, c["first_round"],
            c["second_round"], c["show"], c["offered"], c["bob_status"],
            c["orientation"], c["ad"]]]})
    sh.values_batch_update(body={"valueInputOption": "RAW", "data": data})
    log(f"  appended {len(new)} row(s) at {start}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
