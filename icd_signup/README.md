# Join Lucy Eco — ICD sign-up

The public link an ICD owner fills in to get their office's credit checks,
sales and knock boards posted in Slack. Their office computer does the reading;
we do the posting.

- **Owner-facing:** `icd_signup/app.py`
- **Deploy:** Streamlit Community Cloud
- **Logic:** `automations/icd_signup/` (schema, store, alert, approval)

## The flow

1. They fill this form. It asks for their selling hours, their timezone, how
   their name is spelled in OwnerVille, whether the computer is a Mac or a PC,
   and how often they want a knocks board.
2. On submit their **relay key is minted** and the page shows their setup
   link. They can install immediately — they are not waiting on us.
3. Megan is pinged in `#claudecorrections-and-requests` with the request and
   the one command that acts on it.
4. `python -m automations.icd_signup.approve <office>` approves **where their
   numbers post**. Until then their laptop can install and relay, and nothing
   reaches a channel.

## What this form never asks for

**A password.** The SaraPlus and OwnerVille logins are typed into the installer
on their own machine and never leave it. A sign-up page that collected one
would quietly undo the entire design.

**A channel it can act on.** What they type is a request. A human approves it,
because an office naming its own channel is an office enrolling itself into
somebody else's room.

## Secrets

| Secret | Why |
|---|---|
| `[gcp_service_account]` or `[gcp_oauth]` | writes the `ICD Signup` and `Relay Keys` tabs of the **Lucy Access App** workbook |
| `slack_user_token` (TOP-LEVEL, above any `[section]`) | the corrections-channel ping |

Without Sheets creds it saves a local draft and hands over no link — the
sign-up survives, but Megan has to send the link by hand.
`ICD_SIGNUP_LOCAL_ONLY=1` forces that path for testing.
