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

from automations.icd_alerts import dialogs as ask

# DISPLAY NAME ONLY. BASE, CONFIG_DIR and PLIST_LABEL below stay
# "lucy-reports": two offices already have those paths on disk, and
# renaming them would orphan their installs (Megan 2026-09-13).
APP_NAME = "Lucy ECOsystem"
_PRIVACY = ("This stays on this computer and is never sent to anyone. "
            "Only the report counts are sent.")
HOME = Path.home()
BASE = HOME / ".lucy-reports"
APP_DIR = BASE / "app"
VENV_DIR = BASE / "venv"
CONFIG_DIR = HOME / ".config" / "lucy-reports"
HERE = Path(__file__).resolve().parent

IS_WINDOWS = platform.system() == "Windows"
TASK_NAME = "LucyReports"
PLIST_LABEL = "com.alphalete.lucy-reports"
# TWO (was three, 2026-09-14: Megan, "we can make it tighter"). The total lag
# is this plus the poster's tick, now sixty seconds -- so the worst case is
# three minutes and the typical case is about ninety seconds.
#
# NOT ONE. The floor is the sweep itself: three SaraPlus report passes, ~30-60s
# against a session the Chrome profile keeps warm. At a one-minute tick a slow
# sweep is still running when the next one is due, and this is an ICD's working
# laptop -- a browser going back-to-back all day is a cost somebody feels. Two
# keeps the duty cycle under half. It is the laptop's own SaraPlus account, so
# no office is competing with another for a rate limit.
#
# THE NUMBER IS ALSO IN sweep_cadence.py, which is what retimes the offices
# that are ALREADY installed -- this one only ever reaches a fresh install.
# test_sweep_cadence keeps the two honest.
EVERY_MINUTES = 2


# READABLE ON ANY BACKGROUND, which is the only requirement that actually
# matters here. Alphalete's red (#B93037) reads on both light and dark, so it
# carries the brand; everything else uses the terminal's OWN foreground, bold
# or plain. The gold went the same way as the background repaint: #C1B38F is
# lovely on near-black and nearly invisible on the default white, and we do
# not get to choose which one an owner has.
#
# NO_COLOR is honoured because it is the one thing a person can set when our
# colours are wrong on their machine.
_TTY = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
RED = "\033[38;2;185;48;55m" if _TTY else ""
GOLD = "\033[1m" if _TTY else ""          # bold, not a colour
DIM = "" if _TTY else ""                   # the terminal's own foreground
BOLD = "\033[1m" if _TTY else ""
OFF = "\033[0m" if _TTY else ""


def say(msg=""):
    print(msg, flush=True)


def banner():
    bar = "\u2501" * 58
    say("")
    say("  %s%s%s" % (RED, bar, OFF))
    say("  %s%sLUCY REPORTS%s   %sAlphalete Marketing%s"
        % (BOLD, GOLD, OFF, DIM, OFF))
    say("  %s%s%s" % (RED, bar, OFF))


def step(n, total, msg):
    say("")
    say("  %s%s%d of %d%s  %s%s%s"
        % (BOLD, RED, n, total, OFF, GOLD, msg, OFF))


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

    # ADDING A CAMPAIGN, NOT REPLACING THE MACHINE. An office that runs two
    # campaigns enrols twice and pastes two lines on the SAME computer
    # (Megan 2026-09-15). Overwriting here -- which is what this used to do --
    # would have left the second install running and the first one's key
    # stranded, with an office quietly losing a board it had already been
    # approved for.
    #
    # Keyed on office_key, so re-running the SAME code updates that campaign
    # instead of giving the machine two of it. Re-running is how somebody
    # fixes a wrong answer, and it has to be safe.
    existing = []
    if target.exists():
        try:
            prior = json.loads(target.read_text())
            existing = prior if isinstance(prior, list) else [prior]
        except ValueError:
            existing = []
    key = str(rec.get("office_key", "")).strip().lower()
    merged = [r for r in existing
              if isinstance(r, dict)
              and str(r.get("office_key", "")).strip().lower() != key]
    # Carry forward anything the earlier record had for THIS campaign -- the
    # channels they asked for, their OwnerVille name -- so a re-run does not
    # lose answers the relay is no longer sending.
    prior_same = next((r for r in existing
                       if isinstance(r, dict)
                       and str(r.get("office_key", "")).strip().lower() == key),
                      {})
    combined = dict(prior_same)
    combined.update(rec)
    merged.append(combined)
    target.write_text(json.dumps(merged, indent=2))
    if len(merged) > 1:
        say("      this computer now runs %d campaigns: %s"
            % (len(merged), ", ".join(str(r.get("campaign") or "att")
                                      for r in merged)))
    return combined


