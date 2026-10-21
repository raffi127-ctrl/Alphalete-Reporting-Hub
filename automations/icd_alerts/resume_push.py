"""Push this office's resumes from its own computer, in the background.

WHY IT MOVED HERE (Carlos, #l10-alphalete 2026-10-05): on Lucy 2 the push
"takes up the screen while pushing", sometimes needs someone to log in, and
one machine is slow across that many offices. On the office's own relay
machine each office pushes only itself, and "they can always have an eye on
it".

ONE APPLICANT AT A TIME, NOT THE BATCH ROBOT (2026-10-20). This used to run
AppStream's "Process in Batches" page, where the Resume Helper extension pulls
every resume off Indeed in one burst. Indeed spots that burst and blocks it,
so the batch robot is gone. The push now works the office's "One App at a
time" queue the way a person does, and the way Lucy 2 and Lucy 4 already do:
open the applicant, read the number from AppStream's attachment (or the Indeed
resume, one page view), fill it in, Send to AI. It is the SAME walk the Lucys
run (automations/oat_processing/run.py, run_walk), shipped here, not a copy:
a fix to the walk reaches every office machine on the next self-update.

IN THE BACKGROUND, NOT HEADLESS. A real Google Chrome on Lucy's OWN profile
(never theirs), kept out of the way. Real, because Indeed's "Verify you are
human" box needs a browser a person at that desk can click when it shows.

MEASURED ON A MAC, 2026-10-05: Chrome brings ITSELF to the front whenever it
starts or opens a window -- `open -g`, `open -j`, a minimized window and a
background tab do not stop it, and the walk opens a tab of its own for
every Indeed resume it reads. Left alone, that is the "takes up the screen" Carlos means. So:
  * Mac: Lucy's Chrome starts hidden, and for a few seconds after Lucy opens
    a window, _FocusGuard HIDES her Chrome (as Cmd-H would) the moment it
    takes the front -- which hands focus straight back to whatever the person
    was using. Needs no permission (lsappinfo + NSRunningApplication.hide;
    `lsappinfo setfront` is refused with permErr).
  * Windows: started minimized without activation; windows are minimized.
Hidden, Chrome still runs timers at full speed and takes clicks (measured: 30
of 30 ticks, click registered), because background throttling is switched off.

IT STAYS HIDDEN FOR THE WHOLE WALK (Megan 2026-10-21: "we want it running in
the background"). Every resume read brings a tab to the front, so the guard
hides Lucy's Chrome all walk long, not only after she opens a tab -- which
also means it cannot be watched mid-walk. The one exception: when Indeed's
"Verify you are human" box walls the walk, the guard stands down so a person
can click Lucy's Chrome in the Dock / taskbar and tick it.

THE OFFICE'S OWN LUCY RESUME LOGIN (Megan, 2026-10-20), signed in by us with
the 30s waits that clear the security box (resources/lucy-login-standard.md
rule 1). One per office, scoped to that office only, so the push can only
reach that office -- and the walk still refuses unless the page shows the
Office ID stated in PUSH_OFFICES.

ONE OFFICE, ONE MACHINE. When an office starts pushing from here, take it out
of ROTATION_BY_MACHINE in automations/applicant_push/offices.py, or Lucy 2/4
and this machine both push it.

    python -m automations.icd_alerts.resume_push            # dry run, visible
    python -m automations.icd_alerts.resume_push --live     # really sends

SEND TO AI CANNOT BE UNDONE. The command line is a dry run unless --live,
and --live only sends for an office listed "live" in PUSH_OFFICES. An office
not listed there does nothing -- see PUSH_OFFICES for why.

NEVER REMOVES FOR MISSING CONTACT INFO, NEVER TEXTS (Carlos, 9/13 + 8/29):
pinned below in _point_walk_here, per PUSHING-OPERATIONS-README.md section 4.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

from automations.icd_alerts import config as C

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

AS_HOME = "https://applicantstream.com/"
AS_BASE = "https://applicantstream.com/index.cfm"
CONSOLE = "#searchMC"

PROFILE_DIR = C.AS_PROFILE_DIR
# Not 9245/9334 -- those are the Lucy pushers' ports, and a Lucy that is also
# somebody's desk must never attach to the other one's Chrome.
PORT = 9247
STATE_PATH = C.APP_DIR / "resume-push.json"
LOG_PATH = C.APP_DIR / "resume-push.log"
LOCK_PATH = C.APP_DIR / "resume-push.lock"

# Lucy 2's cadence and hours: every 10 minutes, 7am-10pm, every day.
EVERY_MINUTES = 10
DAY_START = (7, 0)
DAY_END = (22, 0)
# A push that has held the lock this long has died without cleaning up.
LOCK_STALE_MINUTES = 60
# The walk stops itself this long after it starts, well inside the lock, so it
# always writes its files and its result before the next tick could start.
WALK_MINUTES = 15

# WHICH OFFICE MACHINES PUSH, AND HOW. office_key -> (AppStream office ID,
# "dry" or "live"). An office not listed here does nothing at all.
#
# Every machine that said "yes, push my resumes" already ticks --live every
# 10 minutes. Until 2026-10-20 that was harmless: the batch robot was missing
# on all of them, so each tick stopped before touching anyone. The walk needs
# nothing installed, so without this list the update would have started
# sending for real on all of them at once -- including offices Lucy 2 and
# Lucy 4 already push (two pushers on one queue) -- and even a dry run opens
# Indeed resumes, which is the traffic Indeed blocks. So each office is
# switched on here, in code, one at a time:
#   "dry"  -- walks and reads, sends nothing. The supervised first step.
#   "live" -- really Sends to AI. Same commit must take the office out of
#             ROTATION_BY_MACHINE in automations/applicant_push/offices.py:
#             one office, one pusher.
# The AppStream office ID is stated, never learned: some offices' computers
# hold a login that sees many offices, and the walk refuses unless the page's
# "Office ID:" banner is exactly this one.
PUSH_OFFICES = {
    # Carlos, LIVE (Megan 2026-10-20: "just take it live"). Both of his
    # campaigns' enrollments live on one machine; either may carry the
    # push_resumes answer. 11580 left Lucy 2 in the same change
    # (ROTATION_BY_MACHINE "Carlos's office computer (relay)").
    "carlos": ("11580", "live"),
    "carlos-b2batt": ("11580", "live"),
}
LOGIN_POLL_SECONDS = 90

# Chrome slows timers and rendering in a minimized window. These keep a
# minimized push running at full speed.
_BACKGROUND_FLAGS = [
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
]


def _log(msg: str) -> None:
    print("%s  %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg), flush=True)



# --- who pushes ----------------------------------------------------------------
def push_record() -> dict:
    """The enrollment on this machine that asked for resume pushing, or {}."""
    for r in C.enrollments():
        if isinstance(r, dict) and r.get("push_resumes"):
            return r
    return {}


def _listed(record: Optional[dict] = None):
    """(AppStream office ID, mode) for this machine's office, or None."""
    rec = push_record() if record is None else record
    return PUSH_OFFICES.get(str(rec.get("office_key") or ""))


