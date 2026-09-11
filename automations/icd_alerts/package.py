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
    "automations/shared/saraplus.py",
    "automations/shared/credit_check_line.py",
    "automations/shared/browser_banner.py",
]

# The repo's automations/__init__.py installs the Hub's auto-publish hook. That
# is Hub machinery and has no business on an ICD's laptop, so the bundle gets
# this instead.
BUNDLE_INIT = '''"""Alphalete Alerts."""
'''

GATEKEEPER = """
IF YOUR MAC SAYS IT "CANNOT BE OPENED"
    That is macOS being careful about files from the internet. Right-click
    (or control-click) the installer, choose Open, then click Open again.
    You only have to do this once.
"""

README = """Alphalete Alerts -- {label}
{underline}

WHAT THIS IS
    It watches your own SaraPlus account during the day and tells the
    reporting team when one of your reps runs a credit check. Those show
    up in your team's Slack channel ({channel}).

TO INSTALL
{how}

    Boxes will pop up asking for your SaraPlus login and your OwnerVille
    login. That is the only thing it asks for. A black window will also
    appear showing its progress -- you can ignore that one.
{gatekeeper}
ABOUT YOUR PASSWORDS
    They are saved on your computer only, and are used to sign in from
    your computer. They are never sent to us or to anyone else. The only
    thing that leaves your computer is the number of credit checks each
    rep has run today.

AFTER IT IS INSTALLED
    Nothing. It checks every 15 minutes between 10am and 9:30pm (4pm on
    Saturdays) and does nothing on Sundays. Just leave the computer on and
    connected to the internet during selling hours. If it is asleep, no
    alerts are lost -- they simply arrive when it wakes up.

IF YOU CHANGE YOUR SARAPLUS PASSWORD
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

    folder = OUT / ("alphalete-alerts-%s" % office.key)
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    for rel in AGENT_FILES:
        dest = folder / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dest)
    (folder / "automations" / "__init__.py").write_text(BUNDLE_INIT)
    (folder / "automations" / "shared" / "__init__.py").write_text("")

    for name in ("setup.py", "ask.py"):
        shutil.copy2(DIST / name, folder / name)

    if platform in ("mac", "both"):
        shutil.copy2(DIST / "Install Alphalete Alerts.command",
                     folder / "Install Alphalete Alerts.command")
        (folder / "Install Alphalete Alerts.command").chmod(0o755)

    if platform in ("windows", "both"):
        # CRLF, always. A .bat with bare LF endings is parsed unreliably by
        # cmd.exe, and this repo is developed on a Mac -- so the file on disk
        # here has LF and would ship that way unless converted on the way out.
        bat = (DIST / "Install Alphalete Alerts.bat").read_text()
        (folder / "Install Alphalete Alerts.bat").write_bytes(
            bat.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))

    (folder / "install.json").write_text(json.dumps({
        "office_key": office.key,
        "owner": office.owner,
        "relay_url": O.RELAY_URL,
        "relay_key": relay_key,
    }, indent=2))

    label = "%s (%s)" % (office.label, office.owner)
    how = {
        "mac": '    Double-click "Install Alphalete Alerts.command"',
        "windows": '    Double-click "Install Alphalete Alerts.bat"',
        "both": ('    Mac:      double-click "Install Alphalete Alerts.command"\n'
                 '    Windows:  double-click "Install Alphalete Alerts.bat"'),
    }[platform]
    gatekeeper = GATEKEEPER if platform in ("mac", "both") else ""
    (folder / "README.txt").write_text(README.format(
        label=label, underline="=" * (len("Alphalete Alerts -- ") + len(label)),
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
                    default="both",
                    help="which launcher to include (default both). Use 'mac' "
                         "or 'windows' to make the zip emailable: gmail blocks "
                         ".bat even inside an archive.")
    args = ap.parse_args(argv)
    build(args.office, make_zip=not args.no_zip, platform=args.platform)
    return 0


if __name__ == "__main__":
    sys.exit(main())
