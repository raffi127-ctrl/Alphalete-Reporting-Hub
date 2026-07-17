"""The 6 sections of the daily 'Alphalete Production' post, in post order.

This is the ONE edit-to-add config file. Each section is a dict:
  id      -- stable key
  title   -- caption / header label (Team Sales gets the team name prefixed at runtime)
  emoji   -- unicode emoji for the parent's section list
  react   -- Slack reaction shortcode (added onto the parent)
  kind    -- which capture recipe (see capture.py):
             daily | field_status | energy | team | highrollers | zeros | ranking
  sort    -- for 'ranking' kind: the running-week metric header to sort by (APPS/INT/NL)

Team Sales (kind='team') fans out to ONE image per team found live in column CI.
Everything else is a single image. Order here == order in the Slack thread (Megan 7/5).
"""
from __future__ import annotations

SECTIONS = [
    {"id": "daily_production", "title": "Daily Production",
     "emoji": "\U0001F4CA", "react": "bar_chart", "kind": "daily"},
    {"id": "daily_production_el", "title": "Daily Production — Entry Level",
     "emoji": "\U0001F331", "react": "seedling", "kind": "field_status"},
    {"id": "zeros_two_day", "title": "Back-to-Back Zeros",
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
]
