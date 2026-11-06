"""Read THIS machine's Verizon Optix account and count today's knocks, per rep.

Optix is to a Verizon office what OwnerVille is to an AT&T one: every door a
rep marks lands there. The screen (mapped 2026-11-06 on Nico Murrugarra's
account, High Value Acquisitions):

    optixtogo.verizon.com -> pick the profile -> Dashboard -> SMART LEADS
    -> Lead Details  (lead-list-index.html#!/leaddetailsVCM)
    filters: Vendor / Credico / <office> / All Agents / Opportunities,
             Disposition Date From-To  -> Apply

ONE ROW PER HOUSE, NOT PER KNOCK. Each row carries the agent, the house's
LATEST disposition and `totalDisposition` = how many times it was
dispositioned inside the date range (the header's "682 dispositions from 1229
unique leads" is exactly the sum). A house with totalDisposition 0 is
assigned but untouched that day and is NOT a door knocked.

ALL ROWS ARE ALREADY IN THE PAGE. The grid shows 100 a page, but the Angular
scope holds every row (`summaryList`, 1,229 on 11/5) -- one read, no paging.

ROWS CARRY STREET ADDRESSES. Nothing here sends one: tally() reduces to
counts per rep before anything leaves the machine.

TWO HALVES, as box_read: tally() is arithmetic and tested; read_day() drives a
browser and is proven by the first real run on the office's machine.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List, Optional

from automations.icd_alerts import config as C

BASE = "https://optixtogo.verizon.com"
PROFILE_URL = BASE + "/SimplexMS/web/ContainerUI/Modules/MultiProfile/MultiProfile.html"

# Board columns, in board order. Every Optix disposition seen on 11/5 lands in
# exactly one bucket; anything new goes to "Other" AND is named in `unknown`
# so it gets ruled on instead of silently vanishing.
BUCKETS = ["No Answer", "Not Home", "No Interest", "Declined", "Stop Back",
           "Appointment", "Sale Started", "Sale", "Canceled", "No Access",
           "Existing Customer", "Other"]
TALK_TO = {"No Interest", "Declined", "Stop Back", "Appointment",
           "Sale Started", "Sale", "Canceled", "Existing Customer"}
_RULES = [  # (regex on the disposition text, bucket) -- first match wins
    (r"^no answer", "No Answer"),
    (r"not home", "Not Home"),
    (r"^no interest", "No Interest"),
    (r"^declined", "Declined"),
    (r"^stop back", "Stop Back"),
    (r"^appointment", "Appointment"),
    (r"sale started", "Sale Started"),
    (r"^sale made", "Sale"),          # "Sale Made - Wireless", "... - 281630024"
    (r"^sale cancel", "Canceled"),
    (r"no access|gated|do not solicit|house for sale|vacant", "No Access"),
    (r"^existing customer", "Existing Customer"),
]


class AccountProblem(RuntimeError):
    """Something the office can fix, phrased for the office."""


class SignInNeeded(AccountProblem):
    """The Verizon SSO session is gone; a person has to sign in at the Mac."""


class SignInInProgress(RuntimeError):
    """Somebody is signing in at the keyboard right now -- not a fault."""


def bucket(disposition: str) -> Optional[str]:
    d = (disposition or "").strip().lower()
    if not d:
        return None
    for rx, name in _RULES:
        if re.search(rx, d):
            return name
    return "Other"


def _rep(name: str) -> str:
    # Optix pads with spaces and fuses compound surnames ("Thais   Alvarezaragon").
    return re.sub(r"\s+", " ", name or "").strip() or "(unassigned)"


def tally(rows: List[Dict]) -> Dict:
    """Per-rep counts from Lead Details rows. Addresses never leave here.

    Returns {"reps": {rep: {"Doors", "Knocks", "Talk To", <bucket>: n}},
             "totals": {...same keys...}, "unknown": [disposition, ...]}
    """
    reps: Dict[str, Dict[str, int]] = {}
    unknown: List[str] = []
    for r in rows:
        knocks = int(float(r.get("totalDisposition") or 0))
        latest = r.get("latestDisposition") or ""
        if knocks <= 0 and not latest:
            continue                      # assigned, never touched
        rec = reps.setdefault(_rep(r.get("agent")),
                              {k: 0 for k in ["Doors", "Knocks", "Talk To", *BUCKETS]})
        rec["Doors"] += 1
        rec["Knocks"] += max(knocks, 1)
        b = bucket(latest)
        if b:
            rec[b] += 1
            if b in TALK_TO:
                rec["Talk To"] += 1
            if b == "Other" and latest not in unknown:
                unknown.append(latest)
    totals = {k: sum(v[k] for v in reps.values())
              for k in ["Doors", "Knocks", "Talk To", *BUCKETS]}
    return {"reps": reps, "totals": totals, "unknown": unknown}


def signin_in_progress() -> bool:
    try:
        held = dt.datetime.fromisoformat(C.OPTIX_SIGNIN_LOCK.read_text().strip())
    except (OSError, ValueError):
        return False
    return dt.datetime.now() - held < dt.timedelta(minutes=C.OPTIX_SIGNIN_LOCK_MINUTES)


def _context(p, headless: bool):
    """The Optix profile. NEVER rotated: it IS the Verizon SSO session."""
    C.OPTIX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(C.OPTIX_PROFILE_DIR), headless=headless, args=["--disable-sync"])


# Runs in the Lead Details page once Apply has loaded: the whole result set
# from the Angular scope, reduced to the four fields tally() needs (no
# addresses cross into Python either).
_SCOPE_JS = """() => {
  const tr = [...document.querySelectorAll('tr')].find(t => t.querySelector('td'));
  if (!tr || !window.angular) return null;
  let s = angular.element(tr).scope();
  while (s && !s.summaryList) s = s.$parent;
  if (!s) return null;
  return s.summaryList.map(x => ({agent: x.agent, latestDisposition: x.latestDisposition,
    latestDispositionDate: x.latestDispositionDate, totalDisposition: x.totalDisposition}));
}"""


def read_day(day: Optional[dt.date] = None, *, headless: bool = True, log=print) -> Dict:
    """Today's knocks per rep. UNPROVEN NAVIGATION until the first run on the
    office's machine -- every step below is the click path mapped by hand on
    2026-11-06, and each failure names the step it died on."""
    from patchright.sync_api import sync_playwright

    day = day or C.today()
    if signin_in_progress():
        log("somebody is signing in to Optix at the machine — leaving it alone this tick")
        raise SignInInProgress("an Optix sign-in is happening at the machine")
    when = day.strftime("%m/%d/%Y")
    with sync_playwright() as p:
        ctx = _context(p, headless)
        try:
            page = ctx.new_page()
            page.goto(PROFILE_URL, timeout=60000)
            page.wait_for_timeout(3000)
            if "login" in page.url.lower() or "sso" in page.url.lower():
                raise SignInNeeded(
                    "Verizon Optix has signed this computer out, so knocks cannot be "
                    "read until somebody signs in again. Nothing is lost.")
            # profile page -> Dashboard
            page.get_by_text("Dashboard", exact=False).first.click()
            page.wait_for_timeout(6000)
            # rep dashboard -> SMART LEADS (opens its own tab)
            with ctx.expect_page(timeout=30000) as new:
                page.get_by_text("SMART", exact=False).first.click()
            leads = new.value
            leads.wait_for_load_state("domcontentloaded")
            leads.wait_for_timeout(4000)
            leads.get_by_text("Lead Details", exact=True).first.click()
            leads.wait_for_timeout(4000)
            dates = leads.locator("input[placeholder='MM/DD/YYYY']")
            if dates.count() < 2:
                raise AccountProblem("Optix Lead Details: the Disposition Date boxes "
                                     "were not found — the screen has changed")
            for i in (0, 1):
                dates.nth(i).fill(when)
                leads.keyboard.press("Escape")
            leads.get_by_role("button", name="Apply").click()
            leads.wait_for_function("() => /unique leads/.test(document.body.innerText)",
                                    timeout=90000)
            rows = leads.evaluate(_SCOPE_JS)
            if rows is None:
                raise AccountProblem("Optix Lead Details loaded but its rows could not "
                                     "be read — the page has changed")
            header = re.search(r"(\d+) dispositions from (\d+) unique leads",
                               leads.inner_text("body"))
        finally:
            ctx.close()

    out = tally(rows)
    out["day"] = day.isoformat()
    # PROOF, NOT TRUST: the page states its own total; a mismatch is a read
    # problem, never a quiet board.
    if header and int(header.group(1)) != out["totals"]["Knocks"]:
        log("Optix says %s dispositions, counted %d — check before posting"
            % (header.group(1), out["totals"]["Knocks"]))
        out["mismatch"] = {"page": int(header.group(1)), "counted": out["totals"]["Knocks"]}
    log("optix: %d rep(s), %d doors, %d knocks, %d sale(s)"
        % (len(out["reps"]), out["totals"]["Doors"], out["totals"]["Knocks"], out["totals"]["Sale"]))
    if out["unknown"]:
        log("dispositions nobody has ruled on: %s" % ", ".join(out["unknown"]))
    return out
