"""Due Diligence per-rep report.

Raf asks for a rep's due-diligence numbers in Slack; a channel poller pulls
them from Tableau (new INT / wireless weekly, cancel rates, churn), replies
in-thread, and fills the Due Diligence tab the way Eve does by hand.

See README.md for the flow. Nothing here posts to Slack or writes the Sheet
unless explicitly run live (default is --dry-run / preview).
"""
