# What Megan says, where it contradicts the ARS Processes doc

**This file wins.** Where a ruling here and
[ars-processes-2026.md](ars-processes-2026.md) disagree, this is the current
answer and the ARS doc is stale. The doc is live and still edited, so it will
keep drifting; nothing here is a criticism of it, it is a record of decisions
made after the snapshot.

Megan asked for this on 2026-09-27, working through the applicant SMS audit:
*"we need to have a doc that says what I give that contradicts what the ARS
process doc says."* Before that, every ruling lived only in a chat message
and the audit kept scoring replies against wording the business had already
moved off.

Code reads these through `automations/sms_audit/rebuttals.py`, which carries
the same answers as its approved text. **Change both together** — the module
is what scores every recruiter and AI reply in the weekly audit, so a ruling
recorded here and not there is a ruling nothing enforces.

## The rulings

### 1. Pay — never say there is a "base"

| | |
|---|---|
| **ARS doc says** | line 1035 and line 1088: "We offer a weekly salary pay for the role (**the base salary is determined on your background/experience**) plus bonuses or commission." Line 1036 adds "paid training between **$16-$21 an hour**". |
| **Megan says** | "We offer weekly pay ranging from **$1,000–$1,500** plus bonuses or commission." **Either pay answer is fine** — the weekly range, or the doc's paid-training figure of $16–$21 an hour (Megan 2026-09-27: "Pay could be either of those answers"). Only the word "base" is ruled out. |
| **Ruling** | Raf, relayed by Megan 2026-09-27. Asked directly whether bookers should say there is a base weekly pay: *"No, just weekly pay ranging from $1,000-$1500."* |
| **Note** | The two figures in the doc are not a contradiction; they are two valid ways to answer. The fault is the word "base", which the REBUTTALS table still teaches. |
| **Measured** | 25 messages in the six weeks to 2026-09-25 told applicants there is a base pay. All from people, none from the AI: Jorge Pena 19, Sandy Samaniego 3, Erika Gonzalez 2, Camilo Ovalle 1. |

### 2. Location — name the role they applied to, then the address

| | |
|---|---|
| **ARS doc says** | line 1038: "Our main office is located in \*OfficeLocation\*, however, you applied for our opening in \*JobAdLocation\*." |
| **Megan says** | "You applied to our open **AT&T Enrollment Associate** position. Our office address is in **Irving at 3100 Premier Dr**." |
| **The address** | **3100 Premier Drive, Suite 207, Irving, Texas** (Megan 2026-09-27, confirmed as definitive). Grand Prairie's Suite 610 is the second-interview office and is a different, correct address. |
| **Ruling** | Megan 2026-09-27, shown the replies applicants actually got. |
| **Shape matters** | Role first, then address, in sentence case, and no pivot straight into asking for their email. |

### 3. Group interview — lead with yes, and soften it

| | |
|---|---|
| **ARS doc says** | lines 1043 and 1080: "It looks like 2 other people also applied to the same listing as well. Depending on if they show up will determine if you would be conducting the interview by yourself or with someone else…" |
| **Megan says** | "**Yes, this will be a small group interview.**" |
| **Ruling** | Megan 2026-09-27, rejecting the reply "It is a group interview" as too clipped. |
| **Why it matters** | The rejected reply was factually correct. The fault was tone: answer, then reassure. Same reason "Guaranteed base pay; the commission is separate." was rejected. |

### 4. Never push a job question to the hiring manager

| | |
|---|---|
| **ARS doc says** | nothing explicit — but every question below has an approved answer in the REBUTTALS table, so there is nothing to push. |
| **Megan says** | *"no, I did not say that deflection is fine."* (2026-09-27) |
| **Ruling** | "The Hiring Manager can clarify", "I just help with scheduling", "I'm not able to go into details" are **not acceptable** answers to pay, door-to-door, remote/location, hours or role. Megan rejected this in 35 of 38 cases she reviewed. |
| **The exception** | Committing that **we** will ring them — "I am going to give you a call soon to go over your application" — is correct; we want them on a call. Escalating a scheduling request we cannot fill ("4 PM is outside our times, I'll have the manager reach out") is also correct. The distinction is the question, not the deferral: logistics we cannot resolve may escalate, job facts may not. |
| **Measured** | The AI deflects or disclaims on 203 of 1,510 replies (13%). Recruiters do it on 33 of 3,362 (1%) — the AI does it thirteen times more often. |

### 5. Never shout — no all-caps company name, address or role

| | |
|---|---|
| **ARS doc says** | writes the company as "ALPHALETE MARKETING, INC." throughout. |
| **Megan says** | *"I don't like that the company is in all caps"*, then *"I don't like an all caps address either"* (2026-09-27). |
| **Ruling** | Sentence or title case. "Alphalete Marketing, Inc.", "3100 Premier Dr", "Entry Level Customer Representative". Consistent with the standing house formatting rule on title-cased names. |
| **Not this** | A field label in a template — `ZOOM: https://…` in *Directions* — is a label, not shouting, and is left alone. |
| **Measured** | 212 messages shout: "ALPHALETE MARKETING, INC" 72, "ENTRY LEVEL CUSTOMER REPRESENTATIVE" 56, "ALPHALETE" 49, "THE CORRECT ADDRESS IS 3100…" 12. AI 78, recruiters 74, templates 60 — a copy standard to fix in three places, not an AI problem. |