def enabled() -> bool:
    return (bool(push_record()) and bool(C.appstream_creds())
            and _listed() is not None)


def armed(record: Optional[dict] = None) -> bool:
    """May this machine really Send to AI? Only for an office listed "live"
    in PUSH_OFFICES. Fails closed: no record, no key, no send."""
    got = _listed(record)
    return bool(got) and got[1] == "live"


def quiet_now(now: Optional[dt.datetime] = None) -> bool:
    """The weekend quiet window: nothing pushes Friday 1pm -> Sunday 1pm
    (Carlos, 9/4). The Lucys' own rule, imported, not retyped."""
    from automations.applicant_push.window import quiet_window
    return quiet_window(now or dt.datetime.now())


def in_window(now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    hm = (now.hour, now.minute)
    return DAY_START <= hm < DAY_END


# --- state ---------------------------------------------------------------------
def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(st: dict) -> None:
    try:
        C.APP_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, indent=2))
    except OSError:
        pass


def _lock_held(now: Optional[float] = None) -> bool:
    """By AGE, not by pid: checking a pid on Windows with os.kill ENDS it."""
    try:
        started = float(LOCK_PATH.read_text().strip() or 0)
    except (OSError, ValueError):
        return False
    return ((now or time.time()) - started) < LOCK_STALE_MINUTES * 60


def due(now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    if not in_window(now) or _lock_held(now.timestamp()):
        return False
    last = _state().get("last_start")
    if not last:
        return True
    try:
        then = dt.datetime.fromisoformat(last)
    except ValueError:
        return True
    return (now - then) >= dt.timedelta(minutes=EVERY_MINUTES)


def maybe_kick(log=print) -> bool:
    """Called from every agent tick. Starts a push in its OWN process when one
    is due, and returns at once -- a push can take many minutes and must never
    hold up a credit-check sweep."""
    if not enabled() or not due():
        return False
    root = Path(__file__).resolve().parents[2]
    kw = {"cwd": str(root), "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        kw["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                               | getattr(subprocess,
                                         "CREATE_NEW_PROCESS_GROUP", 0x200))
    else:
        # Out of the tick's process group: launchd kills what is left in a
        # job's group when the job exits (Lucy 2, 2026-09-22).
        kw["start_new_session"] = True
    try:
        C.APP_DIR.mkdir(parents=True, exist_ok=True)
        out = open(LOG_PATH, "a")
        subprocess.Popen([sys.executable, "-m",
                          "automations.icd_alerts.resume_push",
                          "--live", "--scheduled"],
                         stdout=out, stderr=subprocess.STDOUT, **kw)
    except Exception as e:  # noqa: BLE001 — never lose a sweep to this
        log("resume push could not start: %s" % type(e).__name__)
        return False
    log("resume push started in the background")
    return True


# --- Lucy's Chrome -------------------------------------------------------------
def chrome_path() -> Optional[str]:
    if IS_MAC:
        for app in ("/Applications/Google Chrome.app",
                    str(Path.home() / "Applications" / "Google Chrome.app")):
            if Path(app).exists():
                return app
        return None
    if IS_WINDOWS:
        for base in (os.environ.get("ProgramFiles"),
                     os.environ.get("ProgramFiles(x86)"),
                     os.environ.get("LOCALAPPDATA")):
            if base:
                exe = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
                if exe.exists():
                    return str(exe)
    return None


def _port_alive() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % PORT,
                                    timeout=2):
            return True
    except Exception:  # noqa: BLE001
        return False


