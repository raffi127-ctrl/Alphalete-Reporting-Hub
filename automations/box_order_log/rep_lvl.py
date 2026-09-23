"""Box Daily Tracker - Rep Lvl board, captured for the Box Metrics thread.

Carlos's ask (2026-09-23): "can this screenshot get posted in the box threads we
post please. its called the box daily tracker - rep lvl".

Source: Tableau site `sci` -> workbook `B2BBOXEnergyTracker` (B2B Box Energy) ->
view `Box Daily Tracker - Rep Lvl`, as it opens (no URL filters): Daily Tracker
Sales - Rep Lvl on the left, Daily Tracker Metrics - Rep Lvl on the right. It's
the same view tracker_backup.py already reads as a crosstab.

ORG-WIDE board: every owner's reps are on it. So it rides Carlos's own thread
only; a per-office run (--owner-office) never gets it, because that would post
other offices' reps into one office's channel (same reason tier_bonus.py has no
default owner on a per-office run).

Python 3.9 on Lucy 2 / the mini — deferred annotations, no runtime `X | Y`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

VIEW_URL = ("https://us-east-1.online.tableau.com/#/site/sci/views/"
            "B2BBOXEnergyTracker/BoxDailyTracker-RepLvl?:iid=1")

# Carlos's name for it, used for the header line, the reply caption and the file.
BOARD_NAME = "Box Daily Tracker - Rep Lvl"
REP_LVL_LINE = "\U0001F4CB {}".format(BOARD_NAME)

# A board that drew only its title + filter captions (no rep rows) is short.
# A real one with the week's reps runs well past this.
EMPTY_MAX_PX = 400


def _spec(day) -> dict:
    # Dated title = dated filename, like its thread-mates, so today's image never
    # overwrites yesterday's in output/.
    return {
        "id": "box_rep_lvl",
        "title": "{} {}".format(BOARD_NAME, day.strftime("%m-%d-%Y")),
        "url": VIEW_URL,
        "crop": "canvas",
    }


def _check(path: Path) -> None:
    """Raise on an empty board: an empty image in the thread is worse than none."""
    from PIL import Image
    with Image.open(path) as im:
        height = im.height
    if height <= EMPTY_MAX_PX:
        raise RuntimeError(
            "the {} board came back empty ({}px tall)".format(BOARD_NAME, height))


def capture(dest_dir: Path, *, page=None, day=None,
            verbose: bool = True) -> Path:
    """Capture the board. `page` reuses an open Tableau session (the crosstab
    pull's); None opens one."""
    import datetime as _dt
    from automations.tableau_screenshots import capture as cap
    spec = _spec(day or _dt.date.today())
    dest_dir = Path(dest_dir)
    if page is not None:
        out = cap.capture_page(page, spec, dest_dir, verbose=verbose)
    else:
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=verbose) as own_page:
            out = cap.capture_page(own_page, spec, dest_dir, verbose=verbose)
    _check(out)
    return out


def capture_quietly(dest_dir: Path, *, page=None, day=None,
                    verbose: bool = True) -> Tuple[Optional[Path], str]:
    """capture(), but a failure comes back as a message instead of an exception —
    a Tableau flake on this image must never cost the channel the order log."""
    try:
        return capture(dest_dir, page=page, day=day, verbose=verbose), ""
    except Exception as exc:                              # noqa: BLE001
        msg = "{}: {}".format(type(exc).__name__, str(exc).splitlines()[0][:200])
        if verbose:
            print("  ⚠ {} not captured — {}".format(BOARD_NAME, msg), flush=True)
        return None, msg
