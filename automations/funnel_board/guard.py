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
    """The whole tab — the bare sheet name returns exactly the used range.

    NOT a guessed A1:U window. The header is 25 columns wide, not the 21 an
    earlier version assumed, so a fixed window both cut four real columns out of
    the fingerprint and put the stamp on top of live header cells.
    """
    r = S.get(api + "/values/'%s'" % TAB,
              params={"valueRenderOption": "UNFORMATTED_VALUE"})
    return r.json().get("values", []) if r.status_code == 200 else []


def fingerprint(rows):
    """A stable digest of the DATA rows — row 1 excluded, full width.

    Skipping the header is what keeps the stamp out of the fingerprint: the
    stamp lives in row 1, so it can never change the digest of the data it
    describes, no matter which column it lands in.
    """
    body = [[("" if c is None else str(c)) for c in row] for row in rows[1:]]
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
        # Two clear columns past the WIDEST row, not just past the header — a
        # data row can run wider than row 1, and the stamp must never land on a
        # cell anything else reads.
        col = max((len(r) for r in rows), default=0) + 2
        payload = {
            "fp": fingerprint(rows),
            "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "by": identity,
            "machine": machine(),
        }
        rng = "'%s'!%s1:%s1" % (TAB, _a1col(col), _a1col(col + 1))
        r = S.post(api + "/values:batchUpdate", json={
            "valueInputOption": "RAW",
            "data": [{
                "range": rng,
                "values": [[LABEL, json.dumps(payload, separators=(",", ":"))]],
            }],
        })
        # Say it FAILED when it failed. The first cut logged "stamped"
        # unconditionally and the write was silently rejected — a guard that
        # lies about its own state is worse than no guard.
        if r.status_code != 200:
            log("guard: stamp REJECTED at %s (%s) %s"
                % (rng, r.status_code, r.text[:200]))
            return
        log("guard: stamped at %s (%s on %s)" % (rng, identity, payload["machine"]))
    except Exception as e:  # noqa: BLE001
        log("guard: stamp skipped (%s: %s)" % (type(e).__name__, str(e)[:120]))


# One thread for "the Daily Log is being hand-edited", however many mornings it
# keeps happening — each new drift replies under the first notice instead of
# adding another post, and a clean run closes it (Eve 2026-08-14).
INCIDENT = "funnel-daily-log-drift"


def ping(msg, log, dry_run=False):
    """Say it in Slack too. A log line nobody reads is not an alert.

    Never raises — a failed ping must not fail the report it is warning about.
    """
    head = "🔎 *Recruiting Funnel Board* — %s" % msg
    body = ["Not a failure: the run still re-pulls and overwrites the whole "
            "week. Worth knowing who edited it, and whether their numbers just "
            "got overwritten."]
    if dry_run or os.environ.get("FUNNEL_NO_SLACK"):
        log("guard: (not posting) %s" % " ".join([head] + body))
        return
    try:
        from automations.shared import slack_metrics_post as smp
        posted = None
        try:
            from automations.shared import incident_thread as inc
            posted = inc.open_or_followup(key=INCIDENT, title=head, body=body,
                                          channel=SLACK_CHANNEL)
        except Exception as e:  # noqa: BLE001 — fall back to a plain post
            log("guard: incident thread unavailable (%s: %s)"
                % (type(e).__name__, str(e)[:80]))
        if not posted:
            smp._client().chat_postMessage(channel=SLACK_CHANNEL,
                                           text="\n".join([head] + body))
        log("guard: posted the drift notice to Slack")
    except Exception as e:  # noqa: BLE001
        log("guard: Slack notice didn't post (%s: %s)"
            % (type(e).__name__, str(e)[:120]))


def resolved(log, dry_run=False):
    """The Sheet is exactly as this report left it — close an open drift thread.

    Called on the clean path so the channel says when the hand-editing stopped,
    not only when it started. Free when nothing is open."""
    if dry_run or os.environ.get("FUNNEL_NO_SLACK"):
        return
    try:
        from automations.shared import incident_thread as inc
        if inc.resolve_if_open(INCIDENT,
                               what="*Recruiting Funnel Board* — the Daily Log "
                                    "is untouched again",
                               detail="_Nobody has edited it since the last "
                                      "run._",
                               channel=SLACK_CHANNEL):
            log("guard: closed the open drift notice — Sheet is clean")
    except Exception as e:  # noqa: BLE001
        log("guard: couldn't close the drift notice (%s: %s)"
            % (type(e).__name__, str(e)[:120]))
