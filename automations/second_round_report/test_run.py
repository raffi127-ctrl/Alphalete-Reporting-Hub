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
    assert "Carlos 1" in R._as_cell({"same": 1, "carlos": 1}, True)
