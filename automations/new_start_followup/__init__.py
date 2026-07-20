"""New-Start Follow-Up — make sure 2nd-round interviewers text their new starts.

Raf's manual loop, automated:
  Fri  ~4:54pm  Aisha posts "D2D Alphalete New Starts Scheduled for Monday"
  Sat  8:00am   Aisha @-tags every leader in that thread
  Sat  all day  leaders reply "Sent" / "sent x4" as they text their new starts
  Sun  ~1:00pm  Raf hand-builds a numbered ✅ checklist and tags the stragglers

This package rebuilds that checklist from the OBCL sheet + the Slack thread, and
posts the Saturday nudges Raf currently sends by hand.
"""
