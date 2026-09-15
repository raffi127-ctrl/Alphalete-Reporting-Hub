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

  2. PICTURES. Messages takes an attachment down a different path from a
     string, and text working says nothing either way.

IT SENDS THROUGH b2b_dispositions.text_post, NOT ITS OWN APPLESCRIPT. A probe
with its own copy of the send is a probe that can pass while the real path
fails, or fail while the real path works -- and this one nearly was. Writing
it by hand reproduced two things that module already knew and this did not:

  * ADDRESS THE GROUP BY NAME, NEVER BY A STORED ID. A group's chat id is
    regenerated whenever its membership changes, and a stale id does not
    raise -- Messages "sends" into a thread nobody can see. That is how the
    Texas de Brazil texts went missing for weeks.
  * LEAVE A GAP BETWEEN SENDS. Messages uploads asynchronously and crowding
    it drops images SILENTLY, which is why text_post waits
    IMAGE_SEND_DELAY_S between them. Sending a line and a picture
    back-to-back would have been a fair test of nothing.

IT ALWAYS EXITS 0. A probe that answers its question has succeeded, even
when the answer is bad news. Exiting non-zero opened an incident in
#claudecorrections for a question we asked on purpose.

WHY IT PRINTS RATHER THAN DECIDES. An unconsented send does not raise -- it
blocks on a dialog nobody is there to click. The only proof is a human
looking at the chat, so this reports what it attempted and says plainly that
exit 0 is not an answer.

  python -m automations.day_orchestrator.imessage_identity_probe \\
      --group "Admin Staff" [--image path.png] [--text-only] [--send]
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_IMAGE = ROOT / "resources" / "alphalete-logo.png"
TEXT = "Lucy probe — scheduled sends can reach this chat. Ignore."


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--group", required=True,
                    help='exact group name, e.g. "Admin Staff"')
    ap.add_argument("--image", default=str(DEFAULT_IMAGE))
    ap.add_argument("--text-only", action="store_true")
    # DRY BY DEFAULT, like every other sender here. A probe that texts a real
    # group the instant somebody runs it to see what it does is a probe that
    # gets run once and then distrusted.
    ap.add_argument("--send", action="store_true",
                    help="actually send (default: resolve only, send nothing)")
    args = ap.parse_args(argv)

    who = subprocess.run(["id", "-un"], capture_output=True,
                         text=True).stdout.strip()
    print("[probe] running as %s" % who)
    print("[probe] python  %s" % sys.executable)
    print("[probe] group   %s" % args.group)
    print("[probe] mode    %s" % ("SEND" if args.send else "dry run"))

    images = []
    if not args.text_only:
        img = pathlib.Path(args.image)
        if not img.is_file():
            print("[probe] no such image: %s" % img)
            return 1
        images = [img]
        print("[probe] image   %s" % img)

    from automations.b2b_dispositions import text_post as tp
    try:
        res = tp.send_to_group(args.group, TEXT, images,
                               dry_run=not args.send)
    except Exception as e:  # noqa: BLE001 — the answer, not a crash
        # An ambiguous or missing name raises on purpose over there, rather
        # than picking the first match and texting the wrong room.
        msg = str(e)
        print("[probe] no send: %s: %s" % (type(e).__name__, msg[:300]))
        print("")
        # NAME THE DIAGNOSIS. -1712 is the one an operator would otherwise
        # read as "flaky" and re-run forever: an ungranted identity does not
        # refuse, it blocks on a dialog nobody is there to click until the
        # AppleEvent gives up. Lucy 3, 2026-09-15, four minutes exactly.
        if "-1712" in msg or "timed out" in msg.lower():
            print("[probe] VERDICT: this identity has NO control-Messages "
                  "grant.")
            print("[probe] It blocked on a permission dialog nobody clicked.")
            print("[probe] Fix at the machine: run this probe with somebody "
                  "there")
            print("[probe] to click Allow, or switch Messages on for it under")
            print("[probe] System Settings > Privacy & Security > Automation.")
        else:
            print("[probe] VERDICT: the group could not be resolved by name.")
            print("[probe] Permission is not the problem here.")
        # EXIT 0 ON PURPOSE. This is a diagnostic, and a diagnostic that
        # diagnoses something has done its job -- exiting 1 opened an
        # incident in #claudecorrections for a question we asked deliberately
        # (2026-09-15), which is noise in the channel people use for real
        # breakage. The answer is the printed verdict, read with
        # `lucy logtail rerun imessage_identity_probe`.
        return 0

    print("[probe] result  %s" % res)
    if not args.send:
        print("")
        print("[probe] Resolved only — nothing was sent. Add --send to text.")
        return 0

    print("")
    print("[probe] EXIT 0 IS NOT DELIVERY. Look at the chat: an unconsented")
    print("[probe] identity blocks rather than failing, and a crowded send")
    print("[probe] drops the image without saying so.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
