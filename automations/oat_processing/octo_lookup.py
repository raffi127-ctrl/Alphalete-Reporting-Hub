"""Indeed's own phone number for every applicant the walk could not read one
for -- looked up through Octo Browser, once a day at 5am, ON THE OFFICE'S OWN
COMPUTER, and handed straight to that computer's next walk.

WHY. "No phone" on the noon/4pm to-do list only ever meant the RESUME had no
number. Every Indeed applicant still has one: on employers.indeed.com ->
Candidates -> the person -> under the name sit "Set up interview / Message /
Call", and Call opens a pop-up with the number. Carlos, 2026-11-16, after a
day of a person doing that by hand for thirty-six people: "automate this
through the relay machine so that ... Octo Browser gets opened up and it
looks for applicants' phone numbers for the ones that we don't have ... it
knows who doesn't have a phone number, so it should have a list ... Let's
just do it at 5 in the morning."

WHY HERE AND NOT ON A LUCY. The office computer holds no Google access, so a
number found anywhere else has to travel through the relay (phone_lookups.py,
a road that still waits on a relay redeploy). Found ON the office computer,
the number goes into output/phone-lookups.csv, which the walk on that same
computer already reads (phone_lookups.load) -- nothing travels, nothing is
redeployed. Octo Browser profiles live in Octo's cloud, so the same profiles
(the office's Indeed accounts, each with its own proxy and its login) open on
whichever computer is signed in to Octo.

WHAT IT DOES, 5:00 AM LOCAL, ONCE A DAY (the agent's tick kicks it: maybe_kick):
  1. who: the newest flagged snapshot the walk left (output/oat-flagged-*.json,
     <= 3 days old), its "nophone" bucket -- name + the Indeed account each
     applied through -- minus anyone already looked up this week.
  2. where: each account's Octo profile (octo_profiles.json, by the account's
     domain; a machine may override in ~/.config/lucy-reports/octo-profiles.json).
  3. how: Octo's local API starts the profile with a debug port, Playwright
     attaches, the Candidates list is opened ONCE, each name is typed into
     the page's own search box, the match is opened, Call is clicked, the
     number is read off the pop-up, Escape. One account at a time; the
     profile is stopped as soon as its names are done.
  4. out: output/phone-lookups.csv (merged; rows older than a week drop off).
     The 5:30 walk types the number in and clicks Send to AI -- the same send,
     the same rules, nobody removed. A quiet relay row (probe-octo-lookup)
     says who was found and who was not; Octo missing or every account walled
     is a loud fault the office sees.

WHAT IT NEVER DOES. It never clicks a "Verify you are human" box: a walled
account waits up to four minutes for the wall to pass on its own (they do),
then is skipped until tomorrow. It never downloads a resume, never places a
call (the Call pop-up only SHOWS the number), never writes a number into the
repo (output/ is ignored), never texts, never removes anyone.

OFF SWITCH. OAT_OCTO_LOOKUP=0 in the agent's environment.

    python -m automations.oat_processing.octo_lookup --office 11580 --wanted   # who would be looked up
    python -m automations.oat_processing.octo_lookup --office 11580 --dry      # look up, write nothing
    python -m automations.oat_processing.octo_lookup --office 11580            # the real thing, by hand
    python -m automations.oat_processing.octo_lookup --office 11580 \
        --names "Edgar Hendricks, Dexiaun Westbrook" --account hr@titanium-tx.com
"""
from __future__ import annotations  # the office machines run Python 3.9

import argparse
import csv
import datetime as dt
import glob
import json
import os
import platform
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# --- knobs --------------------------------------------------------------------
API_PORT = int(os.environ.get("OCTO_API_PORT", "58888"))
# The first agent tick at or after 5:00 local runs it; a machine that was off
# at five and wakes after seven waits for tomorrow (people use these accounts
# in the day, and a profile open on two computers is a mess).
RUN_START = (5, 0)
RUN_UNTIL = (7, 0)
LOCK_STALE_MINUTES = 60
RUN_BUDGET_MIN = 45             # the whole run, all accounts
ACCOUNT_BUDGET_MIN = 12         # one account's names
WALL_WAIT_S = 240               # a wall that has not passed by then: skip the account
PAUSE_S = 8                     # between names; ~25 fast loads trips Cloudflare
SNAPSHOT_MAX_AGE_DAYS = 3       # an older flagged list is history, not a to-do list
ROW_MAX_AGE_DAYS = 7            # a looked-up row older than this drops off the CSV
OCTO_START_TRIES = 3
OCTO_APP_WAIT_S = 120

