import unittest

from automations.rc_contact_sync import spanish as S
from automations.rc_contact_sync import wrapup as W


class SpanishName(unittest.TestCase):
    def test_waiting_list_from_the_11_9_scrub(self):
        es = ["Armando Pena Martinez", "Alba Alvarez", "Yesenia Cordero", "Felipe Carrillo",
              "Kennir Esau Choc Ramos", "Saraid Gonzalez", "Eva Pacheco", "Omar Piedra",
              "JOSE GAUT", "Erika Gutiérrez"]
        en = ["Thomas Blake", "Devonte Eaglin", "Sri Krishna Vinay Majety", "Rene Patton",
              "Manish Reddy Gorre", "Noelle Katcher", "Mansoor Abbasi", "Subba Rao Maddela",
              "Georgeatte Mcdonald", "Haley Cole", ""]
        for n in es:
            self.assertEqual(S.language(n), "es", n)
        for n in en:
            self.assertEqual(S.language(n), "en", n)

    def test_override_wins(self):
        S.LANGUAGE_OVERRIDES["crystal marquez"] = "en"
        try:
            self.assertEqual(S.language("Crystal MARQUEZ"), "en")
        finally:
            S.LANGUAGE_OVERRIDES.pop("crystal marquez")
        self.assertEqual(S.language("Crystal Marquez"), "es")

    def test_wrapup_in_spanish(self):
        cust = {"customer_name": "YESENIA CORDERO", "rep": "jose deleon",
                "wireless_order": "99-1", "ban": "B1"}
        t = W.build_text(cust)
        self.assertTrue(t.startswith("Hola Yesenia, ¡gracias por elegir AT&T!"))
        self.assertIn("Jose Deleon", t)
        self.assertIn("• Orden # 99-1", t)
        self.assertIn(W.PIN_FALLBACK_ES, t)
        self.assertIn(W.TODO_URL, t)
        self.assertNotIn("{", t)
        # same links as the English one
        for link in ("att.com/orders/checkmyorder", "att.com/activations/activatewireless",
                     "nextqr.com/tradein-nds", "945-337-2199"):
            self.assertIn(link, t)
        # English customer untouched
        self.assertTrue(W.build_text({"customer_name": "Thomas Blake", "rep": "x"})
                        .startswith("Hi Thomas, thank you for choosing AT&T!"))
        # no first name, Spanish surname only
        self.assertTrue(W.build_text({"customer_name": "", "rep": "x"}).startswith("Hi there"))


if __name__ == "__main__":
    unittest.main()
