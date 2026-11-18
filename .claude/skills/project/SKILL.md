---
name: project
description: The team's SOP for large, multi-session builds (Megan, Eve and anyone on the Hub), run on the shared Project Cards page. Use when someone says "project card starter", "use our project card starter", "starting another project", "new project", "large project build", "big build", or starts something that will clearly take several sessions; also for "build what you can on <project>", "where am I on <project>", "show my projects", "project card(s)", or keeping going on any project that has a card.
---

# Project cards

Every big build is one card on Megan's **Project Cards** page:
https://claude.ai/artifact/UP4JrLoKyHLDN3H2RtRHfg

Claude lays the card out. Whoever started the project (Megan, Eve, anyone
on the team; "she" below) combs through it and adds details. Claude
builds every step that's ready. Then the two of you work down from the top of
what still needs her input.

## The loop

1. **Goal and where it runs.** Ask both in one message, skipping whatever
   she already said: "What's the goal? What will be true when this is
   done?" and "Where will it run: an office's ECO machine, one of our
   Lucys, or somewhere else (like a Streamlit page)?" Ask nothing else up
   front. Where it runs changes the build, so settle it before drafting:
   - **ECO machine** (an office's own computer): runs in the background
     with nothing the owner can see (the ECO rule in CLAUDE.md; exceptions
     live in `automations/icd_alerts/visible_windows.py`). It uses that
     office's own logins and facts, works on Mac AND Windows, never leans on
     another machine, and reaches offices through the office package
     (`automations/icd_alerts/agent_files.txt`).
   - **A Lucy**: test runs go to the least-busy Lucy
     (`automations/day_orchestrator/routing.py`). A scheduled run gets its
     own `deploy/` timer and stays clear of the 4am run. The box needs the
     logins (`resources/lucy-login-standard.md`), and a scheduled report
     publishes to the Hub with a card.
   - **Somewhere else**: write where in `runs_on_note`.
2. **Lay out the card.** Draft the whole thing yourself: 3 to 7 big steps in
   order, and the small steps under each one. Also list **every platform**
   it reads from or writes to (ApplicantStream, OwnerVille, Tableau,
   SaraPlus, Sterling, Apex, BlueInk, Slack, Google Sheets, iMessage...),
   spelled the way the Hub spells them. Each platform starts as **Not
   checked**. Mark it **Access works** only after a real login or read
   worked on the machine it will run on. Mark it **Needs access** when it
   doesn't, and add a step to get that access (needing her if it takes her
   login or a new account). Put which login and which Lucy in its `note`.
   Mark every small step:
   - **Ready to build**: you know enough to build it now.
   - **Needs your input**: you can't build it without her. Put the ONE
     question that unblocks it in `question`, in plain words she can answer
     in a line.
   New report or automation? The big steps must cover the house rules:
   sandbox sheet + `--dry-run`, Marcellus preview before rollout, alerts to
   #claudecorrections-and-requests, a Hub card
   (`workflows/new-hub-card-intake-checklist.md`) and
   `workflows/report-validation-checklist.md`. Recruiting work: read
   `resources/recruiting-context/` before drafting.
   Write the card (see "Reading and writing the card"), then send the link
   with one line: "Your card is up. Answer the yellow questions, fix or add
   anything, then tell me 'build what you can'." **Then stop.** Don't build
   anything until she has combed through it.
3. **She combs through it.** On the page she answers questions, adds
   details, renames or removes steps, adds steps and big steps, parks ideas,
   and flips statuses. It saves as she types.
4. **Build what you can.** When she says go ("build what you can on X",
   "done", "go"), read the card fresh and work top to bottom through every
   **Ready to build** step:
   - Read its `details` first. Her words beat your draft.
   - Mark it **Built** only when it's done AND checked, with a one-line
     `built_note`: what got made and where (file path, sheet tab, channel).
   - If you hit something only she can answer, set that step to **Needs your
     input** with a `question` and go on to the next ready step. One question
     never stops the whole pass.
   - House rules still apply. A step whose next move needs her OK (a Slack
     send, a rollout, touching the real Sheet) ends as Needs your input with
     the question "OK to ...?".
5. **Top of what needs you.** When nothing is Ready, take the first **Needs
   your input** step (lowest big step first, then lowest step) and ask its
   question in chat, one at a time. Re-read the card first: she may have
   answered it there already. Write her answer into that step's `details`,
   set it Ready, build it, then move to the next one.
6. Repeat 4 and 5 until every step is built, then set the project's `status`
   to `finished`.

## Things added along the way

Never drop them. Put each one on the card and say in one line where it went
("Added 'X' as step 3.4"):
- part of a big step: a new step inside it (`order` between its neighbours,
  e.g. 2.5)
- a whole new chunk of work: a new big step
- nice-to-have or not now: the parking lot (`ideas`)

## Picking a project back up

"Where am I on X", "show my projects", "keep going on X": read the card and
give a one-line status with the link, like "Big step 2 of 4. 3 ready to
build, 2 need you, 1 platform needs access. Top one: step 2.2, which city
should Kalkan use?" If "Runs on" is still Not decided, ask that first. Then
carry on at step 4 or 5 of the loop.

## End of a session

Make the card match reality: built steps marked, new questions written. Give
the one-line status and the link, then ask "want me to commit + push?".

## Reading and writing the card

Use the ArtifactData tool with `url` set to the card link above. If it's
deferred, load it with ToolSearch `select:ArtifactData`.

Collections:
- `projects/<project-id>`: `title`, `goal`, `status` (`active` or
  `finished`), `runs_on` (`eco`, `lucy`, `other`; missing or `undecided`
  shows as Not decided), `runs_on_note` (which office, which Lucy, or
  where), `created`, `updated` (ISO times), and `phases`, the ordered list
  of big steps as `{id, name}` (ids like `p1`, `p2`).
- `platforms/<platform-id>`: `project`, `name`, `status` (`check` = Not
  checked, `needed` = Needs access, `ready` = Access works), `note`,
  `order`, `created`, `updated`. Ids `<project-id>-pl-<n>`.
- `steps/<step-id>`: `project`, `phase` (a phase id), `order` (a number that
  sorts steps inside their big step), `title`, `status` (`input` = Needs
  your input, `ready` = Ready to build, `built`), `question` (yours),
  `details` (hers), `built_note`, `added_by` (`claude` or `you`), `created`,
  `updated`.
- `ideas/<idea-id>`: `project`, `text`, `created`.

Rules:
- Project id = a short kebab-case slug (letters, digits, hyphens). It's also
  the page link: `<card link>#<project-id>`. Step ids `<project-id>-<n>`,
  idea ids `<project-id>-idea-<n>`. Steps she adds on the page get random
  ids, and that's fine.
- Read a project: `get` `projects/<id>`, then `query` `steps`, `ideas` and
  `platforms` where `project == <id>`.
- Read right before every write, and pass that read's `version` as
  `if_version`. If the write is refused because she changed it, re-read and
  redo it. Never overwrite her text. Several changes go in one `batch`.
- Set `updated` to now on every write.
- Never delete a step she added or wipe her `details`. Ask before removing
  either.
- The step numbers she sees ("2.3") are the big step's position plus the
  step's position by `order`. Use them when you talk to her.

## The page itself

Source: `projects/project-cards.html`. To change how the page works (not the
data), edit that file and republish it to the same URL. From a new chat,
Artifact `read` the URL first, then publish with `url`. Leave `capabilities`
out on a redeploy so the page keeps its database. The data survives
republishes.
