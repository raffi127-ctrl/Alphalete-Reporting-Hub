"""Where the OBCL update picture goes: the office's own answer.

Raf's outstanding ask is this post in a Slack THREAD instead of iMessage.
Megan, 2026-11-22: the channel "will need to be asked on the enrollment
form", and "they also need an option here to send to a text group".
"""
from __future__ import annotations

import pytest

from automations.eco_onboarding import settings as ES
from automations.icd_onboarding import office_steps as OS
from automations.obcl_ov_sweep import snapshot as SN


@pytest.fixture
def shot(tmp_path, monkeypatch):
    monkeypatch.setattr(SN, "SHOT_DIR", tmp_path)
    png = tmp_path / "obcl_2026-11-22_1400_1.png"
    png.write_bytes(b"not really a png")
    (tmp_path / "obcl_2026-11-22_1400_1.txt").write_text("OBCL update 11/22")
    return png


def _sheet(monkeypatch, **cols):
    row = {OS.COL_OFFICE: "raf"}
    row.update(cols)
    monkeypatch.setattr(OS, "_rows", lambda *a, **k: [row])


def test_an_office_that_chose_slack_gets_slack(shot, monkeypatch):
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_SLACK,
                           ES.COL_OBCL_CHANNEL: "C0AUAS88FGW"})
    res = SN.send([shot.name], dry_run=True, office_key="raf")
    assert res["ok"] and res["resolved_name"] == "C0AUAS88FGW"
    assert res["participants"] == "slack"


def test_an_office_that_chose_a_text_group_gets_their_group(shot, monkeypatch):
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_TEXT,
                           ES.COL_OBCL_GROUP: "EL PASO CREW"})
    seen = {}
    from automations.b2b_dispositions import text_post as tp
    def fake(group, text, pngs, dry_run=True):
        seen["group"] = group
        return {"ok": True}

    monkeypatch.setattr(tp, "send_to_group", fake)
    SN.send([shot.name], dry_run=True, office_key="raf")
    assert seen["group"] == "EL PASO CREW"


def test_an_office_that_has_not_answered_sends_nowhere(shot, monkeypatch):
    """A fallback to the hardcoded group would put one office's board in
    another office's iMessage."""
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_NEITHER})
    res = SN.send([shot.name], dry_run=True, office_key="raf")
    assert res["ok"] is False
    assert "enrolment form" in res["not_sent"]


def test_alphalete_keeps_the_group_it_has_always_used(shot, monkeypatch):
    """Passing no office key must behave exactly as before: every caller
    that has not been taught about offices still works."""
    seen = {}
    from automations.b2b_dispositions import text_post as tp
    def fake(group, text, pngs, dry_run=True):
        seen["group"] = group
        return {"ok": True}

    monkeypatch.setattr(tp, "send_to_group", fake)
    SN.send([shot.name], dry_run=True)
    assert seen["group"] == SN.GROUP


def test_a_dry_run_posts_nothing_to_slack(shot, monkeypatch):
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_SLACK,
                           ES.COL_OBCL_CHANNEL: "C0AUAS88FGW"})
    from automations.shared import slack_metrics_post as SP
    monkeypatch.setattr(SP, "post_reply_with_image",
                        lambda *a, **k: pytest.fail("a dry run posted"))
    assert SN.send([shot.name], dry_run=True, office_key="raf")["dry_run"]


def test_a_dry_run_leaves_no_sent_marker(shot, monkeypatch):
    """Or the real send afterwards would think it had already gone."""
    _sheet(monkeypatch, **{ES.COL_OBCL_TO: ES.OBCL_SLACK,
                           ES.COL_OBCL_CHANNEL: "C0AUAS88FGW"})
    SN.send([shot.name], dry_run=True, office_key="raf")
    assert not shot.with_suffix(".sent").exists()
