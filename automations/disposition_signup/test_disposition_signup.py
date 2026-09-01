"""Tests for the daily-dispositions sign-up: the record rules, the row it
materializes, and the per-office cadence/route/channel behaviour it unlocks in
gap_alerts.

PURE — no Sheets, no Slack, no Messages, no SMTP. Nothing here sends.

    .venv/bin/python -m pytest automations/disposition_signup/test_disposition_signup.py -q
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from automations.disposition_signup import apply as A, schema as S, store
from automations.gap_alerts import config as C, run as R


def _rec(**kw):
    base = dict(key="cody", owner="Cody Cannon", requested_by="Cody",
                cadence_min=60, deliver=["imessage"],
                imessage_group="Cody's Crew", campaign_key="att")
    base.update(kw)
    return S.DispositionRecord(**base)


# --- identity ---------------------------------------------------------------

def test_slug_from_first_name():
    assert S.slug_from("Cody Cannon") == "cody"
    assert S.slug_from("Jay-Ann O'Neill") == "jayann"
    assert S.slug_from("   ") == ""


# --- the owner's submission -------------------------------------------------

def test_clean_request_passes():
    assert S.validate_request(_rec()) == []


def test_a_route_is_required():
    probs = S.validate_request(_rec(deliver=[], imessage_group=""))
    assert any("at least one way" in p for p in probs)


def test_imessage_needs_a_group_name():
    probs = S.validate_request(_rec(imessage_group=""))
    assert any("group chat" in p for p in probs)


def test_email_route_needs_a_valid_address():
    assert any("at least one email" in p
               for p in S.validate_request(_rec(deliver=["email"],
                                                imessage_group="")))
    probs = S.validate_request(_rec(deliver=["email"], imessage_group="",
                                    email_to=["not-an-address"]))
    assert any("doesn't look like an email" in p for p in probs)


def test_slack_only_is_a_valid_signup():
    """Question 5 alone is an enrollment: some owners want the team channel and
    nothing on their own phone."""
    rec = _rec(deliver=[], imessage_group="", slack_hourly=True,
               slack_channel_name="#cody-sales")
    assert S.validate_request(rec) == []


def test_cadence_is_the_three_choices_raf_asked_for():
    assert S.CADENCE_CHOICES == [15, 30, 60]
    assert any("15 minutes" in p
               for p in S.validate_request(_rec(cadence_min=5)))


def test_a_name_that_already_gets_dispositions_is_refused():
    probs = S.validate_request(_rec(), existing_keys=["cody"])
    assert any("already gets the daily dispositions" in p for p in probs)


def test_parse_emails_splits_commas_and_newlines():
    assert S.parse_emails("a@b.com, c@d.com\ne@f.com") == [
        "a@b.com", "c@d.com", "e@f.com"]


# --- Megan's confirm --------------------------------------------------------

def test_key_must_be_a_legal_handle():
    assert any("lowercase" in p for p in S.validate(_rec(key="Cody Cannon")))


def test_shared_imessage_room_warns_but_does_not_block():
    """Calvin and Jay share ENERGY WELLS DOMINATION on purpose — a shared room
    is a thing to say out loud, not a thing to refuse."""
    rec = _rec(imessage_group="ENERGY WELLS DOMINATION", enabled=True)
    assert S.validate(rec, existing_groups={"energy wells domination": "calvin"}) == []
    warns = S.warnings(rec, existing_groups={"energy wells domination": "calvin"})
    assert any("already receives" in w for w in warns)


def test_office_access_gate_is_warned_about():
    assert any("switched OFF" in w for w in S.warnings(_rec(enabled=False)))


# --- the materialized row ---------------------------------------------------

def test_row_is_a_gap_alerts_office():
    row = A._row(_rec(cadence_min=30, deliver=["imessage", "email"],
                      email_to=["cody@example.com"], slack_hourly=True,
                      slack_channel_id="C0ABC12DE", enabled=True))
    assert row["key"] == "cody"
    assert row["ov"] == "impersonate"        # the login is never the enrollee
    assert row["campaign_id"] == "3"         # AT&T, the id gap_alerts pins
    assert row["cadence_min"] == 30
    assert row["deliver"] == ["imessage", "email"]
    assert row["email_to"] == ["cody@example.com"]
    assert row["slack_channel"] == "C0ABC12DE"
    assert row["label"] == "Cody"
    assert row["enabled"] is True


def test_dropping_the_text_route_clears_the_group():
    """A stale group name left on the row is one config edit away from texting
    a room the owner asked to be taken out of."""
    row = A._row(_rec(deliver=["email"], email_to=["c@d.com"]))
    assert row["group"] == ""


def test_pending_rows_are_never_materialized(monkeypatch, tmp_path):
    rows = [_rec(status="pending").to_json(),
            _rec(key="dana", owner="Dana Reed", status="wired",
                 enabled=True).to_json()]
    monkeypatch.setattr(store, "load_all", lambda: rows)
    monkeypatch.setattr(store, "existing_registry",
                        lambda exclude_key=None: {"keys": [], "groups": {}})
    plans = A.plan()
    assert [p["rec"].key for p in plans] == ["dana"]


def test_apply_writes_the_json_it_prints(monkeypatch, tmp_path, capsys):
    out = tmp_path / "onboarded_offices.json"
    monkeypatch.setattr(A, "ONBOARDED_JSON", out)
    monkeypatch.setattr(A, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(store, "load_all",
                        lambda: [_rec(status="wired", enabled=True).to_json()])
    monkeypatch.setattr(store, "existing_registry",
                        lambda exclude_key=None: {"keys": [], "groups": {}})
    assert A.main([]) == 0
    assert not out.exists()                  # dry-run writes nothing
    assert A.main(["--write"]) == 0
    assert [r["key"] for r in json.loads(out.read_text())] == ["cody"]


def test_store_tolerates_an_unknown_column():
    rec = store.record_from_json({"key": "cody", "owner": "Cody Cannon",
                                  "_derived": {"x": 1}, "future_field": "?"})
    assert rec.key == "cody"


# --- what the row does inside gap_alerts ------------------------------------

def test_config_merges_onboarded_rows(monkeypatch, tmp_path):
    p = tmp_path / "onboarded_offices.json"
    p.write_text(json.dumps([{"key": "cody", "name": "Cody Cannon",
                              "cadence_min": 30},
                             {"key": "rafael", "name": "NOT RAF"}]))
    monkeypatch.setattr(C, "ONBOARDED_JSON", p)
    monkeypatch.setattr(C, "OFFICES", [dict(C.RAF)])
    C._merge_onboarded()
    keys = [o["key"] for o in C.OFFICES]
    assert keys == ["rafael", "cody"]        # hardcoded key always wins
    assert C.OFFICES[0]["name"] == "Rafael Hidalgo"


def test_a_broken_onboarded_file_does_not_take_the_report_down(monkeypatch,
                                                               tmp_path):
    p = tmp_path / "onboarded_offices.json"
    p.write_text("{ not json")
    monkeypatch.setattr(C, "ONBOARDED_JSON", p)
    monkeypatch.setattr(C, "OFFICES", [dict(C.RAF)])
    C._merge_onboarded()                     # must not raise
    assert [o["key"] for o in C.OFFICES] == ["rafael"]


@pytest.mark.parametrize("cadence,minute,due", [
    (15, 0, True), (15, 15, True), (15, 30, True), (15, 45, True),
    (30, 0, True), (30, 15, False), (30, 30, True), (30, 45, False),
    (60, 0, True), (60, 15, False), (60, 30, False), (60, 45, False),
])
def test_cadence_due_on_the_quarter_hour(cadence, minute, due):
    now = dt.datetime(2026, 9, 1, 14, minute)
    assert R._cadence_due({"cadence_min": cadence}, now) is due


@pytest.mark.parametrize("drift", [0, 1, 2, 9, 14])
def test_cadence_survives_the_wrapper_drift(drift):
    """The tick fires on the quarter hour but Python reads the clock a minute
    or three later. Anchoring on the raw minute would make an hourly office
    due never."""
    now = dt.datetime(2026, 9, 1, 14, drift)
    assert R._cadence_due({"cadence_min": 60}, now) is True


def test_hardcoded_offices_keep_every_tick():
    """No cadence_min on a hardcoded row = TICK_MINUTES = due every tick, which
    is what Raf has had since August."""
    for m in (0, 15, 30, 45):
        assert R._cadence_due(C.office("rafael"), dt.datetime(2026, 9, 1, 14, m))


def test_delivery_default_for_hardcoded_offices():
    """Rows written before the form existed have no `deliver` key and are all
    iMessage-only — adding the field must not silently start emailing them."""
    assert C.delivers(C.office("rafael"), "imessage") is True
    assert C.delivers(C.office("rafael"), "email") is False


def test_slack_channel_never_silently_defaults_for_an_enrolled_office():
    """The module default is Raf's org's room; an enrolled office bringing its
    own channel must use it."""
    assert C.slack_channel_for({"slack_channel": "C0ABC12DE"}) == "C0ABC12DE"
    assert C.slack_channel_for({}) == C.SLACK_HOURLY_CHANNEL


# --- the email leg ----------------------------------------------------------

def test_email_subject_carries_office_campaign_and_clock():
    from automations.gap_alerts import email_send as E
    subj = E.subject_for({"label": "Cody", "campaign_label": "AT&T"},
                         "4:45 PM", dt.date(2026, 9, 1))
    assert "Cody" in subj and "AT&T" in subj and "4:45 PM" in subj


def test_email_send_without_addresses_is_a_skip_not_a_crash():
    from automations.gap_alerts import email_send as E
    assert E.send({"email_to": []}, [], "body", "4:45 PM",
                  dt.date(2026, 9, 1), dry_run=True)["skipped"]


def test_email_dry_run_builds_but_sends_nothing(tmp_path):
    from automations.gap_alerts import email_send as E
    png = tmp_path / "board.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    res = E.send({"label": "Cody", "email_to": ["cody@example.com"]},
                 [png], "Rep - 20 min", "4:45 PM", dt.date(2026, 9, 1),
                 dry_run=True)
    assert res["dry_run"] and res["to"] == ["cody@example.com"]
    assert res["attachments"] == ["board.png"]


# --- when + where the field is ----------------------------------------------

def test_hours_default_to_the_org_window():
    rec = _rec()
    assert rec.tz == "America/Chicago"
    assert rec.hours_label().startswith("Mon-Fri 1:30 PM-10:00 PM")


def test_end_before_start_is_refused():
    probs = S.validate_request(_rec(day_start="22:00", day_end="13:30"))
    assert any("after the start time" in p for p in probs)


def test_unsupported_timezone_is_refused():
    """Pacific is not offered — the wrapper's Central hour gate can't reach a
    Pacific 10pm, and a silently clipped last hour is worse than a no."""
    assert "America/Los_Angeles" not in [z["tz"] for z in S.TIMEZONES]
    assert any("time zone" in p
               for p in S.validate_request(_rec(tz="America/Los_Angeles")))


def test_only_non_default_hours_ride_into_the_row():
    """An office that asked for nothing special keeps inheriting the org
    default, instead of freezing today's default into its row."""
    assert "tz" not in A._row(_rec())
    assert "day_start" not in A._row(_rec())
    row = A._row(_rec(tz="America/New_York", day_end="20:00", saturday=False))
    assert row["tz"] == "America/New_York"
    assert row["day_end"] == "20:00"
    assert row["weekdays"] == [0, 1, 2, 3, 4]


