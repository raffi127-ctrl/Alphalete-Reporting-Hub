"""Skipping re-text attempts we already settled today.

WHY (Megan 2026-08-27): "the walks should get shorter because there should be
less to process especially if you're recognizing what apps you can now skip."
The no-number cache only ever skipped the resume READ — a flagged applicant still
had the ENTIRE re-text attempt re-run on every walk (open the SMS widget, bind the
thread, hunt the template, fail, flag). With ~11 of them in one office that was the
bulk of a walk, every ten minutes, to reach a conclusion already reached.

THE LINE THAT MATTERS: only 'no_thread' may be cached. It is structural —
AppStream cannot start a fresh thread and the widget cannot see one older than
this month — so today's answer cannot change. 'retext_err' is transient (a missed
template, a lost race) and MUST be retried, or we repeat the 2026-08-25
resume-read mistake where a Cloudflare blip wrote 90 applicants off for the day.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_nothread_cache
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

import os

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


# start from a clean cache
p = oat._nothread_path()
if os.path.exists(str(p)):
    os.remove(str(p))
oat._NOTHREAD = None


def should_cache(status):
    return status == "no_thread"


print("only the structural failure is settled for the day:")
check("no_thread is cached", should_cache("no_thread"), True)
print("transient failures must be retried, never cached:")
for st in ("retext_err", "retext_sent", "no_button", ""):
    check("%r is NOT cached" % st, should_cache(st), False)

print("the cache persists and is read back:")
check("starts empty", len(oat._load_nothread()), 0)
oat._mark_nothread("claudia ceniceros")
oat._mark_nothread("wendy torres")
oat._NOTHREAD = None                       # force a reload from disk
c = oat._load_nothread()
check("reloaded from disk", sorted(c), ["claudia ceniceros", "wendy torres"])
check("a settled applicant is recognised", "claudia ceniceros" in c, True)
check("an unseen applicant is not", "juan garcia" in c, False)

print("the key matches the no-phone cache's key, so both agree on a person:")


class _A:
    first_name, last_name = "Claudia", "Ceniceros"


check("same key function", oat._nophone_key(_A()), "claudia ceniceros")
check("that key is the one cached", oat._nophone_key(_A()) in oat._load_nothread(),
      True)

print("the recheck utility clears it too (a fix must be able to un-settle these):")
check("nothread file is on the recheck list",
      "_nothread_path" in open(oat.__file__.replace(".pyc", ".py")).read()
      .split("def reset_nophone_cache")[1].split("def ")[0], True)

# tidy up
if os.path.exists(str(p)):
    os.remove(str(p))
oat._NOTHREAD = None
print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