def launch_chrome(url: str, background: bool) -> bool:
    """Start Lucy's Chrome on its own profile. In the background it never takes
    focus. False = it could not start (no Chrome, or nobody is logged in to the
    computer, which a real browser needs)."""
    app = chrome_path()
    if not app:
        _log("Google Chrome is not installed on this computer")
        return False
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    for lock in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (PROFILE_DIR / lock).unlink()
        except OSError:
            pass
    args = ["--user-data-dir=%s" % PROFILE_DIR,
            "--remote-debugging-port=%d" % PORT,
            "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--hide-crash-restore-bubble", "--window-size=1400,900"]
    args += _BACKGROUND_FLAGS + [url]
    if IS_MAC:
        # -n: a separate Chrome from theirs. -g -j: in the background,
        # hidden. Chrome still pulls itself forward once it is up, which is
        # what _FocusGuard is for.
        cmd = ["open", "-n"] + (["-g", "-j"] if background else []) + \
              ["-a", app, "--args"] + args
        rc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode
        if rc != 0:
            _log("could not open Chrome -- is anybody logged in to this Mac?")
            return False
    else:
        kw = {}
        if IS_WINDOWS:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 7 if background else 1   # 7 = minimized, no focus
            kw["startupinfo"] = si
            kw["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x8)
        subprocess.Popen([app] + args, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, **kw)
    for _ in range(30):
        if _port_alive():
            return True
        time.sleep(1)
    _log("Chrome started but never answered")
    return False


def minimize(ctx, page) -> None:
    """Send this tab's window to the Dock / taskbar."""
    try:
        cdp = ctx.new_cdp_session(page)
        win = cdp.send("Browser.getWindowForTarget")
        cdp.send("Browser.setWindowBounds",
                 {"windowId": win["windowId"],
                  "bounds": {"windowState": "minimized"}})
    except Exception:  # noqa: BLE001 — a visible window is not a failure
        pass


class _FocusGuard:
    """Mac only: give focus back when Lucy's Chrome takes it by itself.

    Right after Lucy opened something (expect()), and for the WHOLE walk once
    hold() is called. The 4-second windows alone let most of the walk through
    (Carlos, 2026-10-21: "for sure takes up the computer"): every resume read
    calls bring_to_front twice -- the Indeed tab forward, then the queue tab
    back -- and each one pulls Chrome in front of whatever he was doing,
    outside any window. So during a walk it hides her Chrome every time.

    STANDS DOWN when a person is needed: once Indeed's "verify you are human"
    box walls the walk (stand_down() turns true), Chrome is left alone so
    somebody can bring it forward and tick the box.
    """

    WINDOW_SECONDS = 4.0
    POLL_SECONDS = 0.1
    # Each poll spawns lsappinfo twice. Fine for 4 seconds; for a 15-minute
    # held walk it is CPU the person feels, so a held guard polls slower --
    # Chrome can show for up to a quarter second before it is hidden.
    HELD_POLL_SECONDS = 0.25

    def __init__(self):
        import threading
        self._until = 0.0
        self._pids = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._held = False
        self._stand_down = None
        self.stood_down = False
        self.hidden = 0

    def start(self):
        if IS_MAC:
            self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def expect(self, seconds: float = WINDOW_SECONDS) -> None:
        self._pids = set(_lucy_pids())
        self._until = max(self._until, time.time() + seconds)

    def hold(self, stand_down=None) -> None:
        """Keep Chrome hidden until stop(), or until stand_down() is true."""
        self._pids = set(_lucy_pids())
        self._stand_down = stand_down
        self._held = True

    def _active(self) -> bool:
        if self._held and self._stand_down is not None:
            try:
                if self._stand_down():
                    self._held = False
                    self.stood_down = True
            except Exception:  # noqa: BLE001
                pass
        return self._held or time.time() < self._until

    def _loop(self):
        theirs = 0
        while not self._stop.is_set():
            if self._active():
                pid = _front_pid()
                if pid and (pid in self._pids or pid in _lucy_pids()):
                    # HIDE FIRST, THEN HAND BACK. Measured 2026-10-05:
                    #   hide first   -> Lucy in front ~75ms per window, then
                    #                   whatever macOS picks next (often THEIR
                    #                   Chrome) for ~0.4s, then the right app
                    #   hand back 1st -> Lucy in front ~0.5s per window
                    # Hiding alone never got the right app back, so both.
                    _hide_app(pid)
                    if theirs:
                        _activate_app(theirs)
                    self.hidden += 1
                elif pid:
                    theirs = pid
            self._stop.wait(self.HELD_POLL_SECONDS if self._held
                            else self.POLL_SECONDS)


def _lucy_pids():
    try:
        out = subprocess.run(["pgrep", "-f", "user-data-dir=%s" % PROFILE_DIR],
                             capture_output=True, text=True).stdout
        return [int(x) for x in out.split()]
    except Exception:  # noqa: BLE001
        return []


def _front_pid() -> int:
    """The app in front, by pid. lsappinfo, because Lucy's Chrome and theirs
    have the same name and bundle id -- System Events reports the wrong one."""
    import re
    try:
        asn = subprocess.run(["lsappinfo", "front"], capture_output=True,
                             text=True).stdout.strip()
        out = subprocess.run(["lsappinfo", "info", "-only", "pid", asn],
                             capture_output=True, text=True).stdout
        found = re.findall(r"(\d+)", out)
        return int(found[-1]) if found else 0
    except Exception:  # noqa: BLE001
        return 0


def _hide_app(pid: int) -> None:
    """[[NSRunningApplication runningApplicationWithProcessIdentifier:] hide],
    through ctypes so the agent needs no extra package."""
    _running_app(pid, b"hide")


def _activate_app(pid: int) -> None:
    _running_app(pid, b"activateWithOptions:", 2)   # IgnoringOtherApps


def _running_app(pid: int, selector: bytes, arg=None) -> None:
    try:
        import ctypes
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        ctypes.cdll.LoadLibrary(ctypes.util.find_library("AppKit"))
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def msg(restype, *argtypes):
            return ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p,
                                    *argtypes)(("objc_msgSend", objc))
        app = msg(ctypes.c_void_p, ctypes.c_int)(
            objc.objc_getClass(b"NSRunningApplication"),
            objc.sel_registerName(b"runningApplicationWithProcessIdentifier:"),
            pid)
        if app and arg is None:
            msg(ctypes.c_bool)(app, objc.sel_registerName(selector))
        elif app:
            msg(ctypes.c_bool, ctypes.c_ulong)(
                app, objc.sel_registerName(selector), arg)
    except Exception:  # noqa: BLE001 — a visible window is not a failure
        pass


