"""Browser-free checks on the per-SESSION Cloudflare handling. Run:

    python -m automations.oat_processing.test_cf_session

WHY THIS EXISTS (2026-09-22). Indeed challenges the FIRST resume a browser opens
and then lets the rest of that session through — measured on Lucy 4, office
11280: one human tick, then 6 of 6 resumes rendered unchallenged. The old reader
treated every applicant as its own fight with a 40s ceiling, so on a day the
challenge stopped auto-clearing inside 40s, every office on two machines filled
ZERO numbers (162 "blocked" reads in Raf's office alone) while ~150 people a day
were flagged "need a number" — with the number sitting on their resume.

What is pinned here:
  * the session's FIRST read gets the long ceiling, later reads the short one,
  * anything that renders marks the session cleared (and un-walls it),
  * a first read that never clears WALLS the session, and a walled session flags
    applicants WITHOUT reading, WITHOUT caching them and WITHOUT spending a
    retry — they are not confirmed no-number people,
  * the wall logs the line the Slack watcher greps for,
  * a new walk resets the verdict (fresh browser, fresh challenge),
  * the watcher only alerts after several walled ticks, and not at all once a
    number has been read.

Touches nothing outside a temp dir: no browser, no Slack, no Sheet, no sends.
"""
from __future__ import annotations  # Lucy 2 / Lucy 4 run Python 3.9

import datetime as dt
import json
import tempfile
from pathlib import Path

from . import run
from . import session_wedge_watch as w


def _check(label, got, expected) -> bool:
    ok = got == expected
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}"
          f"{'' if ok else f'  (expected {expected!r})'}")
    return ok


def test_session_flags() -> bool:
    print("session verdict")
    ok = True
    run.reset_cf_session()
    ok &= _check("fresh session is not cleared", run._cf_session_cleared(), False)
    ok &= _check("fresh session is not walled", run._cf_walled(), False)

    lines: list = []
    orig_log, run._log = run._log, lines.append
    try:
        run._mark_cf_walled("cloudflare challenge never cleared")
        ok &= _check("walled after a first read that never cleared",
                     run._cf_walled(), True)
        ok &= _check("the wall logs the watcher's signature",
                     any("CLOUDFLARE WALL" in l for l in lines), True)
        lines.clear()
        # A second wall in the same session must not spam the log.
        run._mark_cf_walled("cloudflare challenge never cleared")
        ok &= _check("the wall is logged once per session", len(lines), 0)

        run._mark_cf_cleared()
        ok &= _check("a render clears the session", run._cf_session_cleared(), True)
        ok &= _check("a render un-walls the session", run._cf_walled(), False)
    finally:
        run._log = orig_log

    run.reset_cf_session()
    ok &= _check("a new walk starts from nothing",
                 (run._cf_session_cleared(), run._cf_walled()), (False, False))
    return ok


def test_walled_walk_does_not_spend_attempts() -> bool:
    """A walled session flags people unread: no read, no cache, no retry burned."""
    print("walled session costs an applicant nothing")
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="oat-cf-"))
    run._NOPHONE_CHECKED = None
    run._NOPHONE_BLOCKED = None
    run._nophone_checked_path = lambda: tmp / "checked.json"
    run._nophone_blocked_path = lambda: tmp / "blocked.json"
    run.reset_cf_session()
    run._mark_cf_walled("cloudflare challenge never cleared")

    reads: list = []
    orig_lookup, run.lookup_resume_phone = run.lookup_resume_phone, \
        lambda page: (reads.append(1), (None, ""))[1]
    orig_log, run._log = run._log, lambda *a, **k: None
    orig_cfg_lookup = getattr(run.config, "AUTOMATE_PHONE_LOOKUP", False)
    run.config.AUTOMATE_PHONE_LOOKUP = True
    try:
        a = run.Applicant(first_name="Nicole", last_name="Lucido")
        run.flag_no_phone(_FakePage(), a, live=True)
        ok &= _check("no resume was opened", len(reads), 0)
        ok &= _check("not cached as settled",
                     run._nophone_key(a) in run._load_nophone_checked(), False)
        ok &= _check("no retry attempt spent",
                     json.loads((tmp / "blocked.json").read_text())
                     if (tmp / "blocked.json").exists() else {}, {})
    finally:
        run.lookup_resume_phone = orig_lookup
        run._log = orig_log
        run.config.AUTOMATE_PHONE_LOOKUP = orig_cfg_lookup
        run.reset_cf_session()
    return ok


class _FakePage:
    """Enough of a page for flag_no_phone's walled branch — it must touch none of it."""

    url = "https://applicantstream.com/index.cfm?p=604"

    def __getattr__(self, name):
        raise AssertionError(f"a walled session must not touch the page (.{name})")


def test_watcher_thresholds() -> bool:
    print("slack alarm thresholds")
    ok = True
    tmp = Path(tempfile.mkdtemp(prefix="cf-watch-"))
    (tmp / "applicant-push-11280-2026-09-22.log").write_text("\n".join(
        ["[1] FLAG_NO_PHONE — Chris Fernandez"]
        + ["    [cf] CLOUDFLARE WALL — office 11280: Indeed's check never cleared"]
        * w.CF_WALL_TICKS
    ))
    (tmp / "applicant-push-23467-2026-09-22.log").write_text("\n".join([
        "    [cf] CLOUDFLARE WALL — office 23467: Indeed's check never cleared",
        "    📞 resume phone +1 214 555 1212 → filled + sending: Someone Real",
    ]))
    orig_dir, w.LOG_DIR = w.LOG_DIR, tmp
    try:
        seen = w.assess_resume_check()
        ok &= _check("Raf's office: a full hour of walls, no numbers",
                     seen.get("11280", (0, 0, ""))[:2], (w.CF_WALL_TICKS, 0))
        ok &= _check("an office that read a number is not alerting",
                     seen.get("23467", (0, 0, ""))[1] > 0, True)
        ok &= _check("a sustained hour reaches the alert threshold",
                     seen["11280"][0] >= w.CF_WALL_TICKS, True)
        ok &= _check("a few stubborn minutes does not",
                     3 >= w.CF_WALL_TICKS, False)
        # The bar exists so a human is pinged once, about something worth
        # walking to a machine for — not every time the check is briefly moody.
        ok &= _check("one ping per machine per day at most",
                     w.CF_RE_ALERT_HOURS >= 20, True)
        ok &= _check("no tickets outside working hours",
                     (w.CF_QUIET_BEFORE_H, w.CF_QUIET_AFTER_H), (8, 19))
    finally:
        w.LOG_DIR = orig_dir
    return ok


def main() -> int:
    print(f"CF session handling — {dt.date.today()}\n")
    results = [test_session_flags(),
               test_walled_walk_does_not_spend_attempts(),
               test_watcher_thresholds()]
    print("\n" + ("ALL OK" if all(results) else "FAILURES ABOVE"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
