"""The owner's weekly PNL, done on the owner's own computer.

WHY HERE AND NOT ON A LUCY (Eve + Megan, 2026-10-29). Each Lucy Eco does its
own owner's PNL end to end, so our machines carry none of it and the payroll
never leaves the owner's Mac:

    Brought In  -- the owner's DD by rep, from Tableau, through THEIR OwnerVille
                   login (the same Tableau hop our Lucys take, p=81 SSO)
    Got Paid    -- their Apex payroll export, from Lucy's Chrome, where they
                   signed into Apex once (like the Box sign-in)
    Profit/Loss -- Brought In - Got Paid x 1.12 (payroll tax), per rep
                   (Carlos's Loom, 2026-10-26)

Nothing of it goes through the relay. The one thing that does is the DD
CHECK below, and only its count and total -- DD is a number our Lucys already
pull for every owner; the payroll is not.

STEP ONE IS THE CHECK, and it is all this file does today. Our Lucys reach the
DD with Raf's login, which sees everybody; whether an OWNER's login sees its
own rows in the same view was never tried. So on an office in PNL_KEYS this
reads the view once, files what it saw as a `probe-pnl-dd` fault (filed in the
Faults tab, never posted -- see post.notify_faults), and stops.

STEP TWO IS APEX (DD proven on Jairo's Mac 2026-10-29: $89,515.91, 49 reps,
WE 10/25, same as Lucy 3). Once the owner signs into Apex in Lucy's window
(apex_signin; autoprompt puts it up when he is at the Mac), the newest pay
period is exported to this computer and matched to the DD by rep name; the
`probe-pnl-apex` line says how many matched and who did not. The sheet comes
after that.

    python -m automations.icd_alerts.pnl --check      # run the DD check now
    python -m automations.icd_alerts.pnl --apex       # run the Apex check now
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
import time
from typing import Dict, List, Optional, Tuple

from automations.icd_alerts import config as C

# Offices whose owner asked for the PNL. Jairo first (2026-10-29, Megan OK).
PNL_KEYS = frozenset({"jairo15"})

TABLEAU = "https://us-east-1.online.tableau.com"
# The view our Lucys already read for DD by rep (override_bulletin.pulls
# DD_DETAIL_VIEW). `.csv` on a view URL is Tableau's own data download --
# no crosstab dialog to drive, which is a lot of browser not shipped here.
#
# BUT ON A DASHBOARD IT RETURNS THE FIRST SHEET, not the table: Jairo's Mac
# got DDDETAILORG.csv back as one column, 'ICD.Full Name' (2026-10-29 13:14).
# So the sheets themselves are tried by their URL names too, ORG first (what
# our Lucys read), then the owner's own ICD cut; the first that carries
# week + total wins, and if none does the line says what each one had.
_DD_BASE = TABLEAU + "/t/sci/views/DirectDepositICDVIEWVersion2_0/"
DD_CSVS = ("DDDETAIL", "DDDETAILORG")   # ORGDDDetail/ICDddDetail: 404

COL_OWNER = ("cl.ICD Owner Name", "ICD Owner Name")
COL_WEEK = ("cl.DD Week", "DD Week")
# DDDETAIL.csv (the owner's own ICD cut) names the rep 'cl.ICD Rep Name' and
# is line by line, one row per order (Jairo's Mac, 2026-10-29 14:34).
COL_REP = ("REP.Name", "Rep Name", "REP Name", "Rep", "cl.ICD Rep Name",
           "ICD Rep Name")
COL_TOTAL = ("Total $ to ICD", "cl.Total $ to ICD", "SUM(Total $ to ICD)")
# Failing an exact name, the first column that reads like the ICD's money.
_TOTAL_HINTS = ("to icd", "total $", "dd amount", "amount")
NO_REP = "(no rep)"

# Office hours only: a browser on somebody's screen at 3am gets Lucy removed.
HOURS = (9, 20)
RETRY_HOURS = 6        # a failed check tries again after this, not every tick

_STATE = C.APP_DIR / "pnl.json"


# --- the arithmetic (tested; no browser) -------------------------------------
def _norm(s) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", str(s or "").lower())).strip()


def _num(s) -> float:
    t = str(s or "").strip().replace("$", "").replace(",", "")
    neg = t.startswith("(") and t.endswith(")")
    try:
        v = float(t.strip("()") or 0)
    except ValueError:
        return 0.0
    return -v if neg else v


def _week(s) -> Optional[dt.date]:
    t = str(s or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return dt.datetime.strptime(t.split(" ")[0], fmt).date()
        except ValueError:
            continue
    return None


def _col(hdr: List[str], names) -> Optional[int]:
    clean = [str(h or "").strip().lower() for h in hdr]
    for n in names:
        if n.lower() in clean:
            return clean.index(n.lower())
    return None


def rep_name(raw) -> str:
    """'Jane Doe (12345)' -> 'Jane Doe'. Tableau carries the rep id."""
    return re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", str(raw or "")).strip()


def dd_by_rep(text: str, owner: str) -> Tuple[Dict[dt.date, Dict[str, float]], Dict]:
    """{DD week: {rep: Total $ to ICD}} for one owner, and what the file had.

    Rows with no rep (Captain Bonus and the like) sum under '(no rep)' -- the
    office's money, not anybody's pay."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    seen = {"rows": max(len(rows) - 1, 0), "columns": rows[0] if rows else [],
            "owners": 0}
    if not rows:
        return {}, seen
    hdr = rows[0]
    oc, wc, tc = _col(hdr, COL_OWNER), _col(hdr, COL_WEEK), _col(hdr, COL_TOTAL)
    # LONG FORMAT. DDDETAIL.csv has no money column at all: one row per
    # order PER MEASURE, 'Measure Names' saying which and 'Measure Values'
    # how much (Jairo's Mac, 2026-10-29 15:39). Keep only the ICD-total rows.
    mc, measure = _col(hdr, ("Measure Names",)), None
    if tc is None and mc is not None and _col(hdr, ("Measure Values",)) is not None:
        names = sorted({str(r[mc]).strip() for r in rows[1:] if len(r) > mc})
        seen["measures"] = names
        low = {n.lower(): n for n in names}
        measure = next((low[n.lower()] for n in COL_TOTAL if n.lower() in low), None)
        if measure is None:
            measure = next((n for hint in _TOTAL_HINTS for n in names
                            if hint in n.lower()), None)
        tc = _col(hdr, ("Measure Values",)) if measure else None
    if tc is None and mc is None:
        low = [str(h or "").strip().lower() for h in hdr]
        tc = next((i for hint in _TOTAL_HINTS for i, h in enumerate(low)
                   if hint in h), None)
    seen["total_col"] = measure or (hdr[tc] if tc is not None else "")
    rc = _col(hdr, COL_REP)
    seen["missing"] = [n for n, c in (("owner", oc), ("week", wc), ("total", tc),
                                      ("rep", rc)) if c is None]
    if None in (wc, tc):
        return {}, seen
    want = _norm(owner)
    owners = set()
    out: Dict[dt.date, Dict[str, float]] = {}
    for r in rows[1:]:
        if len(r) <= max(c for c in (oc, wc, tc, rc, mc) if c is not None):
            continue
        if measure and str(r[mc]).strip() != measure:
            continue
        if oc is not None:
            owners.add(_norm(r[oc]))
            if _norm(r[oc]) != want:
                continue
        wk = _week(r[wc])
        if wk is None:
            continue
        rep = (rep_name(r[rc]) if rc is not None else "") or NO_REP
        day = out.setdefault(wk, {})
        day[rep] = day.get(rep, 0.0) + _num(r[tc])
    seen["owners"] = len(owners)
    return out, seen


