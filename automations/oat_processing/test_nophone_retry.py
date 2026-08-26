"""Browser-free checks on the blocked-vs-empty resume-read split. Run:

    python -m automations.oat_processing.test_nophone_retry

WHY THIS EXISTS (2026-08-25): a resume read that never rendered — Cloudflare's
"Just a moment…" or the Indeed sign-in wall — was filed as "no number on resume"
and cached as settled for the whole day. 90 of that day's 161 flagged reads were
blocked reads, so 90 applicants were written off without their resume ever being
opened; the queue sat at 35 and only 9 were sent.

The split: a resume we ACTUALLY READ that has no number stays settled (Megan's
8/6 rule — don't reopen dead ends every 5 minutes). A read we never got to see is
retried, on a cool-off, a bounded number of times, then handed to the manual list.

Touches nothing outside a temp dir: no browser, no Sheet, no sends.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9

import datetime as dt
import tempfile
from pathlib import Path

from . import run


def _reset() -> None:
    """Point both caches at a FRESH scratch dir and clear the in-process copies, so
    each block below starts from nothing (no leftovers from the previous block)."""
    tmp = Path(tempfile.mkdtemp(prefix="oat-nophone-"))
    run._NOPHONE_CHECKED = None
    run._NOPHONE_BLOCKED = None
    run._nophone_checked_path = lambda: tmp / "checked.json"
    run._nophone_blocked_path = lambda: tmp / "blocked.json"


def _check(label, got, expected) -> bool:
    ok = got == expected
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}"
          f"{'' if ok else f'  (expected {expected!r})'}")
    return ok


def main() -> int:
    results = []

    # --- 1. classifying the page the poll gave up on -------------------------
    print("blocked-page detection:")
    real_resume = ("Alex Rivera\nDallas, TX 75201\nSales Associate\n"
                   "Experience\n" + ("worked the door for two years. " * 20))
    results.append(_check("cloudflare interstitial",
                          run._blocked_reason("just a moment...", "verify you are human"),
                          "cloudflare challenge never cleared"))
    results.append(_check("indeed sign-in wall",
                          run._blocked_reason("indeed for employers",
                                              "Employer sign in\n" + "x" * 400),
                          "indeed sign-in wall"))
    results.append(_check("blank page",
                          run._blocked_reason("indeed for employers", "   "),
                          "resume page never rendered (empty body)"))
    results.append(_check("resume that really has no number",
                          run._blocked_reason("alex rivera - resume", real_resume),
                          ""))

    # --- 2. the detail string carries the verdict ----------------------------
    print("detail-string tagging:")
    results.append(_check("blocked detail",
                          run._is_blocked_detail(run._BLOCKED_PREFIX + "whatever"),
                          True))
    results.append(_check("empty-resume detail",
                          run._is_blocked_detail("no phone on resume (title='x')"),
                          False))

    # --- 3. retry budget + cool-off ------------------------------------------
    print("retry budget:")
    _reset()
    key = "alex rivera"
    results.append(_check("first sighting is due", run._blocked_due(key), True))

    n1 = run._mark_nophone_blocked(key, "cloudflare challenge never cleared")
    results.append(_check("attempt 1 recorded", n1, 1))
    results.append(_check("cooling off, not retried yet", run._blocked_due(key), False))
    results.append(_check("not settled while retries remain",
                          key in run._load_nophone_checked(), False))
    results.append(_check("counted as pending", run._blocked_pending_count(), 1))

    # Age the stamp past the cool-off — the next walk should try again.
    state = run._load_nophone_blocked()
    state[key]["last"] = (dt.datetime.now() - dt.timedelta(
        minutes=run._BLOCKED_RETRY_AFTER_MIN + 1)).isoformat(timespec="seconds")
    results.append(_check("due again after the cool-off", run._blocked_due(key), True))

    # Burn the remaining attempts.
    for _ in range(run._BLOCKED_MAX_ATTEMPTS - 1):
        run._mark_nophone_blocked(key, "cloudflare challenge never cleared")
        state[key]["last"] = (dt.datetime.now() - dt.timedelta(
            minutes=run._BLOCKED_RETRY_AFTER_MIN + 1)).isoformat(timespec="seconds")
    results.append(_check("budget spent → settled for the day",
                          key in run._load_nophone_checked(), True))
    results.append(_check("budget spent → no longer due", run._blocked_due(key), False))
    results.append(_check("budget spent → no longer pending",
                          run._blocked_pending_count(), 0))

    # --- 4. an empty resume is still settled on the FIRST read ---------------
    print("empty resume stays settled on the first read:")
    _reset()
    run._mark_nophone_checked("dana empty")
    results.append(_check("settled immediately",
                          "dana empty" in run._load_nophone_checked(), True))
    results.append(_check("no retry slot used", run._blocked_pending_count(), 0))

    # --- 5. state survives the next walk (fresh process reads the file) ------
    print("state persists across walks:")
    _reset()
    run._mark_nophone_blocked("pat persist", "indeed sign-in wall")
    run._NOPHONE_BLOCKED = None          # simulate the next walk starting cold
    results.append(_check("reloaded from disk",
                          run._load_nophone_blocked().get("pat persist", {}).get("n"), 1))

    passed = sum(results)
    print(f"{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
