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

import ask

APP_NAME = "Alphalete Alerts"
_PRIVACY = ("This stays on this computer and is never sent to anyone. "
            "Only the report counts are sent.")
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


def _ask_one(filename, title, user_label, user_field, pass_field, required):
    """Ask for one login in a real dialog box, or keep the one already saved.

    ONE LOGIN AT A TIME, each in its own box naming the system it belongs to.
    Two username fields and two password fields on one screen is how somebody
    puts their SaraPlus password in the OwnerVille box and then cannot be told
    why nothing works.
    """
    path = CONFIG_DIR / filename
    if path.exists():
        say("      A %s login is already saved." % title)
        return True

    say("      asking for the %s login (look for the pop-up box)..." % title)
    try:
        user = ask.text("%s\n\nYour %s %s:"
                        % (_PRIVACY, title, user_label)).strip()
        if not user:
            raise ask.Cancelled()
        password = ask.password("Your %s password:" % title)
        if not password:
            raise ask.Cancelled()
    except ask.Cancelled:
        if required:
            ask.message("Setup needs your %s login to continue.\n\n"
                        "Nothing was saved. Open the installer again when you "
                        "have it." % title, error=True)
            raise SystemExit(1)
        say("      skipped -- you can add it later by running this again.")
        return False

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({user_field: user, pass_field: password}))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    say("      %s login saved on this computer." % title)
    return True


def ask_for_login():
    sara = _ask_one("saraplus-creds.json", "SaraPlus", "email",
                    "email", "password", required=True)
    _ask_one("ownerville-creds.json", "OwnerVille", "username",
             "username", "password", required=False)
    return sara


def ask_for_channel():
    """Where should this office's alerts go? Their answer is a REQUEST.

    Asked here rather than decided for them, because nobody on our side knows
    which room an office wants -- and a guess lands in front of their whole
    team, which is not a thing you undo. Nothing is posted anywhere until
    somebody on the reporting team approves the answer, so a typo costs a
    conversation and not a misdirected alert.
    """
    rec = json.loads((CONFIG_DIR / "install.json").read_text())
    current = rec.get("requested_channel", "")
    if current:
        say("      already asked for: %s" % current)
        return current

    say("      asking where the alerts should go (look for the pop-up box)...")
    try:
        answer = ask.text(
            "Which Slack channel should these alerts be posted in?\n\n"
            "For example:  #palace-sales\n\n"
            "If you are not sure, leave this blank and the reporting team "
            "will check with you.").strip()
    except ask.Cancelled:
        answer = ""

    if answer:
        if not answer.startswith("#"):
            answer = "#" + answer.lstrip("#")
        say("      noted: %s (the reporting team will confirm it)" % answer)
    else:
        say("      left blank -- the reporting team will check with you.")

    rec["requested_channel"] = answer
    (CONFIG_DIR / "install.json").write_text(json.dumps(rec, indent=2))
    return answer


# The answers offered for the knocks report. A FIXED SET, because every one of
# them has to turn into a schedule -- and because an owner should not have to
# guess what we can do. "No thanks" is a real answer and is offered plainly:
# an office that does not want this should not have to cancel it later.
KNOCKS_OPTIONS = [
    "Once at the end of the night",
    "Twice a day - midday and end of night",
    "Every hour during selling hours",
    "No knocks report, thanks",
]
KNOCKS_SAME = "The same channel as my credit-check alerts"
KNOCKS_OTHER = "A different channel"


def ask_about_knocks():
    """How often the office wants their knocks report, and where it goes.

    ASKED HERE so nobody has to be chased for it later, and so the answer
    arrives with the install rather than as a separate conversation. Like the
    channel, it is a REQUEST: it lands on the reporting team's sheet and
    somebody sets it up.
    """
    rec = json.loads((CONFIG_DIR / "install.json").read_text())
    if rec.get("requested_knocks_frequency"):
        say("      already asked for: %s" % rec["requested_knocks_frequency"])
        return

    say("      asking about the knocks report (look for the pop-up box)...")
    try:
        how_often = ask.choose(
            "How often would you like your knocks report?", KNOCKS_OPTIONS)
    except ask.Cancelled:
        say("      skipped -- the reporting team will check with you.")
        return

    channel = ""
    if not how_often.startswith("No knocks report"):
        try:
            where = ask.choose("Where should the knocks report be posted?",
                               [KNOCKS_SAME, KNOCKS_OTHER])
            if where == KNOCKS_OTHER:
                channel = ask.text(
                    "Which Slack channel should the knocks report go to?\n\n"
                    "For example:  #palace-sales").strip()
                if channel and not channel.startswith("#"):
                    channel = "#" + channel.lstrip("#")
            else:
                channel = rec.get("requested_channel", "")
        except ask.Cancelled:
            channel = rec.get("requested_channel", "")

    rec["requested_knocks_frequency"] = how_often
    rec["requested_knocks_channel"] = channel
    (CONFIG_DIR / "install.json").write_text(json.dumps(rec, indent=2))
    say("      noted: %s%s" % (how_often,
                               (" -> %s" % channel) if channel else ""))


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

    total = 9
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

    step(6, total, "Your logins")
    ask_for_login()
    ok = check_account()

    step(7, total, "Where your alerts should go")
    ask_for_channel()

    step(8, total, "Your knocks report")
    ask_about_knocks()

    step(9, total, "Setting it to run through the day")
    if IS_WINDOWS:
        schedule_windows()
    else:
        schedule_mac()
    say("      it will check every %d minutes, 10am to 9:30pm "
        "(4pm Saturdays), and never on Sunday." % EVERY_MINUTES)

    say()
    say("=" * 62)
    if ok:
        done = ("All set — you do not need to do anything else.\n\n"
                "Just leave this computer on and connected to the internet "
                "during selling hours.\n\n"
                "The reporting team will confirm which Slack channel your "
                "alerts go to, and they will start appearing there.\n\n"
                "You can close the black window behind this box.")
        say("  All set.")
    else:
        done = ("Everything is installed, but signing in to SaraPlus did not "
                "work.\n\nPlease tell the reporting team — they can sort it "
                "out from their end. Nothing else needs doing on this "
                "computer.")
        say("  Installed, but SaraPlus did not check out.")
    say("=" * 62)
    ask.message(done, error=not ok)
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        say("\nStopped. Nothing was changed.")
        sys.exit(1)
