"""The rules that make email delivery safe to leave running unattended.

These pin the decisions that are cheap to make once and expensive to rediscover:
an office has exactly ONE destination, a capture diverts rather than posts, a day
with nothing in it is never mailed, and the scratch-channel override cannot turn
an email office into a Slack one.

    python -m unittest automations.shared.test_email_delivery
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from automations.office_metrics.offices import Office
from automations.office_onboarding import schema as S


def _png(path: Path, w: int = 600, h: int = 200) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), (250, 250, 250)).save(path)
    return path


class OneDestinationPerOffice(unittest.TestCase):
    """An office reads its day in ONE place. Two destinations is the failure this
    guards: it makes "did today go out?" unanswerable, and it is exactly the shape
    of mistake a copied config row produces."""

    def _rec(self, **kw):
        base = dict(key="joseph", owner="Joseph Logan", knocks_office="Joseph Logan",
                    business_name="Logan Legacy Group", website="https://x.com",
                    channel_id="", channel_name="", sheet_id="SHEET",
                    family="d2d", owner_email="joseph@loganlegacygroup.com",
                    email_to=["joseph@loganlegacygroup.com"],
                    reports=[S.EnrolledReport(key="order_log", order=1)])
        base.update(kw)
        return S.OnboardingRecord(**base)

    def test_email_office_is_valid_without_any_channel(self):
        self.assertEqual(S.validate(self._rec()), [])

    def test_both_channel_and_email_is_refused(self):
        problems = S.validate(self._rec(channel_id="C0ABC12DE", channel_name="#x"))
        self.assertTrue(any("BOTH" in p for p in problems), problems)

    def test_neither_channel_nor_email_is_refused(self):
        problems = S.validate(self._rec(email_to=[]))
        self.assertTrue(any("channel_id is empty" in p for p in problems), problems)

    def test_a_typo_for_an_address_is_refused(self):
        problems = S.validate(self._rec(email_to=["joseph.loganlegacygroup.com"]))
        self.assertTrue(any("isn't an email address" in p for p in problems), problems)

    def test_registry_refuses_two_offices_mailing_the_same_person(self):
        """The email flavour of the shared-channel mistake: one inbox, two 'Daily
        Metrics' mails, no way to tell whose numbers are whose."""
        from automations.office_metrics import offices as off
        common = dict(sheet_id="S", knocks_office="K", channel_id="", channel_name="")
        saved = dict(off.OFFICES)
        try:
            off.OFFICES.clear()
            for k in ("a", "b"):
                off.OFFICES[k] = Office(key=k, report_id=f"{k}_metrics",
                                        label=f"{k}'s Office", owner=k,
                                        email_to=("same@example.com",), **common)
            problems = off.validate()
            self.assertTrue(any("already receives" in p for p in problems), problems)
        finally:
            off.OFFICES.clear()
            off.OFFICES.update(saved)