### 6. One address per office, for EVERY stage

Megan 2026-09-27: "the Irving Address is def 3100 Premier Drive Irving Texas
Suite 207", then "carlos' account has a different address than that because
he's in another office", and — correcting me — **"Raf's always go to Irving
address regardless of where they are in the interview process. Carlos has
the same for his location."**

So the address is per OFFICE and does not change between first and second
round. The ARS doc's separate Grand Prairie "2nd Confirmation" address is
Carlos's own office address, not a second-round venue Raf's candidates go to.

| Account | Address, all stages |
|---|---|
| 11280 · Rafael Hidalgo | 3100 Premier Drive, Suite 207, Irving, Texas 75063 |
| 23965 · Rafael 2nd funnel | 3100 Premier Drive, Suite 207, Irving, Texas 75063 |
| 24065 · Raf new recruiter test | 3100 Premier Drive, Suite 207, Irving, Texas 75063 |
| 11580 · Carlos Hidalgo | 1901 N Highway 360, Suite 610, Grand Prairie, Texas 75050 — confirmed by Megan 2026-09-27 in her own words |

**24065 has never sent a correct address.** All 29 of its address messages in
the six weeks to 2026-09-25 are wrong: "Unit 232" 21 times, "3000 Premier
Drive" twice (wrong street number, and shouted), and six that send Raf's
second-interview candidates to Carlos's Grand Prairie office. Every one is
from Maria Quintero, so it is one saved copy to correct, not a process
problem. 11280 and 23965 are right apart from about 140 sends that give the
street with no suite.

A caution for anyone re-running this count: a message naming the job ad
("Entry Level Associate (Spanish Required), Grand Prairie, TX role") is
quoting the POSTING's location, not directing anyone there. Counting those
turns 6 real errors into 42 imaginary ones.

### 7. The first interview is always a group

| | |
|---|---|
| **Megan says** | "someone is responding with that it's not a group interview - I think that it always is" (2026-09-27). |
| **Measured** | The rule holds and **nobody broke it**. All eight mentions of "one-on-one" in the six weeks to 2026-09-25 are correct in context. |

I first reported Aisha Ceron (11280) as contradicting it, twice. That was
wrong, and Megan caught it: the applicant had just been invited to a SECOND
interview and asked "will this be a group interview as well or one-on-one?"
— which genuinely is 1:1. Reading the reply without the four messages above
it turned a correct answer into a fault.

The other mentions are legitimate too: the second round is 1:1 (Jorge Pena,
Tiffani Brown); Erika Gonzalez explained a session that was 1:1 because only
one person had booked that slot; Destiny Tuangco corrected herself to "this
first interview will be a group"; Maria Quintero's "webinar" framing is the
wording Megan accepted on review.

**Worth knowing:** Erika's message shows a slot can end up with one attendee.
The promise is still the right thing to say; it is not always literally true
on the day.

**A caution, twice learned.** A one-line reply is not evidence on its own —
neither here nor in the Grand Prairie count, where job-ad titles read as
address errors. Check the messages around it before calling anything a fault.

## Open — needs a ruling

### Is an accurate but clipped answer a fail on its own?

Megan's rulings say yes. "It is a group interview" is true and she rejected
it; "Guaranteed base pay; the commission is separate." is true and she
rejected it. The approved scripts all answer and then reassure — "Is that
something you're okay with?", "Did you have a preference?" — and a reply
that stops at the fact abandons the applicant mid-decision.

**The audit cannot apply this yet, and here is exactly why.** In her 122
reviewed examples the SAME REPLY appears on both sides:

| They asked | We replied | Megan |
|---|---|---|
| "Is this a group interview?" | "It is a group interview" | not acceptable |
| "I have the link I'm asking. Is this a group interview? **I'm in there now** or is it a one on one?" | "It is a group interview" | fine |

Identical words. The second applicant is sitting in the Zoom waiting, so a
fast bare answer is right; the first is deciding whether to come at all, so
they need the reassurance. The standard is about the applicant's situation,
not the wording — and every signal the audit can measure is wording.

The tendency is real but is not a rule: replies she accepted run 235
characters at the median, rejected ones 117. Sorting by length alone would
get the pair above backwards.

**What would close this.** A rule that can tell "they are mid-decision" from
"they are waiting on us right now" — most likely from the thread state
(booked or not, in a slot now or not) rather than the text. Anyone proposing
one should measure it against Megan's 122 reviews first; they are kept as
the test set for exactly this. The bar to beat is 61%, which is what both
the keyword scorer and a hand-written rule managed, against 59% for simply
answering "not acceptable" every time.

### Other open items

- **The ARS doc still teaches the old pay line.** Ruling 1 corrects it here,
  but bookers reading line 1035 or 1088 will keep saying "base salary is
  determined on your background/experience". Fixing the people without
  fixing the doc brings it straight back.
