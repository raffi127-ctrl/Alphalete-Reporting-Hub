"""Build one ICD's installer folder. Runs on OUR side, never on a laptop.

  python -m automations.icd_alerts.package kash

WHAT GOES IN IS THE POINT. An ICD gets the ten files the agent actually
imports, and nothing else -- not `post.py`, not `offices.py`, not the tests,
and above all not the Hub repo, which carries every office's sheet ids, channel
ids and a committed oauth client secret. Handing a contractor a clone of the
reporting codebase is not a thing to do once, let alone 52 times.

THE OFFICE KEY AND THE RELAY KEY ARE BAKED IN, so nobody types a code. The one
thing the ICD supplies is their own SaraPlus login, which never leaves their
machine.

THE BUILT FOLDER CONTAINS A SECRET -- that office's relay key -- so it is
written to output/ (gitignored) and is meant to be handed over directly, not
posted anywhere a second office could read it.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Optional

from automations.icd_alerts import offices as O

APP_SUBDIR = "program files"        # a name that says "not for you"
REPO = Path(__file__).resolve().parents[2]
DIST = Path(__file__).resolve().parent / "dist"
OUT = REPO / "output" / "icd-alerts"

# The exact closure the agent imports. Listed explicitly rather than globbed:
# a glob is how `post.py` or a test fixture ends up on somebody's laptop the
# day someone adds one.
AGENT_FILES = [
    "automations/icd_alerts/__init__.py",
    "automations/icd_alerts/config.py",
    "automations/icd_alerts/relay.py",
    "automations/icd_alerts/sara_read.py",
    "automations/icd_alerts/state.py",
    "automations/icd_alerts/run.py",
    "automations/icd_alerts/ov_read.py",
    "automations/shared/ownerville_knocks.py",
    "automations/shared/saraplus.py",
    "automations/shared/credit_check_line.py",
    "automations/shared/sale_hype.py",
    "automations/shared/browser_banner.py",
]

# The repo's automations/__init__.py installs the Hub's auto-publish hook. That
# is Hub machinery and has no business on an ICD's laptop, so the bundle gets
# this instead.
BUNDLE_INIT = '''"""Alphalete Alerts."""
'''

GATEKEEPER = """
IF NOTHING HAPPENS WHEN YOU DOUBLE-CLICK IT
    That is macOS being careful about files from the internet, not
    something being wrong. Two ways past it -- try the first, and if your
    Mac is a recent one, use the second.

    1. Right-click (or control-click) the installer, choose Open, then
       click Open again.

    2. Double-click it once and let it be blocked. Then open
       System Settings > Privacy & Security, scroll down, and you will
       see a line about "Install Lucy Reports" with an "Open Anyway"
       button. Click that, then double-click the installer again.

    You only have to do this once.
"""

README = """Lucy Reports -- {label}
{underline}

WHAT THIS IS
    Lucy watches your own SaraPlus account through the day and tells the
    reporting team when one of your reps runs a credit check -- the same
    Lucy that already posts in your team's Slack. Those alerts show up in
    {channel}.

    If you asked for it, she also posts your knocks and dispositions
    board on the schedule you picked.

TO INSTALL
{how}

    (The "program files" folder next to it is the program itself -- you
    never need to open it.)

    Boxes will pop up asking for your SaraPlus login and your OwnerVille
    login, and where you would like things posted. That is everything it
    asks for. A Lucy Reports window also opens showing its progress --
    you can ignore that one and close it at the end.
{gatekeeper}
ABOUT YOUR PASSWORDS
    They are saved on your computer only, and are used to sign in from
    your computer. They are never sent to us or to anyone else. The only
    thing that leaves your computer is the number of credit checks each
    rep has run today.

AFTER IT IS INSTALLED
    Nothing. It checks every few minutes between 10am and 9:30pm (4pm on
    Saturdays) and does nothing on Sundays. Just leave the computer on and
    connected to the internet during selling hours -- plugged in, so it
    does not go to sleep. If it does sleep, no alerts are lost; they
    simply arrive when it wakes up.

