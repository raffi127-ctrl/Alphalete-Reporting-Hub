"""`lucy update` must reach EVERY Lucy (Megan 2026-09-21).

A fix pushed and queued to Lucy 1/2/3 left Lucy 4 on old code. The rule: an
update with no machine named (or --machine all) queues to every runner in
fleet.RUNNERS, so a machine added there is covered without touching this.

    python -m pytest automations/day_orchestrator/test_mini_control_update_fleet.py -q
"""
from unittest import mock

from automations.day_orchestrator import mini_control as mc
from automations.shared import fleet


def _queued(argv):
    with mock.patch.object(mc, "enqueue") as enq:
        mc.main(argv)
    return [c.kwargs["machine"] for c in enq.call_args_list]


def test_update_with_no_machine_goes_to_every_lucy():
    assert _queued(["--enqueue", "update"]) == list(fleet.RUNNERS)


def test_update_machine_all_goes_to_every_lucy():
    assert _queued(["--machine", "all", "--enqueue", "update"]) == list(fleet.RUNNERS)


def test_update_to_one_named_machine_stays_one():
    assert _queued(["--machine", "Lucy 2", "--enqueue", "update"]) == ["Lucy 2"]


def test_other_actions_keep_their_default_target():
    assert _queued(["--enqueue", "ping"]) == [None]
