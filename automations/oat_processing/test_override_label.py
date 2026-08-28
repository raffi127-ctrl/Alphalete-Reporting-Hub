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


if __name__ == "__main__":
    for fn in (test_overwrite_wording, test_override_wording,
               test_no_control_means_no_send, test_cannot_override_message_blocks):
        fn(); print(f"  ok  {fn.__name__}")
    print("4/4 passed")
