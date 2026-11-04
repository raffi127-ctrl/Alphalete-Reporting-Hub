# AppStream AI voice calls: our review and the flow we want

**Session record, 2026-10-27 to 2026-11-03.** AppStream is rolling out AI voice
calls (the agent is "Lucy"). Megan shared the 24065 script and asked to pick it
apart against everything we know about recruiting and the applicant experience.

- Their script, verbatim: [ai-voice-call-script-ORIGINAL-2026-10-27.md](ai-voice-call-script-ORIGINAL-2026-10-27.md)
- Our full review + rewrite: below (also in `output/ai-call-script-review-2026-10-27.md`)

## Decisions Megan made in the session

- **Do NOT add an AI disclosure.** Item "says it's AI only if asked" was
  disregarded (Megan: "5- disregard"). Lucy introduces herself as "Lucy with
  Alphalete Marketing", no "AI assistant". Don't re-raise it.
- **Ruled: wanted the flow as short steps**, not full scripts, when asked for "the flow".

## The flow (the short version Megan asked for)

1. Greet and confirm it's them
2. Say why you're calling and ask for a minute
3. Offer times, soonest first
4. Book it
5. Confirm the email
6. Say what's next and ask them to reply to the text
7. Close with a recap

No answer: voicemail with the callback number, then a text.

## Still open (only Megan can answer)

- Is 24065's address now 5217 Tennyson Pkwy, Suite 100, Plano (like 11280
  since 10/2)? The offices tab cache still has 24065 at 3100 Premier Dr, Irving.
- Is the 1st-round interview 20 minutes?
- The 7 eStream questions at the bottom: not sent yet as of this record.

---

# Full review + rewrite (2026-10-27)

Source reviewed: `~/Desktop/Alphalete_AI_Call_Script_2026-10-27.md`
Checked against: `resources/recruiting-context/` (megan-overrides.md, ars-processes-2026.md
Opens Scripts / Rebuttals / Voicemails, first-round-booking-call.md, appstream-ai-settings.md,
booking-call-rubric-DRAFT.md), the offices tab cache (`automations/sms_audit/offices`), and
the SMS/call/booking audits (see memory: applicant SMS audit, Ringover call audit, AppStream
audit data model).

## What the data says moves show-up

This decides what is worth changing.

| Lever | Evidence | Matters? |
|---|---|---|
| Wording of the booking call | 857 recorded human booking calls graded on 16 items: **nothing said predicted show-up** (51.9 vs 51.1, p=0.09) | Low. Fix what is wrong, then stop polishing. |
| How far out the slot is | 7,951 bookings: under 24h **50.6%** vs 24h+ **38.6%** (p=1e-13); 11280 same-day 57% / next-day 42% | **High** |
| Whether the applicant texts in | texted in 46–61% vs never texted **23%** (p=2e-18) | **High** (correlation, so it needs a test) |
| Who books (AI vs human) | 46% vs 48%, p=0.70 | None |
| Phone-booked vs text-booked | 14% vs 47%, mostly because silent applicants are the ones who get booked by phone | The AI call will mostly reach this weaker group |

So the order is: **(1) wrong facts and legal gaps, (2) same-day booking and getting a reply text, (3) wording.**

---

## 1. Must fix: wrong, against a ruling, or a legal exposure

| # | Script says | Problem | Fix |
|---|---|---|---|
| 1 | Pay, hours, duties: "the hiring manager goes over that in the interview" and **ends the call if they keep asking** | Breaks **ruling 4**: deflecting job questions is not acceptable (Megan rejected it in 35 of 38 cases). The AI already deflects 13x more often than people do by text. Hanging up on someone asking about pay throws away an interested applicant. | Give the approved answers (see the Q&A below), then "Is that something you're okay with?", then go back to the times. |
| 2 | "It's a Zoom video call **with the hiring manager**, about 20 minutes" | **Ruling 7**: the first interview is always a small group. "With the hiring manager" sounds one-on-one. | "It's about a 20-minute Zoom with our hiring manager. It's a small group interview." Also check 20 min against the office's AI Settings → "How long are your interviews?" |
| 3 | Address "5217 Tennyson **Parkway Dr**, Plano" | Real address is **5217 Tennyson Pkwy, Suite 100**, Plano TX 75024. The missing suite is the exact cause of last month's "Is it suite 232 or 207?" texts (AppStream has no suite field, eStream ticket open). **Also**, our offices tab still lists 24065 at the old Irving address. Ruling 6 says every Raf account uses one address, so 24065 is most likely Plano now. Confirm it. | Add the suite. Update the offices tab row for 24065 once confirmed. |
| 4 | Voicemail: "please give us a call back" | **No callback number.** Every ARS voicemail gives one. For an artificial-voice call, FCC rules also require the business's name at the start and a phone number in the message (47 CFR 64.1200(b)). | Add the office number, and say a text is coming (text is where bookings convert). |
| 5 | Spanish: "I just noticed a note on your file that my hiring manager wanted to talk with you" | **That's a made-up reason.** Some of Raf's ads say "Spanish Required", and Spanish is the #3 thing applicants text (6.7 per 1k). | Honest handoff: "No problem, I'll have someone from our team who speaks Spanish give you a call." No time word (ruling 8). Better still, ask eStream whether the voice agent can switch to Spanish. |
| 6 | "Don't call me again": polite goodbye | A goodbye alone doesn't stop the next AI call, SMS blast or call-list pass. | Must also mark the applicant do-not-contact in AppStream. Confirm with eStream that it does this. |

## 2. Structural: these move show-up