class CaptureDivertsInsteadOfPosting(unittest.TestCase):
    """With METRICS_EMAIL_DIR set, a board goes to the capture and NOT to Slack.

    The point of the interception is that no metric module knows about it, so the
    thing worth testing is that the diversion happens at the shared helper and
    that it reports success the way a real post does — a captured board HAS been
    delivered, and a caller that reads `landed` must not see a good run as
    unverifiable."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self._saved = os.environ.get("METRICS_EMAIL_DIR")
        os.environ["METRICS_EMAIL_DIR"] = str(self.d)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("METRICS_EMAIL_DIR", None)
        else:
            os.environ["METRICS_EMAIL_DIR"] = self._saved
        shutil.rmtree(self.d, ignore_errors=True)

    def test_image_is_captured_and_no_slack_client_is_built(self):
        from automations.shared import slack_metrics_post as smp
        boom = lambda *a, **k: self.fail("built a Slack client for an email office")
        saved, smp._client = smp._client, boom
        try:
            res = smp.post_reply_with_image(_png(self.d / "src" / "b.png"),
                                            comment="📋 Order Log")
        finally:
            smp._client = saved
        self.assertTrue(res["emailed"])
        self.assertTrue(res["ok"])
        self.assertTrue(res["landed"], "a captured board has been delivered")
        self.assertTrue(Path(res["file"]).exists())

    def test_header_is_recorded_once_however_many_metrics_ask(self):
        from automations.shared import slack_metrics_post as smp
        first = smp.ensure_metrics_thread(today=dt.date(2026, 9, 13),
                                          sections=["📋 Order Log"])
        again = smp.ensure_metrics_thread(today=dt.date(2026, 9, 13),
                                          sections=["📋 Order Log"])
        self.assertFalse(first["existed"])
        self.assertTrue(again["existed"])
        from automations.shared import metrics_email_capture as mec
        self.assertEqual(
            sum(1 for r in mec.entries(self.d) if r["kind"] == "header"), 1)

    def test_capture_is_off_by_default(self):
        os.environ.pop("METRICS_EMAIL_DIR", None)
        from automations.shared import metrics_email_capture as mec
        self.assertIsNone(mec.active())


class NeverMailABlankDay(unittest.TestCase):
    """[[feedback_never_post_blank]] — an email headed 'here are today's boards'
    with no board in it is worse than no email at all, because it reads as a
    complete day. Both empty shapes have to be refused: nothing captured (nothing
    ran) and sections captured with no image among them."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        from automations.office_metrics import email_digest as D
        self.D = D
        self._saved = D.capture_dir
        D.capture_dir = lambda key, day=None: self.d
        self.o = Office(key="joseph", report_id="joseph_metrics",
                        label="Joseph's Local Office", owner="Joseph Logan",
                        channel_id="", channel_name="", sheet_id="S",
                        knocks_office="Joseph Logan",
                        email_to=("joseph@loganlegacygroup.com",))

    def tearDown(self):
        self.D.capture_dir = self._saved
        shutil.rmtree(self.d, ignore_errors=True)

    def test_nothing_captured_is_refused(self):
        res = self.D.send_for_office(self.o, dry_run=True)
        self.assertTrue(res["skipped"])
        self.assertIn("no boards were captured", res["reason"])

    def test_text_only_sections_are_not_a_day(self):
        (self.d / "manifest.jsonl").write_text(
            json.dumps({"kind": "text", "seq": 1, "text": "no new orders"}) + "\n")
        res = self.D.send_for_office(self.o, dry_run=True)
        self.assertTrue(res["skipped"])
        self.assertIn("no board image", res["reason"])

    def test_an_office_with_no_recipients_sends_nothing(self):
        bare = Office(key="x", report_id="x_metrics", label="X", owner="X",
                      channel_id="", channel_name="", sheet_id="S",
                      knocks_office="X")
        self.assertTrue(self.D.send_for_office(bare, dry_run=True)["skipped"])

    def test_a_quiet_section_is_not_counted_as_missing(self):
        """A board that said 'nothing new today' RAN. Counting it as a miss turns
        every quiet day into an alarm."""
        _png(self.d / "01-order.png")
        (self.d / "manifest.jsonl").write_text("\n".join([
            json.dumps({"kind": "image", "seq": 1, "label": "📋 Order Log",
                        "file": "01-order.png"}),
            json.dumps({"kind": "text", "seq": 2, "text": "🚫 Cancels — none"}),
        ]) + "\n")
        res = self.D.send_for_office(self.o, dry_run=True)
        self.assertEqual(res["boards"], 1)
        self.assertEqual(res["missing"], 0)


