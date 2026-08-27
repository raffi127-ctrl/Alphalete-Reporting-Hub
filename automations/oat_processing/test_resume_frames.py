"""Browser-free checks on reading a phone off an Indeed resume page.

THE BUG THIS PINS (2026-08-27): Indeed's resume viewer puts the resume in a
NESTED FRAME. The reader only ever looked at the top document, which holds just
the viewer chrome — real text, comfortably over the blocked-read length floor —
so the page looked like it loaded fine and simply had no number on it. Every such
applicant was settled as "no phone on resume" for the day while a human opening
the same link saw the number in the header at once (Carlos Nevarez, office 23467:
"(303) 710-6301"). 24 of Atef's and 19 of Carlos's sat that way in one morning.

Run:  PYTHONPATH=. .venv/bin/python -m automations.oat_processing.test_resume_frames
"""
from __future__ import annotations  # Lucy 2 runs Python 3.9

import re

from automations.oat_processing.run import _PHONE_RE, _blocked_reason

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


# The real page, as the two screenshots showed it.
CHROME = ("Carlos Nevarez's Resume\nView candidate\nBack to candidates\n"
          "Indeed for Employers\nMessages  Jobs  Candidates  Analytics\n"
          "© 2026 Indeed Inc. 200 West 6th Street Floor 36 Austin TX 78701\n"
          "Cookie Policy  Privacy Policy  Terms of Service\n")
RESUME_FRAME = ("Carlos Nevarez\n"
                "\U0001F4F1 (303) 710-6301 | cnevarez2004@protonmail.com | LinkedIn\n"
                "Detail-oriented IT professional with a 36-credit Computer "
                "Networking certificate from Emily Griffith Technical College.\n"
                "Key Skills, Certifications, & Technologies\n")


def find_phone(texts):
    """The reader's search, in the order the fixed code uses it."""
    for t in texts:
        for m in _PHONE_RE.finditer(t):
            digits = re.sub(r"\D", "", m.group(0))
            if 10 <= len(digits) <= 11:
                return m.group(0).strip()
    return None


print("the reported case — number in a frame, chrome in the top document:")
# This is the whole bug: top-document-only finds nothing, all-frames finds him.
check("top document alone (the OLD read) misses it", find_phone([CHROME]), None)
check("with frames (the FIX) finds his real number",
      find_phone([CHROME, RESUME_FRAME]), "(303) 710-6301")

print("the chrome is why it was called 'no phone' and not 'blocked':")
# Over the length floor and carrying no challenge markers, so nothing upstream
# could tell this apart from a resume that genuinely has no number on it.
check("chrome clears the blocked-read length floor", len(CHROME) > 200, True)
check("chrome is not flagged as blocked", _blocked_reason("carlos nevarez's resume",
                                                          CHROME), "")

print("a genuinely empty read is still blocked, not settled:")
check("short body still reads as blocked",
      bool(_blocked_reason("just a moment...", "")), True)

print("top document still WINS when it has the number (no behaviour change):")
# Résumés list former employers' phone numbers in the work history, so the search
# must stay nearest-the-top-first or we would text an old boss instead.
check("main-document number is preferred",
      find_phone(["Call me at (214) 555-0100", RESUME_FRAME]), "(214) 555-0100")

print("frames that cannot be read are skipped, not fatal:")


class _BadFrame:
    def evaluate(self, _js):
        raise RuntimeError("cross-origin frame")


def collect(frames):
    out = []
    for fr in frames:
        try:
            t = fr.evaluate("() => (document.body.innerText || '')")
        except Exception:
            continue
        if t and t not in out:
            out.append(t)
    return out


class _Frame:
    def __init__(self, t):
        self.t = t

    def evaluate(self, _js):
        return self.t


check("a throwing frame doesn't lose the good one",
      collect([_BadFrame(), _Frame(RESUME_FRAME)]), [RESUME_FRAME])
check("duplicate frame text is not doubled",
      collect([_Frame(RESUME_FRAME), _Frame(RESUME_FRAME)]), [RESUME_FRAME])

print("%d/%d passed" % (_passed, _passed + _failed))
raise SystemExit(1 if _failed else 0)
