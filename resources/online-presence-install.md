# Online presence install — the Zoom checklist

Lucy runs an ICD office's **own** socials and **own** Google reviews. One Slack room per
office holds both: photos to post, and review replies waiting on an approver.
Code: `automations/online_presence/` (rows in `offices.json`), reusing
`automations/brand_audit/` (photo screen + edit + caption, review voice, Zoho driver).

**Everything starts dry.** Nothing posts until the office's row says `"mode": "live"`
AND the run is started with `--live`.

## Before the call (us, ~10 min)

1. **Slack room:** create `#<office>-online-presence`. Invite **Lucy Reporting**
   and **@hubposter** (the bot opens the photos), plus the owner and approvers.
2. **Zoho account:** make a free Zoho Social account for the office, with its own email.
   Lucy can't create accounts, so a person does this. Keep the login for step 5.
3. **Office row:**
   ```
   python -m automations.online_presence.setup add --office <key> --name "<Business name as on Google>" --room "#<office>-online-presence" --approvers "<Name>, <Name>" --email "<complaints email>" --timezone "America/Chicago"
   ```
   `<key>` = the office's ECO key (same as `icd_alerts/offices.py`). Names resolve from
   `resources/owner-slack-ids.md` first; anyone not there needs their Slack id.

## On the call (owner)

4. **Google listing → Manager.** Owner opens Google Business Profile → ⋮ → Business
   Profile settings → People and access → Add → `alphaletemarketing@gmail.com` →
   **Manager** (not "Site manager", which can't reply through the API). The listing must be **verified**.
5. **Connect socials in Zoho.** Owner signs into the office's Zoho (the login from step 2),
   Settings → Channels, and connects their Instagram, Facebook Page, Google Business
   Profile, LinkedIn **company page**, X. Lucy never posts to a personal LinkedIn.
6. **Ask, and record in the row:**
   - Business name exactly as it shows on Google.
   - Email for complaints (negative reviews are invited to write there).
   - Who approves posts and replies (Slack names).
   - Which socials they have.

## Right after (us)

7. Accept the Google invite and link the listing:
   ```
   python -m automations.online_presence.setup invites --accept
   python -m automations.online_presence.setup link-google <key>
   ```
8. Lucy's own Zoho login, on the Lucy that will run it. This opens a visible window, once.
   Sign in, handle the code, then create the `.stop` file it prints:
   ```
   python -m automations.brand_audit.zoho_draft --login --office <key>
   ```
9. The checklist. Everything ✅ except Mode = ready for a dry run:
   ```
   python -m automations.online_presence.setup check <key> --zoho
   ```
10. Dry run. It reads the room and the reviews and prints what it *would* do:
   ```
   python -m automations.online_presence.run --office <key>
   ```

## How the room works

**Photos:** someone drops a photo → Lucy screens it (no alcohol, smoking, gang signs,
cash, weapons, profanity) → asks who/what/when if it's missing → posts the edited photo
and a caption → an approver reacts ✅ / ❌ (+ a note to fix it) / 💀 never post →
out at the office's next slot, one a day, 8am–6pm office time → 🚀 on the original.
Free Zoho may not schedule; then Lucy publishes it herself inside that window.

**Reviews:** 4–5★ get an automatic reply (capped at 10 a day per office). Anything
under 4★ waits in the room for ✅ / ❌ (+ a note). Every reply signs off with the office's
own name. Complaints are pointed to the office's own email, never to Alphalete's.

**Approvers:** only the people named in the row count. If nobody is named, Megan and Eve
approve. A rep's ✅ on their own photo never publishes it.

## Not done yet (before the first office goes live)
- Hub card + a scheduled run (noon/4pm like the social scanner) on the Lucy holding the Zoho logins.
- The sign-up form doesn't ask the step-6 questions yet; we collect them on the call.
- Not proven on a real ICD listing yet. The first owner's Manager invite is the test.
- Zoho Agency (10 brands, one login) would need brand switching in the Zoho driver.