# --- signing in ----------------------------------------------------------------
def _rqst_tokens(ctx):
    return [c["name"][len("rqst_"):] for c in ctx.cookies()
            if c.get("name", "").startswith("rqst_")]


def _on_console(page, ctx) -> bool:
    """On the office console, or one token hop from it. A page that rendered
    is not proof -- a wrong username renders one too."""
    try:
        if page.locator(CONSOLE).count() > 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    for tok in _rqst_tokens(ctx):
        try:
            page.goto("%s?rqst=%s&p=701" % (AS_BASE, tok),
                      wait_until="domcontentloaded", timeout=25_000)
            page.wait_for_selector(CONSOLE, timeout=10_000)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def sign_in(page, ctx, log=_log) -> bool:
    """Reach this office's AppStream console as THEIR account."""
    from automations.shared import ownerville_knocks as K
    cr = C.appstream_creds()
    if not cr:
        log("no AppStream login saved on this computer")
        return False
    marker = PROFILE_DIR / ".appstream_account"
    try:
        last = marker.read_text().strip() if marker.exists() else ""
    except OSError:
        last = ""
    if last != cr["username"]:
        # A session another username left here is not this office's.
        ctx.clear_cookies()
    else:
        try:
            page.goto(AS_BASE, wait_until="domcontentloaded", timeout=45_000)
        except Exception:  # noqa: BLE001
            pass
        if _on_console(page, ctx):
            return True

    log("signing in to AppStream as %s" % cr["username"])
    try:
        K.login(page, cr["username"], cr["password"], log=log, url=AS_HOME)
    except Exception as e:  # noqa: BLE001
        log("the AppStream sign-in page did not behave (%s)" % type(e).__name__)
    deadline = time.time() + LOGIN_POLL_SECONDS
    while time.time() < deadline:
        if _on_console(page, ctx):
            try:
                marker.write_text(cr["username"])
            except OSError:
                pass
            log("AppStream is signed in")
            return True
        page.wait_for_timeout(5000)
    global LAST_SIGNIN_PAGE
    LAST_SIGNIN_PAGE = describe_page(page, ctx)
    log("Lucy could not confirm the AppStream office page. What her Chrome "
        "showed:")
    for line in LAST_SIGNIN_PAGE.splitlines():
        log("  " + line)
    return False


