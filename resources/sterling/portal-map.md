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

## 5. THE WAY WE SEND: Client Hub → Invite Candidate → bulk upload

Chosen by Megan 11/4 after Raf's Loom (loom.com/share/e7aecd44b6c84d1c8889a2b5f996d780).
Section 4 (the old one-at-a-time form) is kept only as the fallback.

1. Old portal home (`secure.sterlingdirect.com/sys/`) → the dark banner across the very top,
   **"Click Here to access Client Hub"** (above Help | Support | Admin) — confirmed, Megan screenshot 11/4.
2. Client Hub = **`https://sterlingcheck.app/dashboard/`** (different site from the old portal).
   Left menu: Order Search box · **Invite Candidate** · Orders (Dashboard, Advanced Search,
   Recently Viewed) · Form I-9 · Reporting (Analytics) · Platforms (ScreeningDirect).
   Top: "My Background Checks ▾", Help & Resources, bell, account name (Rafael / Alphalete…).
   **Invite Candidate** → `#/start-order/?orderPage41=start-order`, heading **"New Order
   Settings"**, steps **Order Settings → Summary**, "Reset" link, **Next** button (bottom
   right). Fields, "Select from the following options:" (Megan screenshot 11/4):
   - Account — prefilled `Alphalete Marketing, Inc.` (leave)
   - Workflow — prefilled `Consent Plus` (leave)
   - **Position** — empty dropdown → pick the Elite one
   - **Screening Package** — greyed until Position is picked → pick the Elite one
   - Billing Code — greyed, prefilled `1658411` (Raf's) → nothing to do here (leave; stop if blank)
   - **Location of Job/Position** — ONE text box (not separate state/city); filled it reads
     **"Plano, TX, USA"** — a TYPE-AHEAD: type the city, a suggestion list pops up, click the
     one for the office's state (Megan 11/4; none matching = stop) →
     `sterling_send.pick_location_suggestion` /
     `sterling_send.location_text` / `location_matches`
   - Once Position + Package are set, a **"Package Details"** panel appears on the right
     (SSN Trace, County Criminal, Statewide Criminal, DOJ Sex Offender Search, Extended
     Global Sanctions, Locator Select, Client Matrix Application…) — proof the page took it.
   - Billing Code shows an ✕ (clear) when set — never press it.
   - Projected Salary — prefilled `Unable to provide salary` (leave)
3. Workflow **Consent Plus** (normal) · **Position** = the Elite one · **Package** = the Elite
   one. Options are three: Drug Screen, NBR, Elite (some owners: "Elite / Extra").
4. **Location** = the office's state + city (the one-time Office Settings answer).
   - **Next** → review page **`#/start-order/?orderPage41=review-order-settings`**: the package's
     searches listed again, "Privacy Statement" on the right; at the VERY BOTTOM an
     **"Add Candidate"** card (Megan screenshot 11/4):
     - "Important Disclosures" (collapsible)
     - two tabs: **Send Invites** | **Bulk Upload** ← pick Bulk Upload
     - "Please attach up to 5,000 candidates (first name, last name, email address) in CSV
       format." + "Note: All fields collected under Order Settings will be applied to every
       candidate."
     - **CSV Template** button (download) · drop zone **"Drag here or click to browse for a
       file"** (10 MB limit) → the bot sets the file on its file input
     - **Send Invites** button, bottom right — greyed until a file is attached ← THE send
   - After the file is attached (Megan 11/4): the drop zone becomes a file card
     (`template.csv`) and the text reads **"Bulk candidates uploaded: N found"** (N is a link)
     → the bot checks N == rows it wrote before pressing Send (`check_found`).
   - After **Send Invites**: pop-up **"Your Bulk Upload is Processing"** — "Your file has been
     submitted. A confirmation email will be sent momentarily." — **OK** button. = proof of
     submit. (No confirmation email had reached raffi127 by 11/4 4pm; per-person "E-Invite
     for X is Complete" mails arrive as each one finishes.)
   - **What the applicant gets** (Megan's own test, 11/4 4:09 PM — same minute as the upload):
     from `noreply@us.fadv.co`, subject **"On behalf of Alphalete Marketing, Inc.: You have been
     assigned a task"**, "Dear <First>,", a **Get Started** link, note that mail may come from
     @fadv.co / @fadv.com / @sterlingcheck.com. (So recruiters' "check for the First Advantage
     email" line matches.) Not caught by the code-forward filter (subject differs) — stays private.
   **Route fully mapped AND driven by the bot 11/4** (try_here on Megan's Mac, stopped
   before Send). See "Live-run findings" at the bottom.
5. **Next** → **bulk upload**: the **CSV Template** is exactly `First,Last,Email` + CRLF (downloaded
   11/4, copy: `client-hub-template.csv` here — NOT "First Name…" as the video says) — fill it,
   upload, send to everyone at once (`sterling_send.build_csv`).
_Still to map:_ every Client Hub screen (selectors), the
upload control, the send button, the success screen, Bill Code (not mentioned in the video).

## 4. After Invite — the E-Invite form

Correction (Megan 11/3, screenshot): Invite does NOT send by itself. It opens
**`https://secure.sterlingdirect.com/sys/bgchecks/default.aspx`**, breadcrumb
"Screening » E-Invite »", title **"Invite an Applicant for Background Screening"**.
Nothing is sent until this form is submitted. (* = required)

**From Information** — prefilled from the account:
- *From Name (`Rafael Hidalgo`) · *From Email Address (`raffi127@gmail.com`)

**Applicant Information**
- *First Name · *Last Name — blank, must be typed (V2 calendar's one Name column must
  be split right — matters here)
- *Email Address — prefilled with the email typed on the home page
- *Confirm Email Address — blank, type it again
- *Location of Job/Position — Country [United States ▾] · State [`<state>` ▾] · City [text]
  → **the OWNER's office location**, entered ONCE per office on the admin page ("Where is
  your office?", 'Office Settings' tab), editable with Change, sent with every job
  (Megan 11/3). Section 1 settled.

**Order Information**
- *Bill To [`-> Alphalete Marketing, Inc.` ▾] — prefilled
- *WFD Workflow [`Consent Plus` ▾] — prefilled
- *Job Position [`<select Job Title>` ▾] — must pick
- *Screening Package [`<Select a package>` ▾] — must pick
- *Charge Type [`Invoice Account` ▾] — prefilled
- *Bill Code [`<select billcode>` ▾] — must pick
- A La Carte [`<add search>` ▾] — optional
- ☐ Create International Education Searches… · ☐ Create International Employment Searches…
- Completed Report To: (textarea, one address per line) — optional

→ **Section 2 rule (Megan 11/3):** Bill To, WFD Workflow, Charge Type come PREFILLED on each
ICD's own account — the bot never touches them (but stops + reports if one is ever blank).
A La Carte, both International checkboxes, Completed Report To: left alone. The bot only
picks **Job Position = the ONE option containing "Elite"** — "Sterling - Elite" on
some ICD accounts, "Sterling Elite / Extra" on others, ~3 options total (Megan 11/4); none
or two = stop, **Screening Package = the ONE option containing "Elite"** (same rule, Megan 11/4)
(picking it lists the package's searches: SSN Trace, County Criminal, Statewide Criminal,
Auto County/State, DOJ Sex Offender, Extended Global Sanctions, Locator Select, Client
Matrix Application, Criminal Enhanced Nationwide), **Bill Code = the ONLY option that
appears for that office** (1658411 on Raf's) — none or several = stop, never guess.
Code: `sterling_send.JOB_POSITION / SCREENING_PACKAGE / pick_bill_code`.

Several people, old form (Raf's Loom): press **Send a New** — Location and everything below
stay, only First/Last/Email clear.

**Drug Screen Information** — table (Source · Test Type · Registration Method · Reason For
Test · COC/Site/Kit · App Notify · Action), "No Records Found."

_Still to see:_ the bottom of the form (the submit button's label), the success page, and
Sterling's "already invited" refusal (Sterling won't invite the same email twice — Megan).
Per-office picks to learn: Job Position, Screening Package, Bill Code, State, City.

## Live-run findings (bot dry run on Megan's Mac, 2026-11-04)

Result: `{"status": "dry_run", "would_send": ["Megan Hidalgo"], "found": 1, "location": "Plano, TX, USA"}`.
What the real pages needed, all now in `automations/icd_alerts/sterling_send.py`:

- **"Multiple user alert"** after the code (`secure.sterlingdirect.com/oidc/idpresponse`):
  "This username is already in use. Would you like to disconnect them so you can login?"
  → **Yes** (Megan). ONE session per username: it signs out whoever else is in.
- Login → code → portal: the address stays `auth.sterlingcheck.app/oauth2/login` through
  password AND code (single-page) — don't judge progress by the URL there.
- Client Hub can be opened directly (`#/start-order/?orderPage41=start-order`) once signed in —
  the portal banner isn't needed (it swapped/closed the window once). Its dropdown lists load
  a few seconds AFTER the page draws: wait, then click the box's input.
- Dropdowns are react-select: wrapper `[data-testid="selectDropdown-<key>-wrapper"]`, input
  `#<key>-input`, options `.list__option` (each name appears twice in the DOM — dedupe),
  chosen value in hidden `input[name="<key>"]` (keys: position, screeningPackage, billingCode).
- Location `#locationOfEmployment` only reacts to REAL keystrokes; suggestions are
  `.locationSuggestion[role=option]` reading "**Plano** TX, USA" (no comma before the
  state); after the click the box reads "Plano, TX, USA".
- Osano cookie banner shows on Client Hub too (Deny Non-Essential).
- The review page has TWO hidden file inputs: the first is an **"Attachments"** section — never
  that one; the CSV goes in `input[type=file][accept*=".csv"]`. Then "Bulk candidates
  uploaded: 1 found".
- Still unseen working: pressing **Send Invites** (watch the first live job).