def test_office_name_falls_back_to_the_owner():
    assert A._row(_rec())["name"] == "Cody Cannon"
    assert A._row(_rec(knocks_office="Cannon Group LLC"))["name"] == \
        "Cannon Group LLC"
    assert A._row(_rec(knocks_office="Cannon Group LLC"))["owner"] == \
        "Cody Cannon"


def test_eastern_office_runs_on_its_own_clock():
    """21:30 in Texas is 22:30 in Boston — past a 10pm field day."""
    east = {"key": "e", "tz": "America/New_York"}
    assert C.in_office_window(east, dt.datetime(2026, 9, 1, 19, 0)) is True
    assert C.in_office_window(east, dt.datetime(2026, 9, 1, 21, 30)) is False
    # ...and the same instant is still inside a Central office's day.
    assert C.in_office_window({"key": "c"}, dt.datetime(2026, 9, 1, 21, 30))


def test_the_card_is_stamped_in_the_offices_own_clock():
    n = dt.datetime(2026, 9, 1, 20, 45)
    assert C.slot_label_for({"key": "c"}, n) == "8:45 PM"
    assert C.slot_label_for({"tz": "America/New_York"}, n) == "9:45 PM EST"


def test_saturday_keeps_its_own_start_and_end():
    sat = dt.datetime(2026, 9, 5, 11, 0)             # a Saturday, 11am
    assert sat.weekday() == C.SATURDAY
    assert C.in_office_window({"key": "c"}, sat) is True        # Sat opens 10:45
    assert C.in_office_window({"key": "c"},
                              dt.datetime(2026, 9, 4, 11, 0)) is False  # Fri


