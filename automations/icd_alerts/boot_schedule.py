"""Make the office machine start sweeping at BOOT, with nobody logged in.

THE GAP THIS CLOSES. The agent has always installed as a LaunchAgent, which
lives in the user's own folder and only starts once somebody has logged in at
the keyboard. Kash's iMac restarted overnight on 2026-09-16, came back to the
login screen, and sat there powered on running nothing until noon -- no error,
because there is nothing to error.

Megan, the same day: "we need to make it where they don't need to keep doing
something for this to work."

NOT AUTO-LOGIN. That writes the Mac's login password to /etc/kcpassword in a
form anyone holding the disk can read back, and macOS refuses it outright
while FileVault is on. A LaunchDaemon loads at boot instead, and its UserName
key runs it as the office's own account -- so every path and both browser
profiles stay exactly where they were, no password is stored anywhere, and
FileVault can stay on.

WHY IT LIVES HERE AND NOT IN THE INSTALLER. setup.py is not shipped to the
machines; only the files in agent_files.txt are. An office already enrolled
would have needed a full re-install, which needs the enrolment code they no
longer have to hand -- the same trap the Service Cloud login fell into. This
ships, so a machine self-updates and then runs ONE line.

    python -m automations.icd_alerts.boot_schedule

The installer calls install() too, so there is one definition of what the
boot job is. Two copies is how the installer and the agent end up disagreeing
about a plist nobody can see.
"""
from __future__ import annotations

import getpass
import platform
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

# The per-login job every office runs today, and the boot job that replaces
# it. Different labels deliberately: launchd keeps agents and daemons in
# separate domains, and a machine mid-migration must never hold both.
AGENT_LABEL = "com.alphalete.lucy-reports"
LABEL = AGENT_LABEL + ".boot"

DAEMON_PATH = "/Library/LaunchDaemons/%s.plist" % LABEL

# WHAT THE PASSWORD BOX SAYS. Without `with prompt`, macOS labels the dialog
# with the name of the tool that raised it -- osascript -- which nobody
# outside this trade has heard of. Kash's office, 2026-09-16: "It's asking for
# osascript password. Idk what that is."
#
# Being asked for your password by something you do not recognise is a thing
# people are RIGHT to refuse, and our explanation was in the Terminal window
# BEHIND the dialog, where it does no good.
#
# "Your password" is also ambiguous on a Mac -- there is the login one, the
# Apple ID, and whatever they use for SaraPlus -- so it names which.
PROMPT = ("Lucy Reports needs permission to start by itself after this Mac "
          "restarts.\n\nEnter the password you use to log in to this computer.")
DEFAULT_SECONDS = 120


def agent_plist() -> Path:
    return (Path.home() / "Library" / "LaunchAgents"
            / ("%s.plist" % AGENT_LABEL))


def app_root() -> Optional[Path]:
    """The directory holding `automations/`, derived from this file so it is
    right wherever the office put it."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "automations" / "icd_alerts" / "run.py").is_file():
            return parent
    return None


def current_seconds() -> int:
    """The cadence this machine already sweeps at.

    READ, NOT ASSUMED. Offices do not all run the same interval -- Cyrus is
    on a slower one on purpose -- and a migration that quietly reset everyone
    to the default would change how often two offices post without anybody
    asking for it.
    """
    try:
        with agent_plist().open("rb") as fh:
            got = int(plistlib.load(fh).get("StartInterval") or 0)
        return got if got > 0 else DEFAULT_SECONDS
    except Exception:  # noqa: BLE001 — no agent plist, or an odd one
        return DEFAULT_SECONDS


def plist_text(seconds: Optional[int] = None) -> str:
    """The boot job.

    HOME IS SET EXPLICITLY. launchd does not reliably hand a UserName job the
    user's HOME, and every path this agent uses -- install.json, the SaraPlus
    and Service Cloud browser profiles, the logs -- hangs off it. Left to
    default it would run as the right user against the wrong home, and behave
    exactly like a machine that had never been set up.

    THE INTERPRETER IS sys.executable, which is the venv python whenever this
    is run the way it is meant to be. Spelling a path out here is what put
    "./venv/bin/python" in front of Ryan twice on 2026-09-16.
    """
    root = app_root() or Path.cwd()
    home = Path.home()
    log = home / ".config" / "lucy-reports" / "agent.log"
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>UserName</key><string>{user}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>-m</string>
    <string>automations.icd_alerts.run</string>
    <string>--once</string>
    <string>--if-due</string>
  </array>
  <key>WorkingDirectory</key><string>{cwd}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>{home}</string>
  </dict>
  <key>StartInterval</key><integer>{seconds}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
""".format(label=LABEL, user=getpass.getuser(), python=sys.executable,
           cwd=root, home=home,
           seconds=seconds or current_seconds(), log=log)


