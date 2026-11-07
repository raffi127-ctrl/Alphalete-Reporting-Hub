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
            if _DNK.search(latest):
                rec["Do Not Knock"] = rec.get("Do Not Knock", 0) + 1
            if b in TALK_TO:
                rec["Talk To"] += 1
            if b == "Other" and latest not in unknown:
                unknown.append(latest)
    totals = {k: sum(v[k] for v in reps.values())
              for k in ["Doors", "Knocks", "Talk To", *BUCKETS]}
    return {"reps": reps, "totals": totals, "unknown": unknown}


# tally() bucket -> the knock board's column name (total_knocks.pull). Plain
# strings, because total_knocks is not shipped to office machines;
# test_optix_read pins them to the pull constants so they cannot drift.
BOARD_COLUMNS = {
    "Doors": "Total Leads Knocked", "Knocks": "Total Knocks",
    "No Answer": "No answer", "Not Home": "Not Home",
    "No Interest": "Not Interested", "Declined": "Not Interested",
    "Existing Customer": "Not Interested",
    "Stop Back": "Come Back", "Appointment": "Appointment",
    "Sale Started": "Sale Started", "Sale": "Sale", "Canceled": "Sale Canceled",
    "No Access": "Inaccessible", "Other": None,
}
# Do Not Solicit Sign is its own board column, not just "no access".
_DNK = re.compile(r"do not solicit", re.I)


def board_row(rep: str, counts: Dict[str, int]) -> Dict[str, object]:
    """One relayed row in the knock board's own column names."""
    # First/Last Knock and gaps are BLANK, not 0: Optix Lead Details carries no
    # times, and the board draws "no data" differently from "zero minutes".
    row: Dict[str, object] = {"Rep": rep, "Do Not Knock": counts.get("Do Not Knock", 0),
                              "First Knock": "", "Last Knock": "",
                              "Gaps": "", "Total Gaps (min)": ""}
    for bucket_name, col in BOARD_COLUMNS.items():
        if col:
            row[col] = int(row.get(col, 0) or 0) + int(counts.get(bucket_name, 0))
    row["Inaccessible"] = int(row["Inaccessible"]) - int(counts.get("Do Not Knock", 0))
    # TEXT, like an OwnerVille grid cell: the relay carries strings, and the
    # Hub (knocks_map.to_rows) parses only its count columns as numbers.
    return {k: (v if isinstance(v, str) else str(v)) for k, v in row.items()}


def signin_in_progress() -> bool:
    try:
        held = dt.datetime.fromisoformat(C.OPTIX_SIGNIN_LOCK.read_text().strip())
    except (OSError, ValueError):
        return False
    return dt.datetime.now() - held < dt.timedelta(minutes=C.OPTIX_SIGNIN_LOCK_MINUTES)


def _context(p, headless: bool):
    """The Optix profile. NEVER rotated: it IS the Verizon SSO session.

    ALWAYS A VISIBLE WINDOW, on the office's own ECO machine (Megan
    2026-11-06: "we need to not use a hidden browser and just pop it up on
    nico's eco machine"). Optix opens the way the owner opens it himself, on
    his own computer and his own login; `headless` is ignored on purpose."""
    C.OPTIX_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    # REAL GOOGLE CHROME, like every other Hub site that turns bundled
    # Chromium away (Tableau, Sheets: chrome_guard / tableau_patchright).
    # Megan 2026-11-06: "try again using a regular browser". The profile
    # signed in under bundled Chromium is NOT reused -- Chrome keeps its own
    # (OPTIX_PROFILE_DIR + "-chrome"), signed in once with optix_signin.
    prof = C.OPTIX_PROFILE_DIR.with_name(C.OPTIX_PROFILE_DIR.name + "-chrome")
    prof.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        str(prof), channel="chrome", headless=False, args=["--disable-sync"])


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
            # profile page -> Consumer tab -> Dashboard. Seen 2026-11-06 in
            # Lucy's window: it opens on the BUSINESS tab, whose profile list is
            # EMPTY; Nico's profile (NicMurCr0, Credico USA LLC - D2D) is under
            # CONSUMER. "Welcome {{ssoProfileName}}" never renders here, so it is
            # not a readiness signal -- the profile row is.
            page.wait_for_function("() => /Profile ID/.test(document.body.innerText)", timeout=60000)
            try:
                page.get_by_text("Consumer", exact=True).first.click()
            except Exception:  # noqa: BLE001 — some profiles have no tabs
                pass
            page.wait_for_function(
                "() => /Credico|D2D|Mobile Only/i.test(document.body.innerText)", timeout=60000)
            page.wait_for_timeout(1500)
            page.get_by_role("button", name="Dashboard").first.click()
            page.wait_for_url(lambda u: "MultiProfile" not in u, timeout=60000)
            page.wait_for_timeout(6000)
            # rep dashboard -> SMART LEADS (opens its own tab)
            with ctx.expect_page(timeout=30000) as new:
                page.get_by_text(re.compile(r"smart\s*leads", re.I)).first.click()
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
