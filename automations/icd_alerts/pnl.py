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
Faults tab, never posted -- see post.notify_faults), and stops. Apex and the
sheet come after that answer.

    python -m automations.icd_alerts.pnl --check      # run the check now
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
DD_CSV = TABLEAU + "/t/sci/views/DirectDepositICDVIEWVersion2_0/DDDETAILORG.csv"

COL_OWNER = ("cl.ICD Owner Name", "ICD Owner Name")
COL_WEEK = ("cl.DD Week", "DD Week")
COL_REP = ("REP.Name", "Rep Name", "REP Name", "Rep")
COL_TOTAL = ("Total $ to ICD",)
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
    rc = _col(hdr, COL_REP)
    seen["missing"] = [n for n, c in (("owner", oc), ("week", wc), ("total", tc),
                                      ("rep", rc)) if c is None]
    if None in (wc, tc):
        return {}, seen
    want = _norm(owner)
    owners = set()
    out: Dict[dt.date, Dict[str, float]] = {}
    for r in rows[1:]:
        if len(r) <= max(c for c in (oc, wc, tc, rc) if c is not None):
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
    return "DD OK (%d rows, %d owners in file) -- %s" % (
        seen["rows"], seen["owners"], "; ".join(parts))


# --- the browser half (proven on the owner's Mac, not here) ------------------
def fetch_dd_csv(page) -> str:
    """Tableau's CSV of the DD view, through this computer's OwnerVille login.

    Same two hops our Lucys use: OwnerVille's rqst token, then its p=81 'Login
    to Tableau' link, after which the context holds a Tableau session and the
    view's .csv comes back with the page's own cookies."""
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
    resp = page.request.get(DD_CSV, timeout=180_000)
    body = resp.text()
    if not resp.ok:
        raise RuntimeError("Tableau answered %s: %s" % (resp.status, body[:160]))
    if body.lstrip().startswith("<"):
        raise RuntimeError("Tableau sent a page, not data: %s"
                           % re.sub(r"\s+", " ", body)[:160])
    return body


def _owner_name(rec: Dict) -> str:
    return str(rec.get("owner") or "").strip()


def check(rec: Dict, log=print) -> Tuple[bool, str]:
    """Read the DD once on this computer's OwnerVille browser."""
    from patchright.sync_api import sync_playwright
    from automations.icd_alerts import ov_read

    with sync_playwright() as p:
        try:
            ctx = ov_read._context(p, True)
        except Exception as e:  # noqa: BLE001 -- profile busy: knocks running
            return False, "busy (%s)" % type(e).__name__
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            text = fetch_dd_csv(page)
        except Exception as e:  # noqa: BLE001
            return False, "DD read failed: %s: %s" % (type(e).__name__, str(e)[:240])
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass
    weeks, seen = dd_by_rep(text, _owner_name(rec))
    return bool(weeks), check_line(weeks, seen)


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
    if state.get("dd_ok"):
        return False
    return (time.time() - float(state.get("dd_tried") or 0)) >= RETRY_HOURS * 3600


def run_check(log=print) -> int:
    from automations.icd_alerts import relay as R

    state = _load()
    filed = 0
    for rec in C.active_enrollments():
        if not wanted(rec):
            continue
        ok, line = check(rec, log=log)
        log("pnl: %s %s" % (rec["office_key"], line))
        if line.startswith("busy"):
            continue                       # knocks had the browser; next tick
        state["dd_tried"] = time.time()
        if ok:
            state["dd_ok"] = dt.date.today().isoformat()
        R.report_fault("probe-pnl-dd", "%s: %s" % (_owner_name(rec), line),
                       office_key=rec["office_key"], log=log)
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
    if not check_due(_load()):
        return False
    run_check(log=log)
    return True


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="run the DD check now")
    a = ap.parse_args(argv)
    if a.check:
        print("filed %d check(s)" % run_check())
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
