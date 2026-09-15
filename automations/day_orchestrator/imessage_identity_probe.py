"""Can THIS machine's orchestrator send an iMessage -- and a picture?

TWO QUESTIONS THAT LOOK LIKE ONE.

  1. IDENTITY. macOS grants "control Messages" per executable identity. A
     terminal test grants it to Terminal, which is not what sends anything on
     a schedule. Lucy 3 passed deploy/text_consent_check.sh on 2026-09-15 --
     from a terminal -- and that proved nothing about the orchestrator, which
     is the identity every scheduled text actually runs under. So this probe
     exists to be run THROUGH the orchestrator (`lucy rerun
     imessage_identity_probe`), because only a send from there answers the
     question that matters.

  2. PICTURES. Messages takes an attachment down a different AppleScript path
     from a string. A board that is meant to go out as an image is worth
     nothing if only the words arrive, and text working says nothing either
     way. So this sends both and reports them separately.

WHY IT PRINTS RATHER THAN DECIDES. Neither leg proves delivery. An
unconsented send does not raise -- it blocks on a dialog nobody is there to
click, for about five minutes -- and a chat id that matches nothing returns
cleanly having sent nothing at all. The only proof is a human looking at the
chat, so this reports what it attempted and says plainly that exit 0 is not
an answer.

  python -m automations.day_orchestrator.imessage_identity_probe \\
      --chat "any;+;..." [--image path.png] [--text-only]
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
from typing import Optional, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_IMAGE = ROOT / "resources" / "alphalete-logo.png"
TEXT = "Lucy probe — scheduled sends can reach this chat. Ignore."

# Long enough to outlast the consent dialog's own timeout. An unconsented send
# hangs until macOS gives up; cutting it short here would report "timeout"
# for what is really "this identity was never granted".
TIMEOUT = 420


def _osascript(script: str) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(["osascript", "-e", script],
                              capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, ("timed out after %ds — that is what an UNCONSENTED "
                       "identity looks like: it blocked on a permission "
                       "dialog nobody was there to click" % TIMEOUT)
    if proc.returncode != 0:
        return False, (proc.stderr or "").strip()[:300]
    return True, (proc.stdout or "").strip()


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def send_text(chat_id: str) -> Tuple[bool, str]:
    return _osascript(
        'tell application "Messages"\n'
        '  set theChat to a reference to chat id "%s"\n'
        '  send "%s" to theChat\n'
        'end tell' % (_esc(chat_id), _esc(TEXT)))


def send_image(chat_id: str, path: str) -> Tuple[bool, str]:
    if not os.path.isfile(path):
        return False, "no such file: %s" % path
    # POSIX file ... as alias, which is the only form Messages accepts for an
    # attachment. Passing the path as a plain string sends the TEXT of the
    # path, which arrives looking like a successful send of the wrong thing.
    return _osascript(
        'tell application "Messages"\n'
        '  set theFile to POSIX file "%s" as alias\n'
        '  set theChat to a reference to chat id "%s"\n'
        '  send theFile to theChat\n'
        'end tell' % (_esc(path), _esc(chat_id)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chat", required=True,
                    help='chat id, e.g. "any;+;6f30911..."')
    ap.add_argument("--image", default=str(DEFAULT_IMAGE))
    ap.add_argument("--text-only", action="store_true")
    args = ap.parse_args(argv)

    who = subprocess.run(["id", "-un"], capture_output=True,
                         text=True).stdout.strip()
    print("[probe] running as %s, python %s" % (who, sys.executable))
    print("[probe] chat: %s" % args.chat)

    ok_text, note = send_text(args.chat)
    print("[probe] text : %s%s" % ("sent" if ok_text else "FAILED",
                                   ("  — " + note) if note else ""))

    ok_img = None
    if not args.text_only:
        ok_img, note = send_image(args.chat, args.image)
        print("[probe] image: %s%s" % ("sent" if ok_img else "FAILED",
                                       ("  — " + note) if note else ""))
        print("[probe]        file: %s" % args.image)

    print("")
    print("[probe] NEITHER LINE IS PROOF. A chat id that matches nothing")
    print("[probe] returns cleanly having sent nothing. Look at the chat.")
    # Non-zero only when a send actually errored, so a scheduled run that
    # could not reach Messages at all shows up as failed rather than green.
    return 0 if ok_text and (ok_img is not False) else 1


if __name__ == "__main__":
    sys.exit(main())
