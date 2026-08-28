"""--post must not touch Drive once the week is already posted.

Thu 2026-08-27: the bulletin for WE 8.23.26 was posted, approved by Evelyn and
mailed in the morning. The 19:00 pass still rebuilt the PDF and re-uploaded it,
hit a BrokenPipeError inside upload_pdf, exited 1, and opened a failure incident
for a report that had already gone out. post_review WAS idempotent -- it just
found that out one Drive round-trip too late.
"""
import pytest

from automations.override_bulletin import review_gate as G


def _explode(*a, **k):  # pragma: no cover - the point is that it never runs
    raise AssertionError("built/uploaded a PDF for a week already posted")


def test_post_skips_drive_when_already_posted(monkeypatch, capsys):
    monkeypatch.setattr(G, "_all_posts", lambda *a, **k: [{"ts": "1.0"}])
    monkeypatch.setattr(G, "build_preview", _explode)
    monkeypatch.setattr(G, "build_pdf", _explode)
    monkeypatch.setattr(G, "upload_pdf", _explode)
    monkeypatch.setattr(G, "post_review", _explode)

    assert G.main(["--post", "--date", "2026-08-27"]) == 0
    assert "already posted" in capsys.readouterr().out


def test_repost_still_rebuilds(monkeypatch):
    """--repost exists to replace the message, so it needs a fresh PDF."""
    monkeypatch.setattr(G, "_all_posts", lambda *a, **k: [{"ts": "1.0"}])
    monkeypatch.setattr(G, "build_preview",
                        lambda *a, **k: (["p"], {"weeks": ["8.23.26"]}))
    monkeypatch.setattr(G, "week_label", lambda *a, **k: "8.23.26")
    monkeypatch.setattr(G, "build_pdf", lambda *a, **k: "pdf")
    seen = {}
    monkeypatch.setattr(G, "upload_pdf", lambda *a, **k: seen.setdefault("up", True))
    monkeypatch.setattr(G, "post_review", lambda *a, **k: "1.0")

    assert G.main(["--post", "--repost", "--date", "2026-08-27"]) == 0
    assert seen.get("up") is True


def test_hold_still_wins_when_the_week_is_unposted(monkeypatch, capsys):
    """An unfilled tab must still HOLD, not post last week's column."""
    monkeypatch.setattr(G, "_all_posts", lambda *a, **k: [])
    monkeypatch.setattr(G, "build_preview",
                        lambda *a, **k: (["p"], {"weeks": ["8.16.26"]}))
    monkeypatch.setattr(G, "week_label", lambda *a, **k: "8.23.26")
    monkeypatch.setattr(G, "build_pdf", _explode)
    monkeypatch.setattr(G, "upload_pdf", _explode)
    monkeypatch.setattr(G, "post_review", _explode)

    assert G.main(["--post", "--date", "2026-08-27"]) == 0
    assert "HOLDING" in capsys.readouterr().out
