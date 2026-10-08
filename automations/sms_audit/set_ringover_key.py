"""Put the Ringover API key on this machine, without it passing through
anything.

    python -m automations.sms_audit.set_ringover_key

Asks at a hidden prompt (a terminal prompt when there is a terminal, a
native macOS dialog when there is not), verifies the key against Ringover
before saving, and writes ~/.config/recruiting-report/ringover-key.json at
mode 600. The key never becomes a command-line argument, so it reaches no
shell history, no log, no chat and no Mini Control sheet.

IT VERIFIES BEFORE IT WRITES. A key with the wrong Rights authenticates
perfectly well and then returns calls with no recording on them, which
reads exactly like a team that records nothing. Better to find that out
here, at a prompt, than at 4am inside a report.

Prints NOTHING of the key, not even its length.
"""
from __future__ import annotations  # Lucy runs Python 3.9 -- keep lazy

import argparse
import getpass
import json
import os
import subprocess
import sys

from automations.sms_audit import ringover as RO


def _ask(prompt):
    """Hidden input, terminal or GUI. Never echoed, never an argv."""
    if sys.stdin is not None and sys.stdin.isatty():
        return getpass.getpass(prompt + ": ")
    if sys.platform == "darwin":
        script = ('display dialog "{}" default answer "" with hidden answer'
                  ' buttons {{"Cancel","OK"}} default button "OK"'
                  .format(prompt.replace('"', "'")))
        try:
            out = subprocess.run(["osascript", "-e", script],
                                 capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError:
            return ""
        for part in (out.stdout or "").split(", "):
            if part.startswith("text returned:"):
                return part.split(":", 1)[1].strip()
        return ""
    raise RuntimeError("no way to ask for the key without echoing it on this "
                       "machine -- run it from a terminal")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7,
                    help="how far back the verification probe looks")
    a = ap.parse_args(argv)

    key = (_ask("Ringover API key") or "").strip()
    if not key:
        print("[ringover] nothing entered -- nothing written.", file=sys.stderr)
        return 1

    try:
        got = RO.probe(key=key, days=a.days)
    except RO.RingoverError as e:
        print("[ringover] NOT SAVED. {}".format(e), file=sys.stderr)
        return 1

    RO.CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RO.CREDS_PATH.write_text(json.dumps({"api_key": key}, indent=2),
                             encoding="utf-8")
    try:
        os.chmod(RO.CREDS_PATH, 0o600)
    except OSError:
        pass  # Windows has no mode bits; the write still happened.
    print("[ringover] saved to {} (mode 600).".format(RO.CREDS_PATH))

    # Say what it can see, so the next decision is made on fact.
    print("[ringover] calls visible in the last {} days: {}".format(
        got.get("window_days"), got.get("calls_seen", 0)))
    if got.get("calls_seen"):
        print("[ringover] of those, {} carry a recording and {} carry a "
              "transcript.".format(got.get("with_recording", 0),
                                   got.get("with_transcript", 0)))
        print("[ringover] users this key can see: {}".format(
            ", ".join(got.get("users") or []) or "(none named)"))
        if not got.get("with_recording"):
            print("[ringover] NOTE: no recording came back on any call. "
                  "Either the team is not recording, or this key was made "
                  "without the recording right.", file=sys.stderr)
    else:
        print("[ringover] {}".format(got.get("why", "")), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
