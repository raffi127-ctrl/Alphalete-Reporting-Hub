# 2nd Round Interview Auditor (Lucy)

Slack bot: reps DM a 2nd-round interview recording -> Gemini grades it against
Rafael's 11-frame framework -> scored PDF back. Live scorecard + daily digests.
Code only; per-machine secrets live in `.env` (see `.env.example`). Runs on the
Lucy 1 mini via launchd. One instance per Slack workspace.