class TrackersComeAsAttachments(unittest.TestCase):
    """Megan 2026-09-13. The country trackers are 3400px wide and denser than
    anything else we send; inline they are crushed into a ~1200px mail column.
    An attachment is the email equivalent of clicking a Slack image open."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        from automations.shared import report_email as RE
        self.RE = RE
        self._budget = RE.MAX_WIRE_BYTES
        self._hard = RE.GMAIL_HARD_LIMIT

    def tearDown(self):
        self.RE.MAX_WIRE_BYTES = self._budget
        self.RE.GMAIL_HARD_LIMIT = self._hard
        shutil.rmtree(self.d, ignore_errors=True)

    def _blocks(self):
        return [("AT&T Internet Country Sales Tracker - Sep 13",
                 _png(self.d / "a.png", 3400, 900)),
                ("NDS Tracker - Sep 13", _png(self.d / "b.png", 2600, 700))]

    def _attachments(self, msg):
        return [p for p in msg.walk() if p.get_content_disposition() == "attachment"]

    def test_each_board_is_its_own_attachment(self):
        msg = self.RE.build_message(subject="s", to=["a@b.com"], title="T",
                                    blocks=self._blocks(), attach=True)
        self.assertEqual(len(self._attachments(msg)), 2)

    def test_attachments_are_named_for_the_board_not_the_file(self):
        msg = self.RE.build_message(subject="s", to=["a@b.com"], title="T",
                                    blocks=self._blocks(), attach=True)
        names = [a.get_filename() for a in self._attachments(msg)]
        self.assertIn("NDS Tracker - Sep 13.png", names)
        self.assertTrue(all(n.endswith(".png") for n in names), names)

    def test_the_body_lists_every_board_and_embeds_none(self):
        """No inline copies: a board attached BECAUSE the column crushes it gains
        nothing from also being painted in that column."""
        blocks = self._blocks() + [("B2B Box — lands later", None, 0, "note")]
        msg = self.RE.build_message(subject="s", to=["a@b.com"], title="T",
                                    blocks=blocks, attach=True)
        html = next(p.get_content() for p in msg.walk()
                    if p.get_content_type() == "text/html")
        for label, *_ in blocks:
            self.assertIn(label, html)
        # Exactly ONE inline image, and it is Evelyn's signature photo — every
        # board is a file, not a thumbnail.
        inline = [q for q in msg.walk()
                  if q.get_content_type().startswith("image/")
                  and q.get_content_disposition() != "attachment"]
        self.assertEqual(len(inline), 1, "a board was embedded in the body")
        self.assertEqual(html.count('<img src="cid:'), 1)

    def test_an_oversized_set_is_reduced_and_says_so(self):
        self.RE.MAX_WIRE_BYTES = 1000        # force the ladder
        msg = self.RE.build_message(subject="s", to=["a@b.com"], title="T",
                                    blocks=self._blocks(), attach=True)
        html = next(p.get_content() for p in msg.walk()
                    if p.get_content_type() == "text/html")
        self.assertIn("were reduced", html)
        self.assertEqual(len(self._attachments(msg)), 2,
                         "reducing must never DROP a board")

    def test_a_set_that_still_will_not_fit_fails_with_a_usable_sentence(self):
        """Better a named refusal than an opaque SMTP reject after a morning of
        Tableau pulls — and far better than the boards going quietly nowhere."""
        self.RE.MAX_WIRE_BYTES = 500
        self.RE.GMAIL_HARD_LIMIT = 1000
        res = self.RE.send_boards(subject="s", to=["a@b.com"], title="T",
                                  blocks=self._blocks(), attach=True,
                                  dry_run=True, preview_dir=self.d,
                                  logfn=lambda *a, **k: None)
        self.assertFalse(res["ok"])
        self.assertIn("over Gmail's", res["reason"])

    def test_inline_is_still_the_default(self):
        """The metrics boards are narrow and read fine in the column — only the
        trackers opted into attachments."""
        msg = self.RE.build_message(subject="s", to=["a@b.com"], title="T",
                                    blocks=self._blocks())
        self.assertEqual(self._attachments(msg), [])


class TrackerEmailOrgs(unittest.TestCase):
    def setUp(self):
        from automations.tableau_screenshots import slack_post as sp
        self.sp = sp
        self._saved = dict(sp.ORG_EMAILS)
        sp.ORG_EMAILS["joseph"] = ["joseph@loganlegacygroup.com"]

    def tearDown(self):
        self.sp.ORG_EMAILS.clear()
        self.sp.ORG_EMAILS.update(self._saved)
        os.environ.pop("TABLEAU_TRACKERS_CHANNEL_ID", None)

    def test_email_org_has_no_channel(self):
        self.assertTrue(self.sp.is_email_org("joseph"))
        self.assertEqual(self.sp.channels_for("joseph"), [])

    def test_scratch_channel_override_cannot_hijack_an_email_org(self):
        """TABLEAU_TRACKERS_CHANNEL_ID redirects every CHANNEL org to a scratch
        channel while building. If it also caught email orgs, a build run would
        post an owner's boards into a Slack channel he isn't even in."""
        os.environ["TABLEAU_TRACKERS_CHANNEL_ID"] = "C0SCRATCH1"
        self.assertEqual(self.sp.channels_for("joseph"), [])
        self.assertEqual(self.sp.channels_for("haytham"), ["C0SCRATCH1"])

    def test_reconcile_does_not_read_an_email_org_as_a_missing_thread(self):
        """There is no thread to read back, so the verdict is 'could not look' —
        NOT a miss. Otherwise an explicit --orgs run alarms about a mail that went
        out fine."""
        from automations.tableau_screenshots import reconcile_posted as rp
        rep = rp.reconcile(orgs=["joseph"], day=dt.date(2026, 9, 13))
        (res,) = rep.orgs
        self.assertTrue(res.unreadable)
        self.assertFalse(res.thread_missing)


if __name__ == "__main__":
    unittest.main()
