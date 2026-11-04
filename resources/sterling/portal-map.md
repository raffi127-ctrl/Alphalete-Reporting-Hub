# Sterling (First Advantage) portal map

Mapped with Megan 2026-11-03 for the office admin page's "Send background
checks" button (automations/icd_alerts/sterling_send.py). Each screen as it
really looked; update this file when a screen changes.

## 1. Login — `https://auth.sterlingcheck.app/oauth2/login?client_id=15smt5dkm826r0lbofg6c67loq`

- First Advantage SSO page, title "First Advantage SSO Login". **No Cloudflare check.**
- Cookie banner (Osano): buttons "Accept" / "Deny Non-Essential" → press **Deny Non-Essential**.
- Heading "Log In". Field **"User ID / Email"** (text) + **Continue** (submit).
- After Continue, the SAME page shows **"Password"** under it, a **"Remember me"**
  checkbox, **Sign In** button, "Forgot Password?" link.
- User IDs are not emails (Raf's is `rahidalgo`). Tick Remember me (may spare the
  code on later logins — to confirm).

## 2. Emailed code

- From `noreply@us.fadv.co`, subject "Authentication Request", body
  "Your authentication code is NNNNNN." — goes to the account's email (Raf's →
  raffi127@gmail.com). Arrived ~10 s after Sign In (11/3 test).
- Code screen: heading **"We just sent you a verification code"**, text "We sent a code
  via Email. Please allow up to 2 minutes…". **Six single-digit boxes**, then
  **Continue** (grey until filled), **Back**, "Resend Code" link. Asked for a code even
  though Remember me was ticked (first login on that browser).

- **Code forward (each ICD's own email):** `python -m automations.icd_alerts.sterling_forward`
  on the ICD's computer — Gmail filter from `noreply@us.fadv.co` + subject
  `Authentication Request` → alphaletereporting@gmail.com (results stay private).

## 3. Portal home — `https://secure.sterlingdirect.com/sys/`

- Lands here after the code. Banner "Click Here to access Client Hub"; top links
  Help | Support | Admin | Account Dashboard | Logout; tabs SCREENING / DRUG TOOLS /
  POSTHIRE / ANALYTICS. Breadcrumb "Screening »", account line "Rafael @ Alphalete
  Marketing, Inc." (proves WHICH account is signed in — check it per office).
- Tiles: Workflows In Progress · E-Invites Not Started (24 Hours) · Awaiting/Missing
  Info · Unread Order Notes · Managed Adverse Action - In Process · Draft - Not Yet Submitted.
- **"E-Invite Applicant to Background Check"** panel (right): **E-Mail Address** text
  field (envelope icon) + **Invite** button ← where the send starts (Megan 11/3).
- "Find Background Checks/E-Invites": Look in [Last Name ▾] for [...], Order
  [Completed ▾] from/to, Advanced Search; View "My Background Checks".
- Bottom: **E-Invites** counts — Queue · Un-Deliverable · Delivered · Ready · Archive ·
  Expired (links) — and Screening Orders counts (Draft · Pending · Complete · Adverse
  Action · Dispute · Archive).

## 4. After Invite

- **Invite sends right away** (Megan 11/3) — no form, no name, no package pick. One
  email in the box + Invite = one e-invite sent. So the click path is complete:
  login → code → home → E-Mail Address → Invite.
- Because it is one click, the bot must check (a) the account line is the right office
  and (b) the address isn't already invited (Find Background Checks/E-Invites search)
  before pressing — a second press is a second invite.
- _Still to see:_ the confirmation/error text Invite shows, and where a fresh invite
  appears (E-Invites → Queue/Delivered) — that is how the bot proves it went out.