IF A BROWSER WINDOW OPENS BY ITSELF
    That is Lucy signing in to OwnerVille. It has a red bar across the
    top. Please leave it completely alone -- do not type your password
    and do not tick the security box. It clears on its own, and touching
    it stops the sign-in. The window closes by itself.

IF YOU CHANGE A PASSWORD
    Run the installer again and enter the new one. Nothing else changes.

QUESTIONS
    Tell the reporting team. Please do not share this folder with anyone --
    it contains a code that is specific to your office.
"""


def build(office_key: str, relay_key: Optional[str] = None,
          make_zip: bool = True, platform: str = "both", log=print) -> Path:
    office = O.get(office_key)
    if not office:
        raise SystemExit(
            "no office %r in offices.py. Add the row there first -- it is what "
            "decides where the alerts post and whether they post at all."
            % office_key)

    if not relay_key:
        relay_key = _relay_key_from_sheet(office.key, log=log)

    folder = OUT / ("lucy-reports-%s" % office.key)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    # EVERYTHING EXCEPT THE INSTALLER GOES IN A SUBFOLDER. An owner who
    # unzipped this saw six items -- ask.py, setup.py, install.json, a folder
    # called automations -- and told Megan "nothing happened, there are just a
    # bunch of files" (2026-09-12, live on the enrolment call). The installer
    # has no icon and does not stand out among them. Two items, one of which
    # says Install, is a folder somebody can act on.
    app = folder / APP_SUBDIR
    for rel in AGENT_FILES:
        dest = app / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dest)
    (app / "automations" / "__init__.py").write_text(BUNDLE_INIT)
    (app / "automations" / "shared" / "__init__.py").write_text("")

    for name in ("setup.py", "ask.py"):
        shutil.copy2(DIST / name, app / name)

    if platform in ("mac", "both"):
        shutil.copy2(DIST / "Install Lucy Reports.command",
                     folder / "Install Lucy Reports.command")
        (folder / "Install Lucy Reports.command").chmod(0o755)

    if platform in ("windows", "both"):
        # CRLF, always. A .bat with bare LF endings is parsed unreliably by
        # cmd.exe, and this repo is developed on a Mac -- so the file on disk
        # here has LF and would ship that way unless converted on the way out.
        bat = (DIST / "Install Lucy Reports.bat").read_text()
        (folder / "Install Lucy Reports.bat").write_bytes(
            bat.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))

    (app / "install.json").write_text(json.dumps({
        "office_key": office.key,
        "owner": office.owner,
        "relay_url": O.RELAY_URL,
        "relay_key": relay_key,
        # The knocks report IS the KNOCKS & DISPOSITIONS board that
        # disposition_signup already enrolls offices into (Megan 2026-09-11:
        # "it's the same thing"), so the installer offers ITS choices, in its
        # words, and hands back ITS canonical values. Baked in at build time
        # rather than retyped in the installer: one source of truth, and a
        # rebuilt package picks up any change to the picker for free. A second
        # vocabulary would be two things to keep in step forever.
        "knocks_picker": _knocks_picker(),
        "knocks_default_hours": _default_hours(office),
    }, indent=2))

    label = "%s (%s)" % (office.label, office.owner)
    how = {
        "mac": '    Double-click "Install Lucy Reports.command"',
        "windows": '    Double-click "Install Lucy Reports.bat"',
        "both": ('    Mac:      double-click "Install Lucy Reports.command"\n'
                 '    Windows:  double-click "Install Lucy Reports.bat"'),
    }[platform]
    gatekeeper = GATEKEEPER if platform in ("mac", "both") else ""
    (folder / "README.txt").write_text(README.format(
        label=label, underline="=" * (len("Lucy Reports -- ") + len(label)),
        channel=_channel_blurb(office), how=how, gatekeeper=gatekeeper))

    log("built %s" % folder)
    for f in sorted(p.relative_to(folder) for p in folder.rglob("*") if p.is_file()):
        log("   %s" % f)

    if make_zip:
        archive = folder.with_suffix(".zip")
        if archive.exists():
            archive.unlink()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(folder.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(folder.parent))
        log("\nzipped -> %s (%d KB)" % (archive, archive.stat().st_size // 1024))
        return archive
    return folder


def _knocks_picker():
    """[{'value': minutes, 'label': '...'}] straight from the disposition schema."""
    from automations.disposition_signup import schema as S
    return [{"value": m, "label": S.cadence_picker_label(m)}
            for m in S.CADENCE_PICKER]


def _default_hours(office):
    """THIS office's field hours, in its own clock.

    Off the office record, NOT the org default. The record is what the board
    is actually gated on, so shipping the org's 10:45-18:30 to an office whose
    Saturday is 10:30-17:00 would show the owner hours to confirm that are not
    the hours we use -- and they would confirm them, because they were asked.

    The timezone comes from the record too: it is already known, and "which
    timezone are you in" is a question with a wrong answer available.
    """
    return {"day_start": office.day_start, "day_end": office.day_end,
            "sat_start": office.sat_start, "sat_end": office.sat_end,
            "saturday": office.saturday, "tz": office.timezone}


def _channel_blurb(office) -> str:
    """What the README tells the owner about where their alerts land.

    An office with no channel decided yet must NOT be told a room name -- they
    would go looking for it, not find it, and ask why it is broken.
    """
    if not office.channels:
        return "your team's Slack channel"
    return ", ".join(c.name for c in office.channels)


def _relay_key_from_sheet(office_key: str, log=print) -> str:
    """Read this office's key off the 'Relay Keys' tab.

    Read rather than generated, so the key in the package and the key the
    endpoint will accept cannot drift apart -- a mismatch presents as 'not
    authorised' on a laptop nobody can log into.
    """
    from automations.icd_alerts import post as P
    from automations.recruiting_report.fill import open_by_key
    tab = open_by_key(P.RELAY_SPREADSHEET_ID).worksheet("Relay Keys")
    for row in tab.get_all_values()[1:]:
        if len(row) > 2 and row[0].strip().lower() == office_key:
            if row[2].strip().upper() not in ("TRUE", "YES", "Y"):
                raise SystemExit(
                    "%r is on the 'Relay Keys' tab but is not Active. Switch it "
                    "on before building, or its laptop will install fine and "
                    "then be refused." % office_key)
            log("read %s's relay key off the sheet" % office_key)
            return row[1].strip()
    raise SystemExit(
        "no row for %r on the 'Relay Keys' tab. Add one (Office | Key | Active "
        "| Note) before building -- the package has to carry a key the "
        "endpoint will actually accept." % office_key)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build an ICD's installer folder")
    ap.add_argument("office", help="office key, e.g. kash")
    ap.add_argument("--no-zip", action="store_true")
    # GMAIL BLOCKS .bat FILES, INCLUDING INSIDE A ZIP. A package built "both"
    # cannot reliably be emailed at all -- it is stripped or bounced, and the
    # bounce does not say why. Build for the platform the office actually uses.
    ap.add_argument("--platform", choices=("mac", "windows", "both"),
                    default=None,
                    help="which launcher to include. Defaults to the office's "
                         "own `platform` in offices.py, because GMAIL BLOCKS "
                         ".bat EVEN INSIDE A ZIP -- a 'both' package cannot "
                         "reliably be emailed and the bounce does not say why.")
    args = ap.parse_args(argv)
    office = O.get(args.office)
    platform = args.platform or (office.platform if office else "both")
    build(args.office, make_zip=not args.no_zip, platform=platform)
    return 0


if __name__ == "__main__":
    sys.exit(main())
