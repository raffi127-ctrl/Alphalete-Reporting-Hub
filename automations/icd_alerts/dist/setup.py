"""Set up Alphalete Alerts on this computer. Run by the double-click installer.

ONE SCRIPT FOR BOTH PLATFORMS. The Mac .command and the Windows .bat do nothing
but find a Python and hand over to this file, because every line duplicated
between a shell script and a PowerShell script is a line that will be fixed in
one of them and not the other -- and the Windows half is the one nobody can
test until an ICD runs it.

WHAT IT ASKS FOR: their SaraPlus login and their OwnerVille login. Nothing
else. The office key, the relay url and the relay key are already in
install.json, filled in when this package was built for this office, so there
is no code for anyone to mistype. See `automations/icd_alerts/package.py`.

NEITHER PASSWORD LEAVES THIS COMPUTER. Both are written to the user's own
config directory and used to sign in from here. What gets sent to the reporting
team is counts, and nothing else.

THE OWNERVILLE LOGIN IS THEIR OWN, and that is the point: an owner's account
sees their own office natively, so the knocks read needs no impersonation --
which is the flakiest step in the knocks stack when we do it from our side.

Python 3.8-safe: this runs on whatever Python an ICD's laptop happens to have.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "Alphalete Alerts"
HOME = Path.home()
BASE = HOME / ".alphalete-alerts"
APP_DIR = BASE / "app"
VENV_DIR = BASE / "venv"
CONFIG_DIR = HOME / ".config" / "alphalete-alerts"
HERE = Path(__file__).resolve().parent

IS_WINDOWS = platform.system() == "Windows"
TASK_NAME = "AlphaleteAlerts"
PLIST_LABEL = "com.alphalete.icd-alerts"
EVERY_MINUTES = 15


def say(msg=""):
    print(msg, flush=True)


def step(n, total, msg):
    say("\n[%d/%d] %s" % (n, total, msg))


def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def run(args, **kw):
    """Run a command, showing nothing unless it fails."""
    proc = subprocess.run([str(a) for a in args], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, **kw)
    if proc.returncode != 0:
        say(proc.stdout.decode("utf-8", "replace")[-3000:])
    return proc.returncode


# --- steps ------------------------------------------------------------------
def copy_app():
    src = HERE / "automations"
    if not src.is_dir():
        raise SystemExit("This installer is missing its program files. Please "
                         "ask the reporting team to send the whole folder "
                         "again, not just the installer.")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    dest = APP_DIR / "automations"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def make_venv():
    if venv_python().exists():
        return
    if run([sys.executable, "-m", "venv", str(VENV_DIR)]) != 0:
        raise SystemExit(
            "Could not set up the program's private Python folder. Please send "
            "the reporting team a photo of this window.")


def install_deps():
    py = venv_python()
    run([py, "-m", "pip", "install", "--upgrade", "--quiet", "pip"])
    # certifi is named explicitly, not left to patchright's dependency list: a
    # python.org Python on macOS ships with no CA bundle at all, and without it
    # every single relay dies with a certificate error that reads like a broken
    # internet connection.
    if run([py, "-m", "pip", "install", "--quiet", "patchright", "certifi"]) != 0:
        raise SystemExit(
            "Could not download the program's components. This is usually a "
            "company firewall or a dropped connection -- try again on a normal "
            "wifi network, and tell the reporting team if it keeps happening.")


def install_browser():
    # The browser is ~150MB and this is the slow step, so it says so.
    say("      downloading the browser it uses (this takes a few minutes)...")
    if run([venv_python(), "-m", "patchright", "install", "chromium"]) != 0:
        raise SystemExit(
            "Could not download the browser. Try again on a normal wifi "
            "network; if it keeps failing, tell the reporting team.")


def write_install_json():
    src = HERE / "install.json"
    if not src.is_file():
        raise SystemExit("This installer is missing its setup file. Ask the "
                         "reporting team to send your folder again.")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    rec = json.loads(src.read_text())
    target = CONFIG_DIR / "install.json"
    if target.exists():                       # keep anything already there
        try:
            existing = json.loads(target.read_text())
            existing.update(rec)
            rec = existing
        except ValueError:
            pass
    target.write_text(json.dumps(rec, indent=2))
    return rec


def _ask_one(filename, title, user_label, user_field, pass_field):
    """Ask for one login, or keep the one already saved.

    Asked one at a time with its own heading. Two username boxes and two
    password boxes on one screen is how somebody puts their SaraPlus password
    in the OwnerVille box and then cannot be told why nothing works.
    """
    import getpass
    path = CONFIG_DIR / filename
    if path.exists():
        say("      A %s login is already saved on this computer." % title)
        if input("      Enter it again? (y/N): ").strip().lower() not in ("y", "yes"):
            return True
    say()
    say("      --- %s ---" % title)
    user = input("      %s: " % user_label).strip()
    password = getpass.getpass("      %s password (typing is hidden): " % title)
    if not user or not password:
        say("      Nothing entered -- skipped. You can run this installer "
            "again later.")
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({user_field: user, pass_field: password}))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return True


def ask_for_login():
    say()
    say("      Both passwords stay on THIS computer and are never sent to")
    say("      anyone. Only the counts they produce are sent.")
    sara = _ask_one("saraplus-creds.json", "SaraPlus", "SaraPlus email",
                    "email", "password")
    _ask_one("ownerville-creds.json", "OwnerVille", "OwnerVille username",
             "username", "password")
    if not sara:
        raise SystemExit(
            "The SaraPlus login is the one this cannot run without. Run the "
            "installer again when you have it.")


def check_account() -> bool:
    say("      signing in to SaraPlus to make sure it works...")
    proc = subprocess.run(
        [str(venv_python()), "-m", "automations.icd_alerts.run", "--check"],
        cwd=str(APP_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode("utf-8", "replace")
    for line in out.splitlines():
        if line.strip() and not line.startswith("[icd_alerts]"):
            say("      " + line.strip())
    return proc.returncode == 0


# --- scheduling -------------------------------------------------------------
def schedule_mac():
    plist = HOME / "Library" / "LaunchAgents" / ("%s.plist" % PLIST_LABEL)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string>
    <string>-m</string>
    <string>automations.icd_alerts.run</string>
    <string>--once</string>
    <string>--if-due</string>
  </array>
  <key>WorkingDirectory</key><string>{cwd}</string>
  <key>StartInterval</key><integer>{seconds}</integer>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
</dict>
</plist>
""".format(label=PLIST_LABEL, python=venv_python(), cwd=APP_DIR,
           seconds=EVERY_MINUTES * 60, log=CONFIG_DIR / "agent.log"))
    subprocess.run(["launchctl", "unload", str(plist)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["launchctl", "load", str(plist)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def schedule_windows():
    # schtasks cannot set a working directory, so it runs a one-line wrapper
    # that cds first. pythonw.exe, not python.exe: python.exe flashes a console
    # window every 15 minutes, which somebody would rightly close.
    pyw = VENV_DIR / "Scripts" / "pythonw.exe"
    runner = pyw if pyw.exists() else venv_python()
    bat = BASE / "run-agent.bat"
    bat.write_text('@echo off\r\ncd /d "%s"\r\n"%s" -m automations.icd_alerts.run '
                   '--once --if-due\r\n' % (APP_DIR, runner))
    subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/TR",
                    '"%s"' % bat, "/SC", "MINUTE", "/MO", str(EVERY_MINUTES),
                    "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    say("=" * 62)
    say("  %s -- setup" % APP_NAME)
    say("=" * 62)

    total = 7
    step(1, total, "Copying the program onto this computer")
    copy_app()

    step(2, total, "Setting up its private Python")
    make_venv()

    step(3, total, "Downloading the components it needs")
    install_deps()

    step(4, total, "Getting the browser it uses")
    install_browser()

    step(5, total, "Reading your office's settings")
    rec = write_install_json()
    say("      office: %s" % rec.get("office_key", "?"))

    step(6, total, "Your SaraPlus login")
    ask_for_login()
    ok = check_account()

    step(7, total, "Setting it to run through the day")
    if IS_WINDOWS:
        schedule_windows()
    else:
        schedule_mac()
    say("      it will check every %d minutes, 10am to 9:30pm "
        "(4pm Saturdays), and never on Sunday." % EVERY_MINUTES)

    say()
    say("=" * 62)
    if ok:
        say("  All set. You do not need to do anything else.")
        say("  Leave this computer on and connected during selling hours.")
    else:
        say("  Setup finished, but SaraPlus did not check out (see above).")
        say("  Send that message to the reporting team -- everything else")
        say("  is installed and will start working once it is sorted.")
    say("=" * 62)
    say()
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        say("\nStopped. Nothing was changed.")
        sys.exit(1)
