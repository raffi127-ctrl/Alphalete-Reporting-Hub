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


def test_rerun_goes_to_the_least_loaded_lucy():
    """2026-10-21: 17 rows backed up on Lucy 2 while Lucy 3 sat empty."""
    import datetime as _dt
    from automations.day_orchestrator import routing
    raw = {"reports": {"rc_contact_sync": {
        "machine": "Lucy 2", "source_type": "appstream",
        "can_run_on": ["Lucy 1", "Lucy 3"]}}}
    loads = {"Mini Control - Lucy 2": 17, "Mini Control": 1,
             "Mini Control - Lucy 3": 0, "Mini Control - Lucy 4": 0}
    sheet = mock.MagicMock()
    sheet.worksheet.side_effect = lambda tab: SimpleNamespace(
        get_all_values=lambda: [["hdr"]] + [["", "", "", "", "queued"]] * loads[tab])
    # A FIXED clock, and the idle notes stamped on that same clock. The first
    # version stamped them with the real time while faking 2pm, so it failed
    # every morning — and the 5:15am push gate (10/22) refused to ship over it.
    afternoon = _dt.datetime(2026, 10, 21, 14, 0).astimezone()
    stamp = afternoon.astimezone(_dt.timezone.utc) - _dt.timedelta(minutes=3)
    idle = {"mini_control_lucy_%d" % i: {"note": routing.batch_note(False, stamp)}
            for i in (1, 2, 3, 4)}
    with mock.patch.object(mc.registry, "load_config",
                           return_value=SimpleNamespace(raw=raw)), \
         mock.patch.object(mc._fill, "_client") as client, \
         mock.patch("automations.shared.silent_job_watch.read_beats",
                    return_value=idle), \
         mock.patch.object(routing._dt, "datetime", wraps=_dt.datetime) as fake:
        fake.now.side_effect = lambda tz=None: (
            afternoon.astimezone(tz) if tz else afternoon)
        client.return_value.open_by_key.return_value = sheet
        assert mc._rerun_home("rc_contact_sync", "Megan") == "Lucy 3"
        # a watchdog's rerun is never moved
        assert mc._rerun_home("rc_contact_sync", "auto:watch") == "Lucy 2"


def test_queue_read_failure_keeps_it_home():
    raw = {"reports": {"rc_contact_sync": {
        "machine": "Lucy 2", "can_run_on": ["Lucy 3"]}}}
    with mock.patch.object(mc.registry, "load_config",
                           return_value=SimpleNamespace(raw=raw)), \
         mock.patch.object(mc._fill, "_client", side_effect=RuntimeError("429")):
        assert mc._rerun_home("rc_contact_sync", "Megan") == "Lucy 2"
