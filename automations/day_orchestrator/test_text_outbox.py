import json
from pathlib import Path

from automations.day_orchestrator import text_outbox as tob


def _manifest(tmp_path: Path, day="2026-10-26", name="text_manifest_nds_board_x.json"):
    d = tmp_path / "out" / day
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text("{}")
    return p


def test_drop_and_drain_sends_then_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(tob, "OUTBOX_DIR", tmp_path / "outbox")
    mp = _manifest(tmp_path)
    tob.drop(mp, by="nds_oof")
    assert len(tob.pending()) == 1
    calls = []
    sent, left = tob.drain(lambda a: (calls.append(a), (True, "texted 2 group(s)"))[1], log=lambda s: None)
    assert calls == ["text_manifest_nds_board_x.json 2026-10-26"]
    assert (sent, left) == (1, 0) and tob.pending() == []


def test_failed_ticket_is_retried_then_parked(tmp_path, monkeypatch):
    monkeypatch.setattr(tob, "OUTBOX_DIR", tmp_path / "outbox")
    tob.drop(_manifest(tmp_path), by="b2b_dispositions")
    logs = []
    sent, left = tob.drain(lambda a: (False, "Messages not running"), log=logs.append, max_attempts=2)
    assert (sent, left) == (0, 1)
    info = json.loads(tob.pending()[0].read_text())
    assert info["attempts"] == 1 and "Messages" in info["last_error"]
    sent, left = tob.drain(lambda a: (False, "still down"), log=logs.append, max_attempts=2)
    assert (sent, left) == (0, 0) and tob.pending() == []
    assert list((tmp_path / "outbox" / "failed").glob("*.json"))


def test_drain_is_oldest_first_and_survives_exceptions(tmp_path, monkeypatch):
    monkeypatch.setattr(tob, "OUTBOX_DIR", tmp_path / "outbox")
    tob.drop(_manifest(tmp_path, name="a.json"), by="x")
    tob.drop(_manifest(tmp_path, name="b.json"), by="x")
    seen = []
    def send(a):
        seen.append(a.split()[0])
        if a.startswith("a.json"):
            raise RuntimeError("boom")
        return True, "ok"
    sent, left = tob.drain(send, log=lambda s: None)
    assert seen == ["a.json", "b.json"] and (sent, left) == (1, 1)


def test_second_drainer_steps_aside(tmp_path, monkeypatch):
    """Text lane + main covering for it (or an old poller mid-rollout) must
    never drain at once: the one that finds the drain lock held sends nothing."""
    import fcntl
    import os
    monkeypatch.setattr(tob, "OUTBOX_DIR", tmp_path / "outbox")
    tob.drop(_manifest(tmp_path), by="nds_oof")
    fd = os.open(str(tob.OUTBOX_DIR / tob.DRAIN_LOCK_NAME), os.O_CREAT | os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)     # "the other poller"
    try:
        calls = []
        sent, left = tob.drain(lambda a: (calls.append(a), (True, "ok"))[1],
                               log=lambda s: None)
        assert calls == [] and (sent, left) == (0, 1)
    finally:
        os.close(fd)
    sent, left = tob.drain(lambda a: (True, "ok"), log=lambda s: None)
    assert (sent, left) == (1, 0)
    assert not (tob.OUTBOX_DIR / tob.DRAIN_LOCK_NAME).name.endswith(".json")
