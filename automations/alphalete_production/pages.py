"""The 6 sections of the daily 'Alphalete Production' post, in post order.

This is the ONE edit-to-add config file. Each section is a dict:
  id      -- stable key
  title   -- caption / header label (Team Sales gets the team name prefixed at runtime)
  emoji   -- unicode emoji for the parent's section list
  react   -- Slack reaction shortcode (added onto the parent)
  kind    -- which capture recipe (see capture.py):
             daily | team_totals | team_totals_detail | field_status | energy |
             team | highrollers | zeros | ranking | new_starts
  sort    -- for 'ranking' kind: the running-week metric header to sort by (APPS/INT/NL)
  weekdays-- optional: post this section only on these weekdays (Mon=0). Absent
             means every day. See sections_for().

Team Sales (kind='team') fans out to ONE image per team (Raf 8/6 "what Eve sent"): normal
day opens up that day's block, Monday shows the whole week. Order == thread (Megan 7/5).
"""
from __future__ import annotations

SECTIONS = [
    {"id": "daily_production", "title": "Daily Production",
     "emoji": "\U0001F4CA", "react": "bar_chart", "kind": "daily"},
    {"id": "all_teams_sales", "title": "All Teams Sales Board",
     "emoji": "\U0001F3C5", "react": "sports_medal", "kind": "team_totals"},
    {"id": "all_teams_sales_detail", "title": "All Teams Sales Board — Product Detail",
     "emoji": "\U0001F9FE", "react": "receipt", "kind": "team_totals_detail"},
    {"id": "daily_production_el", "title": "Daily Production — Entry Level",
     "emoji": "\U0001F331", "react": "seedling", "kind": "field_status"},
    {"id": "zero_streak", "title": "Zero Streak",
     "emoji": "\U0001F6AB", "react": "no_entry_sign", "kind": "zeros"},
    {"id": "energy_board", "title": "Energy Sales Board",
     "emoji": "⚡", "react": "zap", "kind": "energy"},
    {"id": "team_sales", "title": "Team Sales",
     "emoji": "\U0001F465", "react": "busts_in_silhouette", "kind": "team"},
    {"id": "highrollers", "title": "Highrollers of the Day",
     "emoji": "\U0001F48E", "react": "gem", "kind": "highrollers"},
    {"id": "rank_apps", "title": "Total Week Production (Ranking based on Apps)",
     "emoji": "\U0001F3C6", "react": "trophy", "kind": "ranking", "sort": "APPS"},
    {"id": "rank_new_internets", "title": "Ranking based on New Internets",
     "emoji": "\U0001F310", "react": "globe_with_meridians", "kind": "ranking", "sort": "INT"},
    {"id": "rank_wireless", "title": "Ranking based on Wireless",
     "emoji": "\U0001F4F6", "react": "signal_strength", "kind": "ranking", "sort": "NL"},
    {"id": "new_starts", "title": "New Starts", "weekdays": (1, 2, 3, 4, 5, 6),
     "emoji": "\U0001F195", "react": "new", "kind": "new_starts"},
]

ALL_WEEKDAYS = (0, 1, 2, 3, 4, 5, 6)


def sections_for(today, only=None) -> list:
    """SECTIONS for `today`, minus any section its own 'weekdays' rules out.

    Eve 8/31: New Starts is a TUE-SUN section. On Monday the week's new-start
    list doesn't exist yet -- it depends on who physically shows up -- so the
    block would go out empty. An explicit `--only` naming a section overrides
    the calendar: asking for a section by id IS asking for it today."""
    picked = set(only or ())
    if picked:
        return [s for s in SECTIONS if s["id"] in picked]
    return [s for s in SECTIONS
            if today.weekday() in s.get("weekdays", ALL_WEEKDAYS)]
