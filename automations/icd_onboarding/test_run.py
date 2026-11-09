"""The runner: one office, every step, nothing stopping on one failure.

The rules here are about a run that is PARTLY able to work. A morning where
OwnerVille is down should still tick Blue Ink, and a source that could not be
read must leave its column alone rather than reporting everyone as behind.
"""
from __future__ import annotations

import datetime as dt

from automations.icd_onboarding import run as R

MONDAY = dt.date(2026, 11, 2)


def test_one_source_failing_does_not_stop_the_others(monkeypatch):
    ran = []

    def ok(name):
        def fn(office, week, *, dry_run=True, log=print):
            ran.append(name)
            return 1
        return fn

    def boom(office, week, *, dry_run=True, log=print):
        raise RuntimeError("OwnerVille is having a morning")

    monkeypatch.setattr(R, "STEPS", (("seed", ok("seed")),
                                     ("ownerville", boom),
                                     ("blueink", ok("blueink"))))
    got = R.for_office("raf", MONDAY, log=lambda *a: None)
    assert ran == ["seed", "blueink"], "the rest still ran"
    assert got["seed"] == 1 and got["blueink"] == 1
    assert "RuntimeError" in got["ownerville"], "and the failure is reported"


def test_an_office_with_no_ov_programme_is_skipped_not_guessed(monkeypatch):
    """A guess reads an empty table, which looks exactly like nobody having
    done anything."""
    said = []
    monkeypatch.setattr(R, "_ov_program", lambda k: "")
    n = R.from_ownerville("omar", MONDAY, log=said.append)
    assert n == 0
    assert any("rather than guessing" in s for s in said)


def test_an_office_with_no_appstream_id_does_not_seed(monkeypatch):
    said = []
    monkeypatch.setattr(R, "_appstream_id", lambda k: "")
    assert R.seed("nowhere", MONDAY, log=said.append) == 0
    assert any("no ApplicantStream id" in s for s in said)


def test_a_dry_run_is_the_default():
    import inspect
    for name, fn in R.STEPS:
        assert inspect.signature(fn).parameters["dry_run"].default is True, name
    assert inspect.signature(R.for_office).parameters["dry_run"].default is True


def test_only_runs_just_the_named_steps(monkeypatch):
    ran = []

    def mk(name):
        def fn(office, week, *, dry_run=True, log=print):
            ran.append(name)
            return 0
        return fn

    monkeypatch.setattr(R, "STEPS", (("seed", mk("seed")), ("blueink", mk("blueink"))))
    R.for_office("raf", MONDAY, only=["blueink"], log=lambda *a: None)
    assert ran == ["blueink"]


def test_the_two_self_ticking_sources_are_not_run_here():
    """The contact sync and the Apex run tick as they act — running them from
    here would be asking them to redo work they already recorded."""
    names = [n for n, _ in R.STEPS]
    assert "contacts" not in names and "apex" not in names
    from automations.icd_onboarding import fillers as F
    assert set(F.SOURCES) - set(names) == {"contacts", "apex"}
