"""Captainship Churn fills on the Owners Metrics Report Google Sheet.

Covers the captainships under each campaign type:
  * ATT Fiber  — Wayne / Starr Rodenhurst / Chan Park / Tony Chavez / Sahil Multani   (per-ICD churn)
  * B2B        — Carlos Hidalgo / Eveliz Wright           (per-ICD churn, 5 buckets incl. 120-day)
  * NDS        — Khalil Mansour / Colten Wright / Jairo Ruiz (per-ICD churn)

One Hub card, one Tableau session, one pull per captainship → one fill
per destination tab. Sheet-only (no Slack post — distinct from the
Local Office Slack flow).

Phased rollout:
  Phase 1: Fiber (Wayne / Starr / Chan / Tony / Sahil) — this file
  Phase 2: B2B  (Carlos / Eveliz)        — when megan sends B2B URLs
  Phase 3: NDS  (Khalil / Colten / Jairo) — when megan sends NDS URLs
"""
