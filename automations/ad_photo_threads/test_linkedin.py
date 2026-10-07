import unittest

from automations.ad_photo_threads.linkedin import same_person


class SamePerson(unittest.TestCase):
    def test_first_and_last(self):
        self.assertTrue(same_person("Noah", "Nothrop", "Noah Nothrop"))

    def test_accents_and_middle_names(self):
        self.assertTrue(same_person("Jocelyne", "Patino De Leon", "Jocélyne Patiño De León"))

    def test_suffix_uses_the_real_last_name(self):
        self.assertTrue(same_person("Davon", "Graham Ii", "Davon Graham"))

    def test_other_person_same_first_name(self):
        self.assertFalse(same_person("Noah", "Nothrop", "Noah Smith"))


if __name__ == "__main__":
    unittest.main()
