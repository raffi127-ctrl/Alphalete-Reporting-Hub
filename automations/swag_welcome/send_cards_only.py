"""Send the CARDS for a batch whose texts already went out — no re-texting.

This is the recovery path for the exact failure that keeps happening: the batch
texts 100% fine, then every card comes back "card failed" (auto-send switched
off, Shortcut not built, or the Mac is below macOS 26). The hires got a message
promising a sneak peek and no photo.

The cards are already on disk from that run — `output/swag_welcome/<date>/` holds
one PNG per person named `<Name>_<digits>.png`, so the recipient is recoverable
from the filename. This walks that folder and sends ONLY the image to each
number. It never sends text, so nobody gets a second welcome message.

    # see exactly who would get a card (sends nothing) — always run this first
    python -m automations.swag_welcome.send_cards_only

    # actually send them, from THIS Mac's iMessage account
    python -m automations.swag_welcome.send_cards_only --send

    # a different day's batch, or just a few people
    python -m automations.swag_welcome.send_cards_only --date 2026-08-15 --send
    python -m automations.swag_welcome.send_cards_only --only 14695890574 --send

Run it on the SAME Mac that sent the texts — the card then lands in the thread
the hire already has, instead of arriving from a stranger's number.

macOS 26+ only, like every card send: on macOS 15 `shortcuts run` exits 0 and
delivers nothing, so this refuses up front rather than reporting 54 phantom
sends. On 15 the fallback is the Shortcut with "Show When Run" ON — one click
per card.
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from automations.swag_welcome import imessage, run as swag_run


def _mac_major() -> int:
    try:
        return int((platform.mac_ver()[0] or "0").split(".")[0])
    except Exception:
        return 0


def _cards(folder: Path) -> list[tuple[str, str, Path]]:
    """[(name, +e164, path)] parsed from `<Name>_<digits>.png` filenames."""
    out = []
    for p in sorted(folder.glob("*.png")):
        stem = p.stem
        if "_" not in stem:
            continue
        name, _, digits = stem.rpartition("_")
        if not digits.isdigit():
            continue
        out.append((name.replace("_", " "), "+" + digits, p))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="batch folder under output/swag_welcome "
                                   "(default: the most recent one)")
    ap.add_argument("--only", action="append", default=[],
                    help="send to just this number (repeatable); digits are matched")
    ap.add_argument("--send", action="store_true",
                    help="actually send. Without it this only lists.")
    args = ap.parse_args(argv)

    root = swag_run.OUTPUT_DIR
    if args.date:
        folder = root / args.date
    else:
        dirs = sorted(d for d in root.glob("*") if d.is_dir())
        folder = dirs[-1] if dirs else None
    if not folder or not folder.is_dir():
        print(f"No batch folder found under {root} — nothing to send.")
        return 1

    cards = _cards(folder)
    if args.only:
        wanted = {"".join(c for c in o if c.isdigit()) for o in args.only}
        cards = [c for c in cards if "".join(x for x in c[1] if x.isdigit()) in wanted]
    if not cards:
        print(f"No cards matched in {folder}.")
        return 1

    print(f"Batch: {folder}  ({len(cards)} card(s))")
    for name, phone, _ in cards:
        print(f"  {name:<20} {phone}")

    if not args.send:
        print("\nDRY RUN — nothing sent. Add --send to send these cards "
              "(text messages are NOT re-sent).")
        return 0

    # Gate the two things that make a "send" silently do nothing, before we
    # claim any of it worked.
    if _mac_major() < 26:
        print(f"\nREFUSING: this Mac is macOS {platform.mac_ver()[0]}. Automated "
              "image sends need macOS 26+ — below that `shortcuts run` exits 0 "
              "and delivers nothing. Use the Shortcut with 'Show When Run' ON "
              "and click Send per card, or run this from a macOS 26 Mac.")
        return 2
    if not imessage.shortcut_installed():
        print(f"\nREFUSING: the '{imessage.SHORTCUT_NAME}' Shortcut isn't on this "
              "Mac (`shortcuts list` doesn't show it). Build it first — see the "
              "setup steps in the Hub's swag card.")
        return 2

    ok, detail = imessage.messages_ready()
    if not ok:
        print(f"\nREFUSING: {detail}")
        return 2

    sent = failed = 0
    for name, phone, path in cards:
        try:
            imessage._send_image_via_shortcut(phone, str(path))
            sent += 1
            print(f"  card sent  {name} {phone}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  FAILED     {name} {phone} — {e}")
    print(f"\nCards sent {sent}/{len(cards)} (failed {failed}). No texts were sent.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
