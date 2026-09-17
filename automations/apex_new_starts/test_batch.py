"""The batch the card shows, and unticking from it."""
import json

from automations.apex_new_starts import batch, filler


PEOPLE = [
    {"name": "Paris Carroll", "find": "Carroll", "hire": "09/14/2026",
     "pages": {"profile": {"First Name": "Paris"}}},
    {"name": "Bailey Soda", "find": "Soda", "hire": "09/14/2026",
     "pages": {"profile": {"First Name": "Bailey"}}},
]


def _write(tmp_path, monkeypatch, people=PEOPLE):
    monkeypatch.setattr(batch, "PATH", tmp_path / ".apex-batch.json")
    batch.save(week="WE 9.20", build="Sep 17 16:12", notice="", start="2026-09-14",
               people=people)


def test_the_batch_follows_the_output_directory(tmp_path):
    """A hardcoded path in a module a test can reach is a path a test will
    write to: the suite put two people called "A" and "B" into the live batch
    and they turned up on the card (Megan, 2026-09-17)."""
    batch.save(week="WE 9.20", build="x", notice="", start="2026-09-14",
               people=PEOPLE, out_dir=tmp_path)
    assert (tmp_path / batch.NAME).exists()
    assert batch.load(tmp_path)["week"] == "WE 9.20"
    assert batch.names(tmp_path) == ["Paris Carroll", "Bailey Soda"]


def test_the_card_can_list_who_was_pulled(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch)
    assert batch.names() == ["Paris Carroll", "Bailey Soda"]
    assert batch.load()["week"] == "WE 9.20"


def test_unticking_rebuilds_the_setup_without_them(tmp_path, monkeypatch):
    """The whole reason the batch is kept: the board and Blue Ink are the slow
    half, so unticking must not pay for them again."""
    _write(tmp_path, monkeypatch)
    text = batch.setup_for(["Paris Carroll"])
    assert text and "Bailey Soda" in text
    assert "Paris Carroll" not in text
    assert text.startswith("(function(")


def test_unticking_everybody_gives_nothing_to_copy(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch)
    assert batch.setup_for(["Paris Carroll", "Bailey Soda"]) is None


def test_no_batch_yet_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "PATH", tmp_path / "nothing.json")
    assert batch.load() is None
    assert batch.names() == []
    assert batch.setup_for([]) is None


def test_a_social_is_never_in_the_batch(tmp_path, monkeypatch):
    """Socials are typed at run time and are in neither the setup nor this."""
    _write(tmp_path, monkeypatch)
    raw = (tmp_path / ".apex-batch.json").read_text()
    low = raw.lower()
    for word in ("ssn", "social"):
        assert word not in low, f"{word!r} has no business in the batch"
