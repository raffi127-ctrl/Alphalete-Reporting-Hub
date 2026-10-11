"""A `rerun` with no machine named goes to the Lucy that OWNS the report.

2026-10-10: the failure post said `lucy rerun rc_contact_sync`, it went to
Lucy 1, and Lucy 1 has no B2B SaraPlus login. An explicit --machine still wins.

    python -m pytest automations/day_orchestrator/test_mini_control_rerun_routing.py -q
"""
from types import SimpleNamespace
from unittest import mock

import pytest

from automations.day_orchestrator import mini_control as mc


HOMES = {"rc_contact_sync": "Lucy 2", "daily_focus": "Lucy 1",
         "alphalete_org_focus": "Lucy 3"}


@pytest.fixture(autouse=True)
def _registry():
    def resolve(_cfg, rid):
        return SimpleNamespace(machine=HOMES[rid]) if rid in HOMES else None
    with mock.patch.object(mc.registry, "load_config", return_value=None), \
         mock.patch.object(mc.registry, "resolve_report", side_effect=resolve):
        yield


def test_home_of_a_lucy2_report():
    assert mc._rerun_home("rc_contact_sync") == "Lucy 2"


def test_extra_args_do_not_confuse_the_lookup():
    assert mc._rerun_home('alphalete_org_focus --only "Marcellus Butler"') == "Lucy 3"


def test_lucy1_report_keeps_the_default_queue():
    assert mc._rerun_home("daily_focus") is None


def test_unknown_report_falls_through_to_the_default():
    # _action_rerun then says "unknown report_id" -- the same answer as before.
    assert mc._rerun_home("no_such_report") is None
    assert mc._rerun_home("") is None


class _Routed(Exception):
    pass


def _target(**kw):
    """The machine enqueue() actually routes to, stopped before any Sheet write."""
    def stop(machine):
        raise _Routed(machine)
    with mock.patch.object(mc._fill, "_client"), \
         mock.patch.object(mc, "_control_tab_for", side_effect=stop):
        with pytest.raises(_Routed) as e:
            mc.enqueue("rerun", **kw)
    return e.value.args[0]


def test_enqueue_rerun_with_no_machine_goes_home():
    assert _target(args="rc_contact_sync", by="Megan") == "Lucy 2"


def test_explicit_machine_still_wins():
    assert _target(args="rc_contact_sync", by="Megan", machine="Lucy 4") == "Lucy 4"