# WHAT THE PAGE WAS, WHEN THE PROOF FAILS. Drew, 2026-10-06: Lucy signed in --
# he watched AppStream open -- and the check still said "never opened". The
# proof is #searchMC, the office SWITCHER, and every account it was learned on
# sees many offices; an office's own login sees one. Whether that page has no
# switcher is a guess until we see it, so a failure now says what was there.
LAST_SIGNIN_PAGE = ""
SIGNIN_SHOT = C.APP_DIR / "resume-push-signin.png"


def _no_tokens(url: str) -> str:
    """rqst is a live session token: it never leaves the machine."""
    import re
    return re.sub(r"(rqst=)[^&#]+", r"\1<hidden>", url or "")


def describe_page(page, ctx) -> str:
    """URL (token hidden), title, the markers that decide signed-in, and the
    opening text. Never raises; a screenshot stays on this computer."""
    from automations.shared import ownerville_knocks as K
    out = []

    def add(label, fn):
        try:
            out.append("%s: %s" % (label, fn()))
        except Exception as e:  # noqa: BLE001
            out.append("%s: ? (%s)" % (label, type(e).__name__))

    add("url", lambda: _no_tokens(page.url))
    add("title", lambda: page.title())
    add("office switcher #searchMC", lambda: page.locator(CONSOLE).count())
    add("password box", lambda: page.locator(K._PASSWORD_SELECTOR).count())
    add("security check frame", lambda: page.locator(
        'iframe[src*="challenges.cloudflare"]').count())
    add("session cookies (rqst_)", lambda: len(_rqst_tokens(ctx)))
    add("tabs", lambda: len(ctx.pages))
    add("text", lambda: " ".join(page.inner_text("body").split())[:300])
    try:
        page.screenshot(path=str(SIGNIN_SHOT))
        out.append("screenshot on this computer: %s" % SIGNIN_SHOT)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(out)


# A CHROME WITH NO WINDOW CANNOT BE DRIVEN. On a Mac, closing Lucy's last
# Chrome window leaves Chrome running -- port 9247 still answers -- but Chrome
# unloads the profile behind it, and connect_over_cdp then dies on its first
# call: "Protocol error (Browser.setDownloadBehavior): Browser context
# management is not supported." Drew, 2026-10-06; reproduced here on Chrome
# 154 + patchright 1.60 (window open: fine; windows closed: that exact error).
# Not a version mismatch, and nothing a password can fix.
_NO_PROFILE = "context management is not supported"


def _page_count() -> int:
    """Open tabs in Lucy's Chrome; -1 when it cannot be asked."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % PORT,
                                    timeout=5) as r:
            return sum(1 for t in json.loads(r.read())
                       if t.get("type") == "page")
    except Exception:  # noqa: BLE001
        return -1


def _open_window(url: str) -> bool:
    """Ask Lucy's Chrome for a new window over plain HTTP. That loads her
    profile again, which is all connect_over_cdp was missing. Measured: it
    brings a windowless Chrome back without restarting it, on any OS."""
    import urllib.parse
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:%d/json/new?%s"
            % (PORT, urllib.parse.quote(url, safe=":/?=&")), method="PUT")
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:  # noqa: BLE001
        return False
    for _ in range(10):
        if _page_count() > 0:
            return True
        time.sleep(0.5)
    return False


def _connect(p, background: bool, url: str = AS_BASE, guard=None):
    """(browser, ctx, page) on Lucy's Chrome, starting it if needed."""
    if guard:
        guard.expect(30)            # a cold Chrome takes a while to come up
    if _port_alive():
        if _page_count() == 0:
            _log("Lucy's Chrome was open with no window -- opening one")
            _open_window(url)
    elif not launch_chrome(url, background):
        return None, None, None
    cdp = "http://127.0.0.1:%d" % PORT
    try:
        browser = p.chromium.connect_over_cdp(cdp)
    except Exception as e:  # noqa: BLE001
        # The window check above can lose a race with a window closing; the
        # message is the proof, so give it one more window and one more try.
        if _NO_PROFILE not in str(e).lower() or not _open_window(url):
            raise
        _log("Lucy's Chrome had no window -- opened one, connecting again")
        browser = p.chromium.connect_over_cdp(cdp)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    for extra in list(ctx.pages)[1:]:
        try:
            extra.close()
        except Exception:  # noqa: BLE001
            pass
    if background:
        if IS_MAC and guard:
            # A Chrome the installer left on screen gets tucked away -- unless
            # it is in front, which means somebody is looking at it.
            lucy = _lucy_pids()
            if _front_pid() not in lucy:
                for pid in lucy:
                    _hide_app(pid)        # helpers are not apps; a no-op
            guard.expect()
            # The walk opens each Indeed resume in a tab of its own, and
            # Chrome comes forward with it. Give the focus straight back.
            ctx.on("page", lambda pg: guard.expect())
        else:
            minimize(ctx, page)
            ctx.on("page", lambda pg: minimize(ctx, pg))
    return browser, ctx, page


