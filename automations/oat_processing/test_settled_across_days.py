"""Does a resume we already read stay read TOMORROW? Run:

    python -m automations.oat_processing.test_settled_across_days

WHY THIS EXISTS (2026-09-13, Megan: "you're tracking each push interval who to
skip over that you've already determined needs a human to process?"). We were —
but only until midnight. The no-number cache is keyed by DATE, so every morning
the entire flagged backlog got its resume reopened again: the same dead ends,
daily, forever, while new applicants queued behind them. In Carlos's office that
was ~26 people x ~12s re-paid every day out of the walk budget that decides how
fast a NEW applicant gets called.

THE SPLIT THIS PINS — and it is the whole point:
  * a resume we OPENED and found no number on is a verdict that keeps, so it
    carries across days and re-checks every SETTLED_RECHECK_DAYS;
  * a BLOCKED read (Cloudflare, the Indeed wall, a tab that never opened) is OUR
    failure and we never saw the resume, so it stays day-scoped and comes back
    tomorrow — exactly as it always did. Regressing that direction is the
    2026-08-25 bug again: 90 applicants written off unread in one day.

Touches nothing outside a temp dir: no browser, no Sheet, no sends.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt
import json
import tempfile
from pathlib import Path

from . import config
from . import run

_passed = 0
_failed = 0


def check(label, got, want) -> None:
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  [ok] {label}: {got!r}")
    else:
        _failed += 1
        print(f"  [FAIL] {label}: got {got!r}, want {want!r}")


class _Office:
    """One office's three caches in a scratch dir. `new_day()` rolls the
    date-keyed files the way midnight does, and leaves the cross-day store."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="oat-settled-"))
        self.day = 0
        run._nophone_settled_path = lambda: self.tmp / "settled.json"
        self.new_day()

    def new_day(self):
        self.day += 1
        run._NOPHONE_CHECKED = None
        run._NOPHONE_BLOCKED = None
        run._nophone_checked_path = lambda: self.tmp / f"checked-{self.day}.json"
        run._nophone_blocked_path = lambda: self.tmp / f"blocked-{self.day}.json"

    def skips(self, key) -> bool:
        return key in run._load_nophone_checked()


print("a resume we OPENED and found empty stays settled tomorrow:")
o = _Office()
run._mark_nophone_checked("dana reyes", confirmed=True)
check("skipped today", o.skips("dana reyes"), True)
o.new_day()
check("still skipped tomorrow — not re-opened", o.skips("dana reyes"), True)
o.new_day()
check("and the day after", o.skips("dana reyes"), True)

print("a BLOCKED read that ran out of tries comes back tomorrow:")
o = _Office()
# This is the promotion inside _mark_nophone_blocked: give up for TODAY having
# never seen the resume. It must NOT become a lasting verdict.
run._mark_nophone_checked("sam okafor")
check("skipped for the rest of today", o.skips("sam okafor"), True)
o.new_day()
check("retried tomorrow (we never saw that resume)", o.skips("sam okafor"), False)

print("the verdict expires, so a stale write-off cannot pin someone forever:")
o = _Office()
stale = (dt.date.today()
         - dt.timedelta(days=config.SETTLED_RECHECK_DAYS + 1)).isoformat()
fresh = dt.date.today().isoformat()
with open(run._nophone_settled_path(), "w") as fh:
    json.dump({"old verdict": stale, "recent verdict": fresh}, fh)
o.new_day()
check("past the re-check window — read again", o.skips("old verdict"), False)
check("inside the window — still skipped", o.skips("recent verdict"), True)
check("the expired row is pruned, not kept forever",
      "old verdict" in run._load_nophone_settled(), False)

print("a mid-day recheck clears the cross-day store too:")
# clear_nophone_cache exists for when the REASON a read failed gets fixed (the
# 2026-08-27 frame-blind read). A verdict that now outlives the day would pin
# those people for a week instead of until midnight, so it must be archived here.
o = _Office()
run._mark_nophone_checked("wrongly written off", confirmed=True)
check("settled before the recheck", o.skips("wrongly written off"), True)
run.reset_nophone_cache()
check("re-read after the recheck", o.skips("wrongly written off"), False)

print("EVERY terminal branch of flag_no_phone records a verdict:")
# THE BUG THIS PINS (2026-09-13). flag_no_phone has three ways to end without
# sending: the resume was blocked, there is no resume link at all, or the resume
# opened and carried no number. Two of them recorded a verdict. The no-link one
# did not — so those applicants were re-decided on every single walk, and each
# re-decision spends one of MAX_PER_RUN's work slots. Once 60 of them collect at
# the front of a queue, the walk never reaches anyone behind them: Carlos's queue
# went 178 -> 185 across three walks, one send, cache still 0.
#
# Read the SOURCE rather than driving a browser: the point is that no future edit
# adds a fourth silent exit. A branch that neither sends, removes, nor records is
# the whole failure mode.
import inspect as _inspect
import re as _re

_src = _inspect.getsource(run.flag_no_phone)


def _branch(start_needle, end_needle=None):
    """The source of ONE arm — from its log line to where the next arm begins.
    Slicing by a character count instead would silently pass the moment someone
    adds a comment, which is how this test would stop testing anything."""
    i = _src.find(start_needle)
    if i < 0:
        return ""
    j = _src.find(end_needle, i) if end_needle else -1
    return _src[i:j] if j > i else _src[i:]


# The two arms that end in a FLAG. Each must record a confirmed verdict, or the
# applicant is re-decided — and re-charged a work slot — on every future walk.
for _label, _seg in (
        ("no resume attached",
         _branch("no resume on file", "The resume OPENED")),
        ("resume opened, no number",
         _branch("no resume phone"))):
    check("%s: branch found" % _label, bool(_seg), True)
    check("%s: records a verdict" % _label,
          "_mark_nophone_checked" in _seg, True)
    check("%s: records it as CONFIRMED (survives the day)" % _label,
          "confirmed=True" in _seg, True)

# The blocked branch must NOT settle — we never saw that resume. Its bookkeeping
# is _mark_nophone_blocked, which retries and only settles after the last try.
_bidx = _src.find("resume read BLOCKED")
_btail = _src[_bidx:_bidx + 700] if _bidx >= 0 else ""
check("blocked read is tracked separately", "_mark_nophone_blocked" in _src, True)
check("blocked read does NOT get a confirmed verdict",
      "confirmed=True" in _btail, False)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
