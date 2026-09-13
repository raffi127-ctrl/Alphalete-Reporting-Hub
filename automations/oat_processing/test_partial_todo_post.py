"""A partial walk still produces a to-do list, and says it is partial. Run:

    python -m automations.oat_processing.test_partial_todo_post

WHY THIS EXISTS (2026-09-13). A walk stops at MAX_PER_RUN, so it is PARTIAL
whenever the queue is bigger than that. A partial walk used to write no snapshot
at all, and the noon/4pm to-do post then found nothing and skipped — silently.
That withheld the list from exactly the offices that needed it most: Carlos's
queue crossed 60 and both his lists simply stopped, with nothing saying so.

The 2026-08-27 bug the all-or-nothing rule was written for is still guarded, just
differently. The danger then was a SHORT list read as the whole backlog — Megan:
"you have follow up need for 6 on atef but his inbox is 23." A list that states
its own coverage cannot be misread that way, so the post now labels itself.

Touches nothing outside a temp dir: no browser, no Sheet, no posts.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt
import json
import tempfile
import os
from pathlib import Path

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


TODAY = dt.date(2026, 9, 13)
tmp = Path(tempfile.mkdtemp(prefix="oat-snap-"))
os.chdir(tmp)          # the writer uses a relative "output/" path
FLAG = {"nophone": [{"name": "Dana Reyes", "account": "a@b.c"}], "retext": []}


def snap():
    p = tmp / "output" / f"oat-flagged-{TODAY.isoformat()}.json"
    try:
        with open(p) as fh:
            return json.load(fh)
    except Exception:
        return None


print("a PARTIAL walk now writes a snapshot instead of nothing:")
run._write_flagged_snapshot(FLAG, 183, TODAY, complete=False, covered=62)
s = snap()
check("snapshot exists", s is not None, True)
check("it is marked partial", s.get("complete"), False)
check("it carries what it covered", s.get("covered"), 62)
check("and the queue it was measured against", s.get("queue_total"), 183)

print("a better partial (more coverage) replaces a worse one:")
run._write_flagged_snapshot(FLAG, 183, TODAY, complete=False, covered=120)
check("kept the wider walk", snap().get("covered"), 120)

print("a worse partial does NOT replace a better one:")
run._write_flagged_snapshot(FLAG, 183, TODAY, complete=False, covered=30)
check("still the wider walk", snap().get("covered"), 120)

print("a COMPLETE walk replaces a partial:")
run._write_flagged_snapshot(FLAG, 183, TODAY, complete=True, covered=183)
check("now complete", snap().get("complete"), True)

print("and a later partial must NOT clobber today's complete snapshot:")
# This is the 2026-08-27 protection: the best information of the day wins, so a
# short walk late in the afternoon cannot shrink a full picture already taken.
run._write_flagged_snapshot(FLAG, 183, TODAY, complete=False, covered=40)
check("complete snapshot survived", snap().get("complete"), True)
check("coverage not downgraded", snap().get("covered"), 183)

print("coverage is measured against the queue we STARTED on:")
# THE BUG (2026-09-13, live in Carlos's channel): the denominator was the queue
# size at the END of the walk. That is smaller than what the walk went through,
# precisely because the walk sent and removed people out of it — so the post read
# "partial: walk covered 23 of 10 in the queue". Megan: "23 of 10??"
# A FRESH day: the block above deliberately left a COMPLETE snapshot for TODAY,
# and the precedence rule would (correctly) refuse to overwrite it.
OTHER = dt.date(2026, 9, 14)
run._write_flagged_snapshot(FLAG, 10, OTHER, complete=False, covered=23,
                            queue_start=48)


def snap2():
    with open(tmp / "output" / f"oat-flagged-{OTHER.isoformat()}.json") as fh:
        return json.load(fh)


s2 = snap2()
check("denominator is the START queue", s2.get("queue_start"), 48)
check("the END queue is still recorded separately", s2.get("queue_total"), 10)
check("covered is what we read", s2.get("covered"), 23)

print("the header renders a sane ratio, and refuses an insane one:")
from . import summary as _summary
import datetime as _dt
_t = {"nophone": [{"name": "Dana Reyes", "account": ""}], "retext": []}


def _header(cov):
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _summary.post_nophone_report(_dt.date(2026, 9, 13), _t, dry_run=True,
                                     coverage=cov)
    for line in buf.getvalue().splitlines():
        if "recruiting to-do" in line:
            return line
    return ""


check("a real ratio is stated",
      "covered 23 of 48 in the queue" in _header(
          {"complete": False, "covered": 23, "queue_start": 48, "queue_total": 10}),
      True)
# An old snapshot has no queue_start; a walk can also read MORE than it started
# with when records arrive mid-walk. Neither is a ratio — say the honest half
# rather than print another "23 of 10".
check("no queue_start -> no fake ratio",
      "applicant(s)" in _header(
          {"complete": False, "covered": 23, "queue_total": 10}),
      True)
check("covered > start -> no fake ratio",
      "applicant(s)" in _header(
          {"complete": False, "covered": 23, "queue_start": 10}),
      True)
check("a complete walk still says nothing about coverage",
      "partial" not in _header({"complete": True, "covered": 48, "queue_start": 48}),
      True)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