LIST_URL = "https://employers.indeed.com/candidates?statusName=All&id=0&tab=manage"
WALL = ("Additional Verification Required", "Verify you are human")
CSV_NAME = "phone-lookups.csv"          # == phone_lookups.MANUAL_CSV, the walk's own road
CSV_HEAD = ["name", "phone", "account_email", "indeed_name", "office_id", "found_at", "source"]
SOURCE = "octo-lookup"
STAGE_QUIET = "probe-octo-lookup"       # the daily tally, read off the ICD Faults tab
STAGE_LOUD = "octo-lookup"              # a person has to do something

US_PHONE = re.compile(r"(?:\+?1[\s.\-]?)?\(?\b(\d{3})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})\b")
ANY_PHONE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")


def _log(msg: str) -> None:
    print("%s  %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg), flush=True)


# --- paths --------------------------------------------------------------------
def _root() -> Path:
    # Repo-root anchored, like the walk's own files: the office push and a
    # hand-run start from different working directories.
    return Path(__file__).resolve().parents[2]


def _out_dir() -> Path:
    return _root() / "output"


def _app_dir() -> Path:
    try:
        from automations.icd_alerts import config as C
        return Path(C.APP_DIR)
    except Exception:  # noqa: BLE001 -- a box without the agent's config
        return Path.home() / ".config" / "lucy-reports"


def _state_path() -> Path:
    return _app_dir() / "octo-lookup.json"


def _lock_path() -> Path:
    return _app_dir() / "octo-lookup.lock"


def _log_path() -> Path:
    return _app_dir() / "octo-lookup.log"


def csv_path() -> Path:
    return _out_dir() / CSV_NAME


# --- names and accounts -------------------------------------------------------
def fold(name) -> str:
    """phone_lookups.fold, retyped so this file ships with no sibling import
    at the top: lower-case, accents and punctuation off, single spaces."""
    t = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower())
    return " ".join(t.split())


def domain(account) -> str:
    """'team@x.com' and 'x.com' both give 'x.com'; a display name gives ''."""
    a = str(account or "").strip().lower()
    a = a.split("@", 1)[1].strip() if "@" in a else a
    if not a or "." not in a or " " in a:
        return ""
    return a


def _squash(s) -> str:
    return fold(s).replace(" ", "")


# --- profiles -----------------------------------------------------------------
def _shipped_profiles() -> Dict:
    p = Path(__file__).resolve().parent / "octo_profiles.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _local_profiles() -> Dict:
    p = _app_dir() / "octo-profiles.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- none is the normal case
        return {}


def profiles(office_id) -> List[Dict]:
    """The Octo profiles that hold this office's Indeed accounts: the shipped
    map, with a local file's entries on top (same title = override)."""
    oid = str(office_id or "")
    out: Dict[str, Dict] = {}
    for src in (_shipped_profiles(), _local_profiles()):
        block = src.get(oid) if isinstance(src, dict) else None
        for pr in (block or {}).get("profiles") or []:
            if isinstance(pr, dict) and pr.get("title") and pr.get("uuid"):
                out[_squash(pr["title"])] = {
                    "title": str(pr["title"]).strip(),
                    "uuid": str(pr["uuid"]).strip(),
                    "domains": [domain(d) for d in (pr.get("domains") or []) if domain(d)],
                }
    return list(out.values())


def offices_with_profiles() -> List[str]:
    ids = set()
    for src in (_shipped_profiles(), _local_profiles()):
        for k, v in (src.items() if isinstance(src, dict) else []):
            if not k.startswith("_") and isinstance(v, dict) and v.get("profiles"):
                ids.add(str(k))
    return sorted(ids)


def profile_for(account, office_id=None, profs: Optional[List[Dict]] = None) -> Optional[Dict]:
    """The profile for an account's domain: listed under the profile first;
    else the profile whose title reads like the domain ('riotspecializedmarketing.com'
    -> 'Riot Specialized Marketing'). None = nobody knows this account."""
    profs = profiles(office_id) if profs is None else profs
    dom = domain(account)
    if not dom:
        return None
    for pr in profs:
        if dom in pr.get("domains", []):
            return pr
    stem = _squash(dom.rsplit(".", 1)[0])
    if len(stem) < 6:
        return None
    for pr in profs:
        t = _squash(pr["title"])
        if t == stem or (len(t) >= 6 and (t.startswith(stem) or stem.startswith(t))):
            return pr
    return None


