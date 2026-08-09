"""Text two of the daily Tableau Country Trackers into their iMessage groups.

Carlos asked (2026-08-09, #l10-alphalete) for the B2B AT&T tracker and the B2B
Box tracker — the images Lucy already posts in the "Tableau Country Trackers"
thread — to also go out as texts, at the same time they hit Slack:
  * B2B AT&T  -> "ATT B2B Leaders" + "New A Players"
  * B2B Box   -> "Box B2B"         + "New A Players"

WHY THIS IS ITS OWN MODULE and not a mode of b2b_dispositions:
  * b2b_dispositions captures OwnerVille *disposition* screens; these are the
    country-wide *Tableau* boards captured by tableau_screenshots. Different
    source, different capture, same three groups.
  * The Slack post runs on the MINI (Lucy 1). The iMessage groups, the Messages
    permission grant, and the sending poller all live on LUCY 2. So the send has
    to happen on Lucy 2 — where att_order_log already proves Tableau is reachable
    (tableau_patchright) and where the poller already holds the Messages grant.

It reuses the two proven halves outright:
  * tableau_screenshots.capture / pages  -> the exact same board image + crop
  * b2b_dispositions.text_post            -> ~/Pictures staging + group send
"""
