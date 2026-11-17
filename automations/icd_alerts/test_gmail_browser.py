"""Lucy's Gmail window (gmail_browser) and Gmail's mails in Spanish. 2026-11-17.

The clicking itself was proven live on Eve's test Gmail (sobrino.eve, Spanish):
address added after one phone tap, confirmed, filter made after a second tap,
read back from the filter list. What is pinned here is what needs no browser.
"""
from __future__ import annotations

import unittest

from automations.icd_alerts import code_answer as CA
from automations.icd_alerts import gmail_browser as GB


class TheAccountInTheTitle(unittest.TestCase):
    def test_gmail_names_the_account(self):
        self.assertEqual(GB._account_in("Recibidos (3) - Owner.X@gmail.com - Gmail"),
                         "owner.x@gmail.com")
        self.assertEqual(GB._account_in("Configuración - a+b@office.com - Gmail"), "a+b@office.com")

    def test_no_account_while_signing_in(self):
        self.assertEqual(GB._account_in("Gmail"), "")
        self.assertEqual(GB._account_in("Sign in - Google Accounts"), "")


class ThePhoneNumber(unittest.TestCase):
    def test_a_line_that_is_only_the_number(self):
        self.assertEqual(GB._phone_number("Verify it's you\n94\nTap this number"), "94")

    def test_no_number(self):
        self.assertEqual(GB._phone_number("Enter your password\n2-Step Verification"), "")


class TheUrls(unittest.TestCase):
    def test_gmail_in_that_account_reloaded(self):
        u = GB.gmail_url("a+b@office.com", "settings/fwdandpop")
        self.assertTrue(u.startswith("https://mail.google.com/mail/?authuser=a%2Bb@office.com&lucy="))
        self.assertTrue(u.endswith("#settings/fwdandpop"))

    def test_sign_in_names_the_account(self):
        self.assertIn("Email=owner@gmail.com", GB.signin_url("owner@gmail.com"))


class NeverTheWholeInbox(unittest.TestCase):
    def test_nothing_touches_the_forward_a_copy_switch(self):
        import inspect
        src = inspect.getsource(GB)
        self.assertNotIn("sx_em][value", src.replace(" ", ""))
        self.assertNotIn("value=\"1\"", src)


SPANISH_SUBJECT = "(Gmail Confirmación de reenvío - Recibir correos de Owner@gmail.com"
SPANISH_BODY = ("Para permitir que owner@gmail.com reenvíe el correo electrónico\n"
                "haz clic en el siguiente vínculo para confirmar la solicitud:\n\n"
                "https://mail-settings.google.com/mail/vf-abc\n\n"
                "Si hiciste clic ... haz clic en\nhttps://mail-settings.google.com/mail/uf-zzz\n")
ENGLISH_BODY = ("To allow owner@gmail.com to automatically forward mail to your address,\n"
                "please click the link below to confirm the request:\n\n"
                "https://mail-settings.google.com/mail/vf-abc\n\n"
                "If you click the link and it appears to be broken...\n"
                "https://mail-settings.google.com/mail/uf-zzz\n")


class GmailMailInSpanish(unittest.TestCase):
    """A Spanish Gmail mails its confirmation in Spanish; it was never matched."""

    def test_the_requester(self):
        self.assertEqual(CA.requester_of(SPANISH_SUBJECT), "owner@gmail.com")
        self.assertEqual(CA.requester_of(
            "(Gmail Forwarding Confirmation - Receive Mail from owner@gmail.com"), "owner@gmail.com")

    def test_the_confirm_link_never_the_cancel_one(self):
        self.assertEqual(CA.confirmation_link(SPANISH_BODY), "https://mail-settings.google.com/mail/vf-abc")
        self.assertEqual(CA.confirmation_link(ENGLISH_BODY), "https://mail-settings.google.com/mail/vf-abc")

    def test_the_search_is_by_sender_only(self):
        self.assertNotIn("subject:", CA.CONFIRM_QUERY)
        self.assertIn("from:forwarding-noreply@google.com", CA.CONFIRM_QUERY)


class ThePageInSpanish(unittest.TestCase):
    def _page(self, before, after):
        import contextlib

        class Page:
            def __init__(self):
                self.text, self.clicked = before, None

            def goto(self, *a, **k):
                pass

            def inner_text(self, _):
                return self.text

            @contextlib.contextmanager
            def expect_navigation(self, **_):
                yield

            def click(self, sel):
                self.clicked = sel
                self.text = after
        page = Page()

        @contextlib.contextmanager
        def open_page():
            yield page
        return page, open_page

    def test_spanish_page_is_confirmed(self):
        page, open_page = self._page(
            "Confirmación\nconfirma el reenvío de correo de owner@gmail.com a alphaletereporting@gmail.com.",
            "¡Confirmación exitosa! owner@gmail.com ahora puede reenviar mensajes")
        CA.accept_confirmation("https://mail-settings.google.com/mail/vf-x", "owner@gmail.com",
                               open_page=open_page)
        self.assertEqual(page.clicked, 'input[type="submit"]')

    def test_a_page_for_someone_else_is_never_pressed(self):
        page, open_page = self._page("confirma el reenvío de correo de other@gmail.com", "")
        with self.assertRaises(ValueError):
            CA.accept_confirmation("https://mail-settings.google.com/mail/vf-x", "owner@gmail.com",
                                   open_page=open_page)
        self.assertIsNone(page.clicked)


if __name__ == "__main__":
    unittest.main()
