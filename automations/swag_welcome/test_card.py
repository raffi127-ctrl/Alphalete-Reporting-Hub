"""Verify the swag CARD path on a machine — send one card to a number you own.

Run this whenever a new Mac is set up to send swag (or after a macOS upgrade),
BEFORE trusting a real batch. It exercises the exact Shortcut path the Hub uses
and prints what the Shortcut saw and returned.

Usage (quote-free):
    cd ~/recruiting-report
    .venv/bin/python automations/swag_welcome/test_card.py +14197697114

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

phone = sys.argv[1] if len(sys.argv) > 1 else "+14197697114"
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
