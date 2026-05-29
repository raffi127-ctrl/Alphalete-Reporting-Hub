"""Captainship Churn — fills the Captainship - New Internet Churn and
Captainship - Wireless Churn tabs on the AT&T Fiber Metrics Report
Google Sheet.

Mirrors `automations/churn/` (Raf's Local Office) but:
  * data is per-ICD (one row per ICD owner), not per-rep
  * source is Megan's CaptainshipChurn / CaptainshipWIRELESSChurn
    Tableau custom views
  * NO Slack post — sheet fill is silent (Megan 2026-05-29)
"""
