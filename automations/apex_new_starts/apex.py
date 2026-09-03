"""Drive Apex (apex.herbjoyent.com) to add one new start, from a real session.

NO CREDENTIAL HANDLING, EVER. Like `apex_payroll`, this rides the Apex session
already signed in inside the operator's everyday Chrome: the profile is copied
to a private directory, Chrome is relaunched against the copy with a debug
port, and the cookies come along. If Apex shows a login page the run STOPS and
says so -- a human signs in once at that machine and clicks Run again. That is
the whole reason this report is push-a-button rather than scheduled.

WHY THE FIELDS ARE FOUND BY LABEL. Nobody had a logged-in Apex screen in front
of them when this was written, and hard-coding selectors from a screenshot is
how you type a birthday into a hire-date box. So every field is located by the
LABEL a person reads next to it -- 'Last Name', 'Zip', 'Birth Date' -- with the
wordings Apex might use listed as alternatives. Two consequences on purpose:

  * `--explore` writes the real screen's inventory to `apex_screen.json`, so
    the first logged-in run turns guesses into facts.
  * Anything not matched with confidence is NOT typed. It is reported, and the
    person is left for a human to finish. Half a record that says so beats a
    full record that is quietly wrong.

ISOLATION (do not collide with the other CDP modules):
    profile /tmp/apexns_cdp_profile   port 9248
    vantura 9246 · resume_pushing 9245 · apex_payroll 9247
The '_cdp_profile' suffix is what `day_orchestrator.chrome_guard` looks for to
know this Chrome is ours and must not be killed as a stray human window.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from automations.apex_payroll.run import _looks_logged_out  # one login test only

APEX_URL = "https://apex.herbjoyent.com/"
CDP_PROFILE = "/tmp/apexns_cdp_profile"
CDP_PORT = "9248"
SCREEN_PATH = Path(__file__).resolve().parent / "apex_screen.json"

# Cross-platform: every report here has to run on macOS AND Windows.
CHROME_CANDIDATES = {
    "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
    "Windows": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "Linux": ["/usr/bin/google-chrome", "/usr/bin/chromium-browser"],
}

# The labels a person reads beside each box, most likely wording first. Matched
# case-insensitively as a SUBSTRING, so 'Employee First Name' hits 'first name'.
LABELS: Dict[str, tuple] = {
    "first": ("first name", "legal first name", "employee first name"),
    "middle": ("middle name", "middle initial", "middle"),
    "last": ("last name", "legal last name", "employee last name"),
    "address1": ("address 1", "address line 1", "street address", "address"),
    "address2": ("address 2", "address line 2", "apt", "unit", "suite"),
    "city": ("city",),
    "state": ("state", "st"),
    "zip": ("zip", "zip code", "postal code", "postal"),
    "dob": ("birth date", "date of birth", "dob", "birthdate"),
    "email": ("personal email", "email address", "email", "e-mail"),
    "phone": ("cell phone", "mobile phone", "home phone", "phone number",
              "phone"),
}

# Never typed by this runner, on purpose -- see run.py's SENSITIVE note. Listed
# here so a stray entry in LABELS can never resurrect one.
NEVER_TYPE = ("ssn", "social security", "social", "routing", "account number",
              "bank")

# Fields the run will not proceed without: a record missing one of these is not
# a usable employee record.
REQUIRED = ("first", "last", "address1", "city", "state", "zip", "dob")


def chrome_path() -> str:
    for cand in CHROME_CANDIDATES.get(platform.system(), []):
        if os.path.exists(cand):
            return cand
    raise RuntimeError(
        f"Google Chrome not found on this {platform.system()} machine. Apex is "
        "driven through the operator's own signed-in Chrome; there is no "
        "headless path, by design.")


def _kill_ours() -> None:
    """Only ever our own Chrome. The filter is the full profile name so it can
    never match apex_payroll's '/tmp/apex_cdp_profile' or anyone else's."""
    if platform.system() == "Windows":
        subprocess.run(["taskkill", "/F", "/FI",
                        "COMMANDLINE like %apexns_cdp_profile%"],
                       capture_output=True)
    else:
        subprocess.run(["pkill", "-f", "apexns_cdp_profile"], capture_output=True)
    time.sleep(2)


def _copy_profile(log=print) -> str:
    """Copy the operator's Chrome data into our own dir so the debug port works
    and their Apex session rides along. Read-only on the source."""
    home = os.path.expanduser("~")
    if platform.system() == "Windows":
        src = os.path.join(home, r"AppData\Local\Google\Chrome\User Data")
    elif platform.system() == "Darwin":
        src = f"{home}/Library/Application Support/Google/Chrome"
    else:
        src = f"{home}/.config/google-chrome"
    if not os.path.isdir(src):
        raise RuntimeError(f"No Chrome profile at {src} — is Chrome installed "
                           "and has it been opened at least once?")
    import shutil
    _kill_ours()
    shutil.rmtree(CDP_PROFILE, ignore_errors=True)
    os.makedirs(CDP_PROFILE, exist_ok=True)
    shutil.copy2(f"{src}/Local State", f"{CDP_PROFILE}/Local State")
    profiles = [d for d in os.listdir(src)
                if d == "Default" or d.startswith("Profile ")]
    # The caches are the bulk of a Chrome profile and none of them carry the
    # session, so skipping them turns a multi-gigabyte copy into a quick one.
    SKIP = {"Cache", "Code Cache", "GPUCache", "DawnCache",
            "GraphiteDawnCache", "Application Cache", "CacheStorage",
            "Service Worker"}
    if platform.system() == "Windows":
        ignore = shutil.ignore_patterns(*SKIP)
        for prof in profiles:
            shutil.copytree(f"{src}/{prof}", f"{CDP_PROFILE}/{prof}",
                            ignore=ignore, dirs_exist_ok=True)
    else:
        excludes = []
        for pat in SKIP:
            excludes += ["--exclude", pat]
        for prof in profiles:
            subprocess.run(["rsync", "-a", *excludes,
                            f"{src}/{prof}/", f"{CDP_PROFILE}/{prof}/"],
                           capture_output=True)
    last = "Default"
    try:
        st = json.loads(Path(f"{CDP_PROFILE}/Local State").read_text())
        cand = st.get("profile", {}).get("last_used", "Default")
        if cand in profiles:
            last = cand
    except Exception:  # noqa: BLE001
        pass
    log(f"[profiles] copied {profiles}; launching with {last!r}")
    return last


def _launch(url: str, profile_dir: str = "Default"):
    return subprocess.Popen(
        [chrome_path(), f"--user-data-dir={CDP_PROFILE}",
         f"--profile-directory={profile_dir}",
         f"--remote-debugging-port={CDP_PORT}",
         # The copy may hold a sync-enabled Google account; without this it can
         # reconnect and broadcast these tabs to somebody's other devices.
         "--disable-sync", "--no-first-run", "--no-default-browser-check",
         "--restore-last-session=false", "--disable-session-crashed-bubble",
         "--disable-infobars", "--window-size=1600,1000", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _attach(p):
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return browser, page


class ApexSession:
    """Context manager: a live Apex page, or a clear reason there isn't one."""

    def __init__(self, log=print):
        self.log = log
        self.proc = None
        self._pw = None
        self.browser = None
        self.page = None

    def __enter__(self):
        from patchright.sync_api import sync_playwright
        prof = _copy_profile(self.log)
        self.proc = _launch(APEX_URL, prof)
        time.sleep(8)
        self._pw = sync_playwright().start()
        self.browser, self.page = _attach(self._pw)
        self.page.wait_for_load_state("domcontentloaded", timeout=30000)
        time.sleep(3)
        return self

    def __exit__(self, *exc):
        try:
            if self._pw:
                self._pw.stop()
        finally:
            if self.proc:
                self.proc.terminate()
            _kill_ours()
        return False

    def require_login(self) -> None:
        if _looks_logged_out(self.page):
            raise NotLoggedIn(
                "Apex is showing a login page — the session didn't ride along. "
                "Sign in to Apex once in this machine's normal Chrome (tick "
                "remember-this-device on the 2FA prompt), leave it signed in, "
                "then click Run again. This automation never types a password.")
        self.log(f"Apex session is live at {self.page.url}")


