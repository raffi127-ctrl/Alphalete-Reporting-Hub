"""Opening Owner Submit never closes the form under us (2026-11-17).

Emmanuel Holley, 18:06: every section COMPLETED, the box ticked, then "Save
Changes failed". The section was opened with `ov._expand`, whose proof-marker
was the old attestation sentence OwnerVille deleted on 11/16. With nothing to
find, `_expand` ran all its fallbacks -- the chevron, then `_force_expand`,
which JS-clicks buttons in the rows around the section out to the modal, where
the buttons are X / Save Changes / Close. The form shut, the box was ticked
inside a closed form by a DOM click, and there was no Save Changes on screen.

These pin: the section is opened by its heading and nothing else, at most two
clicks; a box that never comes on screen is never ticked; and a form that shut
before Save is said in those words, not as a failed click.

    python -m unittest automations.obcl_ov_sweep.test_owner_submit_open
"""
from __future__ import annotations

import unittest
from unittest import mock

from automations.obcl_ov_sweep import owner_submit as OS
from automations.obcl_ov_sweep.test_owner_submit_confirm import code


class _Section:
    """One accordion section: `open` flips on each heading click."""
    def __init__(self, open_=False, opens=True):
        self.open, self.opens, self.clicks = open_, opens, 0


class _Lab:
    def __init__(self, sec):
        self.sec = sec

    def is_visible(self):
        return self.sec.open

    def wait_for(self, state="visible", timeout=0):
        if state == "visible" and not self.sec.open:
            raise TimeoutError("not visible")


class _Toggle:
    def __init__(self, sec):
        self.sec = sec

    def click(self, timeout=0):
        self.sec.clicks += 1
        if self.sec.opens:
            self.sec.open = not self.sec.open


def _patched(sec):
    lab = _Lab(sec)
    return (mock.patch.object(OS, "_confirm_box", lambda m: (lab, "BOX")),
            mock.patch.object(OS, "_section_toggle", lambda m: _Toggle(sec)))


class OpeningTheSection(unittest.TestCase):

    def _open(self, sec):
        a, b = _patched(sec)
        with a, b:
            return OS._open_owner_submit(object(), object())

    def test_an_open_section_is_not_clicked(self):
        """Clicking an open accordion row SHUTS it."""
        sec = _Section(open_=True)
        lab, box, shown = self._open(sec)
        self.assertTrue(shown)
        self.assertEqual(sec.clicks, 0)

    def test_a_shut_section_opens_on_one_click(self):
        sec = _Section(open_=False)
        _, _, shown = self._open(sec)
        self.assertTrue(shown)
        self.assertEqual(sec.clicks, 1)

    def test_a_section_that_will_not_open_stops_at_two_clicks(self):
        """Never the _force_expand walk: two heading clicks, then say so."""
        sec = _Section(open_=False, opens=False)
        lab, _, shown = self._open(sec)
        self.assertFalse(shown)
        self.assertIsNotNone(lab)
        self.assertEqual(sec.clicks, 2)

    def test_it_does_not_use_expand(self):
        """`_expand` with a marker that no longer exists clicks the form shut."""
        src = code()
        fn = src[src.index("def _open_owner_submit"):src.index("def _checked")]
        body = src[src.index("def submit_one"):]
        self.assertNotIn("_expand(", fn)
        self.assertNotIn("_force_expand", fn)
        self.assertNotIn('"OWNER SUBMIT", page', body)


# --- submit_one end to end, with OwnerVille faked -------------------------

_DONE = "\n".join(f"{s}\nCOMPLETED" for s in OS.REQUIRED)


class _Modal:
    def __init__(self, text, visible=True, save_visible=True):
        self.text, self.visible, self.save_visible = text, visible, save_visible

    def inner_text(self):
        return self.text

    def is_visible(self):
        return self.visible

    def get_by_role(self, role, name="", **kw):
        m = self

        class _B:
            first = None

            def is_visible(self_inner):
                return m.visible and m.save_visible
        b = _B()
        b.first = b
        return b


class _Page:
    def wait_for_timeout(self, ms):
        pass


class SubmitOne(unittest.TestCase):

    def _run(self, first, after_text, on_screen=True, tick=True):
        opens = iter([(first, "Emmanuel Holley"),
                      (_Modal(after_text), "Emmanuel Holley")])
        clicked = []
        with mock.patch.object(OS.ov, "open_set_status",
                               lambda *a, **k: next(opens)), \
             mock.patch.object(OS, "_open_owner_submit",
                               lambda m, p: ("LAB", None, on_screen)), \
             mock.patch.object(OS, "_tick", lambda lab, box: tick), \
             mock.patch.object(OS.ov, "_click_any",
                               lambda scope, label, page=None: clicked.append(label)):
            out = OS.submit_one(_Page(), "Emmanuel Holley", dry_run=False)
        return out, clicked

    def test_happy_path_saves_and_confirms(self):
        out, clicked = self._run(
            _Modal(_DONE + "\nOWNER SUBMIT\nNOT SUBMITTED"),
            _DONE + "\nOWNER SUBMIT\nREVIEW IN PROGRESS")
        self.assertEqual(out[0], "submitted", out)
        self.assertEqual(clicked, ["Save Changes"])

    def test_a_form_that_shut_is_not_saved_and_says_so(self):
        """Emmanuel's case: never a blind click on a Save that isn't there."""
        out, clicked = self._run(
            _Modal(_DONE + "\nOWNER SUBMIT\nNOT SUBMITTED", save_visible=False),
            _DONE + "\nOWNER SUBMIT\nNOT SUBMITTED")
        self.assertEqual(out[0], "refused")
        self.assertIn("closed before Save Changes", out[1])
        self.assertEqual(clicked, [])

    def test_a_box_off_screen_is_never_ticked(self):
        ticked = []
        opens = iter([(_Modal(_DONE + "\nOWNER SUBMIT\nNOT SUBMITTED"),
                       "Emmanuel Holley")])
        with mock.patch.object(OS.ov, "open_set_status",
                               lambda *a, **k: next(opens)), \
             mock.patch.object(OS, "_open_owner_submit",
                               lambda m, p: ("LAB", None, False)), \
             mock.patch.object(OS, "_tick",
                               lambda lab, box: ticked.append(1) or True):
            out = OS.submit_one(_Page(), "Emmanuel Holley", dry_run=False)
        self.assertEqual(out[0], "refused")
        self.assertIn("never came on screen", out[1])
        self.assertEqual(ticked, [])

    def test_a_gap_still_refuses_before_anything_is_opened(self):
        text = _DONE.replace("BACKGROUND CHECK\nCOMPLETED",
                             "BACKGROUND CHECK\nPENDING")
        with mock.patch.object(OS.ov, "open_set_status",
                               lambda *a, **k: (_Modal(text), "X")), \
             mock.patch.object(OS, "_open_owner_submit",
                               side_effect=AssertionError("opened")):
            out = OS.submit_one(_Page(), "X", dry_run=False)
        self.assertEqual(out[0], "refused")
        self.assertIn("BACKGROUND CHECK=PENDING", out[1])


if __name__ == "__main__":
    unittest.main()