def check_line(weeks: Dict[dt.date, Dict[str, float]], seen: Dict) -> str:
    """One line for the Faults tab: enough to compare with what our Lucys see
    (WE 10/18 = 46 reps + no-rep, $86,838.91 for Jairo)."""
    if seen.get("missing"):
        if seen.get("measures"):
            return ("DD file has no money measure (measures: %s)"
                    % " | ".join(seen["measures"])[:400])
        return ("DD file has no %s column (columns: %s)"
                % ("/".join(seen["missing"]), " | ".join(seen["columns"])[:300]))
    if not weeks:
        return ("DD file read (%d rows, %d owners) but none for this owner"
                % (seen["rows"], seen["owners"]))
    parts = []
    for wk in sorted(weeks, reverse=True)[:3]:
        reps = weeks[wk]
        parts.append("WE %s: %d reps $%s" % (wk.isoformat(), len(reps),
                                             format(sum(reps.values()), ",.2f")))
    line = "DD OK (%d rows, %d owners in file, money from %r) -- %s" % (
        seen["rows"], seen["owners"], seen.get("total_col", ""), "; ".join(parts))
    if seen.get("measures"):
        line += " (measures: %s)" % " | ".join(seen["measures"])[:200]
    return line


# --- the browser half (proven on the owner's Mac, not here) ------------------
def fetch_dd_csvs(page) -> List[Tuple[str, str]]:
    """Tableau's CSV of the DD view, through this computer's OwnerVille login.

    Same two hops our Lucys use: OwnerVille's rqst token, then its p=81 'Login
    to Tableau' link, after which the context holds a Tableau session and the
    view's .csv comes back with the page's own cookies. Returns
    [(name, body or 'ERROR ...')] for every candidate in DD_CSVS."""
    from automations.shared import ownerville_knocks as K

    rqst = K.capture_rqst(page)
    if not rqst:
        raise RuntimeError("OwnerVille is not signed in on this computer")
    try:
        page.goto("%s?p=81&rqst=%s&ssook=1" % (K.V2_URL, rqst),
                  wait_until="domcontentloaded", timeout=90_000)
    except Exception:  # noqa: BLE001 -- the hop can land after its timeout
        pass
    page.wait_for_timeout(15_000)
    if "tableau.com" not in (page.url or "").lower():
        raise RuntimeError("Tableau sign-in did not land (at %s)"
                           % (page.url or "")[:80])
    out = []
    for name in DD_CSVS:
        try:
            resp = page.request.get(_DD_BASE + name + ".csv", timeout=180_000)
            body = resp.text()
        except Exception as e:  # noqa: BLE001 -- one candidate, not all
            out.append((name, "ERROR %s" % type(e).__name__))
            continue
        if not resp.ok:
            out.append((name, "ERROR %s" % resp.status))
        elif body.lstrip().startswith("<"):
            out.append((name, "ERROR page not data"))
        else:
            out.append((name, body))
    return out