def test_an_office_that_skips_saturday_is_off_on_saturday():
    cfg = A._row(_rec(saturday=False))
    assert C.office_window(cfg, C.SATURDAY) is None


def test_sunday_is_off_for_everyone():
    sun = dt.datetime(2026, 9, 6, 15, 0)
    assert sun.weekday() == 6
    assert C.in_office_window({"key": "c"}, sun) is False
    assert C.in_office_window({"key": "e", "tz": "America/New_York"},
                              sun) is False


def test_a_broken_time_string_falls_back_instead_of_raising():
    """A typo in one office's row must not take the whole report down."""
    assert C.office_window({"day_start": "nope"}, 0)[0] == C.DAY_START_HHMM


# --- preflight --------------------------------------------------------------

def test_preflight_refuses_a_row_that_is_still_pending(monkeypatch):
    from automations.disposition_signup import preflight as P
    monkeypatch.setattr(store, "load_one",
                        lambda k: _rec(status="pending").to_json())
    res = P.check("cody")
    assert res["ok"] is False
    assert "confirm it on the form first" in res["checks"][0]["note"]


def test_preflight_passes_and_reports_both_checks(monkeypatch):
    from automations.disposition_signup import preflight as P
    monkeypatch.setattr(store, "load_one",
                        lambda k: _rec(status="wired").to_json())
    monkeypatch.setattr(P, "_check_group",
                        lambda rec: {"name": "iMessage group", "ok": True,
                                     "note": "resolved (7 participants)"})
    monkeypatch.setattr(P, "_check_board",
                        lambda rec, day, headless=True: {
                            "name": "Office Access + campaign", "ok": True,
                            "note": "impersonated OK — 12 rep row(s) pulled"})
    res = P.check("cody")
    assert res["ok"] is True
    assert "READY" in P.summary("cody", res)


def test_preflight_failure_leaves_the_office_off(monkeypatch):
    from automations.disposition_signup import preflight as P
    monkeypatch.setattr(store, "load_one",
                        lambda k: _rec(status="wired").to_json())
    monkeypatch.setattr(P, "_check_group",
                        lambda rec: {"name": "iMessage group", "ok": True,
                                     "note": "ok"})
    monkeypatch.setattr(P, "_check_board",
                        lambda rec, day, headless=True: {
                            "name": "Office Access + campaign", "ok": False,
                            "note": "GroupTextError: no such office"})
    res = P.check("cody")
    assert res["ok"] is False
    assert res["rec"].enabled is False
    assert "NOT READY" in P.summary("cody", res)


def test_preflight_skips_the_chat_check_for_an_email_only_office(monkeypatch):
    from automations.disposition_signup import preflight as P
    rec = _rec(deliver=["email"], email_to=["c@d.com"], imessage_group="")
    out = P._check_group(rec)
    assert out["ok"] is True and "skipped" in out["note"]