def _ask_one(filename, title, user_label, user_field, pass_field, required,
             replace=False):
    """Ask for one login in a real dialog box, or keep the one already saved.

    ONE LOGIN AT A TIME, each in its own box naming the system it belongs to.
    Two username fields and two password fields on one screen is how somebody
    puts their SaraPlus password in the OwnerVille box and then cannot be told
    why nothing works.
    """
    path = CONFIG_DIR / filename
    if path.exists() and not replace:
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


def confirm_office(rec):
    """Make them say out loud whose office this package is for.

    CAUGHT LIVE ON THE ENROLMENT CALL (2026-09-12): Cyrus ran Kash's package
    on his own MacBook. It failed only because the folder was not there --
    had he downloaded the right zip under the wrong name, or been handed the
    wrong attachment, it would have installed perfectly and relayed his
    office's credit checks under Kash's office key, into Kash's channel, as
    Kash's numbers. Nothing downstream could have told the difference: the
    relay key would have been valid and the data plausible.

    One dialog, once, and the whole class of mistake is gone.
    """
    owner = rec.get("owner") or "this office"
    try:
        answer = ask.choose(
            "This copy of Lucy ECOsystem is set up for:\n\n    %s\n\n"
            "Is that you?" % owner,
            ["Yes, that's me", "No, that's not me"])
    except ask.Cancelled:
        raise SystemExit("Setup stopped. Nothing was changed.")

    if answer.startswith("Yes"):
        return

    ask.message(
        "Then this is the wrong copy — each office gets its own, and this one "
        "would report your numbers as %s's.\n\n"
        "Ask the reporting team to send you yours. Nothing has been changed "
        "on this computer." % owner, error=True)
    raise SystemExit(1)


def ask_for_login(replace=False):
    """Ask for both logins, keeping anything already saved unless told not to.

    ON A RE-RUN, ASK ONCE WHETHER TO KEEP THEM. Only the SaraPlus password is
    checked during setup, so a mistyped OwnerVille one is invisible here and
    surfaces days later as a knocks board that never appears. Re-running the
    installer is the only instruction we give anybody, and it has to be able
    to fix either login -- otherwise "run it again" is advice that cannot
    work, which is worse than no advice.
    """
    if not replace:
        saved = [f for f in ("saraplus-creds.json", "ownerville-creds.json")
                 if (CONFIG_DIR / f).exists()]
        if saved:
            try:
                pick = ask.choose(
                    "You already have your logins saved on this computer.\n\n"
                    "Keep them, or type them in again?",
                    ["Keep the ones I have", "Let me type them again"])
                replace = pick.startswith("Let me")
            except ask.Cancelled:
                pass

    sara = _ask_one("saraplus-creds.json", "SaraPlus", "email",
                    "email", "password", required=True, replace=replace)
    _ask_one("ownerville-creds.json", "OwnerVille", "username",
             "username", "password", required=False, replace=replace)
    return sara