class NotLoggedIn(RuntimeError):
    pass


# ------------------------------------------------------------- field finding

_FIND_JS = """(labels) => {
  const out = [];
  const seen = new Set();
  const vis = el => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const push = (el, how, text) => {
    if (!el || seen.has(el)) return;
    seen.add(el);
    out.push({how, text, tag: el.tagName.toLowerCase(),
              type: el.getAttribute('type') || '',
              name: el.getAttribute('name') || '',
              id: el.id || '', visible: vis(el),
              readonly: el.hasAttribute('readonly') || el.disabled === true});
  };
  for (const el of document.querySelectorAll('label')) {
    const t = (el.innerText || '').trim().toLowerCase();
    if (!t) continue;
    if (!labels.some(l => t.includes(l))) continue;
    let f = el.htmlFor ? document.getElementById(el.htmlFor) : null;
    if (!f) f = el.querySelector('input,select,textarea');
    if (!f) {                       // label above/beside its box
      let n = el.nextElementSibling;
      for (let i = 0; i < 3 && n; i++, n = n.nextElementSibling) {
        const c = n.matches('input,select,textarea') ? n
                : n.querySelector('input,select,textarea');
        if (c) { f = c; break; }
      }
    }
    if (f) push(f, 'label', t);
  }
  for (const el of document.querySelectorAll('input,select,textarea')) {
    const attrs = [el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                   el.getAttribute('name'), el.id].filter(Boolean)
                  .join(' ').toLowerCase();
    if (labels.some(l => attrs.includes(l.replace(/ /g, '')) || attrs.includes(l)))
      push(el, 'attr', attrs.slice(0, 60));
  }
  return out;
}"""


