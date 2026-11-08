# LucyECO Social: enrolling an ICD office

Lucy runs an ICD office's **own** socials and **own** Google reviews.
- **The ICD owns their Zoho Social:** they make it, they pay for it, and they connect their pages to it.
- **The post goes out from the ICD's own office computer** (their ECO machine), from their Zoho.
- **One Slack room per office** holds both photos and review replies.
- **Lucy 3 does the thinking:** photo check, edit, caption, approvals and review replies.

Code: `automations/online_presence/` (rows in `offices.json`) + `automations/icd_alerts/social_post.py`
(the office-computer half), reusing `automations/brand_audit/`.

**Everything starts dry.** Nothing posts until the office's row says `"mode": "live"` AND the
run is started with `--live`.

## What the ICD does

**Before the call:** fill in the sign-up form at **lucyeco.streamlit.app/join-lucyeco-social**
(link only, not on the front page). It asks:
- Their name and email.
- **Business name, office address, company phone, company website, and their Google listing link**
  (Google Maps → Share → Copy link). These are the TRUTH: every audit checks Google, their website,
  Indeed and Glassdoor against them and flags anything that doesn't match. The Google link is also
  what picks THEIR listing; a name could match two offices.
- Their Indeed and Glassdoor pages, if they have them (optional).
- **Which pages Lucy should post to:** a checkbox each for Instagram, Facebook, Google, LinkedIn and X.
  Ticking one opens a box for the link to THAT profile (Google uses the listing link). Lucy posts ONLY
  there, only DMs them when one of THESE disconnects, and every audit checks their website links to
  those exact accounts.
- Who approves, an email for customer concerns, and their timezone.
- **"Do you already have a Slack channel for your social media / branding?"**
  - **Yes:** a box opens for its Channel ID (a pasted Slack link works too). They add Lucy Reporting.
  - **No:** Lucy creates a **private** channel in our Slack named `<company-name>-lucyeco-social`
    (e.g. `#palace-acquisitions-lucyeco-social`) on her next pass (`python -m automations.online_presence.rooms --live`,
    also run at the start of every `online_presence.run --live`). She adds Megan, Eve, the ICD who
    enrolled, Lucy, the Lucy app and @hubposter, and writes the Channel ID back onto their sign-up.
    Anyone she can't match to a Slack ID is listed, never guessed.

Answers land as PENDING on the **LucyECO Social Signups** tab of the relay workbook. Nothing turns on.

**On the call (~25 min), on their office computer, with us walking them through it:**
1. **Make their Zoho Social account** at zoho.com/social with the **email they already use**
   (no new email for anyone to keep track of). They put **their own card** on it: Standard is
   $10/mo billed yearly, $15 month-to-month, and there's no free plan after the 15-day trial.
2. **Connect their pages in Zoho:** Settings → Channels → connect each page from their answers
   (Instagram, Facebook Page, Google Business Profile, LinkedIn **company** page, X).
3. **Google listing → Manager.** Google Business Profile → ⋮ → Business Profile settings →
   People and access → Add → `alphaletemarketing@gmail.com` → **Manager**, not "Site manager".
   The listing must be verified.
4. **Sign Lucy's window into Zoho.** We send `zoho-signin`, a Zoho window opens on their
   screen, they sign in with the account from step 1, and it closes itself. Lucy never sees the
   password. Zoho's sign-in codes go to THEIR email; if Zoho ever signs them out, Lucy DMs them.

## What we do

Before the call:
- The Slack room: theirs (from the form), or the one Lucy made for them. Either way **Lucy
  Reporting** and **@hubposter** (opens the photos) must be in it; `setup check` confirms both.
- Add the row straight from their form (anything typed on the line wins over the form):
  ```
  python -m automations.online_presence.setup add --office <key> --from-signup "<Business name>"
  ```
  `<key>` = the office's ECO key. Names resolve from `resources/owner-slack-ids.md` first.

On the call:
```
python -m automations.online_presence.setup zoho-signin <key>        # step 4: Zoho opens on their screen
python -m automations.online_presence.setup invites --accept         # after step 3
python -m automations.online_presence.setup link-google <key>
python -m automations.online_presence.setup audit <key>              # every site vs their sign-up answers
python -m automations.online_presence.setup check <key>              # everything ✅ but Mode = ready
python -m automations.online_presence.run --office <key>             # dry run: prints what it WOULD do
```

## How it runs, day to day

**Photos**
1. Someone drops a photo in the room.
2. Lucy screens it (no alcohol, smoking, gang signs, cash, weapons, profanity) and asks who/what/when if that's missing.
3. Lucy posts the edited photo and a caption.
4. An approver reacts ✅, ❌ + a note, or 💀.
5. On ✅, Lucy queues it to the office's computer: one a day, 8am–6pm office time.
6. The computer posts it from the ICD's Zoho to their chosen pages, and 🚀 goes on the original.

**Disconnects**
- Once a day, mid-day, the office computer reports which pages its Zoho still has.
- If one of the **chosen** pages is missing, or Zoho signed out, Lucy DMs the owner.
- That DM goes once a day at most, and says exactly what to reconnect.
- A post that couldn't go out says so in its thread and goes out once it's fixed.

**Reviews**
- 4–5★ get an automatic reply, capped at 10 a day.
- Under 4★ wait in the room for ✅ / ❌.
- Replies sign off with the office's name, and complaints go to the office's own email.

**Approvers:** only the people named count. If nobody is named, it's Megan and Eve.

## Before the first office goes live
- **Deploy the relay** (`resources/icd-alerts-relay.gs`: new job kinds + the Drive photo folder) and
  **release the agent** (bump `automations/icd_alerts/agent_release.txt`) so office computers get
  `social_post.py`. Both need Megan's go.
- Confirm Zoho's channel names on the first real `zoho-signin` (the check prints them). The page
  mapping (`zoho_draft.page_of`) is a best guess until then.
- Hub card + a scheduled `online_presence.run --live` (noon + 4pm like the social scanner).
- The form page goes public when the `site` branch is next promoted (hourly), not on push to main.
- Indeed + Glassdoor are **check by hand** in every audit: both block robots and we don't get around that.
- Prove Google on the first real ICD listing (their Manager invite).
