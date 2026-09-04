"""A resume verdict of "no number" needs proof the RESUME rendered, not the viewer.

THE BUG THIS PINS — Shanice Rankine, office 23467, 2026-09-03. Her number is in
the resume header ("Lakewood, CO 80215 | +1 754 302 3395 | shanice…@indeedemail
.com"), the very layout the reader pulled successfully from Tamara Derryberry and
Manuel Montana the same day. Her first read still came back empty, and
_blocked_reason cleared it as a genuine empty resume: no Cloudflare phrase, no
sign-in phrase, and a body over the 200-char floor — because the VIEWER CHROME
alone is over it. "Confirmed empty" caches for the day, so she was skipped 75
times without the resume being reopened once, and Megan sent her by hand at
6:24 PM.

The 8/27 fix taught the reader to look inside frames. This is the other half:
noticing when there is nothing in the frames to look at. Blocked is retryable;
confirmed-empty is not, so anything we are unsure about must land on blocked.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_rendered_resume
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

from automations.oat_processing.run import (_BLOCKED_PREFIX, _blocked_reason,
                                             _is_blocked_detail)

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


def blocked(title, body):
    """True when the read is retryable rather than a confirmed empty resume."""
    return bool(_blocked_reason(title, body))


# The Indeed viewer shell with nothing rendered inside it — Shanice's case. Well
# over the 200-char floor and free of every existing block phrase.
CHROME_ONLY = (
    "Shanice Rankine's Resume\nView candidate\nBack to candidates\n"
    "Download original message\nReport this resume\nHelp Centre\n"
    "Privacy Centre\nAccessibility at Indeed\nCookies\nPrivacy\nTerms\n"
    "Indeed Home\nEmployers / Post Job\nSign in\nMessages\nHiring dashboard\n"
    "© 2026 Indeed\nDo not sell my personal information\nSitemap\n"
)

# Her resume as it actually renders.
REAL_RESUME = (
    "Shanice Rankine's Resume\nView candidate\n"
    "Shanice Rankine\nLakewood, CO 80215 | +1 754 302 3395 | "
    "shanicerankinep7xx7_yqj@indeedemail.com\n"
    "Authorized to work in the US for any employer\n"
    "Work experience\nCashier/Customer Service\nPublix | Lauderhill, FL\n"
    "November 2025 to Present\nHome Care Aide\nAngels on the ocean | Florida\n"
    "Skills\nHome care\n"
)

print("the chrome-only page must NOT be called a confirmed-empty resume:")
check("Shanice's failed read is blocked (retryable)",
      blocked("shanice rankine's resume", CHROME_ONLY), True)
check("and it says why",
      "never rendered" in _blocked_reason("shanice rankine's resume", CHROME_ONLY),
      True)
check("the OLD 200-char floor let it through (this is the regression)",
      len(CHROME_ONLY.strip()) >= 200, True)

print("a resume that really rendered still reads as rendered:")
check("Shanice's real resume is NOT blocked",
      blocked("shanice rankine's resume", REAL_RESUME), False)

print("each rendered-resume marker is enough on its own:")
_pad = "x " * 150          # clears the length floor without adding any marker
for marker in ("Work experience", "Education", "Skills", "Authorized to work",
               "someone@example.com"):
    check("%r proves it rendered" % marker, blocked("r", _pad + marker), False)

print("a genuinely empty resume is still settled, not retried forever:")
# Rendered, has the section headings and a contact email, just no phone number.
check("rendered with no number -> confirmed empty",
      blocked("r", "Work experience\nCashier\nnobody@example.com\n" + _pad), False)

print("the older block signals are untouched:")
check("cloudflare", blocked("just a moment...", _pad), True)
check("indeed 'Blocked' title", blocked("blocked - indeed.com", _pad), True)
check("sign-in wall", blocked("r", "employer sign in" + _pad), True)
check("empty body", blocked("r", ""), True)

print("blocked details are recognised as retryable by the caller:")
check("prefix round-trips",
      _is_blocked_detail(_BLOCKED_PREFIX + "viewer chrome only"), True)
check("a plain verdict does not", _is_blocked_detail("no phone on resume"), False)

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
