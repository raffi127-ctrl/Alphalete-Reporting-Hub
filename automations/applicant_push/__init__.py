"""Applicant Push — the unified office-11580 (Carlos) recruiting-push pipeline.

Merges the two stages that used to run as separate reports:

  1. BATCH  — Resume Pushing (ApplicantStream v2 → Process in Batches → extract
     resumes → Send to AI). Bulk first pass. (automations.resume_pushing)
  2. LEFTOVERS — OAT Processing (One-App-at-a-time cleanup of what the batch pass
     couldn't send: no phone, blocked, duplicate, needs re-text).
     (automations.oat_processing)

They are two stages of ONE pipeline — OAT's input is the batch pass's rejects —
and both need office 11580's AppStream session and both hit the same Indeed
employer-portal Turnstile. Running them separately made them fight over the
session on two different browser paths (real-Chrome/CDP vs patchright). This
module runs them SEQUENTIALLY on ONE warm real-Chrome/CDP session, so a single
login/warm (and a single Indeed re-login) serves both.

The two underlying modules stay intact and independently runnable — this is a
thin orchestrator over their factored-out cores (resume_pushing.run_batch_stage +
oat_processing.run_walk), so rollback is just re-enabling the two old agents.
"""
