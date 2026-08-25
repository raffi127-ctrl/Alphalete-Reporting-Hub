"""Verify the swag CARD path on a machine — send one card to a number you own.

NOT A UNIT TEST, which is why it is not named test_*.py: running this SENDS A
REAL iMESSAGE. It was called test_card.py until 2026-08-25, when a sweep that
ran every `test_*.py` module in the repo executed it twice in one minute and
fired a real hire's card at Megan's cell while she wasn't even working on swag.
Two things came out of that: the default recipient was removed (below), and the
file was renamed so no test runner — pytest, a for-loop over test_*.py, anything
— can ever pick it up again. Keep it that way.

Run this whenever a new Mac is set up to send swag (or after a macOS upgrade),
BEFORE trusting a real batch. It exercises the exact Shortcut path the Hub uses
and prints what the Shortcut saw and returned.

Usage (quote-free) — the phone number is REQUIRED, pass YOUR OWN cell:
    cd ~/recruiting-report
    .venv/bin/python automations/swag_welcome/verify_card.py +15551234567

There is deliberately no default recipient. A hardware check that sends a real
message must say out loud whose phone it is testing.

Then check that phone: did the card image actually arrive?
  - arrives                  -> this Mac is good to send.
  - "current.png ... no such file" -> the Shortcut's Get File folder needs
    re-picking (Locations -> <user> -> AlphaleteSwagCards).
  - runs clean (rc=0) but nothing arrives -> either "Show When Run" is still
    checked, or this Mac is below macOS 26, which cannot auto-send an image at
    all. See reference: swag card requires macOS 26+.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from automations.swag_welcome import imessage  # noqa: E402

if len(sys.argv) < 2:
    print(__doc__)
    print("ERROR: pass the phone number to test, e.g. +15551234567 "
          "(no default — see above).")
    raise SystemExit(2)
phone = sys.argv[1]
cards = sorted(Path("output/swag_welcome").glob("*/*.png"))
if not cards:
    print("No card .png found under output/swag_welcome — run a send first.")
    raise SystemExit

card = str(cards[-1])
print("shortcut_installed:", imessage.shortcut_installed())
print("shortcut name     :", repr(imessage._find_shortcut()))
print("sending card      :", card)
print("to                :", phone)
try:
    dbg = imessage._send_image_via_shortcut(phone, card)
    print("RESULT: shortcut ran, debug ->", dbg)
    print(">>> Now check the phone: did the CARD image actually arrive?")
except Exception as e:  # noqa: BLE001
    print("RESULT: FAILED ->", type(e).__name__, "|", e)
