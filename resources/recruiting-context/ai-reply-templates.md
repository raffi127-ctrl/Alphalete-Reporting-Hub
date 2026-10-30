# AI reply templates — one per question applicants actually ask

> ## ⚠ DRAFT — needs Megan's sign-off before anything goes into AppStream
>
> Same status as [booking-call-rubric-DRAFT.md](booking-call-rubric-DRAFT.md):
> this is **copy for review, not a deployment**. Nothing here has been
> written into any office's AI Settings. Preview target when it is
> approved: **11280 only**, then roll out.
>
> Requested by Megan 2026-10-26: response defaults for the ApplicantStream
> AI, *"for EVERY office — an office sets up its profile and then we can
> plug and play in the generic templates."*

## Why this exists

The AI books **55% of first interviews on 11280**, at a median **3.7h**
against ~12h for every human recruiter, so its wording *is* most of the
applicant experience. And engagement is the strongest show-up predictor we
have measured: applicants who texted back show at **46–61%**, against
**23%** for those who never did (p=2e-18). A question that gets a real
answer keeps them engaged; one that doesn't mostly ends them.

Measured over the week to **2026-09-25**, all four live accounts
(11280 / 11580 / 23965 / 24065 — 4,832 conversations, 34,374 log rows):

| What happened to an applicant's question | Count | Share |
|---|---|---|
| Got a real answer | 293 | **36%** |
| Got a typed reply that didn't answer it ("Awesome!", "Yes") | 376 | 47% |
| Got nothing back at all | 134 | 17% |
| **Total questions asked** | **803** | |

Source: `analyze.question_responses(recs, convos)` over
`output/sms_thread_dump_<office>_w0925.json` +
`output/sms_log_<office>_w0925.json`, the same function the weekly ACA
report publishes. Buckets are `analyze.QUESTION_BUCKETS` — the existing
15, unchanged.

---

## Rules every template below obeys

From [megan-overrides.md](megan-overrides.md) — it **wins** over the ARS doc.

1. **Never the word "base"** about pay. Weekly range only.
2. **Range only, never an hourly figure** (Megan 2026-10-26). So
   `{{pay_low}}–{{pay_high}}` weekly; the ARS doc's $16–$21/hr training
   figure is **out** of texts — applicants read it as the whole job's pay.
3. **Role first, then address**, sentence case, and don't pivot straight
   into asking for their email.
4. **Never push a job fact to the hiring manager.** Pay, door-to-door,
   remote/location, hours and role all have approved answers.
   *Logistics* we genuinely can't fill may escalate; job facts may not.
5. **Never all-caps** the company, address or role.
6. **One address per office, every stage** — 1st and 2nd round alike.
7. **The first interview is always a group.** Lead with yes, then soften.
8. **Escalation is the handoff — never put a clock on a call.** Say we
   will call; never "shortly"/"soon"/"today", and never ask them to pick
   a time. Nothing holds either promise.
9. **Answer, then reassure.** Every approved script ends with a question
   back ("Is that something you're okay with?"). Replies Megan accepted
   run 235 characters at the median; ones she rejected, 117.
10. **Compliance, no exceptions:** never state or imply age, gender, or
    "who we hire". [[feedback_recruiting_copy_compliance]]
11. Activated/blast templates carry **"Reply STOP to opt out"**
    (AppStream deliverability checklist item 3). Conversational replies
    don't need it.

---

# The templates

Ordered by how often the question is actually asked. Per-office counts are
given where offices differ enough to matter.

---

## 1 · Can we reschedule / a different time?

**Asked 339×** — 42% of every question, and the biggest single thing the
AI handles. 11280 166 · 11580 82 · 23965 46 · 24065 45.
**Only 56 answered. 228 got a typed non-answer. 55 got nothing** (13 of
those never booked).

**Today**, the most common real reply is `"Yes!"` — and the most common
non-answer is the recruiter proposing a time without confirming the old
one is released: *"I hope everything is okay. Can you hope make it into
the office at the same time tomorrow instead?"* (typo theirs, sent 10×).