def find_field(page, semantic: str) -> Optional[dict]:
    """The one input that means `semantic`, or None if it isn't unambiguous.

    Ambiguity is a refusal, not a coin toss. 'Address' matching both 'Address 1'
    and 'Address 2' means we do not know which is which, so nothing is typed and
    the caller reports it -- the alternative is putting a home address in an
    apartment box on somebody's payroll record.
    """
    for label in LABELS.get(semantic, ()):
        hits = [h for h in page.evaluate(_FIND_JS, [label])
                if h["visible"] and not h["readonly"]]
        # A more specific later label ('address 2') can also match an earlier
        # broad one; take the first wording that lands on exactly one box.
        if len(hits) == 1:
            hit = dict(hits[0])
            hit["semantic"] = semantic
            hit["matched_label"] = label
            return hit
    return None


def _selector(hit: dict) -> str:
    if hit.get("id"):
        return f"#{hit['id']}"
    if hit.get("name"):
        return f"{hit['tag']}[name=\"{hit['name']}\"]"
    raise RuntimeError(f"Apex field {hit.get('semantic')} has neither an id nor "
                       "a name attribute — can't address it safely.")


def plan_fill(page, values: Dict[str, str]) -> tuple:
    """(matched, unmatched) without typing a thing.

    `matched` is [(semantic, value, hit)]; `unmatched` is [(semantic, why)].
    This is what --preview prints and what --live types, so what you approve is
    exactly what happens.
    """
    matched, unmatched = [], []
    for semantic, value in values.items():
        if any(bad in semantic for bad in NEVER_TYPE):
            unmatched.append((semantic, "never auto-typed — enter by hand"))
            continue
        hit = find_field(page, semantic)
        if not hit:
            unmatched.append((semantic, "no field on this screen matched "
                                        f"{'/'.join(LABELS.get(semantic, ()))}"))
            continue
        matched.append((semantic, value, hit))
    return matched, unmatched


def apply_fill(page, matched: List[tuple], log=print) -> int:
    """Type the approved values. Nothing is submitted here -- saving is the
    caller's explicit step, so a bad match is still recoverable on screen."""
    done = 0
    for semantic, value, hit in matched:
        sel = _selector(hit)
        el = page.locator(sel).first
        if hit["tag"] == "select":
            el.select_option(label=value, timeout=8000)
        else:
            el.fill("", timeout=8000)
            el.type(value, delay=25)
        log(f"    {semantic:9} -> {hit['matched_label']!r} ({sel})")
        done += 1
    return done


# ---------------------------------------------------------------- explore

def explore(session: "ApexSession") -> dict:
    """Inventory the screen that is open, and save it.

    Read-only. Run it once on a logged-in machine with the Add Employee form
    open and `apex_screen.json` turns every guess in LABELS into a fact -- and
    tells you the exact wording for anything that didn't match.
    """
    page = session.page
    inv = page.evaluate("""() => {
      const f = [];
      for (const el of document.querySelectorAll('input,select,textarea')) {
        const r = el.getBoundingClientRect();
        let lab = '';
        if (el.id) {
          const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
          if (l) lab = (l.innerText || '').trim();
        }
        f.push({tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
                name: el.getAttribute('name') || '', id: el.id || '',
                placeholder: el.getAttribute('placeholder') || '',
                aria: el.getAttribute('aria-label') || '', label: lab,
                visible: r.width > 0 && r.height > 0});
      }
      return {url: location.href, title: document.title, fields: f};
    }""")
    resolved = {}
    for semantic in LABELS:
        hit = find_field(page, semantic)
        resolved[semantic] = (f"{hit['matched_label']} -> "
                              f"{hit.get('id') or hit.get('name')}") if hit else None
    inv["resolved"] = resolved
    SCREEN_PATH.write_text(json.dumps(inv, indent=2) + "\n")
    return inv
