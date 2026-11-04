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