**The fault:** a bare "Yes!" to "can we move it?" leaves the applicant not
knowing *when* they are now booked. This bucket is `judgeable: False` —
there is no answer vocabulary for it, so the audit can't currently score
it either.

> **Template**
>
> Of course, {{name}} — happy to move it. I have {{slot_a}} or
> {{slot_b}} open. Which works better for you?

> **Once they pick**
>
> Locked in for {{chosen_slot}}. Your old time is released, so
> {{chosen_slot}} is the one to come to. {{r1_mode_line}}

`{{r1_mode_line}}` resolves to `Here's your Zoom link: {{zoom}}` or
`We're at {{address}}.`

**Never:** confirm a new time without saying the old one is released.

---

## 2 · Is this remote / where is the office?

**Asked 101×.** 11280 70 · 23965 12 · 24065 10 · 11580 9.
71 answered, 16 got nothing.

**Today:** *"Our main headquarters are located in Irving, but we have
positions available throughout the DFW."*

**The fault:** it leads with the headquarters and never names the role, so
it inverts rule 3 — and "throughout the DFW" leaves an applicant unsure
whether they're driving to Irving or somewhere else.

> **Template**
>
> You applied to our open {{role_title}} position, and it's in person —
> not remote. Our office is at {{address}}. Does that work for your
> commute?

**Spanish (pack 5):**
> Aplicaste a nuestra posición de {{role_title}}, y es presencial, no
> remota. Nuestra oficina está en {{address}}. ¿Te queda bien para
> llegar?

> **⚠ BLOCKED on the address value — this template cannot send yet**
>
> `{{address}}` has **four** candidate values and I will not guess one:
>
> | Source | Says | In the week to 9/25 |
> |---|---|---|
> | megan-overrides.md, 2026-09-27 "definitive" | 3100 Premier Drive, Suite 207, Irving | 347 sends with the full street |
> | Bare city in live replies | Irving | 552 sends |
> | Live Indeed ads | Frisco, TX | 392 sends — but **almost all inside ad titles** ("role in Frisco, TX") |
> | AppStream AI Settings | 5217 Tennyson Pkwy Suite 100, Plano | 14 sends, also inside ad titles |
>
> My data is **pre-move** (week to 9/25; the Irving→Frisco move was
> ~2026-09-30) so it cannot settle this. And Megan's own doc warns that a
> message naming the job ad's city is quoting the *posting*, not directing
> anyone anywhere — which is what the Frisco and Plano counts mostly are.
>
> Megan answered 2026-10-26 that **the address differs per account**, so
> each profile carries its own. Still needed, one line each:
> **11280 · 23965 · 24065**. 11580 stays
> *1901 N Highway 360, Suite 610, Grand Prairie* per her 2026-09-27
> ruling. If the move is live, `megan-overrides.md` ruling 6 goes stale
> and I'll update it in the same pass.

---

## 3 · How do I join the Zoom / link trouble?

**Asked 90×.** 11280 42 · 23965 20 · 11580 14 · 24065 14.
**Only 16 answered — 60 got a typed non-answer, 14 got nothing.**

**Today:** the commonest "reply" is a bare `"Meeting ID: 293 507 7152"` —
an id with no link, sent to someone who already said the link won't open.

**The fault:** this is the worst answer-rate of any high-volume bucket
(18%). An applicant stuck outside the Zoom is minutes from giving up, and
a meeting ID alone doesn't get them in.

