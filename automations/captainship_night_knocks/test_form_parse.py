"""The FORM parser — the fix for the first live harvest, 2026-09-11.

That run came back with "no 'City, ST ZIP' on p=767" for all 44 offices while
every page had loaded perfectly. The reason is in the one line of HTML the
scraper saved:

    <input type="text" name="city" id="city" class="form-control" value="Lubbock">

Company Information is a FORM. The address sits in `value=` attributes, and
`inner_text` cannot see an attribute — so a text scrape of a page that is
working finds nothing at all. These tests pin the shape that actually came
back, so the same page can never fail silently again.

The state is the other half: that page carries NO state field (no
`name="state"`, no `value="TX"`, in 9,600 lines), so it is derived from the
ZIP, which pins it exactly.
"""
from __future__ import annotations

import unittest

from automations.captainship_night_knocks import addresses as A
from automations.captainship_night_knocks.harvest_zones import (
    form_fields, parse_form,
)

# Verbatim shape of what came back for Rashad Reed's office on 2026-09-11.
REAL = ('<div class="tab-pane"><form id="companyInfo">'
        '<input type="text" name="companyName" id="companyName" '
        'class="form-control" value="Alphalete Marketing">'
        '<input type="text" name="address1" id="address1" '
        'class="form-control" value="5217 82nd St">'
        '<input type="text" name="city" id="city" class="form-control" '
        'value="Lubbock">'
        '<input type="text" name="zip" id="zip" class="form-control" '
        'placeholder="" value="79424">'
        '<input type="hidden" name="rqst" value="A1B2C3D4">'
        '</form></div>')


class FormFields(unittest.TestCase):
    def test_reads_values_out_of_the_inputs(self):
        got = form_fields(REAL)
        self.assertEqual(got["city"], "Lubbock")
        self.assertEqual(got["zip"], "79424")
        self.assertEqual(got["address1"], "5217 82nd St")

    def test_empty_values_are_not_fields(self):
        self.assertNotIn("placeholder", form_fields(REAL))
        self.assertEqual(form_fields('<input name="city" value="">'), {})

    def test_reads_a_selected_option_when_there_is_a_select(self):
        html = ('<select name="state"><option value="AL">Alabama</option>'
                '<option value="TX" selected>Texas</option></select>')
        self.assertEqual(form_fields(html)["state"], "TX")

    def test_survives_a_page_with_no_form_at_all(self):
        self.assertEqual(form_fields("<html><body>nothing</body></html>"), {})


class ParseForm(unittest.TestCase):
    def test_the_page_that_failed_now_parses(self):
        self.assertEqual(parse_form(REAL),
                         {"city": "Lubbock", "state": "TX", "zip": "79424"})

    def test_state_comes_from_the_zip_when_the_form_has_none(self):
        for zip_code, state in (("79424", "TX"), ("48075", "MI"),
                                ("46204", "IN"), ("18702", "PA"),
                                ("90001", "CA"), ("32801", "FL")):
            html = ('<input name="city" value="Somewhere">'
                    '<input name="zip" value="%s">' % zip_code)
            self.assertEqual(parse_form(html)["state"], state, zip_code)

    def test_a_real_state_field_wins_over_the_zip(self):
        html = ('<input name="city" value="El Paso">'
                '<input name="state" value="TX">'
                '<input name="zip" value="79901">')
        self.assertEqual(parse_form(html)["state"], "TX")

    def test_a_spelled_out_state_is_ignored_in_favour_of_the_zip(self):
        """'Texas'[:2] is 'TE' — a state name is not a state code, and
        truncating one is how an office lands in a state that does not
        exist."""
        html = ('<input name="city" value="Lubbock">'
                '<input name="state" value="Texas">'
                '<input name="zip" value="79424">')
        self.assertEqual(parse_form(html)["state"], "TX")

    def test_no_city_means_no_answer(self):
        self.assertIsNone(parse_form('<input name="zip" value="79424">'))

    def test_no_zip_and_no_state_means_no_answer(self):
        self.assertIsNone(parse_form('<input name="city" value="Lubbock">'))


class ZipToState(unittest.TestCase):
    def test_the_eleven_measured_offices_land_where_they_are(self):
        # ZIPs from output/office_addresses.json (harvested 2026-08-25).
        for zip_code, state in (("79424", "TX"),   # Lubbock
                                ("75701", "TX"),   # Tyler
                                ("46204", "IN"),   # Indianapolis
                                ("48075", "MI"),   # Southfield
                                ("18702", "PA")):  # Wilkes-Barre
            self.assertEqual(A.state_for_zip(zip_code), state, zip_code)

    def test_junk_is_none_never_a_neighbour(self):
        for junk in ("", "abcde", "1234", "000000", None, "00000"):
            self.assertIsNone(A.state_for_zip(junk), repr(junk))

    def test_zip_plus_four_still_answers(self):
        self.assertEqual(A.state_for_zip("79424-1234"), "TX")

    def test_a_derived_state_still_obeys_the_split_state_rule(self):
        """Deriving the STATE never loosens the zone rule: an unconfirmed city
        in a split state is still nobody's wave."""
        r = A.resolve("Crestview", A.state_for_zip("32536"))
        self.assertEqual(r.confidence, "unknown")
        self.assertIsNone(r.zone)


class TrailingPunctuation(unittest.TestCase):
    """ownerville returned Kash Rai's city as "Fort Worth," — comma and all,
    inside the field's own value. A confirmed city that fails to match is worse
    than an unknown one: it reads as a split-state refusal and sends somebody
    to check a city that was already checked."""

    def test_a_trailing_comma_does_not_hide_a_confirmed_city(self):
        self.assertEqual(A.resolve("Fort Worth,", "TX").zone, "America/Chicago")
        self.assertEqual(A.resolve("Fort Worth,", "TX").confidence, "city")

    def test_the_cities_the_first_captainship_harvest_landed_on(self):
        for city, state, zone in (("Grandville", "MI", "America/Detroit"),
                                  ("Memphis", "TN", "America/Chicago"),
                                  ("Pensacola", "FL", "America/Chicago"),
                                  ("Knoxville", "TN", "America/New_York")):
            self.assertEqual(A.resolve(city, state).zone, zone, city)

    def test_an_unknown_city_in_a_split_state_is_still_refused(self):
        self.assertIsNone(A.resolve("Somewhere", "MI").zone)


if __name__ == "__main__":
    unittest.main()
