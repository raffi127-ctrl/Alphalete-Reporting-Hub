"""Browser-free checks on picking the FOR LUCY template out of the SMS modal.

THE BUG THIS PINS (2026-08-27): the modal renders its template list
asynchronously inside a frame, and the code looked exactly ONCE, after a fixed
sleep. Whenever the render was slower than the sleep, the Select link "wasn't
there" and the re-text was abandoned — 46 times that day (39 Atef, 7 Carlos),
every one of which had ALREADY bound the applicant's thread and only needed the
template picked. The skew is the tell: Atef's office was added to Lucy 2 the day
before, doubling the machine's work and making every fixed sleep likelier to
expire early. Waiting for the row instead of racing it is the fix.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_template_wait
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


class _Page:
    """A page whose template row only appears after `appears_after` looks."""

    def __init__(self, appears_after, waits=None):
        self.looks = 0
        self.appears_after = appears_after
        self.waited = 0
        self.waits = waits if waits is not None else []

    def wait_for_timeout(self, ms):
        self.waited += ms
        self.waits.append(ms)


def patched_xframe(page, selector):
    page.looks += 1
    if page.looks > page.appears_after:
        return "frame", "SELECT_LINK"
    return None, None


def run_wait(page, timeout_s=12.0, on_retry=None):
    orig = oat._xframe
    oat._xframe = patched_xframe
    try:
        return oat._xframe_wait(page, "sel", timeout_s=timeout_s, poll_ms=10,
                                on_retry=on_retry)
    finally:
        oat._xframe = orig


print("the row is already there — found on the first look, no waiting:")
p = _Page(appears_after=0)
fr, loc, tries = run_wait(p)
check("found", loc, "SELECT_LINK")
check("no extra polls", tries, 0)
check("did not sleep", p.waited, 0)

print("the reported case — the row renders late, we now wait for it:")
p = _Page(appears_after=5)
fr, loc, tries = run_wait(p)
check("found instead of abandoned", loc, "SELECT_LINK")
check("took extra polls", tries, 5)

print("the row never appears — still gives up, same as before:")
p = _Page(appears_after=10**9)
fr, loc, tries = run_wait(p, timeout_s=0.05)
check("gives up", loc, None)
check("reports it polled", tries > 0, True)

print("the filter is retyped on every poll (the box can appear late):")
typed = []
p = _Page(appears_after=3)
run_wait(p, on_retry=lambda n: typed.append(n))
check("retyped once per poll", typed, [1, 2, 3])

print("a filter that throws never breaks the wait:")


def _boom(_n):
    raise RuntimeError("search box detached")


p = _Page(appears_after=2)
fr, loc, tries = run_wait(p, on_retry=_boom)
check("still found the row", loc, "SELECT_LINK")

print("the Select selector accepts link, button and input renderings:")
x = oat._SELECT_TEMPLATE_XPATH
for kind in ("//a[normalize-space(.)='Select']", "//button[normalize-space(.)='Select']",
             "//input[@type='button']", "//input[@type='submit']"):
    check("handles %s" % kind.split("[")[0].strip("/"), kind in x, True)
check("still scoped to the FOR LUCY row", x.count("FOR LUCY") >= 4, True)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
