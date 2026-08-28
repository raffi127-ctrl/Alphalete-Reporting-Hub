#!/usr/bin/env python3
"""A blocked resume read must NEVER read as 'this resume has no number'.

The distinction decides whether an applicant keeps their record: a confirmed-empty
resume caches the applicant for the day and, in an office with REMOVE_NO_PHONE on,
REMOVES them for "Incorrect / Insufficient Contact Info". A blocked read is OUR
failure and must stay retryable.

Regression: 2026-08-27/28 — a headless walker gets a page titled
"Blocked - Indeed.com" with a normal-length body. No Cloudflare phrase, no
sign-in phrase, body over the 200-char floor, so it was filed as empty.
"""
from __future__ import annotations

from automations.oat_processing.run import _blocked_reason, _is_blocked_detail, _BLOCKED_PREFIX

_fails = []
BODY = "x" * 400          # long enough to clear the empty-body floor


def check(name, cond, detail=""):
    print(("  ok  " if cond else "  FAIL ") + name + ("" if cond else f" :: {detail}"))
    if not cond:
        _fails.append(name)


def test_indeed_block_titles_are_blocked():
    for title in ("Blocked - Indeed.com", "blocked", "403 Forbidden",
                  "Too Many Requests", "429 Too Many Requests"):
        r = _blocked_reason(title, BODY)
        check(f"title {title!r} -> blocked", bool(r), f"got {r!r}")


def test_cloudflare_and_signin_still_blocked():
    check("cloudflare challenge", bool(_blocked_reason("Just a moment...", BODY)))
    check("sign-in wall", bool(_blocked_reason("Indeed", "please sign in to your account " + BODY)))
    check("empty body", bool(_blocked_reason("Resume", "   ")))


def test_a_real_empty_resume_stays_empty():
    """The whole point of the distinction — a resume that genuinely rendered and
    carries no number must NOT become a permanent retry."""
    r = _blocked_reason("Maria Ramirez's Resume", "EXPERIENCE " + BODY)
    check("real resume with no number -> NOT blocked", r == "", f"got {r!r}")


def test_body_word_blocked_does_not_trip_it():
    """A candidate who 'blocked out schedules' must not read as an Indeed block —
    that would retry their resume forever instead of settling it."""
    body = "Availability: I have blocked out weekends. " + BODY
    r = _blocked_reason("Jane Doe's Resume", body)
    check("'blocked' in the BODY is not a block", r == "", f"got {r!r}")


def test_blocked_detail_round_trips():
    """_blocked_reason's output has to survive being wrapped in the caller's
    prefix and still be recognised as retryable by _is_blocked_detail."""
    reason = _blocked_reason("Blocked - Indeed.com", BODY)
    check("wrapped blocked detail is recognised",
          _is_blocked_detail(f"{_BLOCKED_PREFIX}{reason}"), reason)
    check("a plain empty-resume detail is NOT",
          not _is_blocked_detail("no phone on resume (title='X')"))


if __name__ == "__main__":
    for fn in (test_indeed_block_titles_are_blocked,
               test_cloudflare_and_signin_still_blocked,
               test_a_real_empty_resume_stays_empty,
               test_body_word_blocked_does_not_trip_it,
               test_blocked_detail_round_trips):
        print(fn.__name__)
        fn()
    print("ALL PASSED" if not _fails else f"FAILURES: {_fails}")
    raise SystemExit(1 if _fails else 0)
