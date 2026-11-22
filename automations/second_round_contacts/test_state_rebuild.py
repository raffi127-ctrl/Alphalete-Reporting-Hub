"""The memory of what this job created, read back off the account.

It was a local JSON file and nothing else, which is the only reason this
step still runs on Lucy 1 while the rest of onboarding moved to each
office's own computer. Started on a machine with no file, the audit removes
nobody and the adds put a second copy of everybody on the owner's phone.
"""
from __future__ import annotations

import datetime as dt

from automations.second_round_contacts import contacts as K
from automations.second_round_contacts import state as S


def _card(note, display="Ada Fournier (2R 10/31)", phone="+15550100001",
          email="Ada@x.com", rn="people/c1"):
    p = {"resourceName": rn, "names": [{"displayName": display}],
         "biographies": [{"value": note}]}
    if phone:
        p["phoneNumbers"] = [{"value": phone}]
    if email:
        p["emailAddresses"] = [{"value": email}]
    return p


# ------------------------------------------------- the note IS the contract

def test_a_card_this_job_wrote_reads_back_as_its_own_entry():
    """Built from what `note_for` and `display_name` actually produce, not
    from a string typed into a test -- if either changes its wording, the
    memory stops being readable and this is what says so."""
    day = dt.date(2026, 10, 31)
    a = {"first_name": "Ada", "last_name": "Fournier",
         "phone": "5550100001", "email": "ada@x.com"}
    note = K.note_for("Rafael Hidalgo", "11280", day)
    display = K.display_name(a, day)

    got = S.from_card(_card(note, display=display))
    assert got["owner"] == "Rafael Hidalgo"
    assert got["office"] == "11280"
    assert got["second_round"] == "2026-10-31"
    assert got["status"] == S.TRACKED
    assert got["resourceName"] == "people/c1"


def test_the_2r_tag_comes_off_before_the_name_is_split():
    """The card is named "Ada Fournier (2R 10/31)". Left on, every rebuilt
    person's surname is a date."""
    got = S.from_card(_card(K.note_for("Raf", "11280", dt.date(2026, 10, 31))))
    assert got["first_name"] == "Ada"
    assert got["last_name"] == "Fournier"


def test_the_key_matches_the_one_the_adds_dedupe_on():
    """A rebuilt entry nobody can find is the same as no entry: the REMOVED
    check in run_pass looks it up by this key."""
    got = S.from_card(_card(K.note_for("Raf", "11280", dt.date(2026, 10, 31))))
    assert S.key_for(got) == S.key_for({"phone": "5550100001"})


# ------------------------------------------------------- what it refuses

def test_a_card_we_did_not_write_is_not_ours():
    """The owner's own contacts are in the same account."""
    assert S.from_card(_card("Mum's mobile")) == {}


def test_an_unreadable_note_is_skipped_not_guessed():
    """A wrong second-round date takes a card off somebody's phone a
    fortnight early, so a note that will not parse yields nothing."""
    assert S.from_card(_card("2nd round sometime - Raf - second_round_contacts")) == {}
    assert S.from_card(_card("2nd round 31/31/2026 - Raf (AppStream 1) - "
                             "second_round_contacts")) == {}


def test_a_card_with_no_note_at_all_is_skipped():
    assert S.from_card({"resourceName": "people/c1",
                        "names": [{"displayName": "Ada"}]}) == {}


# ----------------------------------------------- a rebuild only fills a gap

def test_an_account_the_file_knows_is_never_rebuilt_over(monkeypatch, tmp_path):
    """The file carries statuses the cards cannot -- removed, kept, the
    reason and the date. A rebuild resets every one of them to tracked, so
    it must only ever run where there is nothing."""
    monkeypatch.setattr(S.C, "STATE_PATH", tmp_path / "state.json")
    S.save({"a@x.com": {"p:5550100001": {"status": S.REMOVED,
                                         "reason": "not hired"}}})
    called = []
    monkeypatch.setattr(S, "rebuild", lambda svc: called.append(1) or {})
    got = S.for_account("a@x.com", svc=object(), log=lambda *a: None)
    assert got["p:5550100001"]["status"] == S.REMOVED
    assert not called, "it rebuilt over a slice that already existed"


def test_an_account_with_nothing_is_rebuilt_and_remembered(monkeypatch, tmp_path):
    monkeypatch.setattr(S.C, "STATE_PATH", tmp_path / "state.json")
    entry = S.from_card(_card(K.note_for("Raf", "11280", dt.date(2026, 10, 31))))
    monkeypatch.setattr(S, "rebuild", lambda svc: {"p:5550100001": entry})
    got = S.for_account("a@x.com", svc=object(), log=lambda *a: None)
    assert got["p:5550100001"]["owner"] == "Raf"
    # and it is on disk, so the next pass does not re-read Contacts
    assert "a@x.com" in S.load()


def test_two_cards_for_one_person_collapse_to_one(monkeypatch):
    """Same person, two cards -- the key is what the adds dedupe on, so a
    second entry under the same key would be unreachable anyway."""
    note = K.note_for("Raf", "11280", dt.date(2026, 10, 31))
    monkeypatch.setattr(K, "ours",
                        lambda svc: [_card(note, rn="people/c1"),
                                     _card(note, rn="people/c2")])
    got = S.rebuild(object())
    assert list(got) == ["p:5550100001"]
    assert got["p:5550100001"]["resourceName"] == "people/c1"


def test_the_signature_is_what_makes_a_card_ours():
    """Matched on the note, not on the contact group: an owner who renames
    or empties "2nd Rounds" has not un-created the contacts."""
    assert K.SIGNATURE in K.note_for("Raf", "11280", dt.date(2026, 10, 31))


# ------------------------------------------- the probe cannot touch anybody

def test_check_rebuild_turns_write_off(monkeypatch, capsys):
    """The only way to queue this on Lucy 1 is through a handle whose
    base_args are ['--write'], so the probe always arrives as
    `--write --check-rebuild`. On a job that edits real people's phones,
    "it returns before the write" is not good enough on its own."""
    from automations.second_round_contacts import run as RUN

    seen = {}
    monkeypatch.setattr(RUN.R, "open_tab", lambda *a, **k: None)
    monkeypatch.setattr(RUN.R, "read", lambda *a, **k: [])
    monkeypatch.setattr(RUN, "check_rebuild",
                        lambda owners: seen.setdefault("ran", True) or 0)
    monkeypatch.setattr(RUN, "run_pass",
                        lambda *a, **k: seen.setdefault("wrote", True))
    monkeypatch.setattr(RUN, "run_audit",
                        lambda *a, **k: seen.setdefault("wrote", True))
    RUN.main(["--write", "--check-rebuild"])
    assert seen.get("ran") is True
    assert "wrote" not in seen, "a read-only probe reached a writing pass"
    assert "--write ignored" in capsys.readouterr().out
