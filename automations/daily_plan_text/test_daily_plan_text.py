import datetime as dt

from automations.daily_plan_text import config as C
from automations.daily_plan_text import run as R


def test_wednesday_has_the_template():
    t = R.template_for(dt.date(2026, 11, 11))   # Wednesday
    assert t.startswith("Wednesday\n*Please assign")
    assert "ATT Day 1 (Garden theory, 5 steps, Fugi)  - " in t
    assert t.endswith("Impact -")


def test_days_without_a_template_send_nothing():
    assert R.template_for(dt.date(2026, 11, 12)) is None   # Thursday, pending
    assert R.template_for(dt.date(2026, 11, 15)) is None   # Sunday, never


def test_only_monday_to_saturday():
    assert C.WEEKDAYS == [0, 1, 2, 3, 4, 5]


def test_once_per_day():
    assert R.already_sent(dt.date(2026, 11, 11), {"sent_day": "2026-11-11"})
    assert not R.already_sent(dt.date(2026, 11, 12), {"sent_day": "2026-11-11"})


def test_route_goes_to_new_a_players_only():
    from automations.b2b_dispositions import config as B
    assert B.TEXT_ROUTES[(C.CAMPAIGN_LABEL, C.KIND)] == [B.TEXT_GROUP_ALL]