def _owner_name(rec: Dict) -> str:
    return str(rec.get("owner") or "").strip()


def check(rec: Dict, log=print) -> Tuple[bool, str, str]:
    """Read the DD once on this computer's OwnerVille browser. Returns
    (worked, one line, every candidate's full column list)."""
    ok, line, cols, _ = read_dd(rec, log=log)
    return ok, line, cols


def read_dd(rec: Dict, log=print):
    """check(), plus the weeks themselves: (ok, line, cols, {week: {rep: $}})."""
    from patchright.sync_api import sync_playwright
    from automations.icd_alerts import ov_read

    with sync_playwright() as p:
        try:
            ctx = ov_read._context(p, True)
        except Exception as e:  # noqa: BLE001 -- profile busy: knocks running
            return False, "busy (%s)" % type(e).__name__, "", {}
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            found = fetch_dd_csvs(page)
        except Exception as e:  # noqa: BLE001
            return (False, "DD read failed: %s: %s"
                    % (type(e).__name__, str(e)[:240]), "", {})
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
    tried, cols = [], []
    for name, text in found:
        if text.startswith("ERROR"):
            tried.append("%s: %s" % (name, text[6:]))
            continue
        weeks, seen = dd_by_rep(text, _owner_name(rec))
        cols.append("%s: %s" % (name, " | ".join(seen["columns"])))
        if weeks:
            return (True, "%s %s" % (name, check_line(weeks, seen)),
                    "\n".join(cols), weeks)
        tried.append("%s: %s" % (name, check_line(weeks, seen)))
    return False, " || ".join(tried), "\n".join(cols), {}


# --- Apex: what each rep got paid (NEVER leaves this computer) --------------
# The export is Carlos's (carlos_payroll_pull, shipped whole): same Payroll
# Entry, same Export button, in Lucy's own Apex profile (apex_signin). It is
# saved under PNL_DIR on this Mac and nowhere else. What the relay hears is
# the pay period, how many people, and which DD reps were or were not found
# by name -- never an amount.
PNL_DIR = C.APP_DIR / "pnl"
APEX_SECTIONS = ("Sales Reps", "Contractors")
APEX_RETRY_MINUTES = 60   # signed out: ask again hourly, not every tick


