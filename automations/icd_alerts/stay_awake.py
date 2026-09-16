"""Keep the office machine awake, and say plainly whether it worked.

THE MACHINE GOING TO SLEEP IS THE FAILURE THIS SYSTEM HAS MOST OFTEN. The
installer already turns laptops away, but a desktop that dims out at 20:00
with the office still knocking is the same silence: the channel simply stops,
and the first anybody knows is a nudge two hours later.

TWO LAYERS, because they fail differently.

  caffeinate  -- needs no password, so it is the one that actually gets
                 installed everywhere. Held open by its own LaunchAgent with
                 KeepAlive, so it comes back if it is killed and starts again
                 at login. It holds only while it runs.
  pmset       -- the real system setting, which survives everything. Needs an
                 administrator password, which plenty of ICDs do not have and
                 none of them expect to be asked for mid-install. Offered,
                 never required: declining leaves caffeinate doing the work.

WHAT THIS DELIBERATELY DOES NOT DO: turn on automatic login. A LaunchAgent
only runs once somebody is logged in, so auto-login is genuinely the last gap
after a restart -- but it is a security setting on a machine we do not own,
storing a decryptable password, and nobody asked us to. status() reports
whether it is on so the gap is visible, and that is where we stop.

AND IT REPORTS. Every safeguard here can fail quietly: a declined password, a
managed Mac that ignores pmset, an MDM profile that puts the sleep timer
straight back. Assuming it worked is how we would end up certain a machine
stays awake while it sleeps every night, so apply() returns what it actually
achieved and the relay carries that upstream.
"""
from __future__ import annotations

import os
import platform
import subprocess
from typing import Dict, List, Optional

HOME = os.path.expanduser("~")
CAFFEINE_LABEL = "com.alphalete.lucyreports.awake"

# -d display, -i idle system sleep, -m disk. NOT -s: that one is honoured only
# on AC power, so on the one laptop we knowingly allow it would assert nothing
# while quietly looking identical to a working flag.
CAFFEINATE_ARGS = ["-d", "-i", "-m"]

# What a machine that stays up looks like, in pmset's own words.
PMSET_WANTED = {"sleep": "0", "displaysleep": "0", "disksleep": "0"}


# NAMED, for the same reason boot_schedule's is: macOS labels an unprompted
# dialog "osascript", and being asked for your password by something you do
# not recognise is a thing people are right to refuse.
PROMPT = ("Lucy Reports needs permission to stop this Mac going to sleep, so "
          "your numbers keep posting.\n\nEnter the password you use to log "
          "in to this computer.")


def _run(cmd: List[str], timeout: int = 20) -> "subprocess.CompletedProcess":
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


# --- the no-password layer --------------------------------------------------
def caffeinate_plist_path() -> str:
    return os.path.join(HOME, "Library", "LaunchAgents",
                        "%s.plist" % CAFFEINE_LABEL)


def install_caffeinate() -> bool:
    """A LaunchAgent that holds `caffeinate` open forever.

    KeepAlive rather than StartInterval: caffeinate asserts only while its
    process is alive, so the agent's job is to make sure that process never
    stays dead -- after a crash, a logout, or somebody tidying up Activity
    Monitor.
    """
    if platform.system() != "Darwin":
        return False
    path = caffeinate_plist_path()
    args = "".join("    <string>%s</string>\n" % a for a in CAFFEINATE_ARGS)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string>