| # | Script says | Problem | Fix |
|---|---|---|---|
| 7 | Asks for **email before** offering times | Dani's sanctioned pitch and the ARS Opens script both lock the time first, then confirm the email. Asking for the email first adds a step before they've committed. | Order: intro → times → book → email → what's next. |
| 8 | None of today's times work: "I can give you a call tomorrow" | Turns a live, willing applicant into a callback that may never connect. Next-day bookings still show 42%, better than a missed callback. | Offer tomorrow's **earliest** 2 times. Use the callback only if they want 2+ days out (ARS: put on Hold). Leave the calendar on "today only" by default and show tomorrow only as this fallback. |
| 9 | Times offered in whatever order | Text bookings under 2 hrs out show **59%** vs 33% at 6–24 hrs. | Always lead with the soonest slot. |
| 10 | After booking: "You're all set for today at 1:45" | Doesn't say what happens next (rubric `what_next`, Dani's script). Nothing asks the applicant to do anything, yet applicants who text in show 2x as often. | "You'll get a text and an email with the Zoom link in a minute. **Can you reply to that text so I know it came through?**" Plus "hop on 5 minutes early." Run it as an A/B test, because the 2x is a correlation. |
| 11 | Wrap-up: "anything else?" | Opens questions after the booking is done. | Swap it for a recap: "Perfect, see you at 1:45 today, [first name]!" |
| 12 | Intro: "I just had a few quick questions for you" | Then it asks no questions, only for an email. "Questions" also sounds like screening. | Give the reason for the call the way Dani's script does: "our hiring manager asked me to get you set up for a quick Zoom interview." |

## 3. Smaller wording and setup checks

- **Persona name**: AI Settings rule. "Lucy" must match how 24065's texts are signed, and the escalation contact must be a different, real person. 11280 had Aisha vs Dani Pena.
- **Name the source**: "the application you sent on Indeed" helps with "don't remember applying" (1.1 per 1k, almost all Raf's accounts).
- **Spam answer**: add the ARS line: "Sorry about that, our office number probably isn't saved in your phone."
- **Already booked**: also confirm they have the Zoom link (ARS Zoom Confirmations script).
- **Callback time**: ruling 8 bans asking for a time that nobody tracks. Here the AI schedules its own callback, so it's fine **only if** AppStream really does call back at that time. Verify.
- **"A person will reach out"**: correct, with no time word (ruling 8). Confirm it creates a highlighted escalation in AppStream. Last month an applicant wrote "no one called me, I waited over an hour."
- **Driving**: don't push the "only takes a few seconds" line on someone who said they're driving. Go straight to the callback.
- **Time zone**: say "Central time" when the area code is outside Texas.
- **Kept as is (good)**: no "are you still interested", reads the email back, one question at a time, never picks a time for them, same-day calendar.

---

## Rewritten script

**Intro**
> "Hi, good [morning/afternoon/evening]! Is this [first name]?"
> "Hey [first name], this is Lucy with Alphalete Marketing. I'm calling about the application you sent in for our [job title] role. Our hiring manager asked me to get you set up for a quick Zoom interview. Do you have a minute?"

**Times** (soonest first)
> "I've got [soonest] or [next] today. Which works better?"
> None work → "No problem. I've got [tomorrow earliest] or [tomorrow next] tomorrow morning. Would one of those work?"
> 2+ days out → callback / Hold.

**Book**
> "Perfect, you're locked in for today at 1:45."

**Email** (after booking)
> "I've got [email] for you, is that still good?"

**What's next**
> "You'll get a text and an email in a minute with the Zoom link. Can you reply to that text so I know it came through? And hop on about five minutes early."
> "See you at 1:45, [first name]!"

**Q&A**: answer it, check in, then go back to the times. Never defer to the hiring manager.

| They ask | Lucy says |
|---|---|
| Pay | "We offer weekly pay ranging from $1,000 to $1,500 plus bonuses or commission. Does that work for you?" (Never "base". The paid-training $16–$21/hr line is also approved.) |
| Schedule | "Shifts run between 8am and 8pm, Monday through Saturday. Does that work for you?" |
| What's the job / is it sales | "It's customer service and sales with our AT&T client: new customers, upgrades and helping existing ones. Is that something you're comfortable with?" |
| Door to door | "We have different setups for the role, in office, in store or business-to-business, depending on the client. We work from leads, not random doors. Did you have a preference?" |
| No experience | "All of our roles are entry level, and we provide complete paid training." |
| Advancement | "Yes, we promote from within and train across every department." |
| Zoom or in person / group | "It's about a 20-minute Zoom with our hiring manager. It's a small group interview." |
| Address | "Our office is at 5217 Tennyson Parkway, Suite 100, in Plano." (once 24065 is confirmed) |
| Spanish | "No problem, I'll have someone from our team who speaks Spanish give you a call." |
| Scam / spam | "Sorry about that, our number probably isn't saved in your phone. You applied for our [job title] role on Indeed, and I'm just following up on that." |
| Real person | "Of course, I'll have someone from our team give you a call." (no time word) |
| Stop calling | Goodbye **+ do-not-contact flag in AppStream** |

**Voicemail**
> "Hi [first name], this is Lucy from Alphalete Marketing, calling about the [job title] role you applied for. We'd love to get you on a quick Zoom interview today. I'll send you a text too, or call us back at [office number]. Thanks!"

---

## Questions for eStream

1. What is the consent basis for AI-voice calls under the TCPA?
2. Does "don't call me again" set do-not-contact everywhere (AI calls, SMS, Mass SMS, call list)?
3. Does "someone will call you" create a highlighted escalation the way SMS does?
4. Does a requested callback time actually trigger an AI call at that time?
5. Can the voice agent speak Spanish?
6. Can the calendar show tomorrow only as a fallback when today has nothing?
7. Can AI-call bookings be tagged as their own source, so we can measure their show rate against text and human calls?
