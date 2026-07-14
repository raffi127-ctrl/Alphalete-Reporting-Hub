"""Send iMessages from whatever Mac runs this — no account is hardcoded.

AppleScript drives the local Messages.app, so it sends from the iMessage
account currently signed in on THIS machine (the Hub laptop, the mini,
wherever). Run it on the mini, it sends as the mini's account; run it on a
laptop, it sends as that laptop's.

Guardrails:
- `messages_ready()` checks Messages is running / signed in before a batch,
  so we fail loudly up front instead of silently dropping 30 texts.
- macOS only, obviously. On anything else we raise rather than pretend.
- Sending is a real, outward action — run.py gates the actual send behind an
  explicit --send flag; --dry-run (the default) never touches Messages.
"""

from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path


class IMessageError(RuntimeError):
    pass


def _osascript(script: str) -> str:
    if platform.system() != "Darwin":
        raise IMessageError(
            "iMessage sending only works on macOS (needs Messages.app)."
        )
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise IMessageError(proc.stderr.strip() or "osascript failed")
    return proc.stdout.strip()


def messages_ready() -> tuple[bool, str]:
    """(ok, detail). Confirms Messages is reachable and has an active iMessage
    service on this machine before we try to send a batch."""
    if platform.system() != "Darwin":
        return False, "not macOS — no Messages.app"
    try:
        # `id of 1st service whose service type = iMessage` is the reliable probe:
        # iterating services + reading `service type` throws -10000 on recent
        # macOS, but the whose-filter works. A non-empty id = iMessage is ready.
        out = _osascript(
            'tell application "Messages" to get id of 1st service '
            'whose service type = iMessage'
        )
        if out.strip():
            return True, "Messages ready"
        return False, "Messages has no active iMessage account signed in"
    except Exception as e:
        return False, f"couldn't reach Messages: {e}"


def _send_text(phone: str, text: str) -> None:
    # Text over the iMessage service. Resolve service by id (the whose-filter
    # works; index access throws -10000 on recent macOS).
    safe = text.replace("\\", "\\\\").replace('"', '\\"')
    _osascript(
        'tell application "Messages"\n'
        '  set svcId to id of 1st service whose service type = iMessage\n'
        '  set targetService to service id svcId\n'
        f'  set targetBuddy to buddy "{phone}" of targetService\n'
        f'  send "{safe}" to targetBuddy\n'
        'end tell'
    )


def _paste_image_into_chat(attachment: str) -> None:
    """Send an image by pasting it (clipboard) into the focused Messages chat.

    AppleScript's `send <file>` attaches images as raw documents that Messages
    fails to DELIVER on recent macOS (they show as an undelivered file icon).
    Pasting clipboard image data — exactly like sending a screenshot — makes
    Messages treat it as an inline photo, which delivers. This is GUI driven,
    so it needs Accessibility permission and drives the Messages window.
    """
    ap = Path(attachment)
    if not ap.exists():
        raise IMessageError(f"attachment not found: {attachment}")
    # 1. Put the card on the clipboard as image data (like a screenshot).
    _osascript(f'set the clipboard to (read (POSIX file "{ap.resolve()}") '
               'as JPEG picture)')
    # 2. Paste into the chat the text-send just opened, and hit send.
    _osascript(
        'tell application "Messages" to activate\n'
        'delay 0.7\n'
        'tell application "System Events"\n'
        '  keystroke "v" using command down\n'
        '  delay 1.0\n'
        '  key code 36\n'          # Return → send
        'end tell'
    )


def send(phone: str, text: str, attachment: str | None = None,
         dry_run: bool = True) -> dict:
    """Send one welcome text (+ optional swag image). dry_run just reports what
    WOULD send. Returns a per-recipient result dict for the run summary."""
    result = {"phone": phone, "sent": False, "dry_run": dry_run,
              "attachment": attachment, "error": None}
    if dry_run:
        return result
    try:
        # Text first — this opens/focuses the recipient's chat — then paste the
        # card image into that focused chat.
        if text:
            _send_text(phone, text)
        if attachment:
            time.sleep(1.5)
            _paste_image_into_chat(attachment)
        result["sent"] = True
    except Exception as e:
        result["error"] = str(e)
    return result