%s  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
""" % (CAFFEINE_LABEL, args))
        _run(["launchctl", "unload", path])
        _run(["launchctl", "load", path])
        return True
    except Exception:  # noqa: BLE001 — a safeguard must never fail an install
        return False


def caffeinate_running() -> bool:
    """Is OUR caffeinate holding the assertion right now?

    Asked of pmset rather than of our own plist, because a loaded agent whose
    process is dying on a loop looks installed and asserts nothing.

    IT MUST BE OURS. The system-wide summary at the top of `pmset -g
    assertions` reads PreventUserIdleSystemSleep 1 whenever ANYTHING holds it
    -- and on a Mac with the screen on, powerd holds it itself, named "Prevent
    sleep while display is on". Believing that line reported every machine
    with a lit screen as permanently awake, right up until the display slept
    and took the assertion with it. So this reads the by-owning-process list
    underneath and insists on seeing caffeinate's own name there.
    """
    if platform.system() != "Darwin":
        return False
    try:
        out = _run(["pmset", "-g", "assertions"]).stdout.decode(
            "utf-8", "replace")
    except Exception:  # noqa: BLE001
        return False
    for line in out.splitlines():
        if "(caffeinate)" not in line:
            continue
        if ("PreventUserIdleSystemSleep" in line
                or "NoIdleSleepAssertion" in line):
            return True
    return False


# --- the real setting, if they can approve it -------------------------------
def pmset_command() -> str:
    pairs = " ".join("%s %s" % (k, PMSET_WANTED[k])
                     for k in sorted(PMSET_WANTED))
    # autorestart brings a desktop back by itself after a power cut, which is
    # the other way an office goes quiet overnight without anybody touching
    # it. Harmless on a machine that does not support it.
    return "pmset -a %s autorestart 1" % pairs


def apply_pmset(ask: bool = True) -> bool:
    """Ask for the administrator password ONCE, through the normal Mac box.

    osascript's own prompt, not a typed password anywhere near us: it is the
    dialog they already know, it goes to the system, and this code never sees
    what they type. Declining is an ordinary outcome, not an error -- it
    returns False and the install carries on.
    """
    if platform.system() != "Darwin" or not ask:
        return False
    script = ('do shell script "%s" with administrator privileges '
              'with prompt "%s"' % (pmset_command(), PROMPT))
    try:
        proc = _run(["osascript", "-e", script], timeout=180)
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def pmset_values() -> Dict[str, str]:
    """What the machine is ACTUALLY set to, whoever set it."""
    if platform.system() != "Darwin":
        return {}
    try:
        out = _run(["pmset", "-g", "custom"]).stdout.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return {}
    found = {}
    # `pmset -g custom` prints an AC block and a battery block. A desktop has
    # only the one; on the allowed laptop the LAST value wins, which is the
    # battery block -- the pessimistic half, and the half that decides whether
    # it goes quiet when somebody pulls the plug.
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in PMSET_WANTED:
            found[parts[0]] = parts[1]
    return found


def pmset_ok() -> bool:
    vals = pmset_values()
    if not vals:
        return False
    return all(vals.get(k) == v for k, v in PMSET_WANTED.items())


# --- the gap we report but do not close -------------------------------------
def autologin_on() -> Optional[bool]:
    """True/False, or None when we genuinely cannot tell.

    None is not False. A LaunchAgent needs a logged-in user, so this is the
    difference between "comes back by itself after a restart" and "waits for
    somebody to walk in" -- and guessing False would put a machine on a list
    of problems it may not have.
    """
    if platform.system() != "Darwin":
        return None
    try:
        out = _run(["defaults", "read",
                    "/Library/Preferences/com.apple.loginwindow",
                    "autoLoginUser"])
    except Exception:  # noqa: BLE001
        return None
    if out.returncode != 0:
        return False
    return bool((out.stdout or b"").strip())


# --- windows ----------------------------------------------------------------
def apply_windows() -> bool:
    """The same intent in powercfg's vocabulary.

    Windows has still never been exercised for real, so this stays to the two
    settings that need no administrator: the ACTIVE power scheme's timeouts.
    A machine where those are locked by policy reports False rather than
    pretending.
    """
    if platform.system() != "Windows":
        return False
    ok = True
    for args in (["/change", "standby-timeout-ac", "0"],
                 ["/change", "monitor-timeout-ac", "0"],
                 ["/change", "disk-timeout-ac", "0"],
                 ["/change", "hibernate-timeout-ac", "0"]):
        try:
            if _run(["powercfg"] + args).returncode != 0:
                ok = False
        except Exception:  # noqa: BLE001
            ok = False
    return ok


def windows_ok() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        out = _run(["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP"])
        text = (out.stdout or b"").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return False
    # 0x00000000 is "never". Any non-zero AC index means it still sleeps.
    for line in text.splitlines():
        if "Current AC Power Setting Index" in line:
            if line.strip().split()[-1] not in ("0x00000000", "0"):
                return False
    return True


# --- what actually happened -------------------------------------------------
def status() -> Dict:
    """Read the machine, do not remember what we tried.

    Everything here is asked of the system fresh. A setting an MDM profile put
    back an hour after the install has to read as off, or the report becomes a
    record of our intentions instead of the machine's state.
    """
    if platform.system() == "Windows":
        return {"os": "Windows", "never_sleeps": windows_ok(),
                "holder": False, "setting": windows_ok(), "autologin": None}
    holder = caffeinate_running()
    setting = pmset_ok()
    return {"os": platform.system(),
            # EITHER layer is enough to stay awake. Both is better, because
            # caffeinate alone dies with the login session.
            "never_sleeps": bool(holder or setting),
            "holder": holder,
            "setting": setting,
            "autologin": autologin_on()}


def apply(ask_for_password: bool = True, log=None) -> Dict:
    """Install the safeguards. Returns status() read back afterwards."""
    def say(msg):
        if log:
            log(msg)

    if platform.system() == "Windows":
        apply_windows()
        st = status()
        say("      never sleeps: %s" % ("yes" if st["never_sleeps"] else "no"))
        return st

    if install_caffeinate():
        say("      this computer is now held awake while it is logged in")
    else:
        say("      could not install the stay-awake helper")

    if ask_for_password:
        say("      asking for your Mac password, to stop it sleeping for good")
        if apply_pmset():
            say("      done — sleep is switched off on this computer")
        else:
            # NOT AN ERROR AND NOT SILENT. An office that skipped this is one
            # whose machine sleeps the moment it is logged out, and that is
            # worth knowing here rather than discovering from a quiet channel.
            say("      skipped — the helper above still keeps it awake while "
                "somebody is logged in")

    st = status()
    if not st["never_sleeps"]:
        say("      WARNING: this computer can still go to sleep")
    return st
