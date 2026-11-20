"""The machine-wide Messages send lock (automations/shared/messages_lock.py).

    python -m pytest automations/shared/test_messages_lock.py

Covers: it is reentrant inside one process (send_manifest -> send_to_group),
it really excludes a SECOND process, and send_manifest's .sent de-dupe holds
under it. No Messages.app, no osascript: the sender is stubbed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from automations.shared import messages_lock as ml

pytestmark = pytest.mark.skipif(ml._fcntl is None, reason="flock is POSIX-only")


def test_reentrant_in_one_process(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "LOCK_PATH", tmp_path / "m.lock")
    with ml.held("outer"):
        with ml.held("inner", wait_s=0.5):     # would time out if not reentrant
            assert ml._DEPTH == 2
    assert ml._DEPTH == 0


def test_excludes_another_process(tmp_path, monkeypatch):
    lock = tmp_path / "m.lock"
    monkeypatch.setattr(ml, "LOCK_PATH", lock)
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent("""
            import sys, time
            from pathlib import Path
            from automations.shared import messages_lock as ml
            ml.LOCK_PATH = Path(sys.argv[1])
            with ml.held("other process"):
                print("held", flush=True)
                time.sleep(30)
        """), str(lock)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(ml.MessagesBusy):
            with ml.held("this process", wait_s=1.5):
                pass
    finally:
        holder.kill()
        holder.wait()
    with ml.held("after the holder died", wait_s=2):   # kernel released it
        pass


def test_send_manifest_sends_once(tmp_path, monkeypatch):
    from automations.b2b_dispositions import text_post as tp
    monkeypatch.setattr(ml, "LOCK_PATH", tmp_path / "m.lock")
    man = tmp_path / "text_manifest_x.json"
    man.write_text(json.dumps({"kind": "hourly", "title": "t", "text": "hi",
                               "by_campaign": {}}))
    sends = []

    def fake_send_specs(specs, dry_run=True):
        if not dry_run:
            assert ml._DEPTH == 1, "a live send must run under the Messages lock"
        sends.append(dry_run)
        return {"ok": True, "sent": [], "errors": [], "skipped_routes": []}
    monkeypatch.setattr(tp, "send_specs", fake_send_specs)
    tp.send_manifest(man, dry_run=False)
    again = tp.send_manifest(man, dry_run=False)
    assert sends == [False] and again.get("skipped")
    tp.send_manifest(man, dry_run=True)                # dry run: no lock, no marker check
    assert sends == [False, True]


# ---- SALE ALERTS GO NEXT (Carlos 2026-11-19) --------------------------------

def _other_live_pid() -> int:
    import os
    return os.getppid()          # the test runner's parent: alive, not us


def _mark(tmp_path, pid, *, age_s=0.0):
    import os
    import time
    p = (tmp_path / "m.lock").with_suffix(".priority")
    p.write_text("%d test\n" % pid)
    if age_s:
        t = time.time() - age_s
        os.utime(p, (t, t))
    return p


def test_a_sender_stands_aside_while_another_process_has_a_sale_text(tmp_path, monkeypatch):
    import time
    lock = tmp_path / "m.lock"
    monkeypatch.setattr(ml, "LOCK_PATH", lock)
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent("""
            import sys, time
            from pathlib import Path
            from automations.shared import messages_lock as ml
            ml.LOCK_PATH = Path(sys.argv[1])
            with ml.priority("sale"):
                print("marked", flush=True)
                time.sleep(2.0)
            print("unmarked", flush=True)
            time.sleep(30)
        """), str(lock)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "marked"
        t0 = time.monotonic()
        with ml.held("board"):
            waited = time.monotonic() - t0
        assert waited >= 1.0, "the board went ahead of a sale text in hand"
        assert holder.stdout.readline().strip() == "unmarked"
        assert not lock.with_suffix(".priority").exists()
    finally:
        holder.kill()
        holder.wait()


def test_the_priority_holder_never_waits_on_its_own_mark(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(ml, "LOCK_PATH", tmp_path / "m.lock")
    t0 = time.monotonic()
    with ml.priority("sale"):
        assert ml._priority_path().exists()
        with ml.held("sale text", wait_s=0.5):
            pass
    assert time.monotonic() - t0 < 1.0
    assert not ml._priority_path().exists()


def test_a_stale_mark_is_a_crash_leftover(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(ml, "LOCK_PATH", tmp_path / "m.lock")
    _mark(tmp_path, _other_live_pid(), age_s=ml.PRIORITY_STALE_S + 60)
    t0 = time.monotonic()
    with ml.held("board", wait_s=0.5):
        pass
    assert time.monotonic() - t0 < 1.0


def test_a_dead_holders_mark_is_ignored(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(ml, "LOCK_PATH", tmp_path / "m.lock")
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    _mark(tmp_path, gone.pid)
    t0 = time.monotonic()
    with ml.held("board", wait_s=0.5):
        pass
    assert time.monotonic() - t0 < 1.0


def test_standing_aside_is_capped_so_boards_still_go(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(ml, "LOCK_PATH", tmp_path / "m.lock")
    monkeypatch.setattr(ml, "PRIORITY_YIELD_MAX_S", 0.6)
    _mark(tmp_path, _other_live_pid())          # live, fresh, never released
    t0 = time.monotonic()
    with ml.held("board", wait_s=0.5):
        pass
    waited = time.monotonic() - t0
    assert 0.5 <= waited < 3.0


def test_a_nested_send_does_not_stand_aside(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(ml, "LOCK_PATH", tmp_path / "m.lock")
    with ml.held("manifest"):
        _mark(tmp_path, _other_live_pid())      # a sale text shows up mid-post
        t0 = time.monotonic()
        with ml.held("its pictures", wait_s=0.5):
            pass
        assert time.monotonic() - t0 < 0.5, "a post must never split for it"
