"""Tick the "Blue Ink" checkbox for anyone whose packet is SIGNED.

Two different marks live in that one column, and they mean different things:

  light green background  we sent it            (mark.highlight, at send time)
  checkbox ticked         they have SIGNED it   (here)

Sending is a moment; signing happens whenever the person gets round to it. So
this is a separate pass that re-reads Blue Ink's own list and ticks whoever has
finished since last time. Safe to run as often as you like.

Only ever ticks ON. It never un-ticks: somebody may have checked a box by hand
for a packet sent before this report existed, and clearing that would be
deleting a colleague's work to satisfy our own view of the world.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Dict, List

import gspread

from automations.blueink_docs import recent_ui
from automations.blueink_docs import session as S
from automations.blueink_docs.roster import NewStart

# Row prefixes on the dashboard list that mean "signed and finished".
DONE = {"completed", "complete", "signed"}

# How far back a completion counts (Megan 2026-08-24). The Completed column
# sorts newest first and runs to thousands of rows, so only the last week is
# this cohort; anything older belongs to an earlier one -- or to a rehire whose
# previous packet must not tick this week's box.
#
# Shorter than the duplicate check's 14 days on purpose: the two answer
# different questions. "Don't send them a second packet" wants to be generous
# about what counts as recent; "they have signed THIS week's packet" wants to
# be strict.
LOOKBACK_DAYS = 7

TRUTHY = {"true", "yes", "y", "1", "x", "✓"}


def _within(datestr: str, today: dt.date, days: int = LOOKBACK_DAYS) -> bool:
    """Is this row's date inside the window? An unreadable date does NOT count
    -- the opposite of the duplicate check, and deliberately. There, an
    unparseable date blocks a send (cautious). Here it would tick a box saying
    somebody signed, which is a claim we shouldn't make on a date we couldn't
    read."""
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            when = dt.datetime.strptime(datestr, fmt).date()
        except ValueError:
            continue
        return 0 <= (today - when).days <= days
    return False


def _is_done(text: str, today=None) -> bool:
    """Does this search result show a FINISHED packet, in the last week?

    The dashboard is three columns -- Draft / Sent / Completed -- and a search
    returns the person's rows from all of them. So "Complete" appearing is not
    enough on its own: a rehire could have signed something months ago while
    this week's packet sits unsigned.
    """
    today = today or dt.date.today()
    for status, datestr in recent_ui._ROW_RE.findall(text or ""):
        if status.lower() in DONE and _within(datestr, today):
            return True
    return False


_COMPLETE_RE = re.compile(
    r"Complete(\d{1,2}/\d{1,2}/\d{2,4})\s+(.+?)"
    r"(?=Complete\d|Sent\d|Draft\d|Started\d|Declined\d|Expired\d|$)")

# How many times to scroll the Completed pane. Each pass loads ~40 more rows;
# the default view holds 40 and reaches back ~4 days, 8 passes reached 3 weeks.
_SCROLL_PASSES = 8

_SCROLL_JS = """() => {
    const els = [...document.querySelectorAll('div')]
      .filter(e => e.scrollHeight > e.clientHeight + 50 && e.clientHeight > 200);
    const last = els[els.length - 1];      // Draft | Sent | Completed
    if (last) last.scrollTop = last.scrollHeight;
}"""


def scan_completed(page, today: dt.date = None) -> Dict[str, str]:
    """{normalised name: date} for every packet signed inside the window.

    ONE page read for the whole roster, rather than a search each. A search is
    ~10 seconds, so per-person cost 50+ people nearly ten minutes -- fine once
    on a Monday, hopeless for a sweep meant to run through the day. The
    Completed column already lists exactly what we need; it just has to be
    scrolled, since it loads 40 rows at a time.
    """
    today = today or dt.date.today()
    for _ in range(_SCROLL_PASSES):
        page.evaluate(_SCROLL_JS)
        page.wait_for_timeout(2200)
    text = " ".join((page.inner_text("body") or "").split())

    out: Dict[str, str] = {}
    for datestr, name in _COMPLETE_RE.findall(text):
        if not _within(datestr, today):
            continue
        name = name.strip()
        # Rows carry the signer's INITIALS after the name ("Cale Mckenna CM");
        # and an envelope nobody renamed reads "Raf Documents", which is a
        # label, not a person -- it can't match a roster name, so it falls out.
        name = re.sub(r"\s+[A-Z]{1,3}$", "", name).strip()
        if name:
            out.setdefault(_norm_name(name), datestr)
    return out


def _norm_name(s: str) -> str:
    from automations.blueink_docs.roster import _norm
    parts = [p for p in re.split(r"\s+", (s or "").strip()) if p]
    if len(parts) < 2:
        return ""
    return _norm(parts[-1]) + "|" + _norm(" ".join(parts[:-1]))


def find_completed(people: List[NewStart], headless: bool = True) -> Dict[str, str]:
    """{person key: date signed} for everyone whose packet is now signed.

    Skips anyone already ticked -- no point looking up what the sheet says.
    """
    todo = [p for p in people
            if p.blueink_col and (p.blueink_val or "").strip().lower() not in TRUTHY]
    if not todo:
        return {}
    with S._sync_api()() as pw:
        browser, ctx = S.open_context(pw, headless=headless)
        page = ctx.new_page()
        try:
            page.goto(recent_ui.DASHBOARD, wait_until="domcontentloaded",
                      timeout=recent_ui.NAV_TIMEOUT)
            page.wait_for_timeout(12000)
            if "/login" in page.url:
                raise RuntimeError(
                    "The Blue Ink session on this machine has expired. At the "
                    "keyboard here run: python -m "
                    "automations.blueink_docs.session --login")
            signed = scan_completed(page)
        finally:
            browser.close()
    return {p.key: signed[p.key] for p in todo if p.key in signed}


def tick(worksheet, people: List[NewStart], done_keys: Dict[str, str]) -> int:
    """Write TRUE into the Blue Ink cell for everyone in `done_keys`.

    One batched write -- a per-cell loop burns the Sheets quota and 429s the
    next report as well as this one.
    """
    targets = [p for p in people
               if p.key in done_keys and p.blueink_col and p.row]
    if not targets:
        return 0
    worksheet.batch_update(
        [{"range": gspread.utils.rowcol_to_a1(p.row, p.blueink_col),
          "values": [["TRUE"]]} for p in targets],
        value_input_option="USER_ENTERED")   # so the checkbox actually ticks
    return len(targets)
