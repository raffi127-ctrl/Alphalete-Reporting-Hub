import datetime as dt

from automations.second_round_report import run as R

ROSTERS = {"AT&T": ["Nick Smedra", "Andrew De La Torre", "Nathaly Benitez", "Annett Michell Climaco"],
           "Verizon": ["Will Bautista", "Brandy Ahumada Ruiz", "Gary Van Whitaker", "Jair Hernandez Otero"]}


def test_interviewer_team_by_board_roster():
    assert R.team_of("Nicholas Smedra", ROSTERS) == ("AT&T", "Nick Smedra")          # nickname
    assert R.team_of("William Bautista", ROSTERS) == ("Verizon", "Will Bautista")
    assert R.team_of("Gary Van Whitaker II", ROSTERS) == ("Verizon", "Gary Van Whitaker")   # suffix
    assert R.team_of("Brandy Ahumada", ROSTERS) == ("Verizon", "Brandy Ahumada Ruiz")     # 2nd surname
    assert R.team_of("Jair otero", ROSTERS) == ("Verizon", "Jair Hernandez Otero")
    assert R.team_of("Nathaly Elizabeth Molina Benitez", ROSTERS) == ("AT&T", "Nathaly Benitez")
    assert R.team_of("?", ROSTERS) == (None, None)
    assert R.team_of("Isabella Upegui", ROSTERS) == (None, None)


def test_campaign_fallback():
    assert R.campaign_team("NDS") == "AT&T" and R.campaign_team("B2B ATT") == "AT&T"
    assert R.campaign_team("VERIZON") == "Verizon" and R.campaign_team("Box") is None


def _row(**k):
    base = dict(row=2, cand="X", camp="NDS", who="Nick Smedra", date2=dt.date(2026, 11, 16), orient=None,
                showed=True, noshow=False, offered=True, not_offered=False, accepted=False,
                declined=False, waiting=False, ns_showed=False)
    base.update(k)
    return base


def test_summary_and_day_gaps():
    rows = [_row(cand="A", accepted=True), _row(cand="B", offered=False, not_offered=True),
            _row(cand="C", who="Will Bautista", camp="VERIZON", accepted=True),
            _row(cand="D", showed=False, noshow=True, who="Isabella Upegui", camp=""),
            _row(cand="E", showed=False, offered=False, orient=dt.date(2026, 11, 17), ns_showed=True)]
    R.assign_teams(rows, ROSTERS)
    lo, hi = dt.date(2026, 11, 16), dt.date(2026, 11, 22)
    aps = {dt.date(2026, 11, 16): {"s2": 3, "off": 3, "bob": 2, "nss": 0, "nsh": 0, "b2": 4},
           dt.date(2026, 11, 17): {"s2": 0, "off": 0, "bob": 0, "nss": 1, "nsh": 1, "b2": 0}}
    s = R.summarize(rows, lo, hi, aps)
    assert (s["total"]["conducted"], s["total"]["offered"], s["total"]["accepted"]) == (3, 2, 2)
    assert (s["AT&T"]["conducted"], s["Verizon"]["conducted"]) == (2, 1)
    assert s["ns_total"] == {"scheduled": 1, "showed": 1, "show_pct": 1.0}
    assert s["no_shows"] == 1
    offers = [g for g in s["gaps"] if g["what"] == "offers"]
    assert offers and offers[0]["hint"] == ["B"] and (offers[0]["appstream"], offers[0]["du"]) == (3, 2)
    note = R.offer_note(s)
    assert "off by 1" in note and "B is marked N" in note


def test_closing_pct_is_accepted_over_conducted():
    b = R.second_block([_row(accepted=True), _row(), _row(), _row()])
    assert b["close_pct"] == 0.25 and b["offer_pct"] == 1.0


def test_same_leader_and_carlos():
    assert R.same_leader("Nicholas Smedra", "Nick Smedra", ROSTERS)
    assert R.same_leader("William Bautista", "Will Bautista", ROSTERS)
    assert not R.same_leader("Will Bautista", "Gary Van Whitaker", ROSTERS)
    assert R.is_carlos("Carlos Hidalgo") and R.is_carlos("SELECT=Carlos  Hidalgo") is True
    assert R._clean_who("SELECT=None") == "" and R._clean_who(" Gary  Van Whitaker ") == "Gary Van Whitaker"


