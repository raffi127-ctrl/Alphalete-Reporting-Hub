"""Harvest package config knobs.

SHADOW-ONLY. Nothing on the live 4am path imports this package. See README.md.
"""
from __future__ import annotations

from pathlib import Path

# Repo root: automations/harvest/config.py -> parents[2]
REPO_ROOT = Path(__file__).resolve().parents[2]

# Dated cache lives under output/ (git-ignored scratch area, per CLAUDE.md).
CACHE_ROOT = REPO_ROOT / "output" / "harvest"

# Rolling retention window (days of dated folders to keep, INCLUDING today).
# Doubles as a re-run buffer: a failed report can be rebuilt off cache within
# the window without re-scraping Tableau. Bounded disk footprint:
#   ~19 churn crosstabs/day * ~200 KB each ≈ 4 MB/day  ->  ~12 MB at 3 days.
# Override with the HARVEST_RETENTION_DAYS env var or the harvest() arg.
RETENTION_DAYS = 3

# Compute worker-pool cap (IO-bound gspread + Slack). Kept small because
# gspread 429s on the SAME spreadsheet and Slack rate-limits per channel;
# same-spreadsheet writes are serialized by a per-key lock (see compute.py).
COMPUTE_MAX_WORKERS = 4
