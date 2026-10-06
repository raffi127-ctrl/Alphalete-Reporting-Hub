"""Push this office's resumes from its own computer, in the background.

WHY IT MOVED HERE (Carlos, #l10-alphalete 2026-10-05): on Lucy 2 the push
"takes up the screen while pushing", sometimes needs someone to log in, and
one machine is slow across that many offices. On the office's own relay
machine each office pushes only itself, and "they can always have an eye on
it".

IN THE BACKGROUND, NOT HEADLESS. The resume read is the Resume Helper Chrome
extension, which only runs in a real Google Chrome. So this is a real Chrome
on Lucy's OWN profile (never theirs), kept out of the way.

MEASURED ON A MAC, 2026-10-05: Chrome brings ITSELF to the front whenever it
starts or opens a window -- `open -g`, `open -j`, a minimized window and a
background tab do not stop it, and the extension opens a tab of its own for
every batch. Left alone, that is the "takes up the screen" Carlos means. So:
  * Mac: Lucy's Chrome starts hidden, and for a few seconds after Lucy opens
    a window, _FocusGuard HIDES her Chrome (as Cmd-H would) the moment it
    takes the front -- which hands focus straight back to whatever the person
    was using. Needs no permission (lsappinfo + NSRunningApplication.hide;
    `lsappinfo setfront` is refused with permErr).
  * Windows: started minimized without activation; windows are minimized.
Hidden, Chrome still runs timers at full speed and takes clicks (measured: 30
of 30 ticks, click registered), because background throttling is switched off.

TO WATCH IT, click Lucy's Chrome in the Dock / taskbar. The guard only acts
right after Lucy herself opened something, so a person bringing it forward
is left alone.

THEIR OWN APPSTREAM LOGIN, signed in by us with the 30s waits that clear the
security box (resources/lucy-login-standard.md rule 1). Their account sees
only their office, so the push can only reach their office (rule 3).

ONE OFFICE, ONE MACHINE. When an office starts pushing from here, take it out
of ROTATION_BY_MACHINE in automations/applicant_push/offices.py, or Lucy 2/4
and this machine both push it.

    python -m automations.icd_alerts.resume_push            # dry run, visible
    python -m automations.icd_alerts.resume_push --live     # really sends
    python -m automations.icd_alerts.resume_push --setup    # install Resume Helper

SEND TO AI CANNOT BE UNDONE. The command line is a dry run unless --live.
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
from automations.icd_alerts import push_batch as B

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# Resume Helper, the extension AppStream's batch page relies on. When it is
# missing, AppStream's robot button sends you to its Web Store page instead.
EXT_ID = "goofbdglmeckblcbcoffnkdnmpehhhmo"
STORE_URL = "https://chromewebstore.google.com/detail/" + EXT_ID

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


B.set_log(_log)


# --- who pushes ----------------------------------------------------------------
def push_record() -> dict:
    """The enrollment on this machine that asked for resume pushing, or {}."""
    for r in C.enrollments():
        if isinstance(r, dict) and r.get("push_resumes"):
            return r
    return {}


def enabled() -> bool:
    return bool(push_record()) and bool(C.appstream_creds())


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


def extension_installed() -> bool:
    return (PROFILE_DIR / "Default" / "Extensions" / EXT_ID).is_dir()


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

    ONLY right after Lucy opened something (expect()), so a person clicking
    her Chrome in the Dock to watch is not fought. Polls only inside that
    window, so it costs nothing the rest of the time.
    """

    WINDOW_SECONDS = 4.0
    POLL_SECONDS = 0.1

    def __init__(self):
        import threading
        self._until = 0.0
        self._pids = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
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

    def _loop(self):
        theirs = 0
        while not self._stop.is_set():
            if time.time() < self._until:
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
            self._stop.wait(self.POLL_SECONDS)


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
            # The extension opens its own tab to read resumes, and Chrome
            # comes forward with it. Give the focus straight back.
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


def setup_extension(log=_log, wait_seconds: int = 300) -> bool:
    """Open Resume Helper's store page in LUCY'S Chrome and wait for the click.

    Their own Chrome having it does nothing for Lucy -- an extension belongs
    to a browser profile, and this is a different one. One click, once.
    """
    if extension_installed():
        log("Resume Helper is already installed in Lucy's Chrome")
        return True
    from patchright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, ctx, page = _connect(p, background=False, url=STORE_URL)
        if not page:
            return False
        try:
            page.goto(STORE_URL, wait_until="domcontentloaded", timeout=45_000)
            page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if extension_installed():
                log("Resume Helper is installed")
                return True
            time.sleep(3)
    log("Resume Helper was not added")
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


def push(live: bool, scheduled: bool = False) -> int:
    """One push. 0 = done (or nothing to do), 1 = failed."""
    if not C.appstream_creds():
        _log("no AppStream login saved -- nothing to push with")
        return 1
    C.APP_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(str(time.time()))
    st = _state()
    st["last_start"] = dt.datetime.now().isoformat(timespec="seconds")
    _save_state(st)
    result, out, guard = "ok", {}, None
    try:
        if not extension_installed():
            result = "no_extension"
            _report_once(result, "Resume Helper is not installed in Lucy's "
                                 "Chrome, so resumes cannot be pushed",
                         "Fix on that computer: python -m "
                         "automations.icd_alerts.resume_push --setup")
            return 1
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
            try:
                out = B.run_batch(page, dry_run=not live)
            except B.ExtractionStalled as e:
                result = "stalled"
                _log("extract stalled: %s" % e)
                return 1
            if not out.get("reached"):
                result = "no_batch_page"
                _report_once(result, "the resume push could not reach Process "
                                     "in Batches on AppStream")
                return 1
            # LEAVE CHROME RUNNING, minimized. The next tick reuses it, so the
            # session and the security check it already passed carry over.
            _log("%s: %s waiting, %s still unread, %d sent to AI"
                 % ("LIVE" if live else "DRY RUN", out.get("waiting"),
                    out.get("left"), out.get("sent", 0)))
            return 0
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
        if out:
            day = dt.date.today().isoformat()
            sent = st.get("sent_by_day") or {}
            sent = {k: v for k, v in sent.items() if k >= (
                dt.date.today() - dt.timedelta(days=14)).isoformat()}
            sent[day] = int(sent.get(day, 0)) + int(out.get("sent", 0))
            st["sent_by_day"] = sent
            st["waiting"] = out.get("waiting")
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
                    help="add Resume Helper to Lucy's Chrome")
    ap.add_argument("--check-login", action="store_true",
                    help="sign in to AppStream and stop")
    args = ap.parse_args(argv)
    if args.setup:
        return 0 if setup_extension() else 1
    if args.check_login:
        rc = check_login()
        if rc == NO_CHROME:
            _log("could not open Lucy's Chrome, so the login was not tried")
        return rc
    return push(live=args.live, scheduled=args.scheduled)


if __name__ == "__main__":
    sys.exit(main())
