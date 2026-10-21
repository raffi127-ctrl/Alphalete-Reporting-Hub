"""The bulletin's own SMTP send notes the delivery (2026-10-20: RCs & NCs went
out at 4:37pm and its ticket stayed open). Fake SMTP; nothing is mailed.

    python -m unittest automations.override_bulletin.test_send_records_delivery
"""
from __future__ import annotations

import unittest
from email.message import EmailMessage
from unittest import mock

from automations.override_bulletin import send as S


class _SMTP:
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False

    def login(self, *a):
        pass

    def send_message(self, msg):
        _SMTP.sent.append(msg)


class SendRecords(unittest.TestCase):

    def test_send_records_under_the_report(self):
        msg = EmailMessage()
        msg["To"], msg["Subject"] = "owners@x.com", "Up and Coming RCs and NCs"
        with mock.patch.object(S.smtplib, "SMTP_SSL", _SMTP), \
                mock.patch("automations.scheduled_6_days_out.email_send.app_password",
                           return_value="x"), \
                mock.patch("automations.shared.delivery_ledger.record") as rec:
            S.send_email(msg, report_id="rcs_ncs")
        self.assertEqual(len(_SMTP.sent), 1)
        self.assertEqual(rec.call_args.kwargs["report_id"], "rcs_ncs")
        self.assertEqual(rec.call_args.args[:2], ("email", "owners@x.com"))


if __name__ == "__main__":
    unittest.main()
