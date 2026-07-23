"""Send ONE swag card via the Shortcut from THIS plain process, printing the
debug — to tell whether the card fails to send on a machine no matter who calls
it, or only when the Hub (Streamlit) process calls it.

Temporary debug helper. Usage (quote-free):
    cd ~/recruiting-report
    .venv/bin/python automations/swag_welcome/test_card.py +14197697114
Then WATCH the recipient's phone: did the card arrive?
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