# --- the jobs ------------------------------------------------------------------
NO_CHROME = 3


def check_login(log=_log) -> int:
    """For the installer: sign in where they can see it. 0 ok, 1 no, 2 none,
    3 Lucy's Chrome would not open (so the login was never even tried)."""
    if not C.appstream_creds():
        log("no AppStream login saved on this computer")
        return 2
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page = _connect(p, background=False)
        if not page:
            return NO_CHROME
        # THE RED BAR (Megan's recap, 2026-10-20). This is the one AppStream
        # sign-in a person watches, and the helpful thing to do with a
        # half-finished login is finish it -- which is what breaks it. Only
        # here: it rides this connection, so the scheduled push, where a
        # person may be asked to tick Indeed's box, never shows it.
        from automations.shared import browser_banner
        browser_banner.attach(ctx, detail=(
            "Lucy is signing herself in to AppStream. The security check "
            "clears by itself in 20-30 seconds. Don't type anything and "
            "don't click the box -- just leave this window alone."))
        return 0 if sign_in(page, ctx, log) else 1


# --- when the setup check fails ------------------------------------------------
# Drew, 2026-10-06: the setup screen said "Resume pushing  failed (Error)" and
# nothing else. "Error" is patchright's base class -- it named the library,
# not the problem -- and the message holding the real reason was thrown away,
# with nothing sent to us. Raf was sure the login was right, and it probably
# was: a wrong login says "still needs signing in", never "failed".
_CLOSED = ("has been closed", "target closed", "browser closed",
           "connection closed", "browser has disconnected")


def explain_failure(e: BaseException) -> "tuple[str, str]":
    """(reason, hint) for a crash in the setup check, in plain words.

    The reason goes on the summary line; the hint says what to do. A cause we
    do not recognise keeps its own full message -- a guess would hide it.
    """
    msg = str(e).strip()
    low = msg.lower()
    if _NO_PROFILE in low:      # first: its call log can mention closing
        return ("Lucy's Chrome was running with no window open",
                "Quit Lucy's Chrome (right-click Chrome in the Dock > Quit), "
                "then run this again.")
    if any(s in low for s in _CLOSED):
        return ("Lucy's Chrome window was closed before the check finished",
                "Run this again and leave the Chrome window that opens alone "
                "until this screen says it is done.")
    if "connect_over_cdp" in low or ("127.0.0.1:%d" % PORT) in low:
        return ("could not take control of Lucy's Chrome (port %d)" % PORT,
                "Quit every Chrome window Lucy opened (right-click Chrome in "
                "the Dock > Quit), then run this again.")
    first = msg.splitlines()[0].strip() if msg else ""
    return ("%s: %s" % (type(e).__name__, first) if first
            else type(e).__name__, "")


def report_setup_failure(summary: str, detail: str = "", log=_log) -> bool:
    """File a failed setup check to #claudecorrections-and-requests, the same
    road the scheduled push's faults take. Not de-duplicated like those: a
    person runs setup by hand, so every failed run is news. Never raises."""
    try:
        from automations.icd_alerts import relay as R
        return R.report_fault("resume_push",
                              "Resume pushing setup failed: %s" % summary,
                              detail, log=log,
                              office_key=str(push_record().get("office_key")
                                             or ""))
    except Exception:  # noqa: BLE001
        return False


def _report_once(result: str, summary: str, detail: str = "") -> None:
    """To #claudecorrections-and-requests, never an office channel -- and only
    when the result CHANGES, or a 10-minute job repeats one fault all day."""
    st = _state()
    if st.get("reported") == result:
        return
    try:
        from automations.icd_alerts import relay as R
        R.report_fault("resume_push", summary, detail, log=_log,
                       office_key=str(push_record().get("office_key") or ""))
    except Exception:  # noqa: BLE001
        pass
    st["reported"] = result
    _save_state(st)


# --- the walk --------------------------------------------------------------------
def _point_walk_here(office_id: str, record: dict) -> None:
    """Aim the shared walk at THIS office, with THIS machine's rules.

    The walk's defaults are Carlos's office; applicant_push/offices.py
    rebinds them per office on the Lucys. Here the same rebinding, with the
    rules every office machine gets -- stated, never inherited:
      * never remove anyone for missing contact info (Carlos, 9/13),
      * never text an applicant (texting is 11580/23467 only, on Lucy 2),
      * never remove on a blocked or unreadable resume read.
    """
    from automations.oat_processing import config as OC
    OC.OFFICE_ID = str(office_id)
    OC.OFFICE_HINT = str(record.get("owner") or record.get("office_key") or "")
    OC.FILE_SUFFIX = "-%s" % office_id
    OC.WALK_DIAG_TAB = "OAT Walk Diag %s" % office_id
    OC.REMOVE_NO_PHONE = False
    OC.ALLOW_RETEXT = False
    OC.REMOVE_BLOCKED_READ = False
    OC.MAX_WALK_SECONDS = WALK_MINUTES * 60
    OC.WALK_DEADLINE_EPOCH = time.time() + WALK_MINUTES * 60


