"""Advancing the OAT pager: when is "no next control" really the end of the queue?

THE BUG THIS PINS (2026-08-27): advance_to_next checked each candidate selector
ONCE with count(), no waiting. Every send / remove / re-text re-renders the page,
so a look taken the instant before the pager came back read as "the queue has
ended". Walks stopped with most of the queue untouched — Atef 11 of 21, 15 of 22,
15 of 23; Carlos 2 of 13 and 3 of 13 — and because those walks then called
themselves complete, the to-do post published a short list as the whole backlog.
Megan spotted it from the outside: "you have follow up need for 6 on atef but his
inbox is 23, that doesn't line up." 52 walks ended this way in one day.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_pager_wait
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

from automations.oat_processing import run as oat

_passed = 0
_failed = 0


def check(label, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


class _Loc:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self          # page.locator(xp).first

    def count(self):
        return 1 if self.page.looks >= self.page.appears_after else 0

    def click(self, **_kw):
        self.page.clicked = True


class _Page:
    """Pager control appears only once `appears_after` looks have happened."""

    def __init__(self, appears_after):
        self.appears_after = appears_after
        self.looks = 0
        self.clicked = False
        self.waited = 0

    def locator(self, _xp):
        self.looks += 1          # each candidate selector counts as a look
        return _Loc(self)

    def wait_for_timeout(self, ms):
        self.waited += ms


print("pager is there immediately — clicked, no waiting:")
p = _Page(appears_after=1)
check("advanced", oat.advance_to_next(p), True)
check("clicked it", p.clicked, True)

print("the reported case — pager re-renders late, we now wait for it:")
# 4 candidate selectors per poll, so ~12 looks is roughly 3 extra polls.
p = _Page(appears_after=12)
check("advanced instead of ending the walk", oat.advance_to_next(p), True)
check("clicked it", p.clicked, True)
check("it did wait", p.waited > 0, True)

print("genuinely the end of the queue — still returns False:")
p = _Page(appears_after=10**9)
check("ends the walk", oat.advance_to_next(p), False)
check("never clicked", p.clicked, False)

print("the wait is bounded — a real end gives up rather than hanging:")
check("polled more than once before giving up", p.looks > 4, True)

print("a selector that throws doesn't end the walk by itself:")


class _BoomPage(_Page):
    def __init__(self, appears_after, boom_until):
        _Page.__init__(self, appears_after)
        self.boom_until = boom_until

    def locator(self, xp):
        self.looks += 1
        if self.looks <= self.boom_until:
            raise RuntimeError("detached")
        return _Loc(self)


p = _BoomPage(appears_after=1, boom_until=6)
check("recovered after throwing looks", oat.advance_to_next(p), True)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
