"""Daily Tableau tracker screenshots -> Slack.

Captures a configurable list of Tableau views (automations.tableau_screenshots.
pages.PAGES) as PNGs via the warm ownerville/Tableau session, then posts them
into their own dated parent thread in #alphalete-sales (mirrors the Metrics
thread: bold dated header + one emoji-per-tracker line, then each image as a
threaded reply with the tracker's emoji reacted onto the parent).

Nothing here logs in fresh -- it rides tableau_patchright.tableau_session, the
same warm session every other Tableau report uses (kept warm by the mini's
session_holder).
"""
