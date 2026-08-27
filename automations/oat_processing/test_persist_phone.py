"""Browser-free checks on saving a recovered number back onto the record.

WHY IT EXISTS: when the ATS refuses the send ("correspondence with this phone
number has already occurred"), the number read off the resume is never saved, so
the record still shows a blank phone. The next walk re-reads the same resume ~10
minutes later, forever — Claudia Ceniceros sat in that loop 8/21 to 8/27 — and the
human who has to text these people by hand opens the record and finds no number,
so they go pull it from Indeed themselves. A fresh SMS thread would skip the manual
text entirely, but AppStream cannot start one (Megan 8/27), so the number has to be
ON the record when the human arrives.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_persist_phone
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


SAVE_WORTHY = ("flag_retext", "left", "no_button", "flag_no_phone")
SKIP = ("sent", "sent_override", "removed", "retext_removed")


def should_save(outcome):
    return outcome not in ("sent", "sent_override", "removed", "retext_removed")


print("we save only when the applicant is still sitting in the queue:")
for o in SAVE_WORTHY:
    check("%s -> save the number" % o, should_save(o), True)
print("we never re-save a record that was sent or removed:")
for o in SKIP:
    check("%s -> leave it alone" % o, should_save(o), False)


class _Field:
    def __init__(self, value="", count=1):
        self._v, self._c, self.typed = value, count, False

    def count(self):
        return self._c

    def input_value(self):
        return self._v


class _Page:
    """Just enough page to drive _persist_phone's decisions."""

    def __init__(self, field, save_ok=True):
        self._f, self.save_ok, self.clicked = field, save_ok, []

    def locator(self, sel):
        class _L:
            first = self._f
        return _L()

    def wait_for_timeout(self, _ms):
        pass


def run_persist(page, phone, fill_ok=True, click_ok=True):
    """_persist_phone with its two browser actions stubbed."""
    orig_fill, orig_click = oat._fill_phone_field, oat._click_first
    oat._fill_phone_field = lambda p, ph: fill_ok
    oat._click_first = lambda p, labels: (page.clicked.append(labels) or click_ok)
    try:
        return oat._persist_phone(page, phone)
    finally:
        oat._fill_phone_field, oat._click_first = orig_fill, orig_click


print("the reported case — field went blank on refusal, so retype and save:")
p = _Page(_Field(""))
check("saved", run_persist(p, "+1 720 827 4344"), True)
check("clicked Save Applicant", "Save Applicant" in (p.clicked[0] if p.clicked else []), True)

print("field already holds the number — save without retyping:")
p = _Page(_Field("7208274344"))
check("saved", run_persist(p, "(720) 827-4344", fill_ok=False), True)

print("the leading 1 is not a different number:")
p = _Page(_Field("7208274344"))
check("+1 form matches what's in the field", run_persist(p, "+17208274344", fill_ok=False), True)

print("nothing to save onto — we left the record:")
check("no phone field -> False", run_persist(_Page(_Field("", count=0)), "7208274344"), False)

print("a number that isn't a real US number is never written:")
for bad in ("", "123", "555-010", None):
    check("%r -> False" % (bad,), run_persist(_Page(_Field("")), bad), False)

print("failures are quiet, not fatal:")
check("Save button missing -> False",
      run_persist(_Page(_Field("")), "7208274344", click_ok=False), False)
check("retype failed -> False",
      run_persist(_Page(_Field("")), "7208274344", fill_ok=False), False)


class _Boom:
    def count(self):
        raise RuntimeError("detached frame")


check("an exception is swallowed, the walk survives",
      run_persist(_Page(_Boom()), "7208274344"), False)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
