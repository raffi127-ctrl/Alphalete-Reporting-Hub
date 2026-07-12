"""Resume Pushing — ApplicantStream v2 ("Explore Appstream AI") resume
extraction + send-to-AI for Carlos's office 11580. Runs unattended on Lucy 2
(Carlos's own OV+AS logins) every 10 min, 8am–10pm CST, Sun + Mon–Fri, via
com.alphalete.resume-pushing. Loops extract until "Ready For Extraction" = 0 and
sends until "Sent to Call List" = 0, mirroring Carlos's Cowork skill. See run.py
for the flow + the --dry-run gate."""
