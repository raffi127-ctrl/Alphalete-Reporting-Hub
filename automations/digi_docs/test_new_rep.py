"""new_rep.create against a fake rep list -- the two ways 2026-09-21 went wrong.

Jaylen Anthony was already in OwnerVille under another email and was created a
second time. Faith Moss was created, but the one search right after the save
missed her, so the run told the office to add her by hand.

Nothing here touches a browser: the rep-list helpers are replaced.
"""
from __future__ import annotations

import types
import unittest
from unittest import mock

from automations.digi_docs import new_rep


def _person(first="Jaylen", last="Anthony", email="jaylen.new@gmail.com",
            phone="4695550100"):
    return types.SimpleNamespace(first=first, last=last, email=email,
                                 phone=phone)


class _Page:
    def __init__(self):
        self.waits = []

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


class _Directory:
    """The Sales Reps list. `appears_after` = how many email lookups for a
    freshly created record come back empty before it shows up."""

    def __init__(self, rows, appears_after=0):
        self.rows = list(rows)
        self.appears_after = appears_after
        self.created = []
        self.lookups = 0

    def by_email(self, page, cols, email):
        self.lookups += 1
        for r in self.rows:
            if r["email"] == email.lower():
                return r
        for r in self.created:
            if r["email"] == email.lower():
                if self.appears_after:
                    self.appears_after -= 1
                    return None
                return r
        return None

    def search_rows(self, page, term):
        return [(r, "pid=1") for r in self.rows
                if term.lower() in (r["first"] + " " + r["last"]).lower()]


def _patched(directory):
    def _open_form(page, rqst, verbose=True):
        return None, None

    def _press_add(*a, **k):
        pass

    return [
        mock.patch.object(new_rep.ovn, "open_rep_list", lambda p, **k: "rq"),
        mock.patch.object(new_rep.ovn, "_columns", lambda p: {}),
        mock.patch.object(new_rep.ovn, "_search_rows",
                          lambda p, t, **k: directory.search_rows(p, t)),
        mock.patch.object(new_rep.ovn, "_row_fields",
                          lambda p, row, cols: dict(row, full="")),
        mock.patch.object(new_rep.ovn, "_complaints", lambda p: []),
        mock.patch.object(new_rep, "find_by_email", directory.by_email),
        mock.patch.object(new_rep, "_open_form", _open_form),
        mock.patch.object(new_rep, "_fill", lambda *a, **k: None),
        mock.patch.object(new_rep, "_tick_labelled", lambda *a, **k: None),
    ]


class _AddButton:
    """page.get_by_role('button', name='Add') -> clicking it 'saves'."""

    def __init__(self, directory, person):
        self.directory, self.person = directory, person
        self.clicks = 0

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def click(self, *a, **k):
        self.clicks += 1
        self.directory.created.append(
            {"first": self.person.first, "last": self.person.last,
             "email": self.person.email.lower()})


def _page_with_add(directory, person):
    page = _Page()
    btn = _AddButton(directory, person)
    page.get_by_role = lambda role, name=None, **k: btn
    page.wait_for_load_state = lambda *a, **k: None
    page.add = btn
    return page


class SameNameDifferentEmail(unittest.TestCase):
    def test_a_namesake_stops_the_create(self):
        d = _Directory([{"first": "Jaylen", "last": "Anthony",
                         "email": "jaylen.old@yahoo.com"}])
        p = _person()
        page = _page_with_add(d, p)
        with _stack(_patched(d)):
            with self.assertRaises(new_rep.Refused) as cm:
                new_rep.create(page, p, dry_run=False, verbose=False)
        self.assertEqual(0, page.add.clicks, "nobody may be created")
        msg = str(cm.exception)
        self.assertIn("jaylen.old@yahoo.com", msg,
                      "say which record is already there")
        self.assertIn("correct the email", msg)

    def test_a_different_first_name_is_not_a_namesake(self):
        d = _Directory([{"first": "Jaden", "last": "Anthony",
                         "email": "jaden@gmail.com"}])
        p = _person()
        page = _page_with_add(d, p)
        with _stack(_patched(d)):
            self.assertEqual("created",
                             new_rep.create(page, p, dry_run=False,
                                            verbose=False))
        self.assertEqual(1, page.add.clicks)

    def test_accents_and_case_still_count_as_the_same_name(self):
        d = _Directory([{"first": "ABEL", "last": "Quiñones",
                         "email": "abel@x.com"}])
        p = _person(first="Abel", last="Quinones", email="abel.q@gmail.com")
        page = _page_with_add(d, p)
        with _stack(_patched(d)):
            with self.assertRaises(new_rep.Refused):
                new_rep.create(page, p, dry_run=False, verbose=False)


class SlowToAppearIsNotMissing(unittest.TestCase):
    def test_a_record_that_shows_up_on_the_second_look_is_created(self):
        d = _Directory([], appears_after=1)
        p = _person(first="Faith", last="Moss", email="faith@gmail.com")
        page = _page_with_add(d, p)
        with _stack(_patched(d)):
            self.assertEqual("created",
                             new_rep.create(page, p, dry_run=False,
                                            verbose=False))
        self.assertIn(5000, page.waits, "it waited before looking again")

    def test_never_showing_up_is_still_a_refusal(self):
        d = _Directory([], appears_after=99)
        p = _person(first="Faith", last="Moss", email="faith@gmail.com")
        page = _page_with_add(d, p)
        with _stack(_patched(d)):
            with self.assertRaises(new_rep.Refused):
                new_rep.create(page, p, dry_run=False, verbose=False)


class _stack:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for pt in self.patches:
            pt.start()

    def __exit__(self, *a):
        for pt in reversed(self.patches):
            pt.stop()
        return False


if __name__ == "__main__":
    unittest.main()