def test_leaders_with_appstream_done_by():
    d = dt.date(2026, 11, 16)
    rows = [_row(cand="Ann Lee", accepted=True), _row(cand="Bo Kim"), _row(cand="Cy Do", who="Will Bautista", camp="VERIZON"),
            _row(cand="Di Fox", who="Will Bautista", camp="VERIZON"), _row(cand="Ed Ray", who="Will Bautista", camp="VERIZON")]
    R.assign_teams(rows, ROSTERS)
    asr = [{"Day": d.isoformat(), "Row": "Second Interviews Showed Up", "First": f, "Last": l, "Email": "", "Phone": "",
            "Done By 2nd": who} for f, l, who in (("Ann", "Lee", "Nicholas Smedra"), ("Bo", "Kim", "Carlos Hidalgo"),
                                                  ("Cy", "Do", "Gary Van Whitaker"), ("Di", "Fox", ""))]
    L = R.leaders_summary(rows, d, d, asr, ROSTERS)
    assert L["kinds"] == {"same": 1, "carlos": 1, "other": 1, "blank": 1, "not found": 1}
    att = dict((n, (b, k)) for n, b, ns, k in L["teams"]["AT&T"]["leaders"])
    assert att["Nick Smedra"][0]["conducted"] == 2 and att["Nick Smedra"][1] == {"same": 1, "carlos": 1}
    assert [r["cand"] for r in L["others"]] == ["Cy Do"]
    page = R.render_leaders(L, d, 4)
    assert "Nick Smedra" in page and "Will Bautista" in page
    # Carlos 11/20: no bottom notes box, no AppStream done-by column -- Daily Update numbers only
    assert "class='foot'" not in page and "AppStream" not in page and "Done By" not in page


def test_through_day():
    fri = dt.date(2026, 11, 20)
    assert R.through_day("yesterday", fri) == dt.date(2026, 11, 19)
    assert R.through_day(None, fri) == fri and R.through_day("today", fri) == fri
    assert R.through_day("2026-11-18", fri) == dt.date(2026, 11, 18)


def test_caught_up_through_stops_at_the_last_day_on_the_daily_update():
    wed, thu = dt.date(2026, 11, 18), dt.date(2026, 11, 19)
    rows = [{"showed": True, "date2": wed}] * 11
    asd = {wed: {"s2": 11}, thu: {"s2": 11}}
    assert R.caught_up_through(rows, asd, thu) == wed                      # 11/20: Thursday not typed in yet
    assert R.caught_up_through(rows + [{"showed": True, "date2": thu}] * 10, asd, thu) == thu   # one short is fine
    assert R.caught_up_through(rows, {wed: {"s2": 11}}, thu) == thu        # AppStream shows nothing Thursday
    assert R.caught_up_through(rows, {}, thu) == thu                       # no AppStream log: no step back
    assert R.week_window(wed, 4) == (dt.date(2026, 11, 16), dt.date(2026, 10, 26))
    assert R.week_window(dt.date(2026, 11, 23), 4) == (dt.date(2026, 11, 23), dt.date(2026, 11, 2))


def test_text_routes_one_chain_each():
    from automations.b2b_dispositions import config as C
    want = {("cards", "aplayers"): [C.TEXT_GROUP_ALL], ("leaders", "aplayers"): [C.TEXT_GROUP_ALL],
            ("leaders", "leaders"): [C.TEXT_GROUP_ATT]}
    assert set(R.TEXT_KINDS) == set(want)
    for pc, groups in want.items():
        assert C.TEXT_ROUTES[(R.TEXT_CAMPAIGN, R.TEXT_KINDS[pc])] == groups, pc


def test_text_retry_stops_early_once_every_chain_is_sent():
    """The 9:20 retry after a good 9:00 send returns before any sheet / AppStream read."""
    import json, tempfile
    from pathlib import Path
    from unittest import mock
    state = Path(tempfile.mkdtemp()) / "state.json"
    key = "leaders|4|2026-11-19|full"
    boom = mock.Mock(side_effect=AssertionError("read a sheet"))
    with mock.patch.object(R, "TEXT_STATE", state), mock.patch.object(R, "_sheet", boom):
        state.write_text(json.dumps({key + "|aplayers": "07:45", key + "|leaders": "09:04"}))
        assert R.main(["--view", "leaders", "--through", "2026-11-19", "--text"]) == 0
        state.write_text(json.dumps({key + "|aplayers": "07:45"}))       # A Players only, sent by hand
        assert R.main(["--view", "leaders", "--through", "2026-11-19", "--text", "--to", "aplayers"]) == 0
        try:                                                               # leaders still owed -> does the work
            R.main(["--view", "leaders", "--through", "2026-11-19", "--text"])
            raise RuntimeError("should have read the sheet")
        except AssertionError:
            pass
    assert boom.call_count == 1
