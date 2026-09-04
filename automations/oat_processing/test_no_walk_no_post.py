"""A day the walk never ran must post NO to-do list.

The noon/4pm "recruiting to-do" post reads the walk's snapshot file. On a day
nothing was walked — the weekend quiet window (Fri 1pm -> Sun 1pm), or a wedged
session — that file doesn't exist, every bucket reads empty, and the post used to
go out as "0 need a number, 0 need a manual text · (none today ✅)" to Carlos's
and Atef's channels. The queue isn't clear on those days; it just wasn't looked
at. (2026-09-04, found the afternoon the quiet window shipped — the first
Saturday it would have fired was the next day.)

Safety: post_nophone_report is replaced with a raiser, so a regression FAILS the
test instead of posting to Slack. --dry-run is passed as a second belt.
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

from automations.oat_processing import summary  # noqa: E402


def _boom(*a, **k):
    raise AssertionError("posted a to-do list on a day nothing was walked")


summary.post_nophone_report = _boom
DAY = dt.date(2026, 9, 5)          # the first Saturday inside the quiet window

_prev = os.getcwd()
with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)                   # no output/oat-flagged-<date>.json here
    os.makedirs("output", exist_ok=True)
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = summary.main(["--nophone", "--date", DAY.isoformat(), "--dry-run"])
        out = buf.getvalue()
    finally:
        os.chdir(_prev)

assert rc == 0, f"a skipped day is not an error, got rc={rc}"
assert "no walk snapshot" in out, f"the log has to say why nothing posted:\n{out}"
assert "0 need a number" not in out, f"the empty to-do list leaked out:\n{out}"

# ...and the OTHER side of the line: the walk DID run and found nothing to hand
# a human. That file exists with empty buckets, and "(none today ✅)" is then the
# truth, so it still posts. Guard against the skip growing teeth it shouldn't.
posted = {}
summary.post_nophone_report = lambda date, t, **k: posted.update(
    {"date": date, "t": t}) or {"ok": True}

with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    os.makedirs("output", exist_ok=True)
    path = ("output/oat-flagged-{}{}.json"
            .format(DAY.isoformat(), summary.config.FILE_SUFFIX))
    with open(path, "w") as fh:
        json.dump({"at": "16:00", "queue_total": 0, "nophone": [], "retext": []}, fh)
    try:
        with redirect_stdout(io.StringIO()):
            rc2 = summary.main(["--nophone", "--date", DAY.isoformat(), "--dry-run"])
    finally:
        os.chdir(_prev)

assert rc2 == 0 and posted, "a walk that found nothing must still post the ✅"

print("ok: no walk snapshot -> no to-do post; an empty walk still posts")
