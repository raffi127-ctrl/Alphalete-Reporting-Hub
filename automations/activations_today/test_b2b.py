import unittest

from automations.activations_today import b2b, pull, run


class B2BInstallType(unittest.TestCase):
    def test_y_n_become_words(self):
        rows = b2b.to_pull_rows([{"Tech Install": "Y"}, {"Tech Install": "N"},
                                 {"Tech Install": ""}], "Eveliz")
        self.assertEqual([r[pull.TECH] for r in rows],
                         ["Tech Install", "Self Install", ""])

    def test_words_get_the_d2d_colors(self):
        self.assertEqual(run.status_color(b2b.install_type("Y")), run._YELLOW)
        self.assertEqual(run.status_color(b2b.install_type("n")), run._BLUE)


if __name__ == "__main__":
    unittest.main()