def _pin_office(seen: Optional[str], record: dict) -> "tuple[bool, str]":
    """(ok, why). Is the queue on screen THIS office's, by the number stated
    in PUSH_OFFICES? Checked before a single applicant is read; the walk then
    re-checks the banner before every click."""
    got = _listed(record)
    if not got:
        return False, "this office is not in PUSH_OFFICES"
    if not seen:
        return False, "no Office ID on the One App at a time page"
    if seen != got[0]:
        return False, ("AppStream shows office %s, but this computer pushes "
                       "office %s" % (seen, got[0]))
    return True, ""


def _keep_minimized(ctx):
    """Windows: put Lucy's Chrome back in the taskbar every time the walk
    brings a tab to the front (the Mac guard does the same job by hiding).
    Patched on the Page class for THIS process only -- the office push is
    the only thing running in it. Returns the undo."""
    try:
        from patchright.sync_api._generated import Page
    except Exception:  # noqa: BLE001
        return lambda: None
    original = Page.bring_to_front

    def bring_to_front(self, *a, **k):
        out = original(self, *a, **k)
        try:
            from automations.oat_processing import run as OAT
            if not OAT._cf_walled():     # a person may need it now
                minimize(ctx, self)
        except Exception:  # noqa: BLE001
            pass
        return out
    Page.bring_to_front = bring_to_front
    return lambda: setattr(Page, "bring_to_front", original)


def _walled() -> bool:
    try:
        from automations.oat_processing import run as OAT
        return bool(OAT._cf_walled())
    except Exception:  # noqa: BLE001
        return False


def _walk(page, live: bool, record: dict) -> dict:
    """One walk of the office's One App at a time queue. Returns
    {'reached', 'office', 'rc', 'sent', 'walled', 'why'}."""
    from automations.oat_processing import run as OAT
    OAT.attach_dialog_accept(page)
    # A LOGIN THAT SEES MANY OFFICES (Carlos's computer holds the six-office
    # `Lucy Resume Pushing`, Megan 2026-10-20: "fine for his") lands on
    # whichever office it was on last, and Lucy 2/4 move that same account
    # around all day. So switch to THIS office first, with the Lucys' own
    # switch. An office-only login has no switcher (#searchMC) and skips this.
    # The banner check below still decides; the switch only makes it pass.
    #
    # BEST EFFORT, AND NEVER WHEN ALREADY THERE (Carlos's computer, 10/21
    # 7:53-9:45am: five runs crashed in _switch_office waiting for "11580" in
    # the office search list). A relay stays on ONE office, so after its first
    # switch every run starts already on it, and the list does not offer it
    # back. Lucy 2 never met this: she moves between offices every tick. So:
    # skip the switch when the console title already names the office, and a
    # switch that fails is logged, not fatal -- the Office ID banner on the
    # One App at a time page (_pin_office, below) is what decides.
    listed = _listed(record)
    if listed and page.locator(CONSOLE).count() > 0:
        try:
            title = page.title() or ""
        except Exception:  # noqa: BLE001
            title = ""
        if "(%s)" % listed[0] in title:
            _log("already on office %s -- no switch needed" % listed[0])
        else:
            from automations.recruiting_report import fetch_office as FO
            try:
                ok = FO._switch_office(page, listed[0], "")
            except Exception as e:  # noqa: BLE001
                ok = False
                _log("office switch raised %s -- the Office ID check decides"
                     % type(e).__name__)
            if not ok:
                _log("could not switch to office %s; checking which office "
                     "the queue shows" % listed[0])
    if not OAT.open_oat(page):
        return {"reached": False, "why": "could not open One App at a time"}
    page.wait_for_timeout(1500)
    seen = OAT.office_on_page(page)
    ok, why = _pin_office(seen, record)
    if not ok:
        return {"reached": True, "office": seen, "rc": 2, "why": why}
    _point_walk_here(seen, record)
    before = len(OAT._ACTIVITY_ROWS)
    rc = OAT.run_walk(page, live=live)
    rows = OAT._ACTIVITY_ROWS[before:] if live else []
    sent = sum(1 for r in rows if len(r) > 5
               and str(r[5]).startswith("sent"))
    return {"reached": True, "office": seen, "rc": rc, "sent": sent,
            "walled": bool(OAT._cf_walled()),
            "why": "" if rc == 0 else "the walk stopped (rc=%s)" % rc}