> **Template**
>
> Here it is, {{first_name}} — {{zoomlink1}}. You're set for {{booked_slot}}.
> Can you hop on a couple of minutes early to make sure you have a good,
> clear connection?
>
> *(won't open)* Let's get you in — try this one: {{zoomlink1}}. If it still
> won't open, tell me and I'll pass it to {{escalation_name}} to help you
> troubleshoot.

**Never:** send the ID without the link. **Never** put a time on the call.

---

## 4 · Which role / which company is this?

**Asked 74×.** 11280 50 · 24065 14 · 23965 6 · 11580 4.
59 answered, 9 got nothing (6 never booked).

**Today**, two replies tie — one good, one a rule-4 breach:
- ✅ *"My apologies; this is with Alphalete. We received your resume via
  LinkedIn for our Entry-Level Marketing role. Do you remember applying
  for that position?"*
- ❌ *"The Hiring Manager can provide more details about the role. What's
  the best email to send your interview link and details to?"*

> **Template**
>
> Sorry for the confusion — this is {{company_name}}. You applied to our
> {{role_title}} role{{via_source}}. Does that ring a bell?

`{{via_source}}` → ` via {{source}}` when the application source is known,
else empty.

**Never:** all-caps the company name (rule 5 — 72 sends shouted it).

---

## 5 · When will you call me / what number?

**Asked 47×.** 11280 36 · 23965 8 · 11580 2 · 24065 1.
15 answered, 24 non-answers, 8 nothing.

**Today:** *"WE will call shortly"* — which breaks **two** rules at once:
all-caps (5) and a time word on a call (8). An applicant last week:
*"Excuse me but no one called me. I waited for over an hour. I am no
longer interested."*

> **Template**
>
> Of course — I'll have {{escalation_contact}} from our team give you a
> call. It'll come from {{phone}}, so you'll know it's us.

**Never** "shortly", "soon", "today", "within the hour". **Never** ask
them to pick a time — nothing in the system holds it.

---

## 6 · What is the job / what do you do?

**Asked 39×.** 11280 26 · 24065 8 · 11580 3 · 23965 2.
26 answered, 9 got nothing — **7 of those never booked**, the worst
never-booked count in the set.

**Today**, the good reply is long and concrete; the bad one is
*"Those are questions the Hiring Manager can answer accurately. I'll have
them reach out to you directly."* — rule 4.

> **Template**
>
> You'd be working with our {{clients}} client on customer service, new
> sales and upgrades. {{campaign_line}} Full training is provided and
> every role is entry level. Is that the kind of work you're after?

`{{campaign_line}}` by pack:
- **D2D** — "This is residential: we visit customers from a list who've
  asked for help, so it isn't knocking random doors."
- **B2B** — "You'd be meeting business owners and decision makers."
- **In store** — "You'd be on the floor inside one of our partner stores."
- **In office** — "You'd be desk-based at {{address}}."

**Never:** say "door to door" without the leads clarification — it's the
single phrase that loses this bucket.

---

## 7 · What is the pay?

**Asked 39×.** 11280 23 · 24065 6 · 11580 5 · 23965 5.
24 answered, 6 got nothing.

**Today**, the joint-commonest reply is the rule-4 breach
*"The Hiring Manager can answer compensation questions. What's the best
email to send your interview link and details to?"* — and 11580 has its
own version: *"I can help with scheduling and logistics, but details like
pay structure are handled by our HR manager."*

**Settled 2026-10-26:** a figure **is** allowed in a text — the
booking-call rubric's red flag is call-only. **Weekly range only; never
the hourly training figure.**

> **Template**
>
> On average our team earns {{pay_low}}–{{pay_high}} a week, plus bonuses
> and commission, depending on background and experience. Was there a
> specific range you were looking for?

**Never:** the word "base" (25 sends did, all human). **Never** an hourly
figure. **Never** push it to the hiring manager.

---

## 8 · I can't make it / I'm sick / running late

**Asked 17×** (11280 15). **Only 2 answered; 11 non-answers, 4 nothing.**

> **Template**
>
> No problem at all, {{name}} — thanks for telling me. Would
> {{slot_a}} or {{slot_b}} be better? If you'd rather sort it out once
> you're feeling better, just text me when.

**Never:** make them justify it, and never ask for proof.

---

## 9 · Are you there? (chasing us for a reply)

**Asked 14×.** **1 answered. 11 non-answers, 2 nothing.**

This bucket is pure symptom: they only send it because we went quiet.
Every hit here is a reply we already owed.

> **Template**
>
> I'm here — sorry for the wait. {{answer_to_their_last_question}}

**Rule:** never answer this one on its own. Resolve the question *above*
it; if there isn't one, escalate rather than send "I'm here" alone.

---

## 10 · Hours, training, is it paid?

**Asked 13×.** 10 answered, 3 nothing. Best-performing bucket at volume.

> **Template**
>
> Shifts run {{shift_start}}–{{shift_end}}, {{shift_days}}, and it's
> {{full_or_part}} in person. Training is paid and starts on day one. Did
> you have a schedule in mind?

**Never:** quote the hourly training figure here either (rule 2).

---

## 11 · How long is the interview / what's next?

**Asked 12×.** 9 answered.

**Today:** *"A quick 15-20 minutes"* — fine, and worth keeping.

> **Template**
>
> About {{interview_minutes}}. It's a small group interview over
> {{r1_mode}}, and if it goes well the next step is a 1-on-1 at
> {{address}}. Anything you'd like to know before then?

**Note:** says *group* for round 1 and *1-on-1* for round 2 — rule 7, and
the distinction Megan caught being audited wrongly.

---

## 12 · Is this a real job / who are you?

**Asked 9×. ZERO answered.** 6 non-answers, 3 nothing — and **all 3 never
booked**. 100% loss on the bucket whose whole question is trust.

**Today:** *"I'm with ALPHALETE MARKETING, INC. What's the best email to
send your interview link and details to?"* — shouting the company name at
someone asking if you're a scam, then immediately asking for their email.

> **Template**
>
> Completely fair to ask. I'm {{ai_name}} with {{company_name}} — our
> number probably isn't saved in your phone. You applied to our
> {{role_title}} role. Our office is {{address}} and you can look us up
> or call {{phone}}. Want me to have {{escalation_contact}} call you
> instead?

**Never** all-caps. **Never** ask for an email in the same message.

**⚠ Platform blocker:** the `Mentions "Scam"` escalation row is
`Silent Only` on 11280, so **the AI sends nothing here no matter what we
write**. A message is already saved on that row and will never fire.
Routing has to change before this template does anything.

---

## 13 · I never got the email

**Asked 4× (all 11280). ZERO answered** — 2 non-answers, 2 nothing. One
"reply" is just the applicant's own address echoed back.

> **Template**
>
> Let me re-send it now — check spam and promotions too, it hides there.
> It comes from {{sender_domain}}. Is {{email_on_file}} still the best
> address? I'll text you the Zoom link as well so you don't need the
> email: {{zoom}}

**The point:** don't make the email the only path. Texting the link
removes the dependency entirely.

---

## 14 · What should I wear / bring?

**Asked 4×. 4 answered, 0 missed** — the only clean bucket. But both real
replies are generic pleasantries that happened to pass, so there's no
approved copy to inherit.

> **Template**
>
> Business professional — a suit if you have one. Bring two forms of ID,
> a notebook and a pen. {{r1_mode_note}}

`{{r1_mode_note}}` → for Zoom: "Somewhere quiet with a steady signal is
all you need for the first one." For in person: "We're at {{address}}."

**Note:** "a suit if you have one" deliberately softens the BOB script's
"full suit and tie" — that script is for someone already hired, and a
first-round applicant who doesn't own one shouldn't self-reject.

---

## 15 · Am I still being considered?

**Asked 1×. ZERO answered** — and they never booked. Lowest volume, but a
100% loss on the one question where silence is the cruellest answer.

> **Template**
>
> You are, {{name}} — you're still in the process. The next step is
> {{next_step}}, and I'll have {{escalation_contact}} follow up with you
> directly.

**Never** leave this unanswered, and never answer it with a template
blast. If the status genuinely isn't known, escalate — a guess here is
worse than a handoff.

---

## What I need from Megan

1. **The address for 11280, 23965 and 24065** (one line each, suite
   included). Template 2 cannot send without it. If Frisco is live, I'll
   update `megan-overrides.md` ruling 6 in the same pass.
2. **Two platform blockers** need an eStream/routing change, not copy:
   `Mentions "Scam"` and `Non-English Language Detected` are both
   `Silent Only`, so template 12 and any Spanish variant cannot fire
   however well they're written. Want me to raise these?
3. **Spanish:** applicant copy here is plain English, with full Spanish
   where an office recruits in it — not the English-with-a-Spanish-phrase
   voice, which is your rep-facing Lucy rule.
   [[feedback_lucy_spanish_phrases]] Say the word and I'll switch it.
