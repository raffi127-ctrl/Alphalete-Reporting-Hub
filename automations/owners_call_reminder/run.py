"""Monday reminder to the 'Alphalete Ownrs 🔥' iMessage group.

Maud's ask (relayed by Megan 2026-07-21): each Monday, text the owners group with the
Owner's Call / Leader's Call times + the recognition-sheet link so ICDs fill in their
office promotions before the call. Maud sends this by hand today; this automates it at
Mon 11:00am + 4:00pm CT.

Sends from whatever Mac runs it (the mini = Lucy) via Messages.app / AppleScript, the
same group-chat mechanism the Texas de Brazil poster uses. It targets the group by its
chat GUID (OWNERS_CALL_CHAT_ID) — find that once with `lucy rerun probe_imessage_threads`
(the group's name contains 'Alphalete', so it shows in the probe) and set it below/in env.

  python -m automations.owners_call_reminder.run            # dry-run — prints, never sends
  python -m automations.owners_call_reminder.run --send     # actually text the group
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# Display name (logging only) + the group's chat GUID ('iMessage;+;chat…'). The GUID
# is discovered on the mini via the probe; set it here or via env once known.
GROUP_NAME = os.environ.get("OWNERS_CALL_GROUP", "Alphalete Ownrs 🔥")
CHAT_ID = os.environ.get("OWNERS_CALL_CHAT_ID", "")     # <-- set after the probe

# The recognition sheet ICDs fill in (same link Maud sends). See recognition_tab.
SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
             "1lgYjfpCwYbeeGAdx7FEyI9PIqFk-W57X7HaZ4nsuoFM/edit?usp=sharing")

# Maud's verbatim reminder (Megan relayed it 2026-07-21).
MESSAGE = (
    "Reminder for the Owner's Call tonight at 8:15pm CT and then Leader's Call "
    "following at 8:45pm CT!!!!!! 🔥🎉\n"
    "\n"
    "Make sure to fill out the recognition sheet!\n"
    + SHEET_URL
)


def _osascript(script: str, timeout: int = 60) -> str:
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "osascript failed").strip()[:300])
    return p.stdout.strip()


def messages_ready() -> tuple[bool, str]:
    if sys.platform != "darwin":
        return False, "not macOS — no Messages.app"
    try:
        out = _osascript('tell application "Messages" to get id of 1st service '
                         'whose service type = iMessage')
        return (True, "Messages ready") if out else (False, "no active iMessage account signed in")
    except Exception as e:  # noqa: BLE001
        return False, f"couldn't reach Messages: {e}"


def _applescript_string(text: str) -> str:
    """A Python string → an AppleScript string literal, newlines as `linefeed`."""
    esc = text.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + esc.replace("\n", '" & linefeed & "') + '"'


def send(dry_run: bool = True) -> int:
    if dry_run:
        print(f"[dry-run] WOULD text {GROUP_NAME!r}:\n"
              f"------------------------------------------------------------\n"
              f"{MESSAGE}\n"
              f"------------------------------------------------------------")
        return 0
    if sys.platform != "darwin":
        print("SKIPPED — not macOS (needs Messages.app)")
        return 1
    if not CHAT_ID:
        print("NO CHAT ID — set OWNERS_CALL_CHAT_ID to the group's GUID "
              "(run `lucy rerun probe_imessage_threads` on the mini to find it).")
        return 2
    ok, detail = messages_ready()
    if not ok:
        print(f"Messages not ready: {detail}")
        return 3
    cid = CHAT_ID.replace('"', '\\"')
    _osascript('tell application "Messages"\n'
               f'  set theChat to a reference to chat id "{cid}"\n'
               f'  send {_applescript_string(MESSAGE)} to theChat\n'
               'end tell', 40)
    print(f"✅ Reminder texted to {GROUP_NAME!r}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Text the owners group the Monday recognition "
                                             "reminder.")
    ap.add_argument("--send", action="store_true",
                    help="Actually send (default is a dry-run that prints only).")
    args = ap.parse_args()
    return send(dry_run=not args.send)


if __name__ == "__main__":
    sys.exit(main())
