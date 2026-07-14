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
import shutil
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


# --- Shortcut-based image send (the reliable path) -------------------------
# A macOS Shortcut's "Send Message" action sends an image to an explicitly-typed
# phone number — no focus-stealing, no clipboard paste, no wrong-chat risk, and
# it works for unsaved numbers. It sends from THIS machine's iMessage account.
# The Shortcut reads two files we drop next to it; see README for the 3-action
# build. (Text still goes via AppleScript, which is rock-solid.)
SHORTCUT_NAME = "Alphalete Swag Card"
_SWAG_DIR = Path.home() / ".swag_cards"
_SWAG_IMG = _SWAG_DIR / "current.png"
# Card auto-send via the "Alphalete Swag Card" Shortcut is WORKING (verified
# 2026-07-13): text via AppleScript, card via the Shortcut. Needs the Shortcut
# built + its send-messages permission granted on each sending machine.
_AUTO_SEND_CARD = True


def _find_shortcut(name: str = SHORTCUT_NAME) -> str | None:
    """Return the shortcut's ACTUAL name (matched ignoring surrounding space —
    Shortcuts silently keeps trailing spaces in names), or None."""
    try:
        out = subprocess.run(["shortcuts", "list"], capture_output=True,
                             text=True, timeout=15).stdout
        for line in out.splitlines():
            if line.strip() == name.strip():
                return line
    except Exception:
        pass
    return None


def shortcut_installed(name: str = SHORTCUT_NAME) -> bool:
    return _find_shortcut(name) is not None


def _send_image_via_shortcut(phone: str, attachment: str,
                             name: str = SHORTCUT_NAME) -> None:
    """Phone → clipboard (text), card → the Shortcut's input file. The Shortcut
    does Get Clipboard (phone) → Send [Shortcut Input] to [Clipboard]. `shortcuts
    run` only passes input as a FILE, and reading text from it is unreliable —
    so the phone (which must be text) rides the clipboard, and the card (a file)
    rides the input. No focus-steal; sends from this Mac's iMessage."""
    ap = Path(attachment)
    if not ap.exists():
        raise IMessageError(f"attachment not found: {attachment}")
    actual = _find_shortcut(name) or name   # use the real name (may hold spaces)
    _SWAG_DIR.mkdir(exist_ok=True)
    if ap.resolve() != _SWAG_IMG.resolve():
        shutil.copy(ap, _SWAG_IMG)                   # card → Shortcut input file
    # Put the phone on the clipboard with pbcopy (clean UTF-8). Setting it via
    # AppleScript makes Shortcuts read it with a space between every character
    # ("+ 1 4 1 9…"), which "Get Phone Numbers" can't parse.
    subprocess.run(["pbcopy"], input=phone, text=True, timeout=10)
    proc = subprocess.run(["shortcuts", "run", actual, "-i", str(_SWAG_IMG)],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise IMessageError((proc.stderr or "shortcut run failed").strip()[:200])


def send(phone: str, text: str, attachment: str | None = None,
         dry_run: bool = True) -> dict:
    """Send one welcome text (+ optional swag image). dry_run just reports what
    WOULD send. Returns a per-recipient result dict for the run summary."""
    result = {"phone": phone, "sent": False, "dry_run": dry_run,
              "attachment": attachment, "error": None}
    if dry_run:
        return result
    try:
        # Text via AppleScript (rock-solid). Card via the Shortcut if it's
        # installed — the only reliable, safe way to send an image to an
        # unsaved 1:1 number. If the Shortcut isn't built yet, the text still
        # goes and the card is left for manual send.
        if text:
            _send_text(phone, text)
        result["sent"] = True
        # Image auto-send is OFF (text-only): reliably sending a card to an
        # unsaved 1:1 number on macOS isn't solved (AppleScript won't deliver
        # images; the Shortcut path can't resolve unsaved numbers). Cards are
        # still generated in the grid + output folder to attach manually. Flip
        # _AUTO_SEND_CARD to re-enable once the Shortcut path is proven.
        result["image_auto_sent"] = False
        if attachment and _AUTO_SEND_CARD and shortcut_installed():
            try:
                _send_image_via_shortcut(phone, attachment)
                result["image_auto_sent"] = True
            except Exception as e:
                result["image_error"] = str(e)
    except Exception as e:
        result["error"] = str(e)
    return result
