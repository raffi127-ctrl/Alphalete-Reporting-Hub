"""OAT Processing — the "One App at a time" leftovers handler.

resume_pushing sends the bulk of applicants to the AI call list via the
ApplicantStream **v2** batch grid. Whatever it *can't* auto-send (duplicates
inside the reissue window, applicants with no phone, people already interviewed)
falls to the human queue in the **classic** ApplicantStream surface under
Applicants → Process Emails → **One App at a time (OAT)**. The girls work that
queue by hand.

This module automates that manual OAT pass for Carlos's office (11580) on
Lucy 2, following the decision tree in README.md. It reuses the classic
ApplicantStream driver + office switch from `automations.applicant_tracker`.
"""
from __future__ import annotations  # Lucy 2 / mini run Python 3.9