def loaded() -> bool:
    """Is it actually registered with launchd? ASKED, not assumed.

    A plist copied into /Library/LaunchDaemons that launchd never accepted is
    the worst outcome available here: the machine would report success, the
    per-login job would be removed, and the office would be quieter than
    before anybody touched it.
    """
    try:
        out = subprocess.run(["launchctl", "print", "system/" + LABEL],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, timeout=20)
        return out.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def install(seconds: Optional[int] = None, log=print) -> bool:
    """Ask for the administrator password ONCE and install the boot job.

    osascript's own dialog, the one they already know: it is handled by macOS
    and this code never sees what they type. Declining is an ordinary outcome
    -- it returns False and the machine keeps the per-login job it has.
    """
    if platform.system() != "Darwin":
        return False
    root = app_root()
    if root is None:
        log("  Could not find the installed copy — nothing changed.")
        return False

    staging = Path.home() / ".config" / "lucy-reports" / "boot.plist"
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_text(plist_text(seconds))
    cmd = " && ".join([
        "cp %s %s" % (shlex.quote(str(staging)), shlex.quote(DAEMON_PATH)),
        "chown root:wheel %s" % shlex.quote(DAEMON_PATH),
        "chmod 644 %s" % shlex.quote(DAEMON_PATH),
        "launchctl bootout system/%s 2>/dev/null; launchctl bootstrap system %s"
        % (LABEL, shlex.quote(DAEMON_PATH)),
    ])
    script = ('do shell script "%s" with administrator privileges '
              'with prompt "%s"'
              % (cmd.replace("\\", "\\\\").replace('"', '\\"'), PROMPT))
    try:
        subprocess.run(["osascript", "-e", script], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=300)
    except Exception:  # noqa: BLE001 — declining is ordinary
        return False
    finally:
        try:
            staging.unlink()
        except OSError:
            pass
    return loaded()


def unload_login_agent(log=print) -> None:
    """Drop the per-login job so the machine does not sweep twice.

    ONLY EVER AFTER loaded() SAYS YES. Removing it first and then failing to
    install the daemon would leave the office with no schedule at all.
    """
    plist = agent_plist()
    subprocess.run(["launchctl", "unload", str(plist)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        plist.unlink()
    except OSError:
        pass


def run(log=print) -> int:
    if platform.system() != "Darwin":
        log("This only applies to Macs — nothing to do.")
        return 0
    if loaded():
        log("")
        log("  Already set up — this computer starts on its own after a")
        log("  restart. Nothing to do.")
        unload_login_agent(log=log)
        return 0

    log("")
    log("  This lets the reporting computer start by itself after it")
    log("  restarts, so nobody has to log in for the numbers to run.")
    log("")
    log("  You will see the normal Mac password box. It is handled by the")
    log("  Mac — this program never sees what you type.")
    log("")
    if not install(log=log):
        log("")
        log("  Nothing changed. The computer still works exactly as it does")
        log("  now — somebody just has to log in after it restarts. You can")
        log("  run this again any time.")
        return 1
    unload_login_agent(log=log)
    log("")
    log("  Done. It now starts on its own when the computer boots, with")
    log("  nobody logged in.")
    return 0


def main(argv=None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
