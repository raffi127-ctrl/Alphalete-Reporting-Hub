"""Tests for the daily-dispositions sign-up: the record rules, the row it
materializes, and the per-destination cadence/window behaviour it unlocks in
gap_alerts.

PURE — no Sheets, no Slack, no Messages, no SMTP. Nothing here sends.

    .venv/bin/python -m pytest automations/disposition_signup/ -q
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from automations.disposition_signup import apply as A, schema as S, store
from automations.gap_alerts import config as C, run as R


def _dest(kind="imessage", **kw):
    kw.setdefault("name", "Cody's Crew" if kind == "imessage" else "")
    return S.destination(kind, **kw)


def _rec(**kw):
    base = dict(key="cody", owner="Cody Cannon", requested_by="Cody",
                knocks_office="", ov_account="22901",
                destinations=[_dest("imessage", cadence_min=15)],
                campaign_key="att")
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


def test_a_destination_is_required():
    probs = S.validate_request(_rec(destinations=[]))
    assert any("at least one place" in p for p in probs)


def test_imessage_needs_a_chat_name():
    probs = S.validate_request(_rec(destinations=[_dest("imessage", name="")]))
    assert any("group chat" in p for p in probs)


def test_slack_needs_a_channel():
    probs = S.validate_request(_rec(destinations=[_dest("slack")]))
    assert any("Slack channel" in p for p in probs)


def test_email_needs_a_valid_address():
    assert any("at least one email" in p
               for p in S.validate_request(_rec(destinations=[_dest("email")])))
    probs = S.validate_request(_rec(destinations=[
        _dest("email", emails=["not-an-address"])]))
    assert any("doesn't look like an email" in p for p in probs)


def test_the_same_room_twice_is_refused():
    """Two identical rows are two identical boards arriving together."""
    probs = S.validate_request(_rec(destinations=[
        _dest("imessage", name="Owners"), _dest("imessage", name="owners")]))
    assert any("listed twice" in p for p in probs)


def test_many_destinations_each_with_its_own_cadence():
    rec = _rec(destinations=[
        _dest("imessage", name="Owners", cadence_min=15),
        _dest("slack", name="#reps", channel_id="C1", cadence_min=60),
        _dest("email", emails=["c@d.com"], cadence_min=30)])
    assert S.validate_request(rec) == []
    assert rec.cadence_label() == ("every 15 minutes / every 30 minutes / "
                                   "once an hour")
    assert len(rec.routes()) == 3


def test_cadence_is_the_three_choices_raf_asked_for():
    assert S.CADENCE_CHOICES == [15, 30, 60]
    assert any("How often" in p or "how often" in p
               for p in S.validate_request(_rec(destinations=[
                   _dest("imessage", cadence_min=5)])))


def test_a_name_that_already_gets_dispositions_is_refused():
    probs = S.validate_request(_rec(), existing_keys=["cody"])
    assert any("already gets the daily dispositions" in p for p in probs)


def test_parse_emails_splits_commas_and_newlines():
    assert S.parse_emails("a@b.com, c@d.com\ne@f.com") == [
        "a@b.com", "c@d.com", "e@f.com"]


# --- every campaign is offered ---------------------------------------------

def test_all_campaigns_are_offered_with_proven_ids():
    by_key = {c["key"]: c["id"] for c in S.CAMPAIGNS}
    assert by_key["att"] == "3"          # RES AT&T
    assert by_key["energy"] == "40"      # RES-ENERGYWELL
    assert by_key["b2b_att"] == "2"      # B2B AT&T SBS
    assert by_key["b2b_box"] == "16"     # B2B-BOX-Energy


def test_nds_carries_no_pin():
    """A wireless/NDS owner has no Disposition campaign today, so there is
    nothing to pin — and an empty id means 'whatever impersonation lands on'."""
    assert S.campaign("nds")["id"] == ""
    assert A._row(_rec(campaign_key="nds"))["campaign_id"] == ""


# --- Megan's confirm --------------------------------------------------------

def test_key_must_be_a_legal_handle():
    assert any("lowercase" in p for p in S.validate(_rec(key="Cody Cannon")))


def test_shared_imessage_room_warns_but_does_not_block():
    """Calvin and Jay both text ENERGY WELLS DOMINATION on purpose."""
    rec = _rec(destinations=[_dest("imessage", name="ENERGY WELLS DOMINATION")],
               enabled=True)
    groups = {"energy wells domination": "calvin"}
    assert S.validate(rec, existing_groups=groups) == []
    assert any("already receives" in w
               for w in S.warnings(rec, existing_groups=groups))


def test_office_access_gate_is_warned_about():
    assert any("switched OFF" in w for w in S.warnings(_rec(enabled=False)))


# --- the materialized row ---------------------------------------------------

def test_row_is_a_gap_alerts_office():
    row = A._row(_rec(enabled=True, destinations=[
        _dest("imessage", name="Owners", cadence_min=30),
        _dest("slack", name="#reps", channel_id="C0ABC12DE", cadence_min=60)]))
    assert row["key"] == "cody"
    assert row["ov"] == "impersonate"        # the login is never the enrollee
    assert row["campaign_id"] == "3"         # AT&T, the id gap_alerts pins
    assert row["label"] == "Cody"
    assert row["enabled"] is True
    assert [d["kind"] for d in row["destinations"]] == ["imessage", "slack"]
    assert row["destinations"][0]["cadence_min"] == 30
    # The legacy single-group field stays empty for a form-built office, so the
    # runner reads destinations and never the fallback.
    assert row["group"] == ""


def test_office_name_falls_back_to_the_owner():
    assert A._row(_rec())["name"] == "Cody Cannon"
    assert A._row(_rec(knocks_office="Cannon Group LLC"))["name"] == \
        "Cannon Group LLC"
    assert A._row(_rec(knocks_office="Cannon Group LLC"))["owner"] == \
        "Cody Cannon"


def test_pending_rows_are_never_materialized(monkeypatch):
    rows = [_rec(status="pending").to_json(),
            _rec(key="dana", owner="Dana Reed", status="wired",
                 enabled=True).to_json()]
    monkeypatch.setattr(store, "load_all", lambda: rows)
    monkeypatch.setattr(store, "existing_registry",
                        lambda exclude_key=None: {"keys": [], "groups": {}})
    assert [p["rec"].key for p in A.plan()] == ["dana"]


def test_apply_writes_the_json_it_prints(monkeypatch, tmp_path):
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
    p.write_text(json.dumps([{"key": "cody", "name": "Cody Cannon"},
                             {"key": "rafael", "name": "NOT RAF"}]))
    monkeypatch.setattr(C, "ONBOARDED_JSON", p)
    monkeypatch.setattr(C, "OFFICES", [dict(C.RAF)])
    C._merge_onboarded()
    assert [o["key"] for o in C.OFFICES] == ["rafael", "cody"]
    assert C.OFFICES[0]["name"] == "Rafael Hidalgo"   # hardcoded key wins


def test_a_broken_onboarded_file_does_not_take_the_report_down(monkeypatch,
                                                               tmp_path):
    p = tmp_path / "onboarded_offices.json"
    p.write_text("{ not json")
    monkeypatch.setattr(C, "ONBOARDED_JSON", p)
    monkeypatch.setattr(C, "OFFICES", [dict(C.RAF)])
    C._merge_onboarded()                     # must not raise
    assert [o["key"] for o in C.OFFICES] == ["rafael"]


# --- destinations, inside the engine ----------------------------------------

def test_hardcoded_offices_translate_to_the_destinations_they_always_had():
    """Raf: his chat every tick + the org channel hourly. Calvin: chat only.
    Nothing about their sends may change."""
    raf = C.destinations(C.office("rafael"))
    assert [d["kind"] for d in raf] == ["imessage", "slack"]
    assert raf[0]["name"] == "Alphalete Partners"
    assert raf[0]["cadence_min"] == C.TICK_MINUTES
    assert raf[1]["channel_id"] == C.SLACK_HOURLY_CHANNEL
    assert raf[1]["cadence_min"] == 60
    assert [d["kind"] for d in C.destinations(C.office("calvin"))] == ["imessage"]


@pytest.mark.parametrize("cadence,minute,due", [
    (15, 0, True), (15, 15, True), (15, 30, True), (15, 45, True),
    (30, 0, True), (30, 15, False), (30, 30, True), (30, 45, False),
    (60, 0, True), (60, 15, False), (60, 30, False), (60, 45, False),
])
def test_destination_due_on_the_quarter_hour(cadence, minute, due):
    now = dt.datetime(2026, 9, 1, 14, minute)
    assert R._dest_due({"cadence_min": cadence}, now) is due


@pytest.mark.parametrize("drift", [0, 1, 2, 3, 4])
def test_cadence_survives_the_wrapper_drift(drift):
    """The wrapper launches within a minute of a 5-minute boundary and Python
    reads the clock seconds later. Anchoring on the RAW minute would make an
    hourly destination due never; anchoring on the wake boundary absorbs the
    whole launch window with room to spare."""
    assert R._dest_due({"cadence_min": 60},
                       dt.datetime(2026, 9, 1, 14, drift)) is True


def test_two_destinations_can_disagree_about_now():
    """The whole point: the owners' chat every 15 minutes, the rep channel
    hourly, from one office and one pull."""
    fast = {"kind": "imessage", "cadence_min": 15}
    slow = {"kind": "slack", "cadence_min": 60}
    at_15 = dt.datetime(2026, 9, 1, 14, 15)
    assert R._dest_due(fast, at_15) and not R._dest_due(slow, at_15)
    at_00 = dt.datetime(2026, 9, 1, 14, 0)
    assert R._dest_due(fast, at_00) and R._dest_due(slow, at_00)


def test_a_nonsense_cadence_falls_back_to_the_tick():
    """20 does not divide 60; the wrapper would fire it at :00 and then not
    again until the next :00."""
    assert C.dest_cadence({"cadence_min": 20}) == C.TICK_MINUTES
    assert C.dest_cadence({"cadence_min": "x"}) == C.TICK_MINUTES
    assert C.dest_cadence({}) == C.TICK_MINUTES
    assert C.dest_cadence({"cadence_min": 60}) == 60


def test_a_slack_destination_never_inherits_another_orgs_room():
    """SLACK_HOURLY_CHANNEL is Raf's org's channel; a form destination with no
    id posts nowhere rather than there."""
    assert C.dest_channel({"kind": "slack", "channel_id": "C0ABC12DE"}) == \
        "C0ABC12DE"
    assert C.dest_channel({"kind": "slack"}) == ""


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
    assert "tz" not in A._row(_rec())
    assert "day_start" not in A._row(_rec())
    row = A._row(_rec(tz="America/New_York", day_end="20:00", saturday=False))
    assert row["tz"] == "America/New_York"
    assert row["day_end"] == "20:00"
    assert row["weekdays"] == [0, 1, 2, 3, 4]


def test_eastern_office_runs_on_its_own_clock():
    east = {"key": "e", "tz": "America/New_York"}
    assert C.in_office_window(east, dt.datetime(2026, 9, 1, 19, 0)) is True
    assert C.in_office_window(east, dt.datetime(2026, 9, 1, 21, 30)) is False
    assert C.in_office_window({"key": "c"}, dt.datetime(2026, 9, 1, 21, 30))


def test_the_card_is_stamped_in_the_offices_own_clock():
    n = dt.datetime(2026, 9, 1, 20, 45)
    assert C.slot_label_for({"key": "c"}, n) == "8:45 PM"
    assert C.slot_label_for({"tz": "America/New_York"}, n) == "9:45 PM EST"


def test_saturday_keeps_its_own_start_and_end():
    sat = dt.datetime(2026, 9, 5, 11, 0)
    assert sat.weekday() == C.SATURDAY
    assert C.in_office_window({"key": "c"}, sat) is True
    assert C.in_office_window({"key": "c"},
                              dt.datetime(2026, 9, 4, 11, 0)) is False


def test_an_office_that_skips_saturday_is_off_on_saturday():
    assert C.office_window(A._row(_rec(saturday=False)), C.SATURDAY) is None


def test_sunday_is_off_for_everyone():
    sun = dt.datetime(2026, 9, 6, 15, 0)
    assert sun.weekday() == 6
    assert C.in_office_window({"key": "c"}, sun) is False
    assert C.in_office_window({"key": "e", "tz": "America/New_York"},
                              sun) is False


def test_a_broken_time_string_falls_back_instead_of_raising():
    assert C.office_window({"day_start": "nope"}, 0)[0] == C.DAY_START_HHMM


# --- preflight --------------------------------------------------------------

def test_preflight_refuses_a_row_that_is_still_pending(monkeypatch):
    from automations.disposition_signup import preflight as P
    monkeypatch.setattr(store, "load_one",
                        lambda k: _rec(status="pending").to_json())
    res = P.check("cody")
    assert res["ok"] is False
    assert "confirm it on the form first" in res["checks"][0]["note"]


def test_preflight_checks_every_chat_not_just_one(monkeypatch):
    from automations.disposition_signup import preflight as P
    rec = _rec(status="wired", destinations=[
        _dest("imessage", name="Owners"), _dest("imessage", name="Leaders")])
    monkeypatch.setattr(store, "load_one", lambda k: rec.to_json())
    seen = []

    def _fake_resolve(name):
        seen.append(name)
        if name == "Leaders":
            raise RuntimeError("no iMessage group named 'Leaders'")
        return {"name": name, "participants": 7}

    import automations.b2b_dispositions.text_post as tp
    monkeypatch.setattr(tp, "resolve_group", _fake_resolve)
    monkeypatch.setattr(P, "_check_board",
                        lambda rec, day, headless=True: {
                            "name": "Office Access + campaign", "ok": True,
                            "note": "ok"})
    res = P.check("cody")
    assert seen == ["Owners", "Leaders"]
    assert res["ok"] is False                 # one bad room fails the preflight
    assert "NOT READY" in P.summary("cody", res)


def test_preflight_passes_and_reports_both_checks(monkeypatch):
    from automations.disposition_signup import preflight as P
    monkeypatch.setattr(store, "load_one",
                        lambda k: _rec(status="wired").to_json())
    monkeypatch.setattr(P, "_check_groups",
                        lambda rec: [{"name": "iMessage 'Cody's Crew'",
                                      "ok": True, "note": "resolved (7)"}])
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
    monkeypatch.setattr(P, "_check_groups",
                        lambda rec: [{"name": "iMessage", "ok": True,
                                      "note": "ok"}])
    monkeypatch.setattr(P, "_check_board",
                        lambda rec, day, headless=True: {
                            "name": "Office Access + campaign", "ok": False,
                            "note": "no such office"})
    res = P.check("cody")
    assert res["ok"] is False and res["rec"].enabled is False


def test_preflight_skips_the_chat_check_for_an_email_only_office():
    from automations.disposition_signup import preflight as P
    rec = _rec(destinations=[_dest("email", emails=["c@d.com"])])
    out = P._check_groups(rec)
    assert len(out) == 1 and out[0]["ok"] and "skipped" in out[0]["note"]


# --- the email leg ----------------------------------------------------------

def test_email_subject_carries_office_campaign_and_clock():
    from automations.gap_alerts import email_send as E
    subj = E.subject_for({"label": "Cody", "campaign_label": "AT&T"},
                         "4:45 PM", dt.date(2026, 9, 1))
    assert "Cody" in subj and "AT&T" in subj and "4:45 PM" in subj


def test_email_send_without_addresses_is_a_skip_not_a_crash():
    from automations.gap_alerts import email_send as E
    assert E.send({}, [], "body", "4:45 PM", dt.date(2026, 9, 1),
                  to_addrs=[], dry_run=True)["skipped"]


def test_email_goes_to_that_destinations_addresses(tmp_path):
    from automations.gap_alerts import email_send as E
    png = tmp_path / "board.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    res = E.send({"label": "Cody", "email_to": ["office@example.com"]},
                 [png], "Rep - 20 min", "4:45 PM", dt.date(2026, 9, 1),
                 to_addrs=["cody@example.com"], dry_run=True)
    assert res["to"] == ["cody@example.com"]     # the destination's, not the office's
    assert res["attachments"] == ["board.png"]


# --- the waiting list -------------------------------------------------------

def test_every_campaign_is_offered_grouped_by_family():
    assert [c["key"] for c in S.campaigns_in("D2D")] == ["att", "energy", "nds"]
    assert [c["key"] for c in S.campaigns_in("B2B")] == ["b2b_att", "b2b_box"]


def test_coming_soon_is_only_nds():
    assert S.campaign_live("att") and S.campaign_live("b2b_box")
    assert not S.campaign_live("nds")
    assert "(coming soon)" in S.campaign_choice_label("nds")
    assert "(coming soon)" not in S.campaign_choice_label("att")


def test_a_waiting_list_signup_is_still_a_valid_submission():
    """The whole point: they enroll once, now, and we hold it."""
    assert S.validate_request(_rec(campaign_key="nds")) == []
    assert S.validate(_rec(campaign_key="nds", enabled=True)) == []


def test_apply_refuses_to_wire_a_waiting_list_office(monkeypatch, capsys):
    """Wiring it would put an office in the run that fails every single tick —
    there is nothing in OwnerVille to pull."""
    monkeypatch.setattr(store, "load_all",
                        lambda: [_rec(campaign_key="nds", status="wired",
                                      enabled=True).to_json()])
    monkeypatch.setattr(store, "existing_registry",
                        lambda exclude_key=None: {"keys": [], "groups": {}})
    assert A.plan() == []
    assert "WAITING LIST" in capsys.readouterr().out


def test_a_live_campaign_still_wires(monkeypatch):
    monkeypatch.setattr(store, "load_all",
                        lambda: [_rec(campaign_key="b2b_att", status="wired",
                                      enabled=True).to_json()])
    monkeypatch.setattr(store, "existing_registry",
                        lambda exclude_key=None: {"keys": [], "groups": {}})
    plans = A.plan()
    assert [p["rec"].key for p in plans] == ["cody"]
    assert plans[0]["row"]["campaign_id"] == "2"       # B2B AT&T SBS


def test_the_ping_says_waiting_list_in_its_one_line():
    from automations.disposition_signup import request_notify as RN
    live_title, _ = RN._lines(_rec(campaign_key="att"))
    wait_title, _ = RN._lines(_rec(campaign_key="nds"))
    assert "WAITING LIST" not in live_title
    assert "WAITING LIST" in wait_title


# --- fixed times (Cody's schedule) ------------------------------------------

def test_cody_slots_come_from_the_module_that_already_posts_them():
    from automations.knocks_intraday.schedule import SLOTS
    assert S.CODY_SLOTS == ["%02d:%02d" % (s.hour, s.minute) for s in SLOTS]
    assert S.CODY_SLOTS == ["14:00", "17:15", "21:00"]


def test_set_times_is_offered_alongside_the_intervals():
    assert S.CADENCE_PICKER == [15, 30, 60, S.SLOT_CADENCE]
    assert "Set times" in S.cadence_picker_label(S.SLOT_CADENCE)
    assert "Money Lap 5:15 PM" in S.cadence_picker_label(S.SLOT_CADENCE)


def test_a_set_times_destination_carries_its_slots():
    d = S.destination("imessage", name="Crew", cadence_min=S.SLOT_CADENCE)
    assert d["slots"] == ["14:00", "17:15", "21:00"]
    assert S.validate_request(_rec(destinations=[d])) == []
    assert "Money Lap" in S.dest_label(d)


def test_an_off_quarter_slot_is_refused():
    """The job only wakes on the quarter hour, so 5:20 would never fire."""
    d = S.destination("imessage", name="Crew", cadence_min=S.SLOT_CADENCE,
                      slots=["17:20"])
    assert any("quarter hour" in p
               for p in S.validate_request(_rec(destinations=[d])))


def test_zero_is_a_real_cadence_not_a_missing_one():
    """`cadence_min or 15` reads 0 as unset and turns three boards a day into
    ninety — the bug this test exists to keep dead."""
    d = {"kind": "imessage", "cadence_min": 0, "slots": ["14:00"]}
    assert C.dest_cadence(d) == 0
    assert C.dest_slots(d) == ["14:00"]
    assert C.dest_cadence({}) == C.TICK_MINUTES        # genuinely unset


def test_set_times_fires_only_at_its_slots():
    d = {"kind": "imessage", "cadence_min": 0,
         "slots": ["14:00", "17:15", "21:00"]}
    for hh, mm, due in [(13, 45, False), (14, 0, True), (14, 2, True),
                        (17, 15, True), (21, 0, True), (21, 30, False)]:
        assert R._dest_due(d, dt.datetime(2026, 9, 1, hh, mm)) is due


def test_set_times_uses_the_offices_own_clock():
    """A 2 PM 'first knocks' board is about 2 PM where the reps are — the same
    rule knocks_intraday follows for the four Eastern offices."""
    d = {"kind": "imessage", "cadence_min": 0, "slots": ["14:00"]}
    east = {"tz": "America/New_York"}
    assert R._dest_due(d, dt.datetime(2026, 9, 1, 13, 0), cfg=east) is True
    assert R._dest_due(d, dt.datetime(2026, 9, 1, 14, 0), cfg=east) is False


# --- never two of the same board --------------------------------------------

def test_a_channel_already_on_the_intraday_roster_is_not_double_posted():
    """knocks_intraday posts End of Day to every enrolled channel. An office
    that also enrolls HERE for a 9 PM Slack post must get one board, not two
    (Megan 2026-09-01: "they should only get 1")."""
    from automations.knocks_intraday import roster as ros
    chan = ros.enrolled("eod")[0].channel_id
    dest = {"kind": "slack", "channel_id": chan, "cadence_min": 60}
    assert R._intraday_covers(dest, {}, dt.datetime(2026, 9, 1, 21, 0)) is True
    # ...and only at that moment. The rest of the day is ours to post.
    assert R._intraday_covers(dest, {}, dt.datetime(2026, 9, 1, 19, 0)) is False


def test_a_channel_nobody_else_posts_to_is_left_alone():
    dest = {"kind": "slack", "channel_id": "C0BRANDNEW", "cadence_min": 60}
    assert R._intraday_covers(dest, {}, dt.datetime(2026, 9, 1, 21, 0)) is False


def test_texts_and_email_are_never_deduped():
    """knocks_intraday only posts to Slack — an owner's chat is not a duplicate
    of anything."""
    for kind in ("imessage", "email"):
        assert R._intraday_covers({"kind": kind, "name": "Crew"}, {},
                                  dt.datetime(2026, 9, 1, 21, 0)) is False


def test_dedupe_respects_the_offices_own_clock():
    """An Eastern office's 9 PM is 8 PM Central — the duplicate happens on
    THEIR clock, which is the clock knocks_intraday fires on too."""
    from automations.knocks_intraday import roster as ros
    chan = ros.enrolled("eod")[0].channel_id
    dest = {"kind": "slack", "channel_id": chan, "cadence_min": 60}
    east = {"tz": "America/New_York"}
    assert R._intraday_covers(dest, east,
                              dt.datetime(2026, 9, 1, 20, 0)) is True
    assert R._intraday_covers(dest, east,
                              dt.datetime(2026, 9, 1, 21, 0)) is False


# --- enrolling here REMOVES you from knocks_intraday ------------------------

def test_enrolling_removes_the_office_from_knocks_intraday(monkeypatch,
                                                           tmp_path):
    """Megan 2026-09-01: "they should just get removed from knocks_intraday
    since we want them enrolling in the dispositions." One action — enrolling —
    both wires the office here and stops the other job posting to it."""
    from automations.knocks_intraday import roster as ros
    chan = ros.enrolled("eod")[0].channel_id
    before = len(ros.enrolled("eod"))

    p = tmp_path / "onboarded_offices.json"
    p.write_text(json.dumps([{"key": "x", "enabled": True, "destinations": [
        {"kind": "slack", "channel_id": chan, "cadence_min": 60}]}]))
    monkeypatch.setattr(ros, "_ONBOARDED_JSON", p)
    assert chan in ros.disposition_channels()
    assert len(ros.enrolled("eod")) == before - 1
    assert chan not in {o.channel_id for o in ros.enrolled("eod")}


def test_an_office_wired_but_switched_off_still_gets_the_old_board(monkeypatch,
                                                                   tmp_path):
    """Wired-but-off means nothing is sending from here yet. Removing it from
    knocks_intraday too would leave that channel with no board at all."""
    from automations.knocks_intraday import roster as ros
    chan = ros.enrolled("eod")[0].channel_id
    before = len(ros.enrolled("eod"))
    p = tmp_path / "onboarded_offices.json"
    p.write_text(json.dumps([{"key": "x", "enabled": False, "destinations": [
        {"kind": "slack", "channel_id": chan, "cadence_min": 60}]}]))
    monkeypatch.setattr(ros, "_ONBOARDED_JSON", p)
    assert ros.disposition_channels() == set()
    assert len(ros.enrolled("eod")) == before


def test_an_unreadable_registry_leaves_the_old_board_posting(monkeypatch,
                                                             tmp_path):
    from automations.knocks_intraday import roster as ros
    before = len(ros.enrolled("eod"))
    p = tmp_path / "onboarded_offices.json"
    p.write_text("{ not json")
    monkeypatch.setattr(ros, "_ONBOARDED_JSON", p)
    assert len(ros.enrolled("eod")) == before


# --- which box runs which office --------------------------------------------

def test_the_campaign_decides_the_machine():
    """Not a preference — an office can only be impersonated from the box whose
    OwnerVille login has access to it. Lucy 1 is Raf's (D2D), Lucy 2 Carlos's."""
    assert S.campaign_machine("att") == "Lucy 1"
    assert S.campaign_machine("energy") == "Lucy 1"
    assert S.campaign_machine("nds") == "Lucy 1"
    assert S.campaign_machine("b2b_att") == "Lucy 2"
    assert S.campaign_machine("b2b_box") == "Lucy 2"


def test_the_row_carries_its_machine():
    assert A._row(_rec(campaign_key="att"))["machine"] == "Lucy 1"
    assert A._row(_rec(campaign_key="b2b_box"))["machine"] == "Lucy 2"


def test_a_runner_only_takes_the_offices_it_can_reach():
    rows = [{"key": "d2d_one", "machine": "Lucy 1"},
            {"key": "b2b_one", "machine": "Lucy 2"},
            {"key": "hardcoded"}]          # no machine = Lucy 1, always has been
    monkey = C.for_this_machine(rows)
    assert C.this_machine() == "Lucy 1"    # this laptop carries no marker
    assert [o["key"] for o in monkey] == ["d2d_one", "hardcoded"]


def test_the_hardcoded_offices_stay_on_lucy_1():
    """Raf, Calvin and Jay have always run there and carry no machine key."""
    assert {o["key"] for o in C.enabled()} == {"rafael", "calvin", "jay_att",
                                              "jay_ew"}


# --- staggering -------------------------------------------------------------

def test_offices_are_staggered_across_the_quarter_hour():
    """Megan 2026-09-01: one ICD at :15/:30/:45 and another at :20/:35/:50 is
    fine, "just as long as it's every 15 min". Un-staggered, twenty offices are
    all scraped at :00 and the tick overruns its own window."""
    offsets = {C.office_offset({"key": k})
               for k in ("rafael", "calvin", "cody", "dana", "eve", "frank")}
    assert offsets <= {0, 5, 10}
    assert len(offsets) > 1              # they do not all land on the same one


def test_a_staggered_office_still_gets_exactly_its_cadence():
    dest = {"kind": "imessage", "cadence_min": 15}
    for key in ("rafael", "calvin", "cody"):
        cfg = {"key": key}
        fires = [m for m in range(0, 60, C.WAKE_MINUTES)
                 if R._dest_due(dest, dt.datetime(2026, 9, 1, 13, m), cfg=cfg)]
        assert len(fires) == 4                      # four an hour, exactly
        gaps = {b - a for a, b in zip(fires, fires[1:])}
        assert gaps == {15}                         # evenly spaced


def test_the_offset_is_stable_across_processes():
    """hash() is salted per interpreter — an office's slot must not move on
    every tick."""
    assert C.office_offset({"key": "cody"}) == C.office_offset({"key": "cody"})
    assert C.office_offset({"key": ""}) == 0


def test_fixed_times_are_never_staggered():
    """'First Knocks 2:00 PM' means 2:00, not 2:05."""
    d = {"kind": "imessage", "cadence_min": 0, "slots": ["14:00"]}
    for key in ("rafael", "calvin", "cody"):
        cfg = {"key": key}
        assert R._dest_due(d, dt.datetime(2026, 9, 1, 14, 0), cfg=cfg) is True
        assert R._dest_due(d, dt.datetime(2026, 9, 1, 14, 5), cfg=cfg) is False


def test_the_wake_divides_every_cadence_we_offer():
    for m in S.CADENCE_CHOICES:
        assert m % C.WAKE_MINUTES == 0


# --- one session per tick, not two per office -------------------------------

def test_the_tick_pulls_every_due_office_in_one_session(monkeypatch):
    """The refactor that makes twenty owners possible: pull_offices_days is
    called ONCE with every due office, not once per office."""
    calls = []

    def _fake_pull(jobs, verbose=True, profile_dir=None):
        calls.append(list(jobs))
        return [(name, {}, None) for name, *_ in jobs]

    import automations.rashad_metrics.knocks_pull as KP
    monkeypatch.setattr(KP, "pull_offices_days", _fake_pull)
    monkeypatch.setattr("automations.knocks_intraday.run.compare_office",
                        lambda: "")
    plan = [({"key": "a", "name": "Office A", "campaign_id": "3"}, "1:00 PM"),
            ({"key": "b", "name": "Office B", "campaign_id": "2"}, "1:00 PM"),
            ({"key": "c", "name": "Office C"}, "1:00 PM")]
    R.pull_boards_many(plan, dt.date(2026, 9, 1), pathlib.Path("/tmp"))
    assert len(calls) == 1                       # ONE session, not three
    assert [j[0] for j in calls[0]] == ["Office A", "Office B", "Office C"]
    assert calls[0][0][2] == "3"                 # each keeps its own campaign
    assert calls[0][1][2] == "2"


def test_two_offices_sharing_one_ownerville_name_are_not_confused(monkeypatch):
    """Jay Turnage is TWO offices — jay_att and jay_ew — with one OwnerVille
    name and two campaigns. Matching results by name would hand both reports
    the same rows."""
    day = dt.date(2026, 9, 1)

    def _fake_pull(jobs, verbose=True, profile_dir=None):
        # Distinct rows per JOB, in the order given.
        return [(name, {day: [{"Rep": "%s-%d" % (name, i)}]}, None)
                for i, (name, *_rest) in enumerate(jobs)]

    import automations.rashad_metrics.knocks_pull as KP
    monkeypatch.setattr(KP, "pull_offices_days", _fake_pull)
    monkeypatch.setattr("automations.knocks_intraday.run.compare_office",
                        lambda: "")
    monkeypatch.setattr(R, "_render_board",
                        lambda cfg, rows, extra, day, out_dir, slot: rows)
    plan = [({"key": "jay_att", "name": "Jay Turnage", "campaign_id": "3"}, ""),
            ({"key": "jay_ew", "name": "Jay Turnage", "campaign_id": "40"}, "")]
    got = R.pull_boards_many(plan, day, pathlib.Path("/tmp"))
    assert got["jay_att"][1] != got["jay_ew"][1]


# --- the wrong-account guard ------------------------------------------------

def _plan_with(*kinds):
    return [({"key": "k%d" % i, "name": "N%d" % i, "ov": ov}, "", [])
            for i, ov in enumerate(kinds)]


def _notfound(key):
    return {key: ([], [], RuntimeError(
        "Couldn't impersonate 'X' in ownerville: name not found in ownerville"))}


def test_every_impersonation_failing_reads_as_the_wrong_account():
    """2026-09-01: Lucy 1 was switched to Carlos. Nothing errored — Raf's board
    came back empty (the master office IS whoever is logged in) and every other
    office vanished from Office Access."""
    plan = _plan_with("master", "impersonate", "impersonate")
    boards = {}
    boards.update(_notfound("k1"))
    boards.update(_notfound("k2"))
    boards["k0"] = ([], [], None)
    assert R._wrong_account(plan, boards) is True


def test_one_office_failing_is_an_office_problem_not_a_session_one():
    plan = _plan_with("master", "impersonate", "impersonate")
    boards = {"k0": ([], [], None), "k2": ([], [], None)}
    boards.update(_notfound("k1"))
    assert R._wrong_account(plan, boards) is False


def test_a_single_impersonated_office_is_never_enough_to_call_it():
    """Jay waiting on Office Access must not look like a wrong login."""
    plan = _plan_with("master", "impersonate")
    boards = dict(_notfound("k1"))
    assert R._wrong_account(plan, boards) is False


def test_a_real_pull_error_is_not_mistaken_for_the_wrong_account():
    plan = _plan_with("impersonate", "impersonate")
    boards = {"k0": ([], [], TimeoutError("nav timeout")),
              "k1": ([], [], TimeoutError("nav timeout"))}
    assert R._wrong_account(plan, boards) is False


def test_each_machine_knows_whose_login_it_should_carry():
    assert C.MACHINE_OWNER["Lucy 1"] == "Rafael Hidalgo"
    assert C.MACHINE_OWNER["Lucy 2"] == "Carlos Hidalgo"
    assert C.expected_owner("Lucy 1") == "Rafael Hidalgo"
