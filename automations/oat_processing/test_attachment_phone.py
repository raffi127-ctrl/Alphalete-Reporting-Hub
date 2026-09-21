"""The applicant's number is read off the AppStream attachment, not just Indeed.

2026-09-18. Megan, on an applicant the walk had flagged as needing a number:
"the number is right there." Her screenshot showed the resume in AppStream's own
Attachment / PDF Quick View viewer with a cell number on it, while
lookup_resume_phone was trying Indeed — the path bot-blocked since August. The
probe confirmed the panel (frame p=618) carries a plain 'Download Attachment'
anchor to https://www.applicantStream.com/attachDay/... on the same origin.

Pinned here:
  * the anchor is FOUND, in a frame, by its link text;
  * AppStream's own 'User Guide' (usersguide.pdf) on the same page is NEVER
    mistaken for an applicant's resume;
  * the file is FETCHED, never clicked and never navigated to — clicking is safe
    on a throwaway Indeed tab, but this is the live panel the walk is standing on;
  * a fetch that fails reports a reason, never "no number" (Carlos's rule: an
    applicant we could not read is left alone).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from automations.oat_processing import resume_download as rd  # noqa: E402

# The reader now WAITS for the link (2026-09-21). Tests that expect "no link"
# must not sit through the real wait; the one test about waiting sets its own.
rd.ATTACH_WAIT_S = 0

_failed = 0


def check(label, got, want):
    global _failed
    if got == want:
        print("  [ok] %s: %r" % (label, got))
    else:
        _failed += 1
        print("  [FAIL] %s: got %r, want %r" % (label, got, want))


PANEL_LINKS = [
    {"text": "User Guide", "href": "https://www.applicantstream.com/usersguide.pdf"},
    {"text": "Download Attachment",
     "href": "https://www.applicantStream.com/attachDay/2026/09/11/187988588.pdf"},
]


class _Frame:
    """Stands in for a Playwright frame: evaluate() answers the anchor query."""

    def __init__(self, links):
        self.links = links

    def evaluate(self, js):
        import re
        want = re.compile(r"download\s*(attachment|original|message|resume|file)", re.I)
        return [l["href"] for l in self.links
                if want.search(l["text"]) and "usersguide" not in l["href"].lower()]


class _Resp:
    def __init__(self, body, ok=True, status=200):
        self._b, self.ok, self.status = body, ok, status

    def body(self):
        return self._b


class _Req:
    def __init__(self, resp, log):
        self._resp, self._log = resp, log

    def get(self, url, timeout=None):
        self._log.append(url)
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


class _Ctx:
    def __init__(self, resp, log):
        self.request = _Req(resp, log)


class _Page:
    """A page whose TOP document has no links — the panel is in a frame, which is
    the arrangement the probe actually found."""

    def __init__(self, resp, log, links=PANEL_LINKS):
        self.frames = [_Frame([]), _Frame(links)]
        self.context = _Ctx(resp, log)
        self.navigated = []

    def evaluate(self, js):
        return []

    def goto(self, url, **k):            # must never be called
        self.navigated.append(url)
        raise AssertionError("the walk navigated the live applicant panel")


print("the attachment anchor is found in a frame, the user guide is not:")
fetched = []
pg = _Page(_Resp(b"%PDF-1.4 fake"), fetched)
check("href is the applicant's attachment", rd.attachment_href(pg),
      "https://www.applicantStream.com/attachDay/2026/09/11/187988588.pdf")
check("a panel with only the user guide offers nothing",
      rd.attachment_href(_Page(_Resp(b""), [], links=PANEL_LINKS[:1])), "")

print("the file is FETCHED with the session, never clicked or navigated to:")
rd.phone_from_file = lambda path: "972-482-9544"      # parsing is tested elsewhere
phone, detail = rd.phone_from_attachment(pg)
check("number comes back", phone, "972-482-9544")
check("says where it came from", "AppStream attachment" in detail, True)
check("fetched exactly one url", len(fetched), 1)
check("never navigated the panel", pg.navigated, [])

print("a failure is a reason, never a verdict about the applicant:")
phone, detail = rd.phone_from_attachment(_Page(_Resp(b"", ok=False, status=403), []))
check("http failure reports the status", phone, None)
check("and says so", "403" in detail, True)
phone, detail = rd.phone_from_attachment(_Page(RuntimeError("boom"), []))
check("an exception is caught", phone, None)
check("and named", "fetch failed" in detail, True)
phone, detail = rd.phone_from_attachment(_Page(_Resp(b""), [], links=PANEL_LINKS[:1]))
check("no attachment at all is its own reason",
      detail.startswith("no attachment on the panel"), True)
check("and says how long it waited", "waited" in detail, True)

print("A LINK THAT LOADS LATE IS STILL FOUND (the 0-for-94 bug):")
# 2026-09-21: live, every one of 94 applicants read "no attachment on the panel"
# while the 9/18 probe had found it on 3 of 3 — the panel settles before its
# attachment frame loads, and a single look happened too early. Here the link
# only exists from the THIRD look on.
class _LatePage(_Page):
    def __init__(self, resp, log, show_after):
        super().__init__(resp, log)
        self._looks = 0
        self._show_after = show_after
        self._late = _Frame(PANEL_LINKS)
        self.frames = [_Frame([])]          # the attachment frame is not there yet

    def evaluate(self, js):
        self._looks += 1
        if self._looks >= self._show_after and self._late not in self.frames:
            self.frames.append(self._late)  # ...and now it has loaded
        return []

    def wait_for_timeout(self, ms):
        pass                                 # no real waiting in a test

late = _LatePage(_Resp(b"%PDF-1.4 fake"), [], show_after=3)
check("found once it appears",
      rd.attachment_href(late, wait_s=5.0),
      "https://www.applicantStream.com/attachDay/2026/09/11/187988588.pdf")
check("a single instant look would have missed it",
      rd.attachment_href(_LatePage(_Resp(b""), [], show_after=3), wait_s=0), "")

print("a resume that really has no number says exactly that:")
rd.phone_from_file = lambda path: None
phone, detail = rd.phone_from_attachment(_Page(_Resp(b"%PDF-1.4 fake"), []))
check("no phone", phone, None)
check("but the file WAS read", "no number in it" in detail, True)

print("FAILED" if _failed else "ALL PASSED")
raise SystemExit(1 if _failed else 0)
