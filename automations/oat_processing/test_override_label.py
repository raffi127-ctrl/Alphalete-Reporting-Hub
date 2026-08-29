"""Both AppStream override wordings must be recognised and clicked.

Regression test for the 2026-08-27 finding: the module matched only
"Overwrite Old Applicants (Send to AI)", so a record rendering
"Override and Send to AI" read as un-sendable and was re-texted or removed.
"""
import re
import automations.oat_processing.run as oat


class _FakePage:
    """Minimal page: a body string + a set of button labels."""
    def __init__(self, labels, body):
        self.labels, self._body, self.clicked = labels, body, None

    def inner_text(self, _sel):
        return self._body

    def evaluate(self, js, *a):
        # the override click helper: return the first matching label
        el = next((l for l in self.labels
                   if re.search(r"overri|overwri", l, re.I)
                   and re.search(r"\bai\b", l, re.I)), None)
        el = el or next((l for l in self.labels
                         if re.search(r"overri|overwri", l, re.I)), None)
        self.clicked = el
        return el

    def wait_for_timeout(self, _ms):
        self._body = self._body.replace("cannot send to ai", "sent")


def _run(label):
    p = _FakePage([label, "Save Applicant"],
                  f"cannot send to ai as correspondence ... {label}".lower())
    ok = oat._try_overwrite_send(p)
    return ok, p.clicked


def test_overwrite_wording():
    ok, clicked = _run("Overwrite Old Applicants (Send to AI)")
    assert ok and clicked == "Overwrite Old Applicants (Send to AI)", clicked


def test_override_wording():
    """The wording that was silently missed — the whole point of the fix."""
    ok, clicked = _run("Override and Send to AI")
    assert ok and clicked == "Override and Send to AI", clicked


def test_no_control_means_no_send():
    p = _FakePage(["Save Applicant"], "cannot send to ai as correspondence ...")
    assert oat._try_overwrite_send(p) is False


def test_cannot_override_message_blocks():
    p = _FakePage(["Override and Send to AI"],
                  "cannot override this applicant. override and send to ai")
    assert oat._try_overwrite_send(p) is False




# --- removal reason -------------------------------------------------------- #
class _RemovePage:
    """Page with a Remove Applicant? checkbox, a reason <select>, and a button."""
    def __init__(self, options):
        self.options, self.picked = options, None

    class _Loc:
        def __init__(self, n=1): self._n = n
        def count(self): return self._n
        @property
        def first(self): return self
        def check(self, timeout=0): pass
        def click(self, **kw): pass

    def locator(self, _sel): return self._Loc()
    def wait_for_timeout(self, _ms): pass
    def expect_navigation(self, timeout=0):
        class _C:
            def __enter__(s): return s
            def __exit__(s, *a): return False
        return _C()

    def evaluate(self, js, *args):
        import re as _re
        pat = args[0] if args else r"duplicate"
        o = next((o for o in self.options if _re.search(pat, o, _re.I)), None)
        self.picked = o
        return o or ""


def test_default_reason_is_duplicate():
    p = _RemovePage(["Commute Too Far", "Duplicate Applicant",
                     "Incorrect / Insufficient Contact Info"])
    assert oat._perform_remove(p) is True
    assert p.picked == "Duplicate Applicant", p.picked


def test_no_contact_reason_is_not_duplicate():
    """A no-phone applicant must NOT be filed as a duplicate."""
    p = _RemovePage(["Commute Too Far", "Duplicate Applicant",
                     "Incorrect / Insufficient Contact Info"])
    assert oat._perform_remove(p, oat.NO_CONTACT_REASON) is True
    assert p.picked == "Incorrect / Insufficient Contact Info", p.picked


def test_missing_reason_fails_safe():
    p = _RemovePage(["Commute Too Far"])
    assert oat._perform_remove(p, oat.NO_CONTACT_REASON) is False

if __name__ == "__main__":
    for fn in (test_overwrite_wording, test_override_wording,
               test_no_control_means_no_send, test_cannot_override_message_blocks,
               test_default_reason_is_duplicate, test_no_contact_reason_is_not_duplicate,
               test_missing_reason_fails_safe):
        fn(); print(f"  ok  {fn.__name__}")
    print("7/7 passed")


def test_cannot_override_message_does_not_stop_the_click():
    """Paula Ruiz, 2026-08-28. The page carried "Cannot override this applicant."
    AND a bare "Overwrite old Applicants" button. Those are different controls:
    the button clears the duplicate records so the applicant can be saved, and
    the send is the next click. Bailing on the sentence strands someone who was
    one click from the call list."""
    p = _FakePage(["Overwrite old Applicants", "Send to AI"],
                  "cannot send to ai ... cannot override this applicant. "
                  "overwrite old applicants")
    assert oat._try_overwrite_send(p) is True
    assert p.clicked == "Overwrite old Applicants", p.clicked


def test_bare_overwrite_label_without_ai_suffix_is_matched():
    # body must carry the button text, as the real page does — _try_overwrite_send
    # checks the page for an override affordance before looking for the control.
    p = _FakePage(["Overwrite old Applicants"],
                  "cannot send to ai as correspondence ... overwrite old applicants")
    ok, clicked = oat._try_overwrite_send(p), p.clicked
    assert ok and clicked == "Overwrite old Applicants", clicked