def apex_pay(text: str):
    """((start, end), {name: gross pay}) for the Sales Reps and Contractors
    sections of an Apex export."""
    per, sec, hdr, out = None, None, None, {}
    for line in text.lstrip("﻿").splitlines():
        t = line.strip()
        if t.startswith("Pay Period,"):
            try:
                a, b = t.split(",", 1)[1].split(" - ")
                per = tuple(dt.datetime.strptime(x.strip().strip('"'),
                                                 "%m/%d/%Y").date()
                            for x in (a, b))
            except ValueError:
                pass
        elif t in ("Owner", "Office Admins", "Sales Reps", "Contractors"):
            sec, hdr = t, None
        elif t.startswith("Total,") or t.startswith("Company Total"):
            sec, hdr = None, None
        elif sec and hdr is None and t.startswith("First Name"):
            hdr = next(csv.reader([t]))
        elif sec in APEX_SECTIONS and hdr and t:
            d = dict(zip(hdr, next(csv.reader([t]))))
            name = ("%s %s" % ((d.get("First Name") or "").strip(),
                               (d.get("Last Name") or "").strip())).strip()
            if name:
                out[name.title()] = out.get(name.title(), 0.0) + _num(
                    d.get("Gross Pay"))
    return per, out


def _first_last(name: str) -> str:
    w = _norm(name).split()
    return "%s %s" % (w[0], w[-1]) if len(w) > 1 else " ".join(w)


def match_reps(dd_reps, apex_names) -> Tuple[List[str], List[str], List[str]]:
    """(matched DD reps, DD reps not in Apex, Apex people not in the DD).
    Full name first, then first + last (Tableau keeps middle names)."""
    full = {_norm(n): n for n in apex_names}
    fl = {_first_last(n): n for n in apex_names}
    used, hit, miss = set(), [], []
    for r in sorted(dd_reps):
        if r == NO_REP:
            continue
        a = full.get(_norm(r)) or fl.get(_first_last(r))
        if a:
            hit.append(r)
            used.add(a)
        else:
            miss.append(r)
    return hit, miss, sorted(set(apex_names) - used)


def apex_line(per, pay: Dict[str, float], weeks) -> str:
    """Counts and names only -- no money (the payroll stays on this Mac)."""
    span = ("%s-%s" % (per[0].strftime("%m/%d"), per[1].strftime("%m/%d"))
            if per else "?")
    line = "Apex OK: period %s, %d people paid" % (span, len(pay))
    dd = weeks.get(per[1]) if (per and weeks) else None
    if dd is None and weeks:
        line += "; no DD week ending %s (DD has %s)" % (
            per[1] if per else "?",
            ", ".join(w.isoformat() for w in sorted(weeks, reverse=True)[:3]))
    elif dd is not None:
        hit, miss, extra = match_reps(dd, pay)
        line += "; DD WE %s reps found in Apex %d/%d" % (
            per[1].isoformat(), len(hit), len(hit) + len(miss))
        if miss:
            line += "; DD not in Apex: %s" % ", ".join(miss)[:300]
        if extra:
            line += "; Apex not in DD: %s" % ", ".join(extra)[:300]
    return line


def read_apex(log=print):
    """Export the newest finished pay period in Lucy's Apex profile.
    ('ok', path) / ('signed out', None) / ('busy ...', None) / ('failed ...', None)."""
    from patchright.sync_api import sync_playwright
    from automations.carlos_payroll_pull import run as AP
    from automations.icd_alerts import apex_signin as AS

    if AS.signin_open():
        return "busy (sign-in window open)", None
    if not AS.APEX_PROFILE_DIR.exists():
        return "signed out", None
    PNL_DIR.mkdir(parents=True, exist_ok=True)
    AP.OUT_DIR = PNL_DIR            # Carlos's default is his own Mac's folder
    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                str(AS.APEX_PROFILE_DIR), headless=True, args=["--disable-sync"])
        except Exception as e:  # noqa: BLE001 -- profile held
            return "busy (%s)" % type(e).__name__, None
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                AP.goto_payroll_entry(page)
            except SystemExit:      # its "session expired" -- the login form
                return "signed out", None
            today = dt.date.today()
            done = [pp for pp in AP.list_periods(page) if pp[2] < today]
            if not done:
                return "failed: no finished pay period in the list", None
            idx, _, end = done[0]
            return "ok", AP.export_period(page, idx, end)
        except Exception as e:  # noqa: BLE001
            return "failed: %s: %s" % (type(e).__name__, str(e)[:200]), None
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


