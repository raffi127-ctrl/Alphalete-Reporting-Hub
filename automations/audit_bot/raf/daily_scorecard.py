#!/usr/bin/env python3
"""Manually fire the daily scorecard send — regenerate the page, render the
2-page PDF, DM it to Rafael, and attach the retire pick-list. The running bot
also fires this automatically at 2 PM Central. Run on Lucy 1:
    venv/bin/python daily_scorecard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from slack_watcher import send_daily_scorecard  # noqa: E402

if __name__ == "__main__":
    send_daily_scorecard()
