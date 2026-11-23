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
    monkeypatch.setattr(RUN, "doctor",
                        lambda owners, **kw: seen.setdefault("ran", True) or 0)
    monkeypatch.setattr(RUN, "run_pass",
                        lambda *a, **k: seen.setdefault("wrote", True))
    monkeypatch.setattr(RUN, "run_audit",
                        lambda *a, **k: seen.setdefault("wrote", True))
    RUN.main(["--write", "--doctor"])
    assert seen.get("ran") is True
    assert "wrote" not in seen, "a read-only probe reached a writing pass"
    assert "--write ignored" in capsys.readouterr().out


# --------------------------- "I could not tell" is not "they are gone"

class _Resp:
    """Enough of an httplib2 response for HttpError to render itself."""
    def __init__(self, status):
        self.status = status
        self.reason = "test"


def _http(status):
    from googleapiclient.errors import HttpError
    return HttpError(_Resp(status), b"{}")


def _svc(err=None):
    class _Get:
        def execute(self_):
            if err:
                raise err
            return {"resourceName": "people/c1"}

    class _People:
        def get(self_, **kw):
            return _Get()

    class _Svc:
        def people(self_):
            return _People()
    return _Svc()


def test_a_404_means_the_card_is_gone():
    assert K.still_exists(_svc(_http(404)), "people/c1") is False


def test_a_rate_limit_raises_rather_than_saying_gone():
    """THE BUG. `_retry` gives up and raises after six 429s -- the read
    quota is 90/min/user -- and this used to answer False, which the audit
    reads as "already deleted by hand". It then marks the person REMOVED
    without deleting anything, and nothing ever looks at them again.

    Measured 2026-11-22: 22 on Raf's 143-card account, none on Cyrus's 20
    or Hasan's 24."""
    import pytest
    with pytest.raises(Exception):
        K.still_exists(_svc(_http(429)), "people/c1")


def test_a_server_error_raises_too():
    import pytest
    with pytest.raises(Exception):
        K.still_exists(_svc(_http(500)), "people/c1")


def test_a_card_that_is_there_says_so():
    assert K.still_exists(_svc(), "people/c1") is True


def test_a_card_re_created_under_a_new_id_is_found_by_key(monkeypatch):
    """A 404 on the stored id does not prove they are off the phone."""
    note = K.note_for("Raf", "11280", dt.date(2026, 10, 31))
    monkeypatch.setattr(K, "ours", lambda svc: [_card(note, rn="people/NEW")])
    assert K.find_ours(object(), "p:5550100001") == "people/NEW"


def test_somebody_really_gone_is_not_found(monkeypatch):
    monkeypatch.setattr(K, "ours", lambda svc: [])
    assert K.find_ours(object(), "p:5550100001") == ""


# ------------------------------------------ putting the stuck ones back

def _owner(account="a@x.com", name="Raf"):
    from automations.second_round_contacts import roster as RO
    o = RO.Owner.__new__(RO.Owner)
    object.__setattr__(o, "owner", name)
    object.__setattr__(o, "account", account)
    return o


def _stuck_state(tmp_path, monkeypatch, status):
    from automations.second_round_contacts import run as RUN
    monkeypatch.setattr(S.C, "STATE_PATH", tmp_path / "state.json")
    S.save({"a@x.com": {"p:5550100001": {"display": "Ada (2R 11/11)",
                                         "status": status,
                                         "removed": "2026-11-12",
                                         "reason": "not hired",
                                         "removed_rule": "week"}}})
    monkeypatch.setattr(RUN.K, "has_token", lambda a: True)
    monkeypatch.setattr(RUN.K, "service", lambda a: object())
    monkeypatch.setattr(RUN.S, "rebuild",
                        lambda svc: {"p:5550100001": {"display": "Ada"}})
    return RUN


def test_a_dry_run_changes_nothing(tmp_path, monkeypatch):
    RUN = _stuck_state(tmp_path, monkeypatch, S.REMOVED)
    RUN.unstick_removals([_owner()], write=False)
    assert S.load()["a@x.com"]["p:5550100001"]["status"] == S.REMOVED


def test_a_stuck_removal_goes_back_to_tracked(tmp_path, monkeypatch):
    """Back to tracked, NOT deleted from here. The audit's rules decide who
    comes off a phone and they have had a fortnight of new facts since;
    deleting from here would overrule them on 22 real people."""
    RUN = _stuck_state(tmp_path, monkeypatch, S.REMOVED)
    RUN.unstick_removals([_owner()], write=True)
    e = S.load()["a@x.com"]["p:5550100001"]
    assert e["status"] == S.TRACKED
    assert "removed" not in e and "removed_rule" not in e and "reason" not in e
    assert e["unstuck"]


def test_a_removal_that_really_happened_is_left_alone(tmp_path, monkeypatch):
    """Only a card still ON the account is stuck. Somebody genuinely
    deleted stays removed, or the audit would put them back on the phone."""
    from automations.second_round_contacts import run as RUN
    monkeypatch.setattr(S.C, "STATE_PATH", tmp_path / "state.json")
    S.save({"a@x.com": {"p:5550100001": {"display": "Ada", "status": S.REMOVED}}})
    monkeypatch.setattr(RUN.K, "has_token", lambda a: True)
    monkeypatch.setattr(RUN.K, "service", lambda a: object())
    monkeypatch.setattr(RUN.S, "rebuild", lambda svc: {})   # not on the account
    RUN.unstick_removals([_owner()], write=True)
    assert S.load()["a@x.com"]["p:5550100001"]["status"] == S.REMOVED


def test_a_kept_card_is_not_stuck(tmp_path, monkeypatch):
    """KEPT cards are supposed to still be there."""
    RUN = _stuck_state(tmp_path, monkeypatch, S.KEPT)
    RUN.unstick_removals([_owner()], write=True)
    assert S.load()["a@x.com"]["p:5550100001"]["status"] == S.KEPT


def test_a_per_owner_line_says_whose_LIST_not_who_was_removed(tmp_path,
                                                              monkeypatch,
                                                              capsys):
    """Megan read "Cyrus Wade: 91 marked removed" as Cyrus being removed --
    he started years ago and is an ICD. The owner names the reception
    account the applicants sit in, never a person in the list: this job only
    ever adds second-round applicants read off ApplicantStream."""
    RUN = _stuck_state(tmp_path, monkeypatch, S.REMOVED)
    RUN.unstick_removals([_owner(name="Cyrus Wade")], write=False)
    said = capsys.readouterr().out
    assert "Cyrus Wade's reception list" in said
    assert "applicants marked removed" in said
