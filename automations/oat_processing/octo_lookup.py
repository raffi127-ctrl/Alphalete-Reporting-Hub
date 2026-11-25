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

WHAT IT DOES, 5:00 AM LOCAL (the agent's tick kicks it: maybe_kick; a second,
billing-only pass runs at 1pm -- see SLOTS):
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

AND EVERY ACCOUNT'S BILLING, WHILE IT IS THERE (Carlos, the same evening: "can
we also add in launching all of the accounts and checking if there's a billing
issue with any of the accounts?"). After the lookups the run opens EVERY
profile on file, loads the All Jobs page, and scans it for a payment or
billing alert (the rules that read sixteen real pages clean on 11/16; the
"Add billing identifiers" banner is not one). An alert is a loud fault with
the alert's own words, routed to the office; a clean sweep is silent except
for the tally. The page's screenshot stays on the office computer
(output/octo-billing-<date>/<account>.png) -- the relay carries no pictures.
While the profile is open the run also reads the account's own Gmail tab for
Indeed's billing mail -- "Payment declined: Update your billing information"
and "We received your payment of $..." -- and puts their timestamps in the
tally (billing_mail), so the hold's real start and end travel with the check
(Carlos 2026-11-19: "it needs to somehow communicate when the ads go back
live"). Lucy 1 turns that into the 'Billing Holds' tab and a Slack note
(icd_alerts/billing_holds.py). A signed-out Gmail is reported as such; no
password is ever typed.

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
# TWO PASSES A DAY (Carlos 2026-11-16: "check for it, and actually do it twice
# a day"). The first agent tick inside a slot runs it; a machine that was off
# for the whole slot waits for the next one. 5am: the lookups, then every
# account's billing. 1pm: every account's billing only -- the lookups stay a
# once-a-day, before-the-first-walk thing. (name, start, until, with lookups)
SLOTS = (("am", (5, 0), (7, 0), True),
         ("pm", (13, 0), (15, 0), False))
LOCK_STALE_MINUTES = 60
RUN_BUDGET_MIN = 60             # the whole run: the lookups, then every account's billing
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
STAGE_BILLING = "octo-billing"          # an Indeed account shows a payment / billing alert

JOBS_URL = ("https://employers.indeed.com/jobs?status=open%2Cpaused&claimed=false"
            "&createdOnIndeed=true&tab=0&sortDirection=DESC")
BILLING_WAIT_S = 150                    # the All Jobs page, incl. a wall passing by itself
# The words a payment problem shows up in, on the All Jobs page (16 real
# pages read clean with these on 2026-11-16), and the everyday page furniture
# that uses the same words and means nothing.
BILLING_KEYS = re.compile(
    r"(payment (method|failed|declined|issue|problem|due)|past due|overdue|unpaid|declined|"
    r"suspended|on hold|account (is )?(paused|restricted|disabled)|billing (issue|problem|error|hold)|"
    r"outstanding balance|update your (payment|billing)|unable to (charge|process)|credit card|"
    r"card (on file|expired|declined)|invoice|balance due|paused access|we.ve paused|"
    r"verify your (identity|account)|action required)", re.I)
BILLING_IGNORE = ("billing identifiers", "view billing history", "update payment method",
                  "view performance report", "manage billing details", "export your billing reports")

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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # Octo answers a refusal (profile open on another computer, unknown
        # uuid, too many open) as an HTTP error WITH a body that says why.
        # The reason is the whole point of the log line.
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            raw = ""
        try:
            body = json.loads(raw)
        except ValueError:
            body = {"raw": raw[:300]}
        if isinstance(body, dict):
            body.setdefault("error", "HTTP %s" % e.code)
            body["http"] = e.code
            return body
        return {"error": "HTTP %s" % e.code, "http": e.code, "raw": str(body)[:300]}
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


_LAST_START: Dict = {}      # what Octo said the last time a start failed


def last_start_error() -> str:
    """The last refusal in words: 'in use on another computer' for Octo's
    profiles.already_started (the profile shows nowhere in THIS computer's
    active list, so it is open on another one), else Octo's own text."""
    d = _LAST_START or {}
    if d.get("code") == "profiles.already_started":
        return "in use on another computer"
    return str(d.get("error") or d.get("code") or d.get("raw") or "no answer")[:120]


def octo_start(uuid: str, log=_log) -> Optional[str]:
    """The profile's debug endpoint, started here. None after OCTO_START_TRIES
    (or at once on a refusal) -- last_start_error() then says why."""
    global _LAST_START
    _LAST_START = {}
    for i in range(OCTO_START_TRIES):
        try:
            d = _api("start", {"uuid": uuid, "headless": False, "debug_port": True,
                               "timeout": 120}, timeout=150)
        except Exception as e:  # noqa: BLE001
            d = {"error": type(e).__name__}
        ws = (d or {}).get("ws_endpoint") if isinstance(d, dict) else None
        if ws:
            return ws
        _LAST_START = d if isinstance(d, dict) else {"raw": str(d)[:200]}
        reason = json.dumps(d, ensure_ascii=False)[:200] if isinstance(d, dict) else str(d)[:200]
        log("    octo start try %d: %s" % (i + 1, reason))
        if isinstance(d, dict) and d.get("http") in (400, 401, 403, 404, 409):
            break           # a refusal, not a hiccup: another try says the same thing
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
            # -g DOES NOT RAISE IT, -j STARTS IT HIDDEN. This runs by itself
            # at 5am on somebody's office computer and nobody has to act, so
            # it must not take their screen (CLAUDE.md: ECO runs in the
            # background). Octo cannot run headless -- it exists to look like
            # a real browser to Indeed, and a headless one is the thing
            # Indeed walls -- so the answer is the resume_push answer: open
            # the real browser behind everything, and keep it there.
            subprocess.Popen(["open", "-g", "-j", "-a", app],
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Windows: started without a window of its own being shown.
            si = None
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 7          # SW_SHOWMINNOACTIVE
            except Exception:  # noqa: BLE001 -- not Windows after all
                si = None
            subprocess.Popen([app], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, startupinfo=si,
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


def _octo_pids():
    """Octo Browser's processes on this machine, for the focus guard."""
    try:
        out = subprocess.run(["pgrep", "-f", "Octo Browser"],
                             capture_output=True, text=True).stdout
        return [int(x) for x in out.split()]
    except Exception:  # noqa: BLE001
        return []


def _focus_guard(walled=None):
    """Keep Octo off the owner's screen for the whole run, or None.

    Octo CANNOT run headless for this job: it exists to look like a real
    browser to Indeed, and starting a profile opens a window that takes the
    front. The standing rule for exactly that case is resume_push's -- open
    the real browser behind everything and stop it taking focus -- so this
    borrows resume_push's guard rather than growing a second one.

    `walled` lets the guard STAND DOWN. When Indeed's "Verify you are human"
    box stops the run, a person has to click it, and a hidden window they
    cannot reach is worse than a visible one they can.
    """
    try:
        # IMPORTED AS A MODULE OFF THE PACKAGE, deliberately: test_octo_lookup
        # pins every `automations.*` import this file makes to
        # `automations.icd_alerts`, which is how it checks that nothing is
        # reached for that an office machine does not ship.
        from automations.icd_alerts import resume_push
        _FocusGuard = resume_push._FocusGuard
    except Exception:  # noqa: BLE001 -- not an ECO machine / no Mac helpers
        return None
    try:
        guard = _FocusGuard(pids=_octo_pids).start()
        guard.hold(stand_down=walled)
        return guard
    except Exception:  # noqa: BLE001
        # A guard that will not start must never stop the lookups: the run
        # still works, it is just visible, and that is a smaller fault than
        # no phone numbers.
        return None


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


# --- every account's billing --------------------------------------------------
def billing_hits(text) -> List[str]:
    """The lines of an All Jobs page that read like a payment or billing
    alert, each with the line before and after, at most eight. The page's
    own menu items (View billing history, Add billing identifiers ...) are
    not alerts."""
    lines = [l.strip() for l in str(text or "").splitlines() if l.strip()]
    out = []
    for i, l in enumerate(lines):
        low = l.lower()
        if BILLING_KEYS.search(l) and not any(ig in low for ig in BILLING_IGNORE):
            out.append(" | ".join(lines[max(0, i - 1): i + 2])[:240])
            if len(out) >= 8:
                break
    return out


MAIL_SEARCH = ('from:indeed (subject:"Payment declined" OR subject:"We received your payment" '
               'OR subject:"make your job visible" OR subject:"is live on Indeed") after:%s')
MAIL_ROWS_JS = """() => [...document.querySelectorAll('tr.zA')].map(tr => {
  const s = tr.querySelector('.bog'); const d = tr.querySelector('td.xW span');
  return {subject: s ? s.innerText : '', when: d ? (d.getAttribute('title') || d.innerText) : ''};
})"""
MAIL_WALL = ("Verify it\u2019s you", "Verify it's you", "Sign in", "Choose an account")


def _mail_when(text) -> Optional[str]:
    """Gmail's row title 'Wed, Nov 18, 2026, 7:05 PM' -> '2026-11-18 19:05'."""
    t = str(text or "").strip()
    for fmt in ("%a, %b %d, %Y, %I:%M %p", "%b %d, %Y, %I:%M %p"):
        try:
            return dt.datetime.strptime(t, fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    return None


def mail_times(rows: List[Dict]) -> Dict:
    """The newest decline, the newest payment received, and the newest
    'job visible / live' mail among Gmail search rows: {declined, paid,
    live} as 'YYYY-MM-DD HH:MM' (missing when none)."""
    out: Dict = {}
    for r in rows or []:
        subj = str(r.get("subject") or "").lower()
        when = _mail_when(r.get("when"))
        if not when:
            continue
        key = ("declined" if "payment declined" in subj else
               "paid" if "received your payment" in subj else
               "live" if ("is live on indeed" in subj or "make your job visible" in subj) else "")
        if key and (key not in out or when > out[key]):
            out[key] = when
    return out


def read_billing_mail(ctx, log=_log, days: int = 45) -> Dict:
    """The account's Gmail, as the profile holds it: a search for Indeed's
    billing mail, the timestamps read off the result rows (the title attribute
    carries the full date). Never signs in: a signed-out Gmail is
    {'signed_in': False}. Nothing is clicked inside Gmail."""
    rec: Dict = {"signed_in": None}
    try:
        page = next((pg for pg in ctx.pages if "mail.google.com" in pg.url), None)
        if page is None:
            page = ctx.new_page()
        since = (dt.date.today() - dt.timedelta(days=days)).strftime("%Y/%m/%d")
        q = urllib.request.quote(MAIL_SEARCH % since)
        page.goto("https://mail.google.com/mail/u/0/#search/" + q, wait_until="domcontentloaded", timeout=60000)
        time.sleep(9)
        t = body_text(page)
        if "mail.google.com" not in page.url or any(w in t[:600] for w in MAIL_WALL):
            rec["signed_in"] = False
            return rec
        rec["signed_in"] = True
        rows = page.evaluate(MAIL_ROWS_JS) or []
        rec.update(mail_times(rows))
        rec["rows"] = len(rows)
    except Exception as e:  # noqa: BLE001 -- the mail is extra; the page read is the check
        rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    return rec


def check_billing(ws: str, title: str, shot_dir: Optional[Path], log=_log) -> Dict:
    """One account's All Jobs page: status ok / problem / walled / error,
    the alert lines, and where its screenshot went. Read-only: nothing on
    the page is clicked, a wall is waited out and never touched."""
    rec: Dict = {"title": title, "status": "error", "hits": [], "shot": "", "error": "", "mail": {}}
    sync_playwright = _sync_playwright()
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(ws, timeout=60000)
            ctx = browser.contexts[0]
            page = ctx.new_page()
            try:
                page.set_viewport_size({"width": 1500, "height": 1000})
            except Exception:  # noqa: BLE001
                pass
            page.goto(JOBS_URL, wait_until="domcontentloaded", timeout=60000)
            t, is_walled, deadline, reloaded = "", True, time.time() + BILLING_WAIT_S, False
            while time.time() < deadline:
                time.sleep(8)
                if not reloaded and time.time() > deadline - BILLING_WAIT_S / 2:
                    reloaded = True
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=60000)
                    except Exception:  # noqa: BLE001
                        pass
                t = body_text(page)
                is_walled = walled(page)
                if not is_walled and len(t) > 300:
                    break
            time.sleep(5)
            t = body_text(page) or t
            if shot_dir is not None:
                try:
                    shot_dir.mkdir(parents=True, exist_ok=True)
                    shot = shot_dir / (re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_") + ".png")
                    try:
                        page.screenshot(path=str(shot), full_page=False, timeout=20000,
                                        animations="disabled")
                    except Exception:  # noqa: BLE001 -- fonts never settle: ask Chrome directly
                        import base64
                        cdp = ctx.new_cdp_session(page)
                        data = cdp.send("Page.captureScreenshot", {"format": "png"})["data"]
                        shot.write_bytes(base64.b64decode(data))
                    rec["shot"] = str(shot)
                except Exception as e:  # noqa: BLE001 -- the picture is a bonus
                    log("    %-28s no screenshot (%s)" % (title, type(e).__name__))
            if is_walled or len(t) <= 300:
                rec["status"] = "walled" if is_walled else "blank"
            else:
                rec["hits"] = billing_hits(t)
                rec["status"] = "problem" if rec["hits"] else "ok"
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
            rec["mail"] = read_billing_mail(ctx, log)
            m = rec["mail"]
            log("    %-28s mail: %s" % (title, "signed out" if m.get("signed_in") is False else
                                        (", ".join("%s %s" % (k, m[k]) for k in ("declined", "paid", "live") if m.get(k)) or "no billing mail")))
    except Exception as e:  # noqa: BLE001
        rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
    return rec


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


def _release() -> str:
    """The agent release this computer runs, or '?' (a laptop)."""
    try:
        from automations.icd_alerts import selfupdate as SU
        return str(SU.applied_release() or "?")
    except Exception:  # noqa: BLE001
        return "?"


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
        body = {k: summary.get(k) for k in ("office", "date", "at", "ran", "snapshot", "listed",
                                            "skipped_recent", "found", "missing",
                                            "accounts", "billing", "billing_problems",
                                            "billing_mail", "csv_rows", "elapsed_min")}
        R.report_fault(STAGE_QUIET, "octo lookup %s: %d found, %d not"
                       % (office_id, len(summary.get("found") or []),
                          len(summary.get("missing") or [])),
                       json.dumps(body, ensure_ascii=False, separators=(",", ":")),
                       office_key=key)
        if loud:
            R.report_fault(STAGE_LOUD, loud, json.dumps(body, ensure_ascii=False)[:1500],
                           office_key=key)
        for title, hit in summary.get("billing_problems") or []:
            R.report_fault(STAGE_BILLING,
                           "Indeed account %s shows a payment or billing alert on its All Jobs "
                           "page: \"%s\" -- open it in Octo Browser and fix the payment; its "
                           "jobs may be paused until then." % (title, hit[:200]),
                           json.dumps(body, ensure_ascii=False)[:1500], office_key=key)
    except Exception as e:  # noqa: BLE001 -- the telling, never the work
        log("could not file the tally: %s" % type(e).__name__)


def run(office_id, *, names: Optional[List[str]] = None, account: str = "",
        only: Optional[List[str]] = None, dry: bool = False, scheduled: bool = False,
        billing: bool = True, lookups: bool = True, log=_log) -> Dict:
    """The morning's work for one office: the lookups (accounts with a name
    to find first), then every account's All Jobs page for a billing alert.
    One profile at a time, started and stopped here."""
    office_id = str(office_id)
    t0 = time.time()
    today = dt.date.today()
    summary: Dict = {"office": office_id, "date": today.isoformat(),
                     "at": dt.datetime.now().strftime("%H:%M"), "found": [], "missing": [],
                     "accounts": {}, "billing": {}, "billing_problems": [], "billing_mail": {},
                     "csv_rows": None, "dry": dry,
                     # WHAT RAN THIS (2026-11-18): a 1pm row said "5 found" with no
                     # billing read, and nothing on the row could say which
                     # command, release or computer produced it.
                     "ran": {"argv": sys.argv[1:], "release": _release(),
                             "host": platform.node()[:40], "pid": os.getpid(),
                             "lookups": bool(lookups), "billing": bool(billing)}}
    _write_lock()
    launched = False
    guard = None        # set once Octo is up; stopped in the finally
    try:
        # WHO. The flagged list (or the names given), each with its account.
        items: List[Dict] = []
        info: Dict = {"snapshot": "(lookups off)", "listed": 0, "skipped_recent": 0}
        if lookups:
            if names:
                items = [{"name": n.strip(), "account": account, "domain": domain(account)}
                         for n in names if n.strip()]
                info = {"snapshot": "(names given)", "listed": len(items), "skipped_recent": 0}
            else:
                items, info = wanted(office_id, today)
        summary.update({k: info.get(k) for k in ("snapshot", "snapshot_at", "listed", "skipped_recent")})
        log("[octo] office %s: %d to look up (%s; %d listed, %d looked up this week already)%s"
            % (office_id, len(items), info.get("snapshot") or "no flagged snapshot <= %d days"
               % SNAPSHOT_MAX_AGE_DAYS, info.get("listed") or 0, info.get("skipped_recent") or 0,
               "; then every account's billing" if billing else ""))

        # WHERE. Names grouped under their profile; with billing on, every
        # other profile follows with no names.
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
            groups.setdefault(pr["title"], []).append(it)
            by_title[pr["title"]] = pr
        plan: List[Tuple[Dict, List[Dict]]] = [(by_title[t], its) for t, its in
                                               sorted(groups.items(), key=lambda kv: -len(kv[1]))]
        if billing:
            for pr in profs:
                if pr["title"] not in by_title:
                    plan.append((pr, []))
        if only:
            plan = [(pr, its) for pr, its in plan
                    if any(_squash(o) in _squash(pr["title"]) for o in only)]
        if not plan:
            summary["result"] = "nothing to do"
            if scheduled:
                _report(office_id, summary, log=log)
            return summary

        ok, why, launched = ensure_octo(log)
        if not ok:
            log("[octo] %s" % why)
            summary["result"] = why
            for pr, its in plan:
                summary["accounts"][pr["title"]] = "octo not available"
                for it in its:
                    summary["missing"].append([it["name"], it["domain"], "octo not available"])
            if scheduled:
                _report(office_id, summary,
                        loud=("%s, so the 5am phone lookups and the billing check did not run. "
                              "Install Octo Browser on the office computer and sign it in once; "
                              "the morning run finds it on its own." % why), log=log)
            return summary

        # OCTO IS UP, SO KEEP IT OFF THEIR SCREEN from here until the run
        # ends. Starting a profile opens a window that takes the front, and
        # this fires at 5am with nobody at the desk.
        guard = _focus_guard()

        run_deadline = t0 + RUN_BUDGET_MIN * 60
        found_rows: List[Dict] = []
        walled_accounts = 0
        restarted = False
        shot_dir = (_out_dir() / ("octo-billing-%s" % today.isoformat())) if billing else None
        for pr, its in plan:
            title = pr["title"]
            if time.time() > run_deadline:
                summary["accounts"][title] = "out of time"
                for it in its:
                    summary["missing"].append([it["name"], it["domain"], "out_of_time"])
                if billing:
                    summary["billing"][title] = "out of time"
                continue
            log("[octo] %s: %d name(s)%s" % (title, len(its), " + billing" if billing else ""))
            cur = next((a for a in octo_active() if a.get("uuid") == pr["uuid"]), None)
            ws = cur.get("ws_endpoint") if cur else None
            started_here = False
            if cur and not ws:
                summary["accounts"][title] = "in use (open without a debug port) -- left alone"
                log("    profile is open without a debug port (somebody's window) -- skipped")
                for it in its:
                    summary["missing"].append([it["name"], it["domain"], "account in use"])
                if billing:
                    summary["billing"][title] = "in use"
                continue
            if not cur:
                ws = octo_start(pr["uuid"], log)
                if ws is None and "restart application" in last_start_error().lower() and not restarted:
                    # 2026-11-24: Octo downloaded an update mid-run and from
                    # then on refused every profile with "Update is available.
                    # Please restart application." -- for three runs, until a
                    # person at the office quit and reopened it. Do that here,
                    # once per run: quit, reopen, try the profile again.
                    restarted = True
                    log("    Octo asks to be restarted for an update -- restarting it")
                    quit_octo(log)
                    time.sleep(8)
                    ok2, why2, _ = ensure_octo(log)
                    if ok2:
                        time.sleep(10)
                        ws = octo_start(pr["uuid"], log)
                    else:
                        log("    Octo did not come back: %s" % why2)
                started_here = ws is not None
                if ws:
                    time.sleep(12)
            if not ws:
                why = last_start_error()
                label = why if why == "in use on another computer" else "could not start (%s)" % why
                summary["accounts"][title] = label
                log("    %s" % label)
                for it in its:
                    summary["missing"].append([it["name"], it["domain"], label])
                if billing:
                    summary["billing"][title] = label
                continue
            # the names
            results: List[Dict] = []
            if its:
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
                            octo_stop(pr["uuid"])      # the debug link hung: bounce it once
                            time.sleep(8)
                            ws = octo_start(pr["uuid"], log) or ws
                            time.sleep(15)
                            continue
                        results = [dict(it, status="error", error=msg) for it in its]
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
            # the billing
            if billing and time.time() < run_deadline:
                b = check_billing(ws, title, shot_dir, log)
                if b.get("mail"):
                    summary["billing_mail"][title] = {k: v for k, v in b["mail"].items()
                                                      if k in ("declined", "paid", "live", "signed_in")}
                if b["status"] == "problem":
                    summary["billing"][title] = "PROBLEM: " + b["hits"][0]
                    summary["billing_problems"].append([title, b["hits"][0]])
                    log("[octo] %s: BILLING ALERT -- %s" % (title, b["hits"][0][:160]))
                elif b["status"] == "ok":
                    summary["billing"][title] = "ok"
                    log("[octo] %s: billing ok" % title)
                else:
                    summary["billing"][title] = b["status"] + (" (%s)" % b["error"][:80] if b.get("error") else "")
                    log("[octo] %s: billing not read (%s)" % (title, summary["billing"][title][:100]))
                if not its:
                    summary["accounts"][title] = "billing only"
            if started_here:
                octo_stop(pr["uuid"])
                time.sleep(4)

        if dry:
            summary["csv_rows"] = None
            log("[octo] DRY: %d number(s) read, nothing written" % len(found_rows))
        elif lookups:
            rows = merge_rows(read_csv(csv_path()), found_rows, today)
            write_csv(csv_path(), rows)
            summary["csv_rows"] = len(rows)
            log("[octo] output/%s: %d row(s) for the walk (%d new today)"
                % (CSV_NAME, len(rows), len(found_rows)))
        summary["elapsed_min"] = round((time.time() - t0) / 60, 1)
        checked = [t for t, v in summary["billing"].items() if v == "ok" or v.startswith("PROBLEM")]
        summary["result"] = "%d found, %d not; billing: %d account(s) read, %d alert(s)" % (
            len(summary["found"]), len(summary["missing"]), len(checked),
            len(summary["billing_problems"]))
        try:
            rp = _out_dir() / ("octo-lookup-%s.json" % today.isoformat())
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(json.dumps({"summary": summary, "results": found_rows},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
        loud = ""
        stuck = [t for t, v in summary["accounts"].items() if str(v).startswith("could not start")]
        if stuck and len(stuck) >= max(3, len(summary["accounts"]) - 3):
            # 2026-11-25: every profile answered "Update is available. Please
            # update" from Octo's local API, nothing opened, the quiet tally
            # said so seventeen times and nobody was told.
            why = str(summary["accounts"][stuck[0]])[len("could not start ("):].rstrip(")")[:140]
            loud = ("Octo Browser on the office computer would not open any account this morning "
                    "(%d of %d): \"%s\". Open Octo Browser there and apply the update it is asking "
                    "for; the lookups and the billing check pick up again on the next run."
                    % (len(stuck), len(summary["accounts"]), why))
        named = [pr["title"] for pr, _ in plan if groups.get(pr["title"])]
        if not loud and named and walled_accounts == len(named):
            loud = ("Every Indeed account with a name to look up hit a 'Verify you are human' box "
                    "this morning, so no phone number was read (the box is never clicked by Lucy). "
                    "It usually passes by itself; if it is still there tomorrow, open one of the "
                    "accounts in Octo Browser and click the box once.")
        if scheduled:
            _report(office_id, summary, loud=loud, log=log)
        return summary
    finally:
        if guard is not None:
            try:
                guard.stop()
            except Exception:  # noqa: BLE001
                pass
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


def slot_now(now: Optional[dt.datetime] = None) -> Optional[str]:
    """The slot this minute falls in ('am', 'pm'), or None."""
    now = now or dt.datetime.now()
    hm = (now.hour, now.minute)
    for name, start, until, _ in SLOTS:
        if start <= hm < until:
            return name
    return None


def in_window(now: Optional[dt.datetime] = None) -> bool:
    return slot_now(now) is not None


def slot_has_lookups(slot: str) -> bool:
    return any(name == slot and with_lookups for name, _, _, with_lookups in SLOTS)


def due(now: Optional[dt.datetime] = None) -> Optional[str]:
    """The slot to run now, or None: inside a slot, not run for that slot
    today, and no run holding the lock."""
    now = now or dt.datetime.now()
    slot = slot_now(now)
    if not slot or _lock_held(now.timestamp()):
        return None
    if _state().get("last_day_" + slot) == now.date().isoformat():
        return None
    return slot


def maybe_kick(log=print) -> bool:
    """Called from every agent tick. Once per slot per day starts the run in
    its OWN process and returns at once -- a run can take half an hour and
    must never hold up a sweep. The morning pass looks numbers up and reads
    every account's billing; the afternoon pass reads the billing only."""
    offices = enabled()
    if not offices:
        return False
    slot = due()
    if not slot:
        return False
    st = _state()
    st["last_day_" + slot] = dt.date.today().isoformat()
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
        argv = [sys.executable, "-m", "automations.oat_processing.octo_lookup", "--scheduled"]
        if not slot_has_lookups(slot):
            argv.append("--billing-only")
        subprocess.Popen(argv + ["--office"] + offices,
                         stdout=out, stderr=subprocess.STDOUT, **kw)
    except Exception as e:  # noqa: BLE001 -- never lose a sweep to this
        log("octo lookup could not start: %s" % type(e).__name__)
        return False
    log("octo %s started in the background (office %s)"
        % ("phone lookups + billing check" if slot_has_lookups(slot) else "billing check",
           ", ".join(offices)))
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
    ap.add_argument("--no-billing", action="store_true", help="the lookups only, skip the All Jobs pages")
    ap.add_argument("--billing-only", action="store_true", help="every account's All Jobs page, no lookups")
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
                scheduled=args.scheduled, billing=not args.no_billing,
                lookups=not args.billing_only)
        print(json.dumps({k: s.get(k) for k in ("office", "result", "accounts", "billing",
                                                 "billing_problems", "csv_rows", "elapsed_min")}))
        if s.get("result", "").startswith("Octo Browser"):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
