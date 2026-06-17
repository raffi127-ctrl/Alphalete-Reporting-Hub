"""Brand Health audit — social/reputation auditing for our own company and,
later, other SCI companies as a service.

Replaces the vendor "monthly letter-grade card" with a research-grade audit:
metrics that actually matter (review velocity/trend, response rate, sentiment,
SERP page-1 presence, share-of-voice) instead of vanity follower counts.

Intake is a Google Sheet, one row per company (name, location, and links for
FB / IG / Google Profile / LinkedIn / Reddit / X / Website / Indeed / Glassdoor).
The same engine audits every company, so it scales from Alphalete to clients.

Phase 1 (this module): read-only audit + the Brand Health Card.
Phases 2-3 (later): Slack alerts on negatives, review replies, post drafting.
"""
