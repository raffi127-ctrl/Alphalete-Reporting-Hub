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


def _osascript(script: str, timeout: int = 60) -> str:
    if platform.system() != "Darwin":
        raise IMessageError(
            "iMessage sending only works on macOS (needs Messages.app)."
        )
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
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


def _clean_path(attachment: str) -> Path:
    """Copy the card to a short, SPACE-FREE path. A space in the attachment
    path (e.g. '/Users/megan/1st Claude Folder/…') makes Messages silently fail
    to deliver the file while the text still goes through."""
    import shutil
    dest_dir = Path.home() / ".swag_cards"
    dest_dir.mkdir(exist_ok=True)
    # slug already uses underscores, so the filename itself has no spaces
    dest = dest_dir / Path(attachment).name.replace(" ", "_")
    shutil.copy(attachment, dest)
    return dest


# Seconds to wait AFTER sending the image, inside the AppleScript, so Messages
# finishes UPLOADING before the process returns. Without this the image shows on
# the sender but never reaches the recipient ("Not Delivered"). This is the fix
# the Texas de Brazil sender uses (it waits 18s per full-page poster; our card
# is a small ~280 KB JPEG, so a shorter wait is plenty).
IMG_UPLOAD_DELAY = 12


def _send_image(phone: str, attachment: str) -> None:
    """Send the card as an inline iMessage image — no GUI, no extra permissions,
    straight from this machine's iMessage account.

    Two things matter (both from the Texas de Brazil sender):
    - the card is a PNG — Messages sends PNGs inline; a JPEG file-send comes
      through as a raw document (file icon) that won't deliver.
    - a trailing `delay` lets Messages finish UPLOADING before osascript exits,
      else the image shows on the sender but never reaches the recipient.
    """
    ap = Path(attachment)
    if not ap.exists():
        raise IMessageError(f"attachment not found: {attachment}")
    clean = _clean_path(str(ap))
    _osascript(
        'tell application "Messages"\n'
        '  set svcId to id of 1st service whose service type = iMessage\n'
        '  set targetService to service id svcId\n'
        f'  set targetBuddy to buddy "{phone}" of targetService\n'
        f'  send (POSIX file "{clean}") to targetBuddy\n'
        f'  delay {IMG_UPLOAD_DELAY}\n'
        'end tell',
        timeout=IMG_UPLOAD_DELAY + 30,
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
        # Text first, then the image (its AppleScript waits out the upload).
        if text:
            _send_text(phone, text)
        if attachment:
            _send_image(phone, attachment)
        result["sent"] = True
    except Exception as e:
        result["error"] = str(e)
    return result