def push(live: bool, scheduled: bool = False) -> int:
    """One push. 0 = done (or nothing to do), 1 = failed."""
    if not C.appstream_creds():
        _log("no AppStream login saved -- nothing to push with")
        return 1
    record = push_record()
    if _listed(record) is None:
        _log("office %r is not switched on for resume pushing yet "
             "(PUSH_OFFICES) -- nothing to do" % (record.get("office_key") or "?"))
        return 0
    if live and not armed(record):
        _log("DRY RUN: office %r is switched on for reading only "
             "(PUSH_OFFICES) -- nothing is sent" % record.get("office_key"))
        live = False
    if live and quiet_now():
        _log("weekend quiet window (Fri 1pm - Sun 1pm): nothing pushes")
        return 0
    C.APP_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(str(time.time()))
    st = _state()
    st["last_start"] = dt.datetime.now().isoformat(timespec="seconds")
    _save_state(st)
    result, out, guard = "ok", {}, None
    try:
        from patchright.sync_api import sync_playwright
        guard = _FocusGuard().start() if scheduled else None
        with sync_playwright() as p:
            browser, ctx, page = _connect(p, background=scheduled, guard=guard)
            if not page:
                result = "no_browser"
                _report_once(result, "could not open Lucy's Chrome for the "
                                     "resume push (nobody logged in?)")
                return 1
            if not sign_in(page, ctx):
                result = "login"
                _report_once(result, "AppStream sign-in failed on the office "
                                     "machine; resumes are not being pushed",
                             LAST_SIGNIN_PAGE)
                return 1
            # IN THE BACKGROUND FOR THE WHOLE WALK (Megan 2026-10-21: "we
            # want it running in the background"), not only the moments
            # after a new tab opens.
            undo = lambda: None   # noqa: E731
            if scheduled:
                if guard:
                    guard.hold(stand_down=_walled)
                if IS_WINDOWS:
                    undo = _keep_minimized(ctx)
            try:
                out = _walk(page, live, record)
            finally:
                undo()
            if not out.get("reached"):
                result = "no_queue_page"
                _report_once(result, "the resume push could not open One App "
                                     "at a time on AppStream")
                return 1
            if out.get("rc") == 2 and out.get("why", "").startswith(
                    ("AppStream shows", "no Office ID")):
                result = "wrong_office"
                _report_once(result, "resume push refused: %s" % out["why"],
                             "Nothing was sent. The login saved on this "
                             "computer is showing another office: fix the "
                             "login, or the number in PUSH_OFFICES.")
                return 1
            if out.get("walled"):
                result = "walled"
                _report_once(result, "Indeed is asking to verify a human on "
                                     "this office's computer; no numbers are "
                                     "being read",
                             "Someone at that desk: click Lucy's Chrome in "
                             "the Dock / taskbar and tick the box once. "
                             "Nobody is removed meanwhile; they stay queued.")
            # LEAVE CHROME RUNNING, minimized. The next tick reuses it, so the
            # session and the security check it already passed carry over.
            _log("%s: office %s, %d sent to AI%s"
                 % ("LIVE" if live else "DRY RUN", out.get("office"),
                    out.get("sent", 0),
                    " -- Indeed's check is up" if out.get("walled") else ""))
            return 0 if out.get("rc") == 0 else 1
    except Exception as e:  # noqa: BLE001
        result = "crash"
        import traceback
        _report_once(result, "resume push crashed: %s" % type(e).__name__,
                     traceback.format_exc())
        return 1
    finally:
        if guard:
            guard.stop()
            if guard.hidden:
                _log("gave the screen back %d time(s)" % guard.hidden)
        st = _state()
        st["last_end"] = dt.datetime.now().isoformat(timespec="seconds")
        st["last_result"] = result
        st["last_live"] = bool(live)
        if out:
            day = dt.date.today().isoformat()
            sent = st.get("sent_by_day") or {}
            sent = {k: v for k, v in sent.items() if k >= (
                dt.date.today() - dt.timedelta(days=14)).isoformat()}
            sent[day] = int(sent.get(day, 0)) + int(out.get("sent", 0))
            st["sent_by_day"] = sent
            st["office"] = out.get("office")
        if result == "ok":
            st.pop("reported", None)    # the next fault is news again
        _save_state(st)
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Push this office's resumes")
    ap.add_argument("--live", action="store_true",
                    help="really Send to AI (cannot be undone)")
    ap.add_argument("--scheduled", action="store_true",
                    help="what the agent's tick runs: in the background")
    ap.add_argument("--setup", action="store_true",
                    help="nothing to install any more (kept so old "
                         "instructions do not error)")
    ap.add_argument("--check-login", action="store_true",
                    help="sign in to AppStream and stop")
    args = ap.parse_args(argv)
    if args.setup:
        _log("nothing to set up: the push no longer uses Resume Helper")
        return 0
    if args.check_login:
        rc = check_login()
        if rc == NO_CHROME:
            _log("could not open Lucy's Chrome, so the login was not tried")
        return rc
    return push(live=args.live, scheduled=args.scheduled)


if __name__ == "__main__":
    sys.exit(main())
