"""The SECOND gate on short knock boards — the morning re-check, in code.

Eve, 2026-09-09: "quiero que este doble chequeo lo repitas cada mañana."

WHY A SECOND GATE. The first one lives in total_knocks.pull: a Disposition grid
that comes back with fewer reps than clocked in is read again, and one that stays
drastically short raises KnocksPullFailed instead of mailing a board with most of
the office missing. It deliberately tolerates the rest — a gap under
SHORT_READ_MIN_GAP, or a grid still holding over half the office — because a rep
CAN clock in and disposition nothing, and refusing there would hold a captain's
whole email over a normal day.

That tolerated band is what this module watches. It cannot refuse (the boards are
already drawn by the time it runs, and a marginal gap is usually nothing), so it
does the other thing: it writes the ICD-by-ICD comparison into the capture log
every single morning, and it speaks up in Slack when something in the band looks
wrong. Until today that comparison was a person reading 600 log lines by hand;
this is that person's job, done the same way every day, before the drafts go out.

WHAT IT LOOKS AT, all from records total_knocks.pull wrote during the pull:

  * a FINAL read still under the Time Tracker — the tolerated band itself
  * a re-read that had to happen at all, even one that recovered: the grid was
    read while it was still filling, and that is worth seeing before it grows
  * rows == 0 while the Time Tracker had people out — the first gate's blind
    spot by construction (`bool(n_rows)` short-circuits both its checks), so
    nothing upstream can catch this one
  * an owner on the captainship roster who came back neither as a board nor as
    a note — a silently vanished office
  * an owner whose note is a real FAILURE, not an access gap or a real zero —
    ownerville timing out on ?p=901, the Office-Access table stalling. Until
    2026-09-11 these counted as "accounted for" (they HAVE a note), so the
    2026-09-10 run said CLEAN with four offices missing from the email.

Run as part of the capture (captainship_knocks, order 1, right before the drafts
at 1.1), so it cannot be forgotten and needs no session of its own:

    python -m automations.captainship_drafts.knocks_audit --self-test
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable, Optional

try:
    from automations.captainship_drafts.email_build import NO_DATA_MARK
except Exception:  # noqa: BLE001 — the audit must survive an import hiccup
    NO_DATA_MARK = "no-data::"

# The tolerated band of the FIRST gate is this module's whole beat, so it says
# out loud where its own line sits. A shortfall at or above this many reps is
# reported even though total_knocks.pull let it through; below it, a rep who
# clocked in and knocked nothing is the likeliest explanation and the channel
# does not need to hear about it every morning.
REPORT_MIN_GAP = 2

INCIDENT_KEY = "knocks-short-read"
TITLE = "Captainship knocks — a board came back short or failed"


# ---------------------------------------------------------------------------
# findings — pure, offline-testable
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """Loose name match: the roster spells an owner the way the Sales Board
    does, the audit records carry the canonical ownerville spelling, and the
    board labels can wear a ' — ⚠ INCOMPLETE: …' suffix."""
    s = (s or "").split(" — ")[0]
    return "".join(ch for ch in s.lower() if ch.isalnum())


def short_read_findings(records: Iterable[dict]) -> list[dict]:
    """One finding per office-day whose numbers deserve a look.

    Pure: `records` are total_knocks.pull.take_records() dicts and nothing here
    touches a page, a Sheet or Slack."""
    out = []
    for r in records or []:
        office = r.get("office") or "?"
        day = r.get("date") or ""
        rows = int(r.get("rows") or 0)
        tt = int(r.get("tt_reps") or 0)
        first = int(r.get("first_rows") or 0)
        gap = tt - rows
        if rows == 0 and tt > 0:
            # The blind spot: both halves of the first gate start with
            # `bool(n_rows)`, so an EMPTY grid is never re-read and never
            # refused. It reaches the email as "no knocks recorded yesterday".
            out.append({
                "office": office, "date": day, "kind": "empty-grid",
                "detail": (f"Disposition came back EMPTY but {tt} rep(s) "
                           f"clocked in — the email will say 'no knocks "
                           f"recorded yesterday' for this office"),
            })
        elif gap >= REPORT_MIN_GAP:
            out.append({
                "office": office, "date": day, "kind": "short",
                "detail": (f"board published {rows} rep(s), Time Tracker had "
                           f"{tt} out ({gap} short)"),
            })
        elif r.get("reread"):
            # Recovered — but the grid WAS read mid-fill, which is the failure
            # mode that mailed 2 reps of 22. Worth seeing while it is still
            # cheap to see.
            out.append({
                "office": office, "date": day, "kind": "reread",
                "detail": (f"first read gave {first} rep(s) against {tt} on "
                           f"the Time Tracker; the re-read recovered it to "
                           f"{rows}"),
            })
    return out


def coverage_findings(roster: Iterable[str], labels: Iterable[str],
                      error_keys: Iterable[str], *, captain: str = ""
                      ) -> list[dict]:
    """Roster owners that came back as neither a board nor a note.

    Every owner is supposed to end the capture in exactly one of three places:
    a rendered board, an error note (access gap or otherwise), or a blank with
    a reason. One in none of them did not fail — it disappeared, which is the
    one outcome nobody would notice reading the email."""
    seen = {_norm(x) for x in labels}
    seen |= {_norm(k.split(":", 1)[-1]) for k in error_keys}
    out = []
    for name in roster or []:
        if _norm(name) and _norm(name) not in seen:
            out.append({
                "office": name, "date": "", "kind": "missing",
                "detail": (f"on {captain}'s roster but the capture returned "
                           f"neither a board nor a note for them"),
            })
    return out


def failure_findings(errors: dict, *, captain: str = "") -> list[dict]:
    """Error notes that are real FAILURES.

    The capture marks the two harmless kinds of note with NO_DATA_MARK (grey
    box): an access gap (is_access_gap) and a source that answered with a real
    zero. Every other note is a failure the email shows as a yellow "could not
    be captured" box — an ownerville timeout, a stalled Office-Access table, a
    dead session. coverage_findings counts those owners as accounted for
    (they have a note), so without this check a morning with four offices
    missing still read CLEAN (2026-09-10)."""
    out = []
    for key, note in (errors or {}).items():
        note = str(note or "")
        if note.startswith(NO_DATA_MARK):
            continue
        kind, _, who = str(key).partition(":")
        section = "weekly" if kind == "knock_dispo" else "daily"
        out.append({
            "office": who or f"{captain} (whole {section} section)",
            "date": "", "kind": "failed",
            "detail": f"{section} pull FAILED — {note[:160]}",
        })
    return out


def summary_lines(records: Iterable[dict]) -> list[str]:
    """The ICD-by-ICD table, for the capture log.

    This prints EVERY morning, clean or not — it is the artefact that made the
    2026-09-09 review possible at all, and a check whose output only exists on
    bad days cannot be trusted on good ones."""
    recs = list(records or [])
    if not recs:
        return ["knocks audit: no pull records (every office reused or gapped)"]
    lines = [f"knocks audit - {len(recs)} office-day pull(s), "
             f"board rep(s) vs Time Tracker:"]
    for r in sorted(recs, key=lambda x: (x.get("office") or "").lower()):
        rows, tt = int(r.get("rows") or 0), int(r.get("tt_reps") or 0)
        flag = ""
        if rows == 0 and tt > 0:
            flag = "  <-- EMPTY GRID, people were out"
        elif tt - rows >= REPORT_MIN_GAP:
            flag = f"  <-- {tt - rows} short"
        elif r.get("reread"):
            flag = f"  <-- re-read (first gave {int(r.get('first_rows') or 0)})"
        lines.append(f"  {r.get('office', '?'):<28} {rows:>3} rep(s)  "
                     f"vs TT {tt:>3}{flag}")
    return lines


def verdict(findings: Iterable[dict]) -> str:
    """One line for the log and the Slack headline."""
    f = list(findings or [])
    if not f:
        return "knocks audit: CLEAN - no board came back short of the Time Tracker"
    kinds = {}
    for x in f:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    parts = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
    return f"knocks audit: {len(f)} finding(s) - {parts}"


def alert_body(findings: Iterable[dict]) -> list[str]:
    """The Slack body. English — the whole team reads that channel."""
    findings = list(findings or [])
    body = []
    for x in findings:
        when = f" ({x['date']})" if x.get("date") else ""
        body.append(f"• {x['office']}{when}: {x['detail']}")
    body.append("")
    if any(x["kind"] == "failed" for x in findings):
        body.append("FAILED = ownerville broke on that office (not an access "
                    "gap): its section shows a yellow 'could not be captured' "
                    "box. Re-run the capture for that captain "
                    "(knocks_capture --only <captain> --fresh) before the "
                    "email is approved.")
    if any(x["kind"] != "failed" for x in findings):
        body.append("The first gate (re-read + refuse) did not fire on the "
                    "others — they are inside its tolerated band, which is "
                    "what this second check is for. Look at the office in "
                    "ownerville before the captain's email is approved.")
    return body


# ---------------------------------------------------------------------------
# the morning run
# ---------------------------------------------------------------------------

def run(records, rosters: dict, results: dict, *, logfn=print,
        post: bool = True, dry_run: bool = False) -> list[dict]:
    """Print the table, collect findings, and speak up in Slack if there are any.

    `rosters`  {captain_key: [owner name, ...]}
    `results`  {captain_key: {"labels": [...], "error_keys": [...],
                              "errors": {key: note}}}

    Returns the findings. Best-effort throughout: this runs AFTER every board is
    drawn, so nothing it does may cost the capture its exit code."""
    records = list(records or [])
    for line in summary_lines(records):
        logfn(line)

    findings = short_read_findings(records)
    for key, roster in (rosters or {}).items():
        res = (results or {}).get(key) or {}
        findings += coverage_findings(roster, res.get("labels") or [],
                                      res.get("error_keys") or [], captain=key)
        findings += failure_findings(res.get("errors") or {}, captain=key)

    logfn(verdict(findings))
    if not findings or not post:
        # A clean morning closes yesterday's thread with a ✅ rather than
        # posting "all good" into a corrections channel every day.
        #
        # ONLY when this run actually pulled something. A same-day re-run
        # short-circuits on the capture manifest and hands back the morning's
        # PNGs without opening ownerville, so it has NO records and finds
        # nothing — and "found nothing" there means "looked at nothing". Left
        # unguarded, a rebuild for an unrelated reason would tick an open
        # short-board incident closed without a single grid being re-read.
        if not findings and post and records:
            _resolve(logfn=logfn, dry_run=dry_run)
        return findings

    try:
        from automations.day_orchestrator import notify
        notify.post_alert(TITLE, alert_body(findings), tag="knocks_audit",
                          incident=INCIDENT_KEY, label="Captainship knocks",
                          dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — an alert must never sink the run
        logfn(f"  ⚠ knocks audit alert not posted: {type(e).__name__}: {e}")
    return findings


def _resolve(*, logfn=print, dry_run: bool = False) -> None:
    """Close yesterday's thread when today is clean. `resolve_if_open` is free
    when nothing is open (a local index read, no Slack call), so this is safe on
    every clean morning — which is most of them."""
    try:
        from automations.shared import incident_thread
        incident_thread.resolve_if_open(
            INCIDENT_KEY,
            what="*captainship knock boards* match the Time Tracker again",
            dry_run=dry_run)
    except Exception:  # noqa: BLE001 — nothing open to close is the normal case
        pass


# ---------------------------------------------------------------------------

def _self_test() -> int:
    recs = [
        {"office": "Christian Esposito", "date": "2026-09-07", "first_rows": 2,
         "tt_reps": 22, "rows": 2, "reread": True},
        {"office": "Chan Park", "date": "2026-09-08", "first_rows": 41,
         "tt_reps": 41, "rows": 41, "reread": False},
        {"office": "Quiet Office", "date": "2026-09-08", "first_rows": 0,
         "tt_reps": 0, "rows": 0, "reread": False},
        {"office": "Empty Grid", "date": "2026-09-08", "first_rows": 0,
         "tt_reps": 9, "rows": 0, "reread": False},
        {"office": "One Walk-On", "date": "2026-09-08", "first_rows": 11,
         "tt_reps": 12, "rows": 11, "reread": True},
    ]
    f = short_read_findings(recs)
    kinds = {x["office"]: x["kind"] for x in f}
    assert kinds.get("Christian Esposito") == "short", kinds
    assert "Chan Park" not in kinds, "a clean office must not be reported"
    assert "Quiet Office" not in kinds, "a real zero day is not a finding"
    assert kinds.get("Empty Grid") == "empty-grid", kinds
    # One rep short is under REPORT_MIN_GAP, but it needed a re-read, so it is
    # reported as the weaker 'reread' finding rather than dropped.
    assert kinds.get("One Walk-On") == "reread", kinds

    cov = coverage_findings(["Ada Lovelace", "Alan Turing", "Grace Hopper"],
                            ["Ada Lovelace — ⚠ INCOMPLETE: apps unavailable"],
                            ["daily_knocks:Alan Turing"], captain="rafael")
    assert [x["office"] for x in cov] == ["Grace Hopper"], cov

    fail = failure_findings({
        "daily_knocks:Alan Turing": NO_DATA_MARK + "no ownerville office access",
        "daily_knocks:Ada Lovelace": NO_DATA_MARK + "no knocks recorded yesterday",
        "daily_knocks:Grace Hopper": "RuntimeError: Couldn't reach the "
                                     "ownerville Office Access page (?p=901)",
    }, captain="rafael")
    assert [x["office"] for x in fail] == ["Grace Hopper"], fail

    assert "CLEAN" in verdict([])
    assert "5 finding" not in verdict(f)
    assert summary_lines([])[0].startswith("knocks audit:")
    assert any("EMPTY GRID" in l for l in summary_lines(recs))
    print("knocks_audit self-test: ok")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_self_test() if "--self-test" in sys.argv else _self_test())
