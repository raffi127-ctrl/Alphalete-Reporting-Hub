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


def _send_applescript(phone: str, text: str, attachment: str | None) -> None:
    # Send to the phone number over the iMessage service. Text first, then the
    # image as a follow-up attachment (Messages sends them as two bubbles).
    # Resolve the service by id (whose-filter works; index access throws -10000).
    lines = [
        'tell application "Messages"',
        '  set svcId to id of 1st service whose service type = iMessage',
        '  set targetService to service id svcId',
        f'  set targetBuddy to buddy "{phone}" of targetService',
    ]
    # Send the image FIRST (it needs a moment to upload), pause, then the text,
    # so the two don't race — sending both back-to-back can drop the image.
    if attachment:
        ap = Path(attachment)
        if not ap.exists():
            raise IMessageError(f"attachment not found: {attachment}")
        lines.append(f'  send (POSIX file "{ap.resolve()}") to targetBuddy')
        lines.append('  delay 2')
    if text:
        safe = text.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  send "{safe}" to targetBuddy')
    lines.append("end tell")
    _osascript("\n".join(lines))


def send(phone: str, text: str, attachment: str | None = None,
         dry_run: bool = True) -> dict:
    """Send one welcome text (+ optional swag image). dry_run just reports what
    WOULD send. Returns a per-recipient result dict for the run summary."""
    result = {"phone": phone, "sent": False, "dry_run": dry_run,
              "attachment": attachment, "error": None}
    if dry_run:
        return result
    try:
        _send_applescript(phone, text, attachment)
        result["sent"] = True
    except Exception as e:
        result["error"] = str(e)
    return result