# --- who needs a number -------------------------------------------------------
def snapshot_path(office_id, today: Optional[dt.date] = None) -> Optional[Path]:
    """The newest flagged snapshot the walk left for this office, <= 3 days
    old: output/oat-flagged-<date>.json, or -<date>-<office>.json on a machine
    that walks several offices (the suffixed one wins for a date)."""
    today = today or dt.date.today()
    oid = str(office_id or "")
    best: Optional[Tuple[dt.date, int, Path]] = None
    for p in glob.glob(str(_out_dir() / "oat-flagged-*.json")):
        m = re.search(r"oat-flagged-(\d{4}-\d{2}-\d{2})(-(\d+))?\.json$", p)
        if not m:
            continue
        suffix_oid = m.group(3) or ""
        if suffix_oid and suffix_oid != oid:
            continue
        try:
            d = dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if (today - d).days > SNAPSHOT_MAX_AGE_DAYS or d > today:
            continue
        key = (d, 1 if suffix_oid else 0, Path(p))
        if best is None or key[:2] > best[:2]:
            best = key
    return best[2] if best else None


def wanted(office_id, today: Optional[dt.date] = None,
           csv_rows: Optional[List[Dict]] = None) -> Tuple[List[Dict], Dict]:
    """[{name, account, domain}] to look up, and how the list was made.
    The snapshot's nophone bucket, one entry per (name, account), minus
    anyone with a row in the CSV from this week (found, or found and left
    for a person -- either way it was looked up)."""
    today = today or dt.date.today()
    info: Dict = {"snapshot": None, "listed": 0, "skipped_recent": 0, "unreadable": 0}
    p = snapshot_path(office_id, today)
    if p is None:
        return [], info
    try:
        snap = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        info["snapshot"] = "%s (unreadable)" % p.name
        return [], info
    info["snapshot"] = p.name
    info["snapshot_at"] = "%s %s" % (snap.get("date") or "", snap.get("at") or "")
    recent = set()
    for r in (csv_rows if csv_rows is not None else read_csv(csv_path())):
        if _row_age_days(r, today) <= ROW_MAX_AGE_DAYS:
            recent.add((fold(r.get("name")), domain(r.get("account_email") or r.get("account"))))
    out, seen = [], set()
    for it in snap.get("nophone") or []:
        if isinstance(it, dict):
            nm, acct = str(it.get("name") or "").strip(), str(it.get("account") or "").strip()
        else:
            nm, acct = str(it or "").strip(), ""
        if not nm:
            continue
        if "@" in nm:
            info["unreadable"] += 1
            continue
        key = (fold(nm), domain(acct))
        if key in seen:
            continue
        seen.add(key)
        info["listed"] += 1
        if key in recent:
            info["skipped_recent"] += 1
            continue
        out.append({"name": nm, "account": acct, "domain": domain(acct)})
    return out, info


# --- the CSV the walk reads ---------------------------------------------------
def read_csv(path) -> List[Dict]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            return [dict(r) for r in csv.DictReader(fh)]
    except Exception:  # noqa: BLE001 -- no file yet
        return []


def _row_age_days(row: Dict, today: dt.date) -> int:
    """Days since the row was found; a row with no date (typed by hand)
    counts as today's."""
    s = str(row.get("found_at") or "").strip()
    try:
        return (today - dt.date.fromisoformat(s[:10])).days
    except ValueError:
        return 0


def merge_rows(existing: List[Dict], found: List[Dict], today: Optional[dt.date] = None) -> List[Dict]:
    """Yesterday's rows that are still this week's, with today's finds on top
    (same name + account replaces). Never drops a row typed by hand this week."""
    today = today or dt.date.today()
    keep: Dict[Tuple[str, str], Dict] = {}
    for r in existing:
        if not str(r.get("name") or "").strip() or not str(r.get("phone") or "").strip():
            continue
        if _row_age_days(r, today) > ROW_MAX_AGE_DAYS:
            continue
        row = {k: str(r.get(k) or "") for k in CSV_HEAD}
        keep[(fold(row["name"]), domain(row["account_email"]))] = row
    for f in found:
        if not f.get("phone"):
            continue
        row = {"name": f["name"], "phone": f["phone"],
               "account_email": f.get("domain") or domain(f.get("account")),
               "indeed_name": f.get("shown_as") or "",
               "office_id": str(f.get("office_id") or ""),
               "found_at": today.isoformat(), "source": SOURCE}
        keep[(fold(row["name"]), domain(row["account_email"]))] = row
    return list(keep.values())


def write_csv(path, rows: List[Dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_HEAD, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_HEAD})
    os.replace(tmp, path)


# --- the number off the pop-up ------------------------------------------------
def parse_phone(text) -> str:
    """'XXX-XXX-XXXX' for a US number; the raw string for anything else that
    reads like a number (+52 ..., left for a person); '' for none."""
    t = str(text or "")
    m = US_PHONE.search(t)
    if m:
        return "%s-%s-%s" % m.groups()
    m = ANY_PHONE.search(t)
    if m and len(re.sub(r"\D", "", m.group(0))) >= 8:
        return " ".join(m.group(0).split())
    return ""


# --- Octo Browser's local API -------------------------------------------------
def _api(path: str, payload: Optional[Dict] = None, timeout: int = 30):
    url = "http://127.0.0.1:%d/api/profiles/%s" % (API_PORT, path)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw[:300]}


