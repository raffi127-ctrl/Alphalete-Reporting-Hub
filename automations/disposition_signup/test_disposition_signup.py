"""Tests for the daily-dispositions sign-up: the record rules, the row it
materializes, and the per-destination cadence/window behaviour it unlocks in
gap_alerts.

PURE — no Sheets, no Slack, no Messages, no SMTP. Nothing here sends.

    .venv/bin/python -m pytest automations/disposition_signup/ -q
"""
from __future__ import annotations

import datetime as dt
import json

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


@pytest.mark.parametrize("drift", [0, 1, 2, 9, 14])
def test_cadence_survives_the_wrapper_drift(drift):
    """The tick fires on the quarter hour but Python reads the clock a minute
    or three later. Anchoring on the raw minute would make an hourly
    destination due never."""
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