def check_ownerville() -> bool:
    """Sign in to OwnerVille for real, the same way the knocks read will.

    WHY THIS IS WORTH A MINUTE. Setup verified SaraPlus and said "you are good
    to go" while accepting the OwnerVille password completely untested. Kash's
    install passed, told him everything was fine, and his knocks board then
    failed on the first run with "signed in but it did not open a working
    session" -- a message nobody was watching for, about a login nobody had
    reason to doubt (2026-09-12).

    It costs about a minute, because the security check on the password step
    only clears if it is left alone. That is the right trade against an office
    believing it is set up and silently having no board.
    """
    if not (CONFIG_DIR / "ownerville-creds.json").exists():
        return True                      # they skipped it; nothing to verify
    say("      checking the OwnerVille login (this one takes a minute)...")
    proc = subprocess.run(
        [str(venv_python()), "-m", "automations.icd_alerts.run", "--knocks",
         "--dry-run"],
        cwd=str(APP_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode == 0:
        say("      OwnerVille login works.")
        return True
    for line in proc.stdout.decode("utf-8", "replace").splitlines()[-2:]:
        if line.strip():
            say(line.strip())
    return False


def ownerville_until_it_works(attempts=2):
    """Same offer as SaraPlus: told at the moment it can still be fixed."""
    for attempt in range(1, attempts + 1):
        if check_ownerville():
            return True
        if attempt == attempts:
            break
        try:
            again = ask.choose(
                "OwnerVille did not accept that username and password.\n\n"
                "Would you like to type it again?\n\n"
                "(Your credit-check alerts work either way — this one is only "
                "for the knocks board.)",
                ["Yes, let me try again", "Skip it for now"])
        except ask.Cancelled:
            return False
        if not again.startswith("Yes"):
            return False
        _ask_one("ownerville-creds.json", "OwnerVille", "username",
                 "username", "password", required=False, replace=True)
    return False


def login_until_it_works(attempts=3):
    """Ask, check against the real SaraPlus, and offer another go on a typo.

    A PASSWORD IS TYPED WRONG SOMETIMES, and the only moment anybody is in a
    position to fix it is the moment they are sitting there being told. The
    first version saved whatever they typed, reported the failure at the very
    end, and then -- because a saved login is kept on the next run -- gave
    them no way to correct it at all. The fix was to delete a file they would
    never find.

    So the check happens here, in a loop, while they still have the dialog
    open. Re-entering replaces what is stored, because the reason we are
    asking again is that what is stored is wrong.
    """
    ask_for_login()
    for attempt in range(1, attempts + 1):
        if check_account():
            return True
        if attempt == attempts:
            break
        try:
            again = ask.choose(
                "SaraPlus did not accept that email and password.\n\n"
                "Would you like to type it again?",
                ["Yes, let me try again", "No, I will sort it out later"])
        except ask.Cancelled:
            return False
        if not again.startswith("Yes"):
            return False
        ask_for_login(replace=True)
    return False


def _install_records():
    """install.json, ALWAYS as a list.

    THE SHAPE CHANGED AND THESE READERS DID NOT. An office running two
    campaigns installs twice on one computer, so the file became a LIST of
    records -- and ask_for_ov_name(), ask_for_channel() and ask_about_knocks()
    all still called .get() on it. Carlos was the first multi-campaign office
    to install, on 2026-09-15, and his setup died at step 7 with "'list'
    object has no attribute 'get'".

    Worse than the crash: each of those three then wrote its dict straight
    back over the file. Had the read survived, the write would have thrown
    away every OTHER campaign on that machine without a word.
    """
    try:
        data = json.loads((CONFIG_DIR / "install.json").read_text())
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else [data]


def _current_key() -> str:
    """The office_key being installed right now, from the fetched record."""
    try:
        src = json.loads((HERE / "install.json").read_text())
        return str(src.get("office_key", "")).strip().lower()
    except Exception:  # noqa: BLE001
        return ""


def _load_current() -> dict:
    """This campaign's record. Never another campaign's."""
    key = _current_key()
    recs = _install_records()
    for r in recs:
        if isinstance(r, dict) and str(
                r.get("office_key", "")).strip().lower() == key:
            return r
    # A single-campaign machine written before the list shape existed.
    return recs[0] if recs and isinstance(recs[0], dict) else {}


def _save_current(rec: dict) -> None:
    """Put this campaign's record back WITHOUT touching the others."""
    key = str(rec.get("office_key", "")).strip().lower() or _current_key()
    keep = [r for r in _install_records()
            if isinstance(r, dict)
            and str(r.get("office_key", "")).strip().lower() != key]
    keep.append(rec)
    (CONFIG_DIR / "install.json").write_text(json.dumps(keep, indent=2))


def ask_for_ov_name():
    """Their name EXACTLY as OwnerVille spells it.

    Their own login already lands on their own office, so nothing needs this
    to read their knocks. It is worth asking anyway: OwnerVille spells people
    differently from every other list we keep -- Kash Rai is "Akashdeep Rai"
    there, and Cyrus Wade is "Cy Wade" in Slack -- and the only person who
    knows which spelling is on their screen is the person looking at it.

    Asked once, here, rather than worked out later from a name that did not
    match anything.
    """
    rec = _load_current()
    if rec.get("ov_name"):
        say("      already have your OwnerVille name: %s" % rec["ov_name"])
        return
    try:
        name = ask.text(
            "What is your name EXACTLY as it appears in OwnerVille?\n\n"
            "Top-right of the OwnerVille page, next to your office name. "
            "Spell it the way it is written there, even if that is not how "
            "you normally write it.").strip()
    except ask.Cancelled:
        return
    if name:
        rec["ov_name"] = name
        _save_current(rec)
        say("      noted: %s" % name)


def ask_for_channel():
    """Which Slack channel(s) the credit-check alerts go to. A REQUEST.

    A LIST, like the knocks board. An office can want the pings in more than
    one room -- the owners' channel and the rep channel -- and asking for one
    then making them come back for the second is a worse conversation than
    asking "any others?" once, here, while they are already sitting in front
    of it.

    Nobody on our side knows which room an office wants, and a guess lands in
    front of their whole team, which is not a thing you undo. Nothing is
    posted anywhere until somebody on the reporting team approves the answer,
    so a typo costs a conversation and not a misdirected alert.
    """
    rec = _load_current()
    if rec.get("requested_channels") is not None:
        say("      already asked -- %d channel(s)" % len(rec["requested_channels"]))
        return rec["requested_channels"]

    say("      asking where the alerts should go (look for the pop-up box)...")
    channels = []
    while len(channels) < MAX_ALERT_CHANNELS:
        prompt = (("Which Slack channel should these alerts be posted in?\n\n"
                   "Paste the CHANNEL ID, not the name — in Slack, click the "
                   "channel name at the top, scroll to the bottom of the "
                   "About tab, and copy the ID. It looks like C09AVM17PAR.\n\n"
                   "A #name works too if you cannot find the ID. Leave it "
                   "blank and the reporting team will check with you.")
                  if not channels else
                  "Which channel should they ALSO be posted in?\n\n"
                  "Paste its channel ID, or leave blank if that is all.")
        try:
            answer = ask.text(prompt).strip()
        except ask.Cancelled:
            break
        if not answer:
            break
        answer = _tidy_channel(answer)
        if answer not in channels:
            channels.append(answer)
            say("      noted: %s" % answer)
        if len(channels) >= MAX_ALERT_CHANNELS:
            break
        try:
            if ask.choose("Add another channel for these alerts?",
                          [ADD_NO, ADD_YES]) != ADD_YES:
                break
        except ask.Cancelled:
            break

    if not channels:
        say("      left blank -- the reporting team will check with you.")

    rec["requested_channels"] = channels
    _save_current(rec)
    return channels


KNOCKS_YES = "Yes, please"
KNOCKS_NONE = "No knocks board, thanks"
KNOCKS_OTHER = "A different channel"
ADD_YES = "Yes, add another"
ADD_NO = "No, that's all"
# A ceiling, not a limit anyone will reach. It exists so a mis-clicked dialog
# cannot loop forever on somebody's laptop.
MAX_KNOCKS_DESTINATIONS = 4
MAX_ALERT_CHANNELS = 4
HOURS_OK = "Yes, those are our hours"
HOURS_DIFFERENT = "No, ours are different"


def _ampm(hhmm):
    h, m = hhmm.split(":")
    h = int(h)
    suffix = "AM" if h < 12 else "PM"
    hour = h % 12 or 12
    return "%d:%02d %s" % (hour, int(m), suffix)


def ask_about_knocks():
    """Where the knocks board goes, and how often -- PER CHANNEL.

    An office can want it in more than one room on more than one clock (Megan
    2026-09-11: "they should be able to pick I want it posted every x min in
    this channel"), which is exactly what the disposition enrolment already
    models: a LIST of destinations, each with its own cadence, not one cadence
    shared by everywhere. The owners' room every 15 minutes and the rep channel
    once an hour is a normal answer, and a single picker cannot express it.

    Asked one destination at a time, because "how many channels?" is a question
    nobody can answer before they have been shown what a channel costs them.
    """
    rec = _load_current()
    if rec.get("requested_knocks_destinations") is not None:
        say("      already asked -- %d destination(s)"
            % len(rec["requested_knocks_destinations"]))
        return

    picker = rec.get("knocks_picker") or []
    labels = [o["label"] for o in picker]

    say("      asking about the knocks board (look for the pop-up boxes)...")
    try:
        wants = ask.choose(
            "Would you like your knocks and dispositions board posted to "
            "Slack?", [KNOCKS_YES, KNOCKS_NONE])
    except ask.Cancelled:
        say("      skipped -- the reporting team will check with you.")
        return

    destinations = []
    if wants == KNOCKS_YES:
        asked = rec.get("requested_channels") or []
        default_channel = asked[0] if asked else ""
        while len(destinations) < MAX_KNOCKS_DESTINATIONS:
            channel = _ask_knocks_channel(default_channel, len(destinations))
            if channel is None:
                break
            try:
                chosen = ask.choose(
                    "How often should the board be posted in %s?" % channel,
                    labels)
            except ask.Cancelled:
                break
            destinations.append({
                "channel": channel,
                "cadence_min": next(
                    (o["value"] for o in picker if o["label"] == chosen), None),
                "label": chosen,
            })
            say("      %s -- %s" % (channel, chosen))
            if len(destinations) >= MAX_KNOCKS_DESTINATIONS:
                break
            try:
                if ask.choose("Add another channel for the knocks board?",
                              [ADD_NO, ADD_YES]) != ADD_YES:
                    break
            except ask.Cancelled:
                break

    note = _ask_field_hours(rec) if destinations else ""

    rec["requested_knocks_destinations"] = destinations
    rec["requested_knocks_hours_note"] = note
    _save_current(rec)
    if destinations:
        say("      noted: %s" % "; ".join(
            "%s %s" % (d["channel"], d["label"]) for d in destinations))
    else:
        say("      noted: no knocks board.")


def _tidy_channel(text):
    """A channel ID stays an ID; anything else becomes #name.

    Slack IDs look like C09AVM17PAR, and prefixing one with '#' turns a value
    that resolves in a single call into a name that resolves in none.
    """
    text = (text or "").strip()
    if not text:
        return ""
    bare = text.lstrip("#").strip()
    if (len(bare) >= 9 and bare[0] in "CGD" and bare.isalnum()
            and bare.upper() == bare):
        return bare                      # an ID, left exactly as pasted
    return "#" + bare


def _ask_knocks_channel(default_channel, already):
    """Which room this destination is. None means they are done."""
    options = []
    if default_channel and not already:
        options.append("%s (same as my alerts)" % default_channel)
    options.append(KNOCKS_OTHER)
    if already:
        options.append(ADD_NO)
    try:
        pick = ask.choose(
            "Which Slack channel should the knocks board be posted in?"
            if not already else
            "Which channel should it ALSO be posted in?", options)
    except ask.Cancelled:
        return None
    if pick == ADD_NO:
        return None
    if pick != KNOCKS_OTHER:
        return default_channel
    try:
        typed = ask.text(
            "Which Slack channel?\n\nFor example:  #palace-sales").strip()
    except ask.Cancelled:
        return None
    if not typed:
        return None
    return _tidy_channel(typed)


def _ask_field_hours(rec):
    """Confirm the field hours rather than collecting them.

    The enrolment form says most offices leave these as they are, and it is
    right -- so the default is shown in their own clock and confirmed. An
    office that differs says so in their own words for a human to set. A time
    picker built out of dialog boxes would be a worse way to get an answer
    somebody is going to check anyway.
    """
    hours = dict(rec.get("knocks_default_hours") or {})
    if not hours:
        return ""
    # THEY ALREADY TOLD US, ON THE FORM, MINUTES AGO (Megan 2026-09-13: "the
    # installer shouldn't ask for the same things they are already filling out
    # on the form"). Confirming an answer somebody has just typed is the same
    # question twice, and every extra box is another place an install stalls
    # while nobody is watching.
    if rec.get("hours_from_signup"):
        say("      using the selling hours from your sign-up")
        return ""
    sat = ("Saturdays %s to %s" % (_ampm(hours["sat_start"]),
                                   _ampm(hours["sat_end"]))
           if hours.get("saturday") else "no Saturdays")
    try:
        answer = ask.choose(
            "We would only post during your field hours:\n\n"
            "Monday to Friday, %s to %s\n%s\n\nSundays are off for "
            "everyone. Is that right?"
            % (_ampm(hours["day_start"]), _ampm(hours["day_end"]), sat),
            [HOURS_OK, HOURS_DIFFERENT])
        if answer == HOURS_DIFFERENT:
            return ask.text(
                "What hours are your reps in the field?\n\n"
                "For example:  Mon-Fri 2pm to 9pm, Saturdays 11am to 5pm"
            ).strip()
    except ask.Cancelled:
        pass
    return ""


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


def first_run() -> None:
    """Sweep ONCE, right now, before the installer finishes.

    WITHOUT --if-due, deliberately. The scheduled run is fenced to selling
    hours, so an office installing at 9am would not relay anything until 10 --
    and their channel request rides along with that relay, which means nobody
    could approve them until an hour after they were sitting on the call
    asking to be set up. This is the run that makes the enrolment land while
    somebody is still there to see it.

    Never fatal: everything is installed and scheduled by this point, and a
    first sweep that fails costs a wait, not a setup.
    """
    say("      saying hello to the reporting team...")
    proc = subprocess.run(
        [str(venv_python()), "-m", "automations.icd_alerts.run", "--once"],
        cwd=str(APP_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode == 0:
        say("      done — your office is enrolled.")
        return
    for line in out.splitlines()[-3:]:
        if line.strip():
            say(line.strip())
    say("      (it will try again on its own in a few minutes — nothing is lost.)")


def seed_install_json() -> None:
    """Put the office's key where the relay can find it BEFORE step 1.

    write_install_json does this properly at step 5, with merging. This is the
    cheap early copy, and it exists for one reason: a fault cannot be reported
    without the relay key, so without it the first four steps -- copying,
    the venv, the dependencies, the browser download -- are exactly the ones
    that fail on a machine we cannot see and tell us nothing.
    """
    try:
        src_file = HERE / "install.json"
        target = CONFIG_DIR / "install.json"
        if src_file.is_file() and not target.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            target.write_text(src_file.read_text())
    except Exception:  # noqa: BLE001 — step 5 will do it properly
        pass


def report_fault(stage: str, summary: str, detail: str = "") -> None:
    """Hand a setup failure back to us. Never raises, never blocks the install.

    THIS IS THE POINT OF THE WHOLE EXERCISE (Megan 2026-09-13). An install
    that goes wrong on office #12's laptop currently produces a dialog THEY
    read and we never see, and the first we know is that no numbers ever
    arrive. The relay is the one channel out of that machine, and it already
    carries this office's key.
    """
    try:
        from automations.icd_alerts import relay as R
        R.report_fault(stage, summary, detail)
    except Exception:  # noqa: BLE001 — a diagnostic must never break a setup
        pass


def is_desktop() -> bool:
    """Ask the agent's own check, so the installer and the reports can never
    disagree about what a desktop is.

    Falls back to True if the agent package cannot be imported yet -- at this
    point in setup nothing has been copied, and refusing an office because an
    import failed is worse than letting a laptop through.
    """
    try:
        from automations.icd_alerts.relay import is_desktop as _check
        return _check()
    except Exception:  # noqa: BLE001
        return True


def require_desktop() -> bool:
    """Stop a laptop install before anything is copied onto it.

    THE MACHINE FALLING ASLEEP IS THE FAILURE THIS WHOLE SYSTEM HAS MOST
    OFTEN. A closed lid means the office's channel goes quiet and the first
    anybody knows is a nudge two hours later. An iMac or a Mac mini sits on a
    desk, plugged in, with no lid to close.

    Checked FIRST, before the program is copied or a Python is built, so a
    refusal leaves nothing behind on their machine.
    """
    if is_desktop():
        return True
    say("")
    say("  %s%sThis needs to run on a desktop.%s" % (BOLD, RED, OFF))
    # SAY WHAT IT SAW. Carlos's Mac mini was refused twice on 2026-09-15 and
    # the message gave nobody anything to act on -- the office cannot get past
    # the first step and we cannot tell from here which probe was wrong. These
    # three lines turn the next attempt into an answer instead of a guess.
    say("")
    try:
        from automations.icd_alerts import relay as _R
        say("      model reported : %r" % (_R._model_name(),))
    except Exception as _e:  # noqa: BLE001
        say("      model reported : could not read (%s)" % type(_e).__name__)
    try:
        from automations.icd_alerts import relay as _R2
        say("      battery bytes  : %d" % _R2.battery_bytes())
    except Exception as _e:  # noqa: BLE001
        say("      battery bytes  : could not read (%s)" % type(_e).__name__)
    say("      Send those two lines to the reporting team.")
    say("")
    ask.message(
        "This computer is a laptop.\n\n"
        "Lucy has to read your numbers all day, and a laptop stops the "
        "moment its lid is closed or it goes to sleep — so your channel "
        "would go quiet without anybody noticing.\n\n"
        "Please run this on a desktop that stays on in the office: an iMac, "
        "a Mac mini or a Mac Studio.\n\n"
        "Nothing has been installed on this computer.",
        error=True)
    return False


def main() -> int:
    banner()
    seed_install_json()
    if not require_desktop():
        return 1

    total = 10
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
    say("      office: %s (%s)" % (rec.get("office_key", "?"),
                                   rec.get("owner", "?")))
    confirm_office(rec)

    step(6, total, "Your logins")
    # NOT ASKED FOR A LOGIN THEY DO NOT HAVE. AT&T is the only campaign on
    # SaraPlus; a Box or Energy Wells office has no account, and asking is how
    # an install dies at step 6 with the owner certain they typed it right.
    from automations.icd_alerts import config as _C
    if _C.uses_saraplus():
        ok = login_until_it_works()
    else:
        say("      %s campaign — no SaraPlus needed, skipping that login."
            % _C.campaign())
        ok = True
    ov_ok = ownerville_until_it_works() if ok else False

    step(7, total, "Where your alerts should go")
    ask_for_ov_name()
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

    # A SCHEDULE IS WORTH NOTHING ON A SLEEPING MACHINE. The step above just
    # promised a check every few minutes; this is what makes that true at
    # 20:00 with nobody sitting at the desk (Megan 2026-09-15: "the install
    # code should also set up their machine to always be on / never sleep").
    step(10, total, "Stopping this computer going to sleep")
    awake = {}
    try:
        from automations.icd_alerts import stay_awake as _awake
        awake = _awake.apply(log=say)
    except Exception as e:  # noqa: BLE001 — never fail an install over this
        say("      could not set this up (%s)" % type(e).__name__)
    if ok:
        first_run()

    say("")
    say("  %s%s%s" % (RED, "\u2501" * 58, OFF))
    if ok:
        leave_on = ("Just leave this computer on and connected to the "
                    "internet during selling hours.\n\n")
        if awake and not awake.get("never_sleeps"):
            # SAYING "ALL SET" OVER A MACHINE THAT STILL SLEEPS is the same
            # silence this whole step exists to prevent -- they would leave it
            # on, believing that was enough, and the channel would still stop.
            leave_on = ("This computer can still go to sleep, and your alerts "
                        "stop while it does. Please set it to never sleep in "
                        "System Settings > Lock Screen, or ask whoever looks "
                        "after your computers.\n\n")
        done = ("All set — you do not need to do anything else.\n\n"
                + leave_on +
                "The reporting team will confirm which Slack channel your "
                "alerts go to, and they will start appearing there.\n\n"
                "You can close the window behind this box.")
        if not ov_ok and (CONFIG_DIR / "ownerville-creds.json").exists():
            # Say which half is short, and say it is not fatal. "All set" over
            # a broken knocks login is how an office waits a week for a board
            # that was never coming.
            done = ("Your credit-check alerts are all set.\n\n"
                    "The OwnerVille login did not work, so your knocks and "
                    "dispositions board will not post yet. Everything else is "
                    "running.\n\nOpen this installer again when you have the "
                    "right OwnerVille password, or tell the reporting team.")
        say("  %s%sAll set.%s" % (BOLD, GOLD, OFF))
    else:
        done = ("Everything is installed, but signing in to SaraPlus did not "
                "work.\n\nIf it was a typo, just open this installer again "
                "and it will ask for your login.\n\nIf you are sure the "
                "password is right, tell the reporting team — it may be that "
                "your SaraPlus account cannot see reports, which they have to "
                "fix from their end.")
        say("  %s%sInstalled, but SaraPlus did not check out.%s"
            % (BOLD, GOLD, OFF))
    say("  %s%s%s" % (RED, "\u2501" * 58, OFF))
    say("")

    # THE QUIET FAILURES. Neither of these raises -- the installer finishes,
    # tells the owner, and without this we would never hear about it. An
    # office believing it is set up while half of it is dead is precisely the
    # week-long silence this is meant to end.
    if not ok:
        report_fault("install", "SaraPlus did not verify during setup",
                     "The installer completed but could not sign in to "
                     "SaraPlus, so no alerts will be sent from this machine.")
    elif not ov_ok and (CONFIG_DIR / "ownerville-creds.json").exists():
        report_fault("install", "OwnerVille did not verify during setup",
                     "Credit-check alerts are working. The OwnerVille login "
                     "failed, so no knocks/dispositions board will post.")

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
    except BaseException as e:  # noqa: BLE001
        # A CRASH IS THE CASE WE WERE BLINDEST TO. It used to print a
        # traceback into a terminal window an ICD closes, and we would be
        # told "it didn't work" with nothing to go on.
        import traceback as _tb
        detail = _tb.format_exc()
        try:
            report_fault("install", "setup crashed: %s" % type(e).__name__,
                         detail)
        finally:
            say("\nSomething went wrong during setup.")
            try:
                ask.message(
                    "Setup hit a problem and could not finish.\n\n"
                    "The reporting team has been told what happened "
                    "automatically — you do not need to send anything.\n\n"
                    "They will get back to you.", error=True)
            except Exception:  # noqa: BLE001
                pass
        sys.exit(1)