# --- when -------------------------------------------------------------------
def _load() -> Dict:
    try:
        return json.loads(_STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save(s: Dict) -> None:
    try:
        C.app_dir()
        _STATE.write_text(json.dumps(s), encoding="utf-8")
    except Exception:  # noqa: BLE001 -- only costs another check
        pass


def wanted(rec: Dict) -> bool:
    return str(rec.get("office_key") or "").strip().lower() in PNL_KEYS


def check_due(state: Dict, now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    if not (HOURS[0] <= now.hour < HOURS[1]):
        return False
    if state.get("dd_ok_v4"):
        return False
    return (time.time() - float(state.get("dd_tried_v4") or 0)) >= RETRY_HOURS * 3600


def apex_due(state: Dict, now: Optional[dt.datetime] = None) -> bool:
    """Apex after the DD is proven; hourly while it is not signed in (each
    try may put the sign-in window up, so never faster than that)."""
    now = now or dt.datetime.now()
    if not (HOURS[0] <= now.hour < HOURS[1]):
        return False
    if not state.get("dd_ok_v4") or state.get("apex_ok_v1"):
        return False
    return (time.time() - float(state.get("apex_tried_v1") or 0)
            ) >= APEX_RETRY_MINUTES * 60


def run_apex_check(log=print) -> int:
    """Export the newest pay period, match it to the DD by name, and file
    what was found as `probe-pnl-apex` -- counts and names, never money."""
    from automations.icd_alerts import relay as R

    state = _load()
    filed = 0
    for rec in C.active_enrollments():
        if not wanted(rec):
            continue
        status, path = read_apex(log=log)
        if status.startswith("busy"):
            log("pnl: %s apex %s" % (rec["office_key"], status))
            continue
        state["apex_tried_v1"] = time.time()
        if status == "signed out":
            from automations.icd_alerts import autoprompt as AU
            shown = AU.offer("apex", log=log)
            line = ("Apex not signed in on this computer yet (sign-in window %s)"
                    % ("opened" if shown else "not opened: nobody at the Mac"))
        elif status != "ok":
            line = "Apex " + status
        else:
            per, pay = apex_pay(path.read_text(encoding="utf-8-sig",
                                               errors="replace"))
            _, _, _, weeks = read_dd(rec, log=log)
            line = apex_line(per, pay, weeks)
            # Done only once the names were matched too: a DD read that lost
            # the browser to knocks tries again within the hour.
            if pay and weeks:
                state["apex_ok_v1"] = dt.date.today().isoformat()
        log("pnl: %s %s" % (rec["office_key"], line))
        R.report_fault("probe-pnl-apex", "%s: %s" % (_owner_name(rec), line),
                       office_key=rec["office_key"], log=log)
        filed += 1
    _save(state)
    return filed


def run_check(log=print) -> int:
    from automations.icd_alerts import relay as R

    state = _load()
    filed = 0
    for rec in C.active_enrollments():
        if not wanted(rec):
            continue
        ok, line, cols = check(rec, log=log)
        log("pnl: %s %s" % (rec["office_key"], line))
        if line.startswith("busy"):
            continue                       # knocks had the browser; next tick
        state["dd_tried_v4"] = time.time()
        if ok:
            state["dd_ok_v4"] = dt.date.today().isoformat()
        R.report_fault("probe-pnl-dd", "%s: %s" % (_owner_name(rec), line),
                       detail=cols, office_key=rec["office_key"], log=log)
        filed += 1
    _save(state)
    return filed


def maybe_run(log=print) -> bool:
    """Called from every agent tick. Free unless this office asked for a PNL
    and the check is owed."""
    if os.environ.get("LUCY_NO_PNL"):
        return False
    if not any(wanted(r) for r in C.active_enrollments()):
        return False
    state = _load()
    if check_due(state):
        run_check(log=log)
        return True
    if apex_due(state):
        run_apex_check(log=log)
        return True
    return False


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="run the DD check now")
    ap.add_argument("--apex", action="store_true",
                    help="run the Apex check now")
    a = ap.parse_args(argv)
    if a.check:
        print("filed %d check(s)" % run_check())
        return 0
    if a.apex:
        print("filed %d check(s)" % run_apex_check())
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
