"""Try sending the swag card via AppleScript instead of the Shortcut.

Why: macOS 15.6 (JD) will not let Shortcuts send a message unattended — the
Shortcut runs, exits 0, and silently sends nothing unless the compose sheet is
shown and a human clicks Send. macOS 26.5 (Megan) allows it, which is why the
identical shortcut works on one Mac and not the other.

AppleScript file-send is the older path the Shortcut replaced (it attaches
images as undelivered documents on macOS 26) — but on macOS 15 it historically
delivered fine. This tests whether it does on this machine.

Usage (quote-free):
    cd ~/recruiting-report
    .venv/bin/python automations/swag_welcome/test_card_applescript.py +14197697114
Then check the phone: did the card arrive, and does it say Delivered?
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

phone = sys.argv[1] if len(sys.argv) > 1 else "+14197697114"
cards = sorted(Path("output/swag_welcome").glob("*/*.png"))
if not cards:
    print("No card .png found under output/swag_welcome — run a send first.")
    raise SystemExit

card = cards[-1].resolve()
print("card :", card)
print("to   :", phone)
print("sending via AppleScript (not the Shortcut)...")

script = (
    'tell application "Messages"\n'
    '  set svcId to id of 1st service whose service type = iMessage\n'
    '  set targetService to service id svcId\n'
    f'  set targetBuddy to buddy "{phone}" of targetService\n'
    f'  send POSIX file "{card}" to targetBuddy\n'
    'end tell'
)
proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
print("rc     :", proc.returncode)
print("stdout :", proc.stdout.strip())
print("stderr :", proc.stderr.strip())
print()
print(">>> Check the phone: did the CARD image arrive, and does it show as")
print(">>> Delivered (not stuck as an undelivered document)?")
