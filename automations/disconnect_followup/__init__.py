"""Disconnect / Cancel follow-up feedback logger — Dylan's own report.

Dylan messages AT&T-fiber customers who cancelled or disconnected (via
Salesforce, which lands in RingCentral) asking for feedback. This module scans
RingCentral and, once a customer has replied, writes the whole conversation
that follows the inquiry (both sides, minus the inquiry itself) into the
feedback column of that customer's most-recent matching row in the source
'AT&T Fiber Metrics Report' sheet — Local Office + Raf's Captainship, cancels
and disconnects.

On-demand, matched by phone, handles the source's per-row column shift, and is
idempotent. Runs anywhere with the Google Sheets token + RingCentral creds (no
Tableau / patchright).
"""