def octo_answers() -> bool:
    try:
        return isinstance(_api("active", timeout=5), list)
    except Exception:  # noqa: BLE001
        return False


def octo_active() -> List[Dict]:
    try:
        got = _api("active", timeout=10)
        return got if isinstance(got, list) else []
    except Exception:  # noqa: BLE001
        return []


def octo_start(uuid: str, log=_log) -> Optional[str]:
    """The profile's debug endpoint, started here. None after OCTO_START_TRIES."""
    for i in range(OCTO_START_TRIES):
        try:
            d = _api("start", {"uuid": uuid, "headless": False, "debug_port": True,
                               "timeout": 120}, timeout=150)
        except Exception as e:  # noqa: BLE001
            d = {"error": type(e).__name__}
        ws = (d or {}).get("ws_endpoint") if isinstance(d, dict) else None
        if ws:
            return ws
        log("    octo start try %d: %s" % (i + 1, json.dumps(d)[:160]))
        time.sleep(20)
    return None


def octo_stop(uuid: str) -> None:
    try:
        _api("stop", {"uuid": uuid}, timeout=60)
    except Exception:  # noqa: BLE001
        pass


def octo_app_path() -> Optional[str]:
    if IS_MAC:
        for app in ("/Applications/Octo Browser.app",
                    str(Path.home() / "Applications" / "Octo Browser.app")):
            if Path(app).exists():
                return app
        return None
    if IS_WINDOWS:
        for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"),
                     os.environ.get("ProgramFiles(x86)")):
            if not base:
                continue
            for rel in (("Programs", "Octo Browser", "Octo Browser.exe"),
                        ("Octo Browser", "Octo Browser.exe")):
                exe = Path(base).joinpath(*rel)
                if exe.exists():
                    return str(exe)
        return None
    return None


