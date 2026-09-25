"""THE fleet roster. One place that knows which Lucy machines exist.

WHY THIS FILE EXISTS
--------------------
Before 2026-09-17 the roster was NINE literals in eight files, each one a tuple
or set of machine names maintained by hand. Every one of them fails SILENTLY
when a machine is missing from it — no error, no warning, just a box that is
quietly left out of whatever that literal governs.

Three of the nine never got Lucy 3, and nobody noticed for four weeks:

  * `hub_schedule_status._LUCY` — so every Lucy 3 card reported "no schedule"
    in the change-notification email;
  * `office_onboarding.schema.MACHINES` — so no office could be pinned to it;
  * `card_scheduler._LUCY` — stale AND unused, which is its own tell.

That scatter, not the hardware, is what made Lucy 3's first week expensive. This
module is the fix: add a machine HERE, and every consumer follows.

HOW TO ADD LUCY 5
-----------------
1. Append a `Machine(...)` to `MACHINES` below.
2. Add its `MEMBERS` entry in `automations/dashboard.py` (display only — colour,
   badge; `test_fleet` fails if you forget).
3. That is all. Every roster below is derived.

At GO-LIVE (not at provisioning), flip its capability flags:
`holds_appstream` / `runs_appstream` when its first AppStream report is routed
there, and `morning_clock_since` when it joins the 4am batch.

WHY FLAGS AND NOT ONE LIST. "Which machines exist" and "which machines may hold
an AppStream console" are different questions, and collapsing them is how a
brand-new box starts competing with the live fleet on its first afternoon. See
`holds_appstream` for the specific cost.

STDLIB ONLY, ON PURPOSE. `session_holder`, `login_check` and `mini_control` all
import this; anything imported back from them would be a cycle.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# Every runner signs into AppStream as this one account. It has a SPACE in it.
# A wrong spelling does not error — the form fills, Cloudflare clears, the submit
# goes through, and the console renders off the previous session's cookies
# carrying no token. See resources/lucy-login-standard.md §2.
APPSTREAM_ACCOUNT = "Lucy Reports"


class Machine:
    """One runner. Frozen-ish: built at import, never mutated at runtime."""

    __slots__ = ("name", "badge", "ownerville_account", "owner_display_name",
                 "hostnames", "holds_appstream", "runs_appstream",
                 "morning_clock_since", "office_onboarding_choice", "can_text",
                 "note")

    def __init__(self, name, badge, ownerville_account, owner_display_name="",
                 hostnames=(), holds_appstream=False, runs_appstream=False,
                 morning_clock_since=None, office_onboarding_choice=False,
                 can_text=False, note=""):
        self.name = name
        self.badge = badge
        #: The PERSON whose OwnerVille login this box uses, spelled as people
        #: write it. Same fact as `ownerville_account`, different spelling, and
        #: it was tracked separately in gap_alerts with Lucy 3 and Lucy 4 simply
        #: missing — so the "who is logged in here" line fell back to "this
        #: machine's owner" on the very box most likely to be mid-rerun.
        self.owner_display_name = owner_display_name
        #: Has the Messages grant, for the IDENTITY that actually runs jobs.
        #: Granting it to Terminal grants Terminal and changes nothing — the
        #: poller has to raise the dialog itself
        #: (deploy/grant_orchestrator_messages.sh). An ungranted box does not
        #: error; it blocks four minutes on a dialog nobody is there to click
        #: and returns AppleEvent timeout -1712. Flip this only after seeing a
        #: real line AND image arrive from that machine.
        self.can_text = can_text
        #: OwnerVille is PER PERSON and decides whether numbers are RIGHT, not
        #: merely whether a report runs — saved views, the master office and the
        #: Office Access list all follow the login. Asserted, not just printed:
        #: on 2026-09-01 Lucy 1's file said `chidalgo`, nothing errored, and
        #: Raf's board came back empty for an afternoon.
        self.ownerville_account = ownerville_account
        self.hostnames = tuple(hostnames)
        #: Holds its own warm AppStream console. NOT a synonym for "is a runner".
        #: Every Lucy still signs in as the SAME `Lucy Reports` account, and
        #: session_holder's history is explicit that mutual token invalidation
        #: "returns the moment two machines share an account": each holder
        #: re-hops every ~6 min, and renewing INVALIDATES the token the others
        #: are still holding. So a machine with no AppStream report assigned
        #: must NOT hold one — it would raise churn on the live 4am batches and
        #: warm a session nothing is waiting for.
        self.holds_appstream = holds_appstream
        #: Runs AppStream reports at all (so it may RECEIVE a donated session).
        self.runs_appstream = runs_appstream
        #: ISO date this machine joined the 4am batch, or None if it has not.
        #: Doubles as the heartbeat watchdog's `watch_from`, so a newly-armed box
        #: gets one clean 04:20 cycle before it can page — arming the watch on a
        #: machine that was never given a batch pages every morning about
        #: nothing.
        self.morning_clock_since = morning_clock_since
        #: Offerable in the office-onboarding form's machine picker. Narrow on
        #: purpose: letting someone pin an office to a machine that cannot run
        #: its campaign produces a silently blank board.
        self.office_onboarding_choice = office_onboarding_choice
        self.note = note

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Machine(%r)" % self.name


# ---------------------------------------------------------------------------
# THE ROSTER. Everything below this block is derived from it.
# ---------------------------------------------------------------------------
MACHINES: Tuple[Machine, ...] = (
    Machine(
        name="Lucy 1", badge="1",
        ownerville_account="rhidalgo", owner_display_name="Rafael Hidalgo",
        # Casing as the box itself reports it (`ping`, 2026-09-25); it was
        # recorded all-lowercase here. Nothing matches these exactly today, but
        # reference data that disagrees with the machine is how the next reader
        # gets sent somewhere else.
        hostnames=("Alphaletes-Mac-mini.local",),
        holds_appstream=True, runs_appstream=True, can_text=True,
        morning_clock_since="2026-08-29", office_onboarding_choice=True,
        note="the original mini; D2D / Raf's org. Reachable by SSH.",
    ),
    Machine(
        name="Lucy 2", badge="2",
        ownerville_account="chidalgo", owner_display_name="Carlos Hidalgo",
        # THE RUNNER IS THE FIRST NAME ONLY. `ping` on 2026-09-25 answered
        # `Lucys-MacBook-Neo.local`, and that is the box that runs the jobs.
        # `Carloss-Mac-mini-2` is Carlos's SEPARATE dev/control Mac mini
        # (docs/operating-lucy2.md: "Claude Code runs on Carlos's Mac mini …
        # automations RUN on a separate machine, Lucy 2"). It is listed here on
        # purpose — deploy/lucy2_digest_daily.sh passes it in `--host` so a run
        # started from the mini still gets labelled 'Lucy 2' in the digest — but
        # it is NOT a runner and holds no agents.
        #
        # THIS TUPLE HAS ALREADY MISLED A SESSION (2026-09-25). Asked "did Carlos
        # move the push off Lucy 2?", a reader took `chidalgo` + this hostname to
        # mean Carlos possesses Lucy 2, and answered "no move — and Lucy 2 IS
        # Carlos's box". Raf had the MacBook in hand; Carlos had moved the push to
        # the mini. Nothing here records CUSTODY — `ownerville_account` is a
        # LOGIN — so do not read one out of it.
        hostnames=("Lucys-MacBook-Neo.local", "Carloss-Mac-mini-2"),
        holds_appstream=True, runs_appstream=True, can_text=False,
        morning_clock_since="2026-08-29", office_onboarding_choice=True,
        note="Carlos's org / B2B — the DATA it works, not who holds it. A "
             "LAPTOP: caffeinate does not survive a shut lid. SSH (lucy2@) "
             "since 2026-09-19, same network as the rest.",
    ),
    Machine(
        name="Lucy 3", badge="3",
        ownerville_account="rhidalgo", owner_display_name="Rafael Hidalgo",
        hostnames=("Lucys-Mac-mini.local",),
        holds_appstream=True, runs_appstream=True, can_text=True,
        morning_clock_since="2026-08-29", office_onboarding_choice=False,
        note="rerun/overflow box on Raf's accounts. SSH (lucy3@) since 2026-09-19.",
    ),
    Machine(
        name="Lucy 4", badge="4",
        ownerville_account="rhidalgo", owner_display_name="Rafael Hidalgo",
        # Recorded 2026-09-25 from the box's own `ping` — it had been provisioned
        # for eight days with an EMPTY tuple here, which is how a live runner
        # ends up looking like a machine nobody can name. Mind the collision:
        # this is `Lucys-Mac-mini-2`, one word from Lucy 2's `Carloss-Mac-mini-2`
        # and one character from Lucy 3's `Lucys-Mac-mini`.
        hostnames=("Lucys-Mac-mini-2.local",),
        # EVERY CAPABILITY FLAG IS OFF AT PROVISIONING, DELIBERATELY.
        # Megan 2026-09-17: built to "run anything", but off the 4am clock until
        # a report is actually routed to it. Turning these on early is the one
        # Lucy 4 change that can cost the LIVE fleet — see `holds_appstream`.
        # can_text flipped 2026-09-19: grant_orchestrator_messages.sh run ON this
        # box, and the probe's line AND image both arrived in Admin Staff (Megan
        # confirmed). It first sent "Not Delivered" — iMessage activation on a new
        # Mac; a Messages sign-out, restart and sign-in cleared it, not the grant.
        holds_appstream=False, runs_appstream=False, can_text=True,
        morning_clock_since=None, office_onboarding_choice=False,
        note="provisioned 2026-09-17; workflows/lucy4-provisioning.md. "
             "Capabilities flip at go-live, one at a time.",
    ),
)

_BY_NAME: Dict[str, Machine] = {m.name: m for m in MACHINES}


def get(name: str) -> Optional[Machine]:
    """The machine record, or None when the name is not a known runner."""
    return _BY_NAME.get(name)


def _names(**flags) -> Tuple[str, ...]:
    """Names of machines matching every given attribute value, roster order."""
    return tuple(m.name for m in MACHINES
                 if all(getattr(m, k) == v for k, v in flags.items()))


#: EVERY runner, live or not. The answer to "is this a Lucy machine?".
RUNNERS: Tuple[str, ...] = tuple(m.name for m in MACHINES)

#: Machines that hold their OWN warm AppStream console.
APPSTREAM_HOLD_MACHINES: Tuple[str, ...] = _names(holds_appstream=True)

#: Machines that RUN AppStream reports, so may receive a donated session.
#: Deliberately separate from who HOLDS one: consuming a push costs nothing,
#: holding a competing console is what broke the fleet on 2026-08-29.
APPSTREAM_FLEET_MACHINES: Tuple[str, ...] = _names(runs_appstream=True)

#: Machines on the 4am batch — the ones a heartbeat watchdog should expect.
MORNING_CLOCK_MACHINES: Tuple[str, ...] = tuple(
    m.name for m in MACHINES if m.morning_clock_since)

#: Machine → the ONLY OwnerVille account it may sign in as.
EXPECTED_OWNERVILLE_ACCOUNT: Dict[str, str] = {
    m.name: m.ownerville_account for m in MACHINES}

#: Machines offerable in the office-onboarding machine picker.
OFFICE_ONBOARDING_MACHINES: Tuple[str, ...] = _names(office_onboarding_choice=True)

#: Machines whose runner identity holds the macOS Messages grant.
TEXTING_MACHINES: Tuple[str, ...] = _names(can_text=True)

#: Machine → the person whose OwnerVille login it uses, as people spell it.
MACHINE_OWNER: Dict[str, str] = {
    m.name: m.owner_display_name for m in MACHINES if m.owner_display_name}

#: Machine → known hostnames. Reference data: `machine_digest` resolves a run's
#: hostname to a label and deliberately prints an UNKNOWN host raw rather than
#: guessing, because "Lucys-Mac-mini.local" is Lucy 3 and "Lucys-MacBook-Neo"
#: is Lucy 2 — any "lucy in the hostname → Lucy 1" shortcut names the wrong box.
#:
#: FOUR NAMES, ALL NEARLY THE SAME, ON PURPOSE-ISH. Verified by `ping` on
#: 2026-09-25, because three of these were wrong or missing before that:
#:   Alphaletes-Mac-mini.local  Lucy 1
#:   Lucys-MacBook-Neo.local    Lucy 2  (the runner)
#:   Lucys-Mac-mini.local       Lucy 3
#:   Lucys-Mac-mini-2.local     Lucy 4  ← not Lucy 2, despite
#:   Carloss-Mac-mini-2         Carlos's dev box, filed under Lucy 2 for digests
#: Nothing imports this map; it is documentation, and `machine_digest` gets its
#: own list from `--host`. So an edit here is safe — and worth making the moment
#: a `ping` disagrees with it.
HOSTNAMES: Dict[str, Tuple[str, ...]] = {m.name: m.hostnames for m in MACHINES}


def heartbeat_watch_from(name: str) -> Optional[str]:
    """The date this machine's 4am heartbeat may start paging, or None."""
    m = _BY_NAME.get(name)
    return m.morning_clock_since if m else None
