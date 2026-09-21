"""Raf's grouped to-do thread must not post on a day nothing was walked.

Same rule as test_no_walk_no_post, which covers the per-office post: inside the
weekend quiet window (Fri 1PM -> Sun 1PM CST) no stream writes a flagged
snapshot, so every bucket reads empty. Posting then would tell Raf "0 need a
number ✅" about a queue nobody looked at — and his 11280 queue was 298 deep the
day this shipped.

Safety: the Slack client is never reached; a regression fails here instead.
"""
import datetime as dt
import io
import json
import os
import pathlib
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automations.oat_processing import rollup  # noqa: E402

_failed = 0


def check(label, got, want):
    global _failed
    if got == want:
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


_prev = os.getcwd()
with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)                      # no output/oat-flagged-*.json here
    os.makedirs("output", exist_ok=True)
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = rollup.post("raf", dry_run=False)   # live path on purpose
        out = buf.getvalue()
        print("a weekend day, no walks anywhere:")
        check("posts nothing", res.get("skipped"), "no walk today")
        check("says why", "posting NOTHING" in out, True)

        # One stream walked -> the thread IS worth posting, and the silent ones
        # say so for themselves rather than being counted as clear.
        today = dt.date.today().isoformat()
        with open("output/oat-flagged-%s-11280.json" % today, "w") as fh:
            json.dump({"queue_total": 298, "nophone": [
                {"name": "Ana Diaz", "account": "hr@fasttrackstrategies.com",
                 "days": 3}], "retext": []}, fh)
        buf = io.StringIO()
        with redirect_stdout(buf):
            res2 = rollup.post("raf", dry_run=True)
        out2 = buf.getvalue()
        print("one stream walked, two silent:")
        check("posts", res2.get("skipped"), None)
        check("counts the walked stream", res2.get("no_number"), 1)
        # The PARENT is one line since 2026-09-20 (Raf: "can we make this a
        # cleaner thread"), so the per-stream detail moved to the replies — but
        # a total that silently omits a stream is still the understated-backlog
        # failure, so the parent must say it is partial.
        check("the parent says how many streams it covers",
              "1 of 3 streams" in out2, True)
        check("the unwalked streams still get a reply saying so",
              "No walk has finished for this stream today" in out2, True)
    finally:
        os.chdir(_prev)

print("FAILED" if _failed else "ALL PASSED")
raise SystemExit(1 if _failed else 0)
