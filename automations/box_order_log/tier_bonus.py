"""Box Tier Bonus - Rep Level board, captured for ONE owner.

Carlos's ask (2026-08-15, #l10-alphalete): the BOX Order Log thread Lucy posts
should also carry the Tableau board that shows where each of his reps lands on
the tier ladder this week — the Box twin of the B2B AT&T "Order Tiered Bonus -
Rep Ranking" image.

Source: Tableau site `sci` -> workbook `B2BBOXEnergyTracker` (B2B Box Energy) ->
view `Box Tier Bonus - Rep Level` -> filters `Owner Name` (sliced here, via the
URL), `Rep Name` (left at All), `Sale Date Weekending` (left alone — the view
already opens on the current week). Rows are Owner Name / Rep Tier Volume /
Rep Name; columns are the weekdays of that week plus Grand Total.

Two things this module exists to protect against, both measured on the real
board 2026-08-15:

  CLIPPING — Carlos guessed right that "it may need more than one screenshot".
  The dashboard exports at a FIXED 1800x1600 canvas no matter how tall the
  browser window is, and the rep table sits in a scrolling region whose bottom
  edge lands ~1490px down. Unfiltered (every office, ~50 reps) the export cuts
  mid-row at that edge with no closing border. Filtered to ONE owner it fits
  with room to spare — Carlos 859px / 13 reps, Roshan 979px / 16 reps — so the
  owner slice IS the fix, and CLIP_SUSPECT_PX below is the tripwire for the
  week an office finally outgrows it.

  A SILENTLY EMPTY BOARD — a URL filter value that matches no member doesn't
  error, it just renders an empty table (see the Tableau URL-slice notes in
  tableau_url_filters). An empty board is short, so a height floor catches it.

Python 3.9 on Lucy 2 / the mini — deferred annotations, no runtime `X | Y`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "B2BBOXEnergyTracker/BoxTierBonus-RepLevel")

# Carlos's standalone post. Must match the Owner Name filter member EXACTLY —
# a near-miss renders an empty board rather than failing (see _check below).
DEFAULT_OWNER = "Carlos Hidalgo"

# The Slack caption / header line for this attachment, defined once so the
# parent header and the reply can't drift (same rule as WORKBOOK_LINE). The
# board's name is Megan's exact wording (2026-08-15) — Carlos asked for it by
# that name, so the thread, the file and the Hub card all say it the same way.
BOARD_NAME = "Box Tier Bonus Rep Level"
# Just the board's name — Megan trimmed the trailing description off every line
# in the header on 2026-08-15 (see run.py's PAYOUT_LINE).
TIER_LINE = "\U0001F3C6 {}".format(BOARD_NAME)

# Measured on the live board 2026-08-15 (see the module docstring): the export
# canvas is 1600px tall and the rep table's scroll region ends ~1490px down.
# Anything at or past this is either clipped or one row from it — flag, post it
# anyway (the visible reps are still right).
CLIP_SUSPECT_PX = 1400
# An empty board still draws the title bar, the three filter captions and the
# table header — about 330px. A real board with even one rep clears 400.
EMPTY_MAX_PX = 400


def view_url(owner: str) -> str:
    """The board's URL sliced to one owner via the Owner Name quick filter."""
    from urllib.parse import quote
    return "{}?Owner%20Name={}&:iid=1".format(VIEW_URL, quote(owner))


def _spec(owner: str, day) -> dict:
    # The title is both the PNG's filename and the title Slack shows on the
    # attachment, so it carries the date like its two thread-mates ("BOX Order
    # Log 08-15-2026.xlsx", "BOX Payout 08-15-2026.png") — and a dated name
    # means today's board never overwrites yesterday's in output/.
    return {
        "id": "box_tier_bonus",
        "title": "{} {}".format(BOARD_NAME, day.strftime("%m-%d-%Y")),
        "url": view_url(owner),
        "crop": "canvas",
    }


def _check(path: Path, owner: str) -> str:
    """Return a warning string for a board that looks wrong, else "".

    Raises on an empty board: that means the Owner Name slice missed, and an
    empty tier board in the thread is worse than no tier board at all.
    """
    from PIL import Image
    with Image.open(path) as im:
        height = im.height
    if height <= EMPTY_MAX_PX:
        raise RuntimeError(
            "the Box Tier Bonus board came back empty for Owner Name={!r} "
            "({}px tall). The filter value has to match the board's Owner Name "
            "member exactly — check the spelling on the view.".format(
                owner, height))
    if height >= CLIP_SUSPECT_PX:
        return ("the tier board ran to the bottom of its scroll region "
                "({}px) — {} may now have more reps than fit in one image, so "
                "the last rows could be cut off".format(height, owner))
    return ""


def capture(dest_dir: Path, owner: str = DEFAULT_OWNER, *,
            page=None, day=None, verbose: bool = True) -> Tuple[Path, str]:
    """Capture the tier board for `owner`. Returns (png_path, warning).

    `page` reuses an already-open Tableau session (the crosstab pull's) so a run
    doesn't pay for a second browser launch; pass None to open one.
    """
    import datetime as _dt
    from automations.tableau_screenshots import capture as cap
    spec = _spec(owner, day or _dt.date.today())
    dest_dir = Path(dest_dir)
    if page is not None:
        out = cap.capture_page(page, spec, dest_dir, verbose=verbose)
    else:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=verbose) as own_page:
            out = cap.capture_page(own_page, spec, dest_dir, verbose=verbose)
    warning = _check(out, owner)
    if warning and verbose:
        print("  ⚠ {}".format(warning), flush=True)
    return out, warning


def capture_quietly(dest_dir: Path, owner: str = DEFAULT_OWNER, *,
                    page=None, day=None,
                    verbose: bool = True) -> Tuple[Optional[Path], str]:
    """capture(), but a failure comes back as a message instead of an exception.

    The order log is the report; the tier board is an addition to its thread. A
    Tableau flake on the image must not cost the channel the log itself — so the
    caller posts what it has and says plainly what's missing.
    """
    try:
        return capture(dest_dir, owner, page=page, day=day, verbose=verbose)
    except Exception as exc:                              # noqa: BLE001
        msg = "{}: {}".format(type(exc).__name__, str(exc).splitlines()[0][:200])
        if verbose:
            print("  ✗ Box Tier Bonus board not captured — {}".format(msg),
                  flush=True)
        return None, msg


def main(argv: Optional[list] = None) -> int:
    """Standalone capture, for eyeballing the board without running the report.

        python -m automations.box_order_log.tier_bonus
        python -m automations.box_order_log.tier_bonus --owner "Roshan Ahmad"
    """
    import argparse
    ap = argparse.ArgumentParser(
        description="Capture the Box Tier Bonus - Rep Level board for one owner")
    ap.add_argument("--owner", default=DEFAULT_OWNER,
                    help="Owner Name filter value (default: {})".format(DEFAULT_OWNER))
    ap.add_argument("--out", metavar="DIR",
                    help="where to write the PNG (default: output/)")
    args = ap.parse_args(argv)

    dest = Path(args.out) if args.out else (
        Path(__file__).resolve().parents[2] / "output")
    path, warning = capture(dest, args.owner)
    print("\n✅ {}".format(path))
    if warning:
        print("⚠ {}".format(warning))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
