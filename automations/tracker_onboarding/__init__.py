"""Tracker Onboarding — add an office to the daily Tableau tracker screenshots.

Parallel to office_onboarding, but simpler: the trackers are UNIVERSAL boards
(the same images post to every channel), so onboarding an office is just its
Slack channel + which trackers it wants, in what order. There's no per-office
Tableau view and no new schedule entry — the existing tableau_screenshots run
loops every org in ORG_CHANNELS, and the Hub card reads it too, so a new office
posts + shows up automatically once merged.
"""
