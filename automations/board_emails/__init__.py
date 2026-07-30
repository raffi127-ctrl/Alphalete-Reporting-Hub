"""Screenshot emails for the two sales boards that had none: the Country Sales
Board and the All Units (All Campaigns) Org Sales Board.

Both already produce an exact-sheet PNG for their Slack DM. This package puts
that same image in an email, behind the SAME review gate the Org Sales Board
email and the captainship drafts use — one post in #revision-emails, one
checkmark from Evelyn or Jolie, then it goes out.

NOTHING NEW HAD TO BE INSTALLED for that last step: the checkmark is picked up
by deploy/org_board_email_review.sh, the every-15-min watcher already running on
the mini, which now checks these two boards alongside the Org board's own email.

    python -m automations.board_emails.email_send --board country --dry-run
    python -m automations.board_emails.review_gate --board country --post
    python -m automations.board_emails.review_gate --board country --check --send

Two emails, not one: they are different boards read by the same two people
(Rafael and Maud), and Eve asked for them separately so either can be approved,
held or stopped without touching the other.
"""
