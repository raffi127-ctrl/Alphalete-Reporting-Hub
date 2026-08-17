"""The recruiting funnel, as Raf teaches it — stages, ratios, and constraints.

Transcribed from Raf's 'THE KEYS — Recruiting Funnel & Theory of Constraints'
packet (66 pages, 2026-08-17). The deck's structure IS the spec: it walks the
funnel top to bottom and ends each stage with the same question — "Do I have a
constraint here?" That is the whole point of Theory of Constraints: only ONE
stage is the binding constraint at a time, and work spent anywhere else is
wasted. So a recruiting display that shows nine numbers equally has missed the
idea; it has to point at the one that's binding.

Each stage carries where its number comes from. Some are already pulled by the
Hub (AppStream p=701 feeds the 1st-round trio). Several are NOT sourced yet —
those are marked source="" and MUST render as "not wired" rather than as a
zero. A zero and an unknown look identical on a dashboard and mean opposite
things ([[feedback_fill_but_flag]]).

Goals are deliberately EMPTY. Raf spoke targets at the conference; they are
his to set, and a made-up goal would quietly become the number offices chase.
Fill GOALS in once he confirms.
"""
from __future__ import annotations

from dataclasses import dataclass

# Where a stage's number comes from today.
APPSTREAM = "appstream"      # ApplicantStream admin breakdown (p=701)
LUCY = "lucy"                # Lucy scorecard / interview audit bot
OV = "ownerville"
UNSOURCED = ""               # not wired — render as "not wired", never as 0


@dataclass(frozen=True)
class Stage:
    key: str
    order: int
    label: str              # the funnel stage as Raf names it
    ratio: str              # what the percentage actually divides
    source: str             # APPSTREAM | LUCY | OV | UNSOURCED
    field: str = ""         # the concrete field, when it's already pulled
    deck_pages: tuple = ()  # where it's covered in the packet
    notes: str = ""

    @property
    def is_wired(self) -> bool:
        return bool(self.source)


# Top of funnel -> new start. Order matters: the display walks it in this order
# and marks the first stage failing its goal as the binding constraint.
STAGES: list[Stage] = [
    Stage("applies", 1, "Applies (NLR)",
          ratio="applies received — top of funnel, not a ratio",
          source=APPSTREAM, field="applies / ad response",
          deck_pages=(10, 11, 12, 13),
          notes="Driven by ad quality: titles, location/details, photo, star "
                "rating, NLR rep (deck pp.14-19). If applies are the "
                "constraint, the fix is the AD, not the recruiters."),
    Stage("stcl", 2, "Applies → Set To Call List (STCL)",
          ratio="set to call list / applies",
          source=UNSOURCED, deck_pages=(20,),
          notes="Deck asks the constraint question here explicitly."),
    Stage("rtcl", 3, "Retention To Call List (RTCL)",
          ratio="reached / set to call list",
          source=UNSOURCED, deck_pages=(21, 22, 23, 24, 25, 26),
          notes="Four scripted texts (RTCL Text 1-4) drive this stage."),
    Stage("first_round_booked", 4, "1st Rounds Booked",
          ratio="1st rounds booked — count",
          source=APPSTREAM, field="Interviews Booked",
          deck_pages=(27,),
          notes="Already pulled daily by recruiter_retention.daily."),
    Stage("first_round_retention", 5, "1st Round Retention",
          ratio="1st rounds showed / 1st rounds scheduled",
          source=APPSTREAM, field="First Interviews Showed Up / Total First "
                                  "Interviews",
          deck_pages=(27, 28, 29),
          notes="THE ONE ALREADY LIVE. recruiter_retention colors it <45% red, "
                "45-49.9% grey, >=50% green — the closest thing to a stated "
                "goal anywhere in the codebase (Raf's thresholds). Confirmation "
                "text + zoom links are the lever (deck p.28)."),
    Stage("booked_for_second", 6, "% of 1st Rounds Booked for 2nd",
          ratio="2nd rounds booked / 1st rounds showed",
          source=UNSOURCED, deck_pages=(30, 31, 32, 33),
          notes="Deck pairs this with the Interviewers Report and the "
                "'Answer to Book Ratio'. Interviewer-level, not recruiter-level "
                "— so it needs a per-interviewer source."),
    Stage("second_round_retention", 7, "2nd Round Retention",
          ratio="2nd rounds showed / 2nd rounds booked",
          source=UNSOURCED, deck_pages=(34, 35, 36),
          notes="Deck spends the most pages here (pp.34-57): who conducts the "
                "2nd, posture/indifference, D2D framing, pay structure. If this "
                "is the constraint the fix is interviewer behavior."),
    Stage("job_offered", 8, "Job Offered %",
          ratio="job offers extended / 2nd rounds showed",
          source=UNSOURCED, deck_pages=(37, 38, 39, 40),
          notes="'Turning Job Offered ON' (p.38) implies this is a toggle in "
                "the system — likely an ApplicantStream disposition. Confirm "
                "the field with Eve before wiring."),
    Stage("bob", 9, "BOB %",
          ratio="butts on bench / job offers extended",
          source=UNSOURCED, deck_pages=(41, 42, 43, 44, 45, 58, 59),
          notes="Deck ties BOB to Lucy — 'Lucy Message back to us', 'Lucy Score "
                "card ranking', 'Lucy 11 Frames'. So the Lucy scorecard is "
                "probably the source. Also framed as 1st-round promise vs what "
                "the leader actually says (p.58)."),
    Stage("new_start_retention", 10, "New Start Retention",
          ratio="still working after start / new starts",
          source=UNSOURCED, deck_pages=(60, 61, 62, 63, 64, 65),
          notes="Rehash points 1-4 (incl. a gift) are the levers. Bottom of the "
                "funnel — a leak here wastes the entire funnel above it."),
]

BY_KEY: dict[str, Stage] = {s.key: s for s in STAGES}

# Raf's targets, spoken at the conference — NOT transcribed here because the
# deck's slides are images and the numbers weren't in the text layer. Ask Raf,
# then fill: {stage key: target as a fraction, e.g. 0.50}. Until then the
# display must show actuals with NO goal line rather than invent one.
GOALS: dict[str, float] = {
    # the only threshold that exists in code today (recruiter_retention colors)
    "first_round_retention": 0.50,
}


def wired() -> list:
    return [s for s in STAGES if s.is_wired]


def unwired() -> list:
    """Stages with no source yet — the build list for the recruiting tab."""
    return [s for s in STAGES if not s.is_wired]


def constraint(actuals: dict) -> str:
    """The binding constraint: the EARLIEST stage falling short of its goal.

    Theory of Constraints says fix the first bottleneck, not the worst number —
    a later stage starved by an earlier one will look bad without being the
    problem. Returns a stage key, or "" when nothing is measurably short.
    Stages with no goal or no actual are skipped, never guessed at."""
    for s in STAGES:
        goal, actual = GOALS.get(s.key), actuals.get(s.key)
        if goal is None or actual is None:
            continue
        if actual < goal:
            return s.key
    return ""
