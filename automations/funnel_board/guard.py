"""Catch a hand edit to the Daily Log — someone writing where only the run should.

WHY (2026-08-10). While the five-office access bug was being chased, the Daily
Log kept gaining managers between runs: 9 → 12 → 13 current, while every run's
log showed the same 9 offices pulled. Four separate runs had to be grepped
line-by-line before it was clear the improvements weren't coming from the report
at all. Nobody ever found out who was writing.

The cost isn't the mystery, it's that "the Sheet looks better" was read as "the
run worked". A foreign write and a successful run are indistinguishable when you
only look at the Sheet — so this makes them distinguishable.

HOW. After a successful write the run stamps the Daily Log with who wrote it,
from where, when, and a fingerprint of the rows it left behind. The next run
re-fingerprints what it finds. Same fingerprint means the Sheet is exactly as
this report left it. Different means something edited it in between — the run
says so loudly and pings Slack.

The stamp lives in row 1 past the data columns, and is found by its LABEL, never
by a column index — build.py wipes the whole tab and rewrites it every run, so
the stamp is re-written each time and the header width is free to change.

A drift report is NOT a failure. Late backfills by a person are legitimate, and
the report's own restatement rule overwrites the week anyway. This only removes
the silence.
"""
import datetime as dt
import hashlib
import json
import os
import socket
from pathlib import Path

LABEL = "· last automated write"
TAB = "Daily Log"
_MARKER = Path(__file__).resolve().parents[2] / ".machine-profile"
SLACK_CHANNEL = "C0BK5PRG259"   # #claudecorrections-and-requests


def machine():
    """Which runner this is: the .machine-profile marker, else the hostname."""
    try:
        v = _MARKER.read_text().strip()
        if v:
            return v
    except Exception:  # noqa: BLE001
        pass
    try:
        return socket.gethostname()
    except Exception:  # noqa: BLE001
        return "?"


def _rows(S, api):
    r = S.get(api + "/values/'%s'!A1:U100000" % TAB,
              params={"valueRenderOption": "UNFORMATTED_VALUE"})
    return r.json().get("values", []) if r.status_code == 200 else []


def fingerprint(rows):
    """A stable digest of the data block, stamp cell excluded.

    Only columns A..U — the stamp sits past them, so stamping never changes the
    fingerprint of the data it describes.
    """
    body = [[("" if c is None else str(c)) for c in row[:21]] for row in rows]
    return hashlib.sha1(
        json.dumps(body, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def _a1col(n):
    """1 -> A, 27 -> AA. Spelled out rather than trusting R1C1 in the range."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _read_stamp(S, api):
    """The stamp row-1 cell, found by label. None if it was never written."""
    r = S.get(api + "/values/'%s'!1:1" % TAB)
    row = (r.json().get("values") or [[]])[0] if r.status_code == 200 else []
    for i, cell in enumerate(row):
        if str(cell).strip() == LABEL and i + 1 < len(row):
            try:
                return json.loads(row[i + 1])
            except Exception:  # noqa: BLE001 — a mangled stamp is a missing one
                return None
    return None


def check(S, api, log):
    """Compare what's on the Sheet now against what this report last left.

    Returns the drift message, or None when the Sheet is untouched (or has no
    stamp yet — the first run after this ships has nothing to compare with).
    NEVER raises: a broken guard must not cost a day of numbers.
    """
    try:
        stamp = _read_stamp(S, api)
        if not stamp or not stamp.get("fp"):
            log("guard: no stamp yet — nothing to compare (first run)")
            return None
        now = fingerprint(_rows(S, api))
        if now == stamp["fp"]:
            log("guard: Daily Log is exactly as this report left it")
            return None
        msg = ("the Daily Log changed since the last run of this report — "
               "last written %s by %s on %s, but what's there now doesn't match"
               % (stamp.get("at", "?"), stamp.get("by", "?"),
                  stamp.get("machine", "?")))
        log("guard: ⚠ %s" % msg)
        return msg
    except Exception as e:  # noqa: BLE001
        log("guard: check skipped (%s: %s)" % (type(e).__name__, str(e)[:120]))
        return None


def stamp(S, api, identity, log):
    """Record who just wrote, from where, and what the Sheet looks like now."""
    try:
        rows = _rows(S, api)
        head = rows[0] if rows else []
        # Two clear columns past the data, so the stamp can never be mistaken
        # for a metric and never collides with a widening header.
        col = len(head) + 2
        payload = {
            "fp": fingerprint(rows),
            "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "by": identity,
            "machine": machine(),
        }
        S.post(api + "/values:batchUpdate", json={
            "valueInputOption": "RAW",
            "data": [{
                "range": "'%s'!%s1:%s1" % (TAB, _a1col(col), _a1col(col + 1)),
                "values": [[LABEL, json.dumps(payload, separators=(",", ":"))]],
            }],
        })
        log("guard: stamped (%s on %s)" % (identity, payload["machine"]))
    except Exception as e:  # noqa: BLE001
        log("guard: stamp skipped (%s: %s)" % (type(e).__name__, str(e)[:120]))


def ping(msg, log, dry_run=False):
    """Say it in Slack too. A log line nobody reads is not an alert.

    Never raises — a failed ping must not fail the report it is warning about.
    """
    text = ("🔎 *Recruiting Funnel Board* — %s\n"
            "Not a failure: the run still re-pulls and overwrites the whole "
            "week. Worth knowing who edited it, and whether their numbers just "
            "got overwritten." % msg)
    if dry_run or os.environ.get("FUNNEL_NO_SLACK"):
        log("guard: (not posting) %s" % text.replace("\n", " "))
        return
    try:
        from automations.shared import slack_metrics_post as smp
        smp._client().chat_postMessage(channel=SLACK_CHANNEL, text=text)
        log("guard: posted the drift notice to Slack")
    except Exception as e:  # noqa: BLE001
        log("guard: Slack notice didn't post (%s: %s)"
            % (type(e).__name__, str(e)[:120]))