def ensure_octo(log=_log) -> Tuple[bool, str, bool]:
    """(the API answers, why not, launched by us). Opens Octo Browser when it
    is installed and not running; it has to be signed in already -- a
    password is never typed here."""
    if octo_answers():
        return True, "", False
    app = octo_app_path()
    if not app:
        return False, "Octo Browser is not installed on this computer", False
    try:
        if IS_MAC:
            subprocess.Popen(["open", "-a", app], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen([app], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    except Exception as e:  # noqa: BLE001
        return False, "Octo Browser would not open (%s)" % type(e).__name__, False
    log("opened Octo Browser; waiting for its local API on port %d" % API_PORT)
    deadline = time.time() + OCTO_APP_WAIT_S
    while time.time() < deadline:
        time.sleep(5)
        if octo_answers():
            return True, "", True
    return False, ("Octo Browser opened but its local API on port %d never answered "
                   "-- is it signed in?" % API_PORT), True


def quit_octo(log=_log) -> None:
    try:
        if IS_MAC:
            subprocess.run(["osascript", "-e", 'tell application "Octo Browser" to quit'],
                           timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif IS_WINDOWS:
            subprocess.run(["taskkill", "/IM", "Octo Browser.exe", "/F"], timeout=30,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("closed Octo Browser (it was not open before this run)")
    except Exception:  # noqa: BLE001
        pass


# --- the Indeed page ----------------------------------------------------------
def _sync_playwright():
    try:
        from patchright.sync_api import sync_playwright  # the office machines
    except ImportError:
        from playwright.sync_api import sync_playwright  # a laptop
    return sync_playwright


def body_text(page) -> str:
    try:
        return page.evaluate("() => document.body ? document.body.innerText : ''") or ""
    except Exception:  # noqa: BLE001
        return ""


def walled(page) -> bool:
    try:
        title = page.title() or ""
    except Exception:  # noqa: BLE001
        title = ""
    t = body_text(page)
    return ("Just a moment" in title) or any(w in t for w in WALL)


def dialog_text(page) -> str:
    try:
        return page.evaluate(
            "() => [...document.querySelectorAll('[role=dialog],[aria-modal=true],"
            "[role=menu],[role=tooltip]')].map(e => e.innerText).join('\\n---\\n')") or ""
    except Exception:  # noqa: BLE001
        return ""


def find_search(page):
    for sel in ('input[type="search"]', 'input[placeholder*="earch"]', 'input[aria-label*="earch"]'):
        loc = page.locator(sel)
        if loc.count():
            return loc.first
    return None


def wait_clear(page, log=_log, max_s: int = WALL_WAIT_S) -> bool:
    """Wait for a verify wall to pass BY ITSELF (they do, in minutes). Polls;
    one reload halfway. Never clicks anything on it."""
    if not walled(page):
        return True
    log("    verify wall is showing -- waiting up to %d s for it to pass (never clicked)" % max_s)
    deadline = time.time() + max_s
    reloaded = False
    while time.time() < deadline:
        time.sleep(20)
        if not walled(page) and len(body_text(page)) > 200:
            log("    wall passed")
            return True
        if not reloaded and time.time() > deadline - max_s / 2:
            reloaded = True
            try:
                page.reload(wait_until="domcontentloaded", timeout=60000)
            except Exception:  # noqa: BLE001
                pass
    return not walled(page)


def _type_search(page, box, name: str) -> None:
    try:
        box.click()
        box.fill("")
        box.fill(name)
    except Exception:  # noqa: BLE001 -- not a plain input: select-all and type
        box.click()
        page.keyboard.press("Control+A" if IS_WINDOWS else "Meta+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(name, delay=40)
    page.keyboard.press("Enter")


def _pick_candidate(page, name: str):
    """(locator, shown text) for the list row that is this person, or (None,
    names shown). Exact first; else first and last token both present
    ('Genesis Lee-Chin' vs 'Genesis Lee Chin')."""
    cands = page.locator('a[data-testid="NameCell"]')
    toks = [t for t in re.split(r"[\s\-]+", name.lower()) if t]
    shown = []
    for i in range(min(cands.count(), 40)):
        try:
            txt = (cands.nth(i).inner_text() or "").strip()
        except Exception:  # noqa: BLE001
            continue
        shown.append(txt[:40])
        low = txt.lower()
        if low == name.lower() or (toks and toks[0] in low and toks[-1] in low):
            return cands.nth(i), txt[:60]
    return None, shown


def lookup_names(ws: str, items: List[Dict], log=_log,
                 deadline: Optional[float] = None) -> List[Dict]:
    """One account: Playwright on the profile's debug endpoint, the Candidates
    list once, then per name: search box -> the row -> Call -> the pop-up.
    Returns one result per item: status in found / not_in_account /
    not_in_list / no_call_button / popup_no_number / walled / out_of_time /
    error."""
    results: List[Dict] = []
    deadline = deadline or (time.time() + ACCOUNT_BUDGET_MIN * 60)
    sync_playwright = _sync_playwright()
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(ws, timeout=60000)
        ctx = browser.contexts[0]
        pages = [pg for pg in ctx.pages if "employers.indeed.com/candidates" in pg.url]
        page = pages[-1] if pages else ctx.new_page()
        if not pages:
            try:
                page.set_viewport_size({"width": 1400, "height": 1000})
            except Exception:  # noqa: BLE001
                pass
            page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(8)
        try:
            page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        stopped = ""
        for it in items:
            name = it["name"]
            rec = dict(it)
            rec.update({"status": "", "phone": "", "shown_as": "", "url": ""})
            if stopped:
                rec["status"] = stopped
                results.append(rec)
                continue
            if time.time() > deadline:
                rec["status"] = stopped = "out_of_time"
                results.append(rec)
                continue
            try:
                if "candidates/view" in page.url:
                    page.go_back()
                    time.sleep(4)
                if page.locator('a[data-testid="NameCell"]').count() == 0 and "candidates?" not in page.url:
                    page.goto(LIST_URL, wait_until="domcontentloaded", timeout=60000)
                    time.sleep(8)
                if not wait_clear(page, log):
                    rec["status"] = stopped = "walled"
                    results.append(rec)
                    continue
                box = find_search(page)
                if box is not None:
                    _type_search(page, box, name)
                else:
                    # The compact layout (Revolt) has no search box: the
                    # list's own search link does the same.
                    q = urllib.request.quote(name)
                    page.goto("%s&q=%s&candidateName=%s" % (LIST_URL, q, q),
                              wait_until="domcontentloaded", timeout=60000)
                time.sleep(7)
                if not wait_clear(page, log):
                    rec["status"] = stopped = "walled"
                    results.append(rec)
                    continue
                body = body_text(page)
                if "Showing 1-0" in body or "0 of 0" in body or "No candidates" in body:
                    rec["status"] = "not_in_account"
                    results.append(rec)
                    log("    %-28s not in this account" % name)
                    time.sleep(PAUSE_S)
                    continue
                picked, shown = _pick_candidate(page, name)
                if picked is None:
                    rec["status"] = "not_in_list"
                    rec["shown"] = shown[:12]
                    results.append(rec)
                    log("    %-28s not in the list (shown: %s)" % (name, ", ".join(shown[:6])))
                    time.sleep(PAUSE_S)
                    continue
                rec["shown_as"] = shown
                picked.click()
                time.sleep(6)
                rec["url"] = page.url
                call = page.get_by_role("button", name=re.compile(r"^\s*call\s*$", re.I))
                end = time.time() + 30
                while time.time() < end and call.count() == 0:
                    time.sleep(2)
                if call.count() == 0:
                    call = page.get_by_text(re.compile(r"^\s*call\s*$", re.I))
                if call.count() == 0:
                    rec["status"] = "no_call_button"
                    results.append(rec)
                    log("    %-28s no Call button on the candidate page" % name)
                    time.sleep(PAUSE_S)
                    continue
                call.first.scroll_into_view_if_needed()
                time.sleep(1)
                call.first.click()
                time.sleep(4)
                pop = dialog_text(page)
                if not pop.strip():
                    time.sleep(3)
                    pop = dialog_text(page)
                phone = parse_phone(pop)
                if phone:
                    rec["phone"] = phone
                    rec["status"] = "found"
                    log("    %-28s number read off the Call pop-up" % name)
                else:
                    rec["status"] = "popup_no_number"
                    rec["popup"] = pop[:200]
                    log("    %-28s Call pop-up opened, no number on it" % name)
                page.keyboard.press("Escape")
                time.sleep(2)
                if page.locator("[role=dialog],[aria-modal=true]").count():
                    page.keyboard.press("Escape")
                    time.sleep(1)
            except Exception as e:  # noqa: BLE001 -- one name, not the account
                rec["status"] = "error"
                rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
                log("    %-28s error: %s" % (name, rec["error"][:120]))
                try:
                    page.keyboard.press("Escape")
                except Exception:  # noqa: BLE001
                    pass
            results.append(rec)
            time.sleep(PAUSE_S)
    return results


# --- one run ------------------------------------------------------------------
def _write_lock() -> None:
    try:
        _app_dir().mkdir(parents=True, exist_ok=True)
        _lock_path().write_text(str(time.time()))
    except OSError:
        pass


def _clear_lock() -> None:
    try:
        _lock_path().unlink()
    except OSError:
        pass


def _lock_held(now: Optional[float] = None) -> bool:
    """By age, never by pid (resume_push's rule: os.kill on Windows ENDS it)."""
    try:
        started = float(_lock_path().read_text().strip() or 0)
    except (OSError, ValueError):
        return False
    return ((now or time.time()) - started) < LOCK_STALE_MINUTES * 60


def _state() -> Dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_state(st: Dict) -> None:
    try:
        _app_dir().mkdir(parents=True, exist_ok=True)
        _state_path().write_text(json.dumps(st, indent=2))
    except OSError:
        pass


def _push_office_key(office_id: str) -> str:
    """The relay enrollment that pushes this office here, or '' (a laptop)."""
    try:
        from automations.icd_alerts import resume_push as RP
        rec = RP.push_record() or {}
        if str(office_id) in RP.office_ids(rec):
            return str(rec.get("office_key") or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _report(office_id: str, summary: Dict, loud: str = "", log=_log) -> None:
    """The tally as a quiet relay row; a loud fault when a person has to act.
    Names and statuses only -- no number ever rides a relay row."""
    key = _push_office_key(office_id)
    if not key:
        log("no relay enrollment for office %s here -- tally not filed" % office_id)
        return
    try:
        from automations.icd_alerts import relay as R
        body = {k: summary.get(k) for k in ("office", "date", "at", "snapshot", "listed",
                                            "skipped_recent", "found", "missing",
                                            "accounts", "csv_rows", "elapsed_min")}
        R.report_fault(STAGE_QUIET, "octo lookup %s: %d found, %d not"
                       % (office_id, len(summary.get("found") or []),
                          len(summary.get("missing") or [])),
                       json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                       office_key=key)
        if loud:
            R.report_fault(STAGE_LOUD, loud, json.dumps(body, ensure_ascii=False)[:1500],
                           office_key=key)
    except Exception as e:  # noqa: BLE001 -- the telling, never the work
        log("could not file the tally: %s" % type(e).__name__)


def run(office_id, *, names: Optional[List[str]] = None, account: str = "",
        only: Optional[List[str]] = None, dry: bool = False, scheduled: bool = False,
        log=_log) -> Dict:
    office_id = str(office_id)
    t0 = time.time()
    today = dt.date.today()
    summary: Dict = {"office": office_id, "date": today.isoformat(),
                     "at": dt.datetime.now().strftime("%H:%M"), "found": [], "missing": [],
                     "accounts": {}, "csv_rows": None, "dry": dry}
    _write_lock()
    launched = False
    try:
        if names:
            items = [{"name": n.strip(), "account": account, "domain": domain(account)}
                     for n in names if n.strip()]
            info = {"snapshot": "(names given)", "listed": len(items), "skipped_recent": 0}
        else:
            items, info = wanted(office_id, today)
        summary.update({k: info.get(k) for k in ("snapshot", "snapshot_at", "listed", "skipped_recent")})
        log("[octo] office %s: %d to look up (%s; %d listed, %d looked up this week already)"
            % (office_id, len(items), info.get("snapshot") or "no flagged snapshot <= %d days"
               % SNAPSHOT_MAX_AGE_DAYS, info.get("listed") or 0, info.get("skipped_recent") or 0))
        if not items:
            summary["result"] = "nothing to look up"
            if scheduled:
                _report(office_id, summary, log=log)
            return summary

        profs = profiles(office_id)
        groups: Dict[str, List[Dict]] = {}
        by_title: Dict[str, Dict] = {}
        for it in items:
            pr = profile_for(it["account"], office_id, profs)
            if pr is None:
                it["status"] = "no_profile"
                summary["missing"].append([it["name"], it["domain"], "no Octo profile for this account"])
                log("    %-28s no Octo profile known for %r" % (it["name"], it["domain"] or it["account"]))
                continue
            if only and not any(_squash(o) in _squash(pr["title"]) for o in only):
                continue
            groups.setdefault(pr["title"], []).append(it)
            by_title[pr["title"]] = pr
        if not groups:
            summary["result"] = "no account to open"
            if scheduled:
                _report(office_id, summary, log=log)
            return summary

        ok, why, launched = ensure_octo(log)
        if not ok:
            log("[octo] %s" % why)
            summary["result"] = why
            for title, its in groups.items():
                summary["accounts"][title] = "octo not available"
                for it in its:
                    summary["missing"].append([it["name"], it["domain"], "octo not available"])
            if scheduled:
                _report(office_id, summary,
                        loud=("%s, so the 5am phone lookups did not run. Install Octo Browser "
                              "on the office computer and sign it in once; the lookups find it "
                              "on their own the next morning." % why), log=log)
            return summary

        run_deadline = t0 + RUN_BUDGET_MIN * 60
        found_rows: List[Dict] = []
        walled_accounts = 0
        for title, its in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            pr = by_title[title]
            if time.time() > run_deadline:
                summary["accounts"][title] = "out of time"
                for it in its:
                    summary["missing"].append([it["name"], it["domain"], "out_of_time"])
                continue
            log("[octo] %s: %d name(s)" % (title, len(its)))
            cur = next((a for a in octo_active() if a.get("uuid") == pr["uuid"]), None)
            ws = cur.get("ws_endpoint") if cur else None
            started_here = False
            if cur and not ws:
                summary["accounts"][title] = "in use (open without a debug port) -- left alone"
                log("    profile is open without a debug port (somebody's window) -- skipped")
                for it in its:
                    summary["missing"].append([it["name"], it["domain"], "account in use"])
                continue
            if not cur:
                ws = octo_start(pr["uuid"], log)
                started_here = ws is not None
                if ws:
                    time.sleep(12)
            if not ws:
                summary["accounts"][title] = "could not start"
                for it in its:
                    summary["missing"].append([it["name"], it["domain"], "profile would not start"])
                continue
            results: List[Dict] = []
            for attempt in range(2):
                try:
                    results = lookup_names(ws, its, log,
                                           deadline=min(run_deadline,
                                                        time.time() + ACCOUNT_BUDGET_MIN * 60))
                    break
                except Exception as e:  # noqa: BLE001
                    msg = "%s: %s" % (type(e).__name__, str(e)[:160])
                    log("    attach failed (%s)" % msg[:120])
                    if attempt == 0 and started_here:
                        # The debug link hung: bounce the profile once.
                        octo_stop(pr["uuid"])
                        time.sleep(8)
                        ws = octo_start(pr["uuid"], log) or ws
                        time.sleep(15)
                        continue
                    results = [dict(it, status="error", error=msg) for it in its]
            if started_here:
                octo_stop(pr["uuid"])
                time.sleep(4)
            n_found = 0
            for r in results:
                r["office_id"] = office_id
                if r.get("status") == "found":
                    n_found += 1
                    found_rows.append(r)
                    summary["found"].append([r["name"], r.get("domain", "")])
                else:
                    summary["missing"].append([r["name"], r.get("domain", ""), r.get("status") or "?"])
            if results and all(r.get("status") == "walled" for r in results):
                walled_accounts += 1
            summary["accounts"][title] = "%d of %d found" % (n_found, len(its))
            log("[octo] %s: %d of %d found" % (title, n_found, len(its)))

        if dry:
            summary["csv_rows"] = None
            log("[octo] DRY: %d number(s) read, nothing written" % len(found_rows))
        else:
            rows = merge_rows(read_csv(csv_path()), found_rows, today)
            write_csv(csv_path(), rows)
            summary["csv_rows"] = len(rows)
            log("[octo] output/%s: %d row(s) for the walk (%d new today)"
                % (CSV_NAME, len(rows), len(found_rows)))
        summary["elapsed_min"] = round((time.time() - t0) / 60, 1)
        summary["result"] = "%d found, %d not" % (len(summary["found"]), len(summary["missing"]))
        try:
            rp = _out_dir() / ("octo-lookup-%s.json" % today.isoformat())
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(json.dumps({"summary": summary, "results": found_rows},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        loud = ""
        if groups and walled_accounts == len(summary["accounts"]) and walled_accounts:
            loud = ("Every Indeed account hit a 'Verify you are human' box this morning, so "
                    "no phone number was read (the box is never clicked by Lucy). It usually "
                    "passes by itself; if it is still there tomorrow, open one of the accounts "
                    "in Octo Browser and click the box once.")
        if scheduled:
            _report(office_id, summary, loud=loud, log=log)
        return summary
    finally:
        if launched:
            quit_octo(log)
        _clear_lock()
        st = _state()
        st["last_end"] = dt.datetime.now().isoformat(timespec="seconds")
        st["last_result"] = summary.get("result") or "?"
        _save_state(st)


# --- the agent's tick ---------------------------------------------------------
def enabled() -> List[str]:
    """The offices this computer pushes for that have Octo profiles on file.
    [] on a laptop, on a Lucy, and on an office machine that is not in
    octo_profiles.json -- those do nothing at all."""
    if os.environ.get("OAT_OCTO_LOOKUP", "") == "0":
        return []
    try:
        from automations.icd_alerts import resume_push as RP
        rec = RP.push_record()
        if not rec:
            return []
        have = set(offices_with_profiles())
        return [o for o in RP.office_ids(rec) if o in have]
    except Exception:  # noqa: BLE001
        return []


def in_window(now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    return RUN_START <= (now.hour, now.minute) < RUN_UNTIL


def due(now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    if not in_window(now) or _lock_held(now.timestamp()):
        return False
    return _state().get("last_day") != now.date().isoformat()


def maybe_kick(log=print) -> bool:
    """Called from every agent tick. Once a day, in the 5am hour, starts the
    lookups in their OWN process and returns at once -- a run can take half
    an hour and must never hold up a sweep."""
    offices = enabled()
    if not offices or not due():
        return False
    st = _state()
    st["last_day"] = dt.date.today().isoformat()
    st["last_start"] = dt.datetime.now().isoformat(timespec="seconds")
    _save_state(st)                     # before the start: a crash must not retry every 2 min
    root = _root()
    kw = {"cwd": str(root), "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        kw["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                               | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200))
    else:
        kw["start_new_session"] = True  # out of the tick's process group (resume_push's lesson)
    try:
        _app_dir().mkdir(parents=True, exist_ok=True)
        out = open(_log_path(), "a")
        subprocess.Popen([sys.executable, "-m", "automations.oat_processing.octo_lookup",
                          "--scheduled", "--office"] + offices,
                         stdout=out, stderr=subprocess.STDOUT, **kw)
    except Exception as e:  # noqa: BLE001 -- never lose a sweep to this
        log("octo lookup could not start: %s" % type(e).__name__)
        return False
    log("octo phone lookups started in the background (office %s)" % ", ".join(offices))
    return True


# --- CLI ----------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--office", nargs="+", default=["11580"], help="AppStream office id(s)")
    ap.add_argument("--names", default="", help="comma-separated names instead of the flagged list")
    ap.add_argument("--account", default="", help="the Indeed account (email or domain) for --names")
    ap.add_argument("--accounts", default="", help="only these Octo profiles (comma-separated, by title)")
    ap.add_argument("--dry", action="store_true", help="look up, write nothing")
    ap.add_argument("--wanted", action="store_true", help="print who would be looked up and stop")
    ap.add_argument("--scheduled", action="store_true", help="what the 5am kick runs (files the tally)")
    args = ap.parse_args(argv)
    names = [n for n in args.names.split(",") if n.strip()] if args.names else None
    only = [o for o in args.accounts.split(",") if o.strip()] if args.accounts else None
    if names and not args.account:
        print("--names needs --account <email or domain>")
        return 2
    rc = 0
    for oid in args.office:
        if args.wanted:
            items, info = wanted(oid)
            print("office %s: %s" % (oid, json.dumps(info)))
            profs = profiles(oid)
            for it in items:
                pr = profile_for(it["account"], oid, profs)
                print("  %-30s %-36s -> %s" % (it["name"], it["domain"] or it["account"] or "(no account)",
                                               pr["title"] if pr else "NO PROFILE KNOWN"))
            continue
        s = run(oid, names=names, account=args.account, only=only, dry=args.dry,
                scheduled=args.scheduled)
        print(json.dumps({k: s.get(k) for k in ("office", "result", "accounts", "csv_rows",
                                                 "elapsed_min")}))
        if s.get("result", "").startswith("Octo Browser"):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
