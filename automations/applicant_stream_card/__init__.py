"""Applicant Stream Grade Card — one card per ICD, every part of their
ApplicantStream checked in one place, and every miss handed back with the
steps to fix it.

Megan 2026-11-12: "create an applicant stream audit for ICDs that will then
send them like a grade card ... if anything needs corrected", modelled on the
Lucy ECO social card (online_presence/simple_card.py): sections with a
green/yellow/red dot, a short "Do this first" list, and the why + how for
every item. "We've done the majority of all of this build already. It just
is in multiple places." So this module measures almost nothing itself. It
pulls together:

    sms_audit.gradecard / icd_audit   call list, show rate, lead time, texts
    sms_audit.scorecard               one report card per recruiter
    sms_audit.templates               saved SMS + email templates
    sms_audit.ai_settings             AI tab -> AI Settings
    sms_audit.escalations             AI tab -> AI Settings -> Escalations
    sms_audit.offices                 the address / Zoom / phone on file

and adds the numbers nobody had in one spot (stream_stats.py): AI vs human
booking share and show rate, days from push to booked, booking hours, and
what moves retention the most for THIS office.

READ-ONLY. Reads pulls already on disk. Builds a local HTML card; posts and
sends nothing.

    python -m automations.applicant_stream_card.run --office 11280
"""
