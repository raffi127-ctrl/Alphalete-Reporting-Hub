"""Which of these does a HUMAN have to open, and which is Lucy already handling?

WHY THIS EXISTS (Megan 2026-08-26)
----------------------------------
#claudecorrections-and-requests is now a clean list — one thread per problem,
✅ when it's fixed. What it still doesn't say is the only thing Megan and Eve
actually need off it in the morning: *which of these is mine?*

Everything in that channel already survived the orchestrator's automatic repair
(MAX_RUN_RETRIES=3 whole-report, MAX_AUTO_RETRIES=2 on just the failed parts,
a 90s flake retry, circle-backs every ~25 min to the noon backstop). So the list
mixes two completely different things that look identical while scrolling:

  * a report that is mid-retry and will very likely fix itself by 9am, and
  * a report whose Tableau view was DELETED, where re-running is not a fix and
    every retry is just noise until somebody changes code.

Megan: "put some type of emoji on the ones that Eve and I need to look at
personally so we know which ones to go to first." That is this module. It reads
every OPEN incident, decides which of three states it is in, and puts exactly
ONE reaction on the parent so the answer is visible from the channel list
without opening anything:

    :red_circle:           NEEDS YOU — re-running will not fix this one.
    :pending:              Lucy is on it. Nothing for you to do yet.
    :large_purple_circle:  Waiting on a source that hasn't landed.

IT ONLY SORTS. IT NEVER FIXES.
------------------------------
This module has no write access to anything but reactions, one thread line, and
the marker text on a parent that is ALREADY resolved (see close_stranded below:
it re-badges "open" to "resolved" on posts that already carry the ✅, and can do
nothing to a post that doesn't). It does not edit code, does not re-run reports,
does not post to any other channel. That is deliberate and it is the whole reason it was safe to build:
these reports publish as Lucy to ~11 Slack channels and to owner iMessage
chats, so an unattended thing that "fixes" a report and re-publishes it doesn't
fail quietly — it puts wrong numbers in front of owners under Megan's name. The
retry loop that DOES re-run things is bounded and lives in the orchestrator,
where it has always been. Triage is the read-only layer on top.

THE LINE IT POSTS IS THREE FACTS, IN PLAIN WORDS (Megan 2026-08-26: "the
responses need to be very simple and very clear about what is going on and stop
with all the fluff and confusion"). Every line this module writes answers, in
this order and nothing else:

    what is wrong · who has it · what you do

No emoji in the text (the reactions are the emoji layer — Megan 2026-08-18), no
mechanism footers, no hedging, no restating the report's own error. If a fact
doesn't change what the reader does next, it does not go in the line.

ONE LINE PER STATE CHANGE, NOT PER PASS. The line is posted when an incident
ENTERS a state and never again while it stays there, so a problem sitting open
for three days costs the thread three lines at most, not one per triage run.
State lives in output/state/incident_triage.json, keyed by incident key.

IT ALSO FINISHES STRANDED MARKERS (Megan 2026-08-26). chat.update only touches
your OWN posts, so an incident opened by Lucy and fixed from a laptop keeps its
reply and its ✅ while the marker edit is refused — the thread is closed and the
parent says `open` forever. Triage has always DETECTED that state (it has to, or
it would grade a fixed post and put a red circle on it) and only ever counted
it. Now it closes what Lucy owns and names the rest. Bookkeeping only: nothing
here decides a post is resolved, it just records a resolution that already
happened.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from automations.shared import incident_thread as inc

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = REPO_ROOT / "output" / "state" / "incident_triage.json"

# ---------------------------------------------------------------- buckets ----

NEEDS_YOU = "needs_you"
LUCY = "lucy"
WAITING = "waiting"

# One reaction per post, ever — _apply() strips the other two, or a post ends up
# wearing two answers. The constant itself lives in incident_thread beside the
# other two so incident_sweep can clear it without importing this module.
NEEDS_YOU_REACTION = inc.NEEDS_HUMAN_REACTION
BUCKET_REACTION = {
    NEEDS_YOU: NEEDS_YOU_REACTION,
    LUCY: inc.WORKING_REACTION,          # :pending:
    WAITING: inc.WAITING_REACTION,       # :large_purple_circle:
}
_ALL_REACTIONS = tuple(BUCKET_REACTION.values())

# ------------------------------------------------------------- signatures ----
#
# Matched against the lowercased tail of the report's own orchestrator log. Order
# matters: CODE_CHANGE is asked FIRST, because several of these also emit a
# generic timeout on the way down and would otherwise read as transient.
#
# Each entry is (pattern, plain-English reason). The reason is written for
# somebody who does not read tracebacks — it says what BROKE, not what the
# exception was called.

_CODE_CHANGE: Sequence[Tuple[str, str]] = (
    ("view not found",
     "The Tableau view this pulls from is gone or was renamed."),
    ("no such view",
     "The Tableau view this pulls from is gone or was renamed."),
    ("worksheet not found",
     "The Tableau worksheet this pulls from is gone or was renamed."),
    ("custom view",
     "The saved Tableau view it uses was deleted."),
    ("label not found",
     "The sheet changed — a row label it looks for is not there any more."),
    ("could not find column",
     "The sheet changed — a column it looks for is not there any more."),
    ("no sunday column",
     "The week columns in the sheet don't match what it expects."),
    ("worksheetnotfound",
     "That tab is missing from the workbook."),
    ("keyerror",
     "The data came back in a different shape than the code expects."),
    ("attributeerror",
     "The page or file changed shape — the code hit an error."),
    ("indexerror",
     "The data came back shorter than the code expects."),
    ("no such element",
     "The web page changed — a button or field it clicks is gone."),
    ("selector",
     "The web page changed — something it clicks is not where it was."),
    ("403",
     "This machine is not allowed into that source any more."),
    ("permission denied",
     "This machine is not allowed into that source any more."),
    ("404",
     "The page or file it downloads is gone."),
)

# A re-run genuinely IS the fix for these, and the orchestrator is already doing
# it. Nothing here should ever wear the red circle before the backstop.
_TRANSIENT: Sequence[Tuple[str, str]] = (
    ("appstream session expired", "The ApplicantStream login timed out."),
    ("no live token", "The ApplicantStream login timed out."),
    ("0 rqst token", "The ApplicantStream login timed out."),
    ("turnstile", "The Ownerville login went stale."),
    ("ownerville session is stale", "The Ownerville login went stale."),
    ("invalid_grant", "A Google login token expired."),
    ("token has been expired", "A Google login token expired."),
    ("refresherror", "A Google login token expired."),
    ("timed out", "It timed out."),
    ("timeout", "It timed out."),
    ("connection reset", "The connection dropped."),
    ("connectionerror", "The connection dropped."),
    ("read timed out", "The connection dropped."),
    ("429", "The source rate-limited us."),
    ("quota exceeded", "The source rate-limited us."),
    ("temporarily unavailable", "The source was briefly down."),
    ("502", "The source was briefly down."),
    ("503", "The source was briefly down."),
)

# The source simply hasn't landed yet. Not a failure at all before the backstop.
_WAITING_ON: Sequence[Tuple[str, str]] = (
    ("waiting on", "The data it needs hasn't been posted yet."),
    ("not ready", "The data it needs hasn't been posted yet."),
    ("no board posted", "Nobody has posted today's board yet."),
    ("source not ready", "The data it needs hasn't been posted yet."),
    ("no new emails", "No email has come in for it yet."),
    ("nothing to do", "There was nothing for it to do today."),
    # The ORCHESTRATOR'S OWN wording for a deliberate hold (run.py: exit 75 ->
    # "ran, held with a note"), not the bare word. `held` alone matched three
    # unrelated things that all print it in normal output — a lock that "has
    # held" a profile, tableau_patchright's "the profile was held by an ORPHAN
    # Chrome" (the case that most needs a person), and, on 2026-08-27, the
    # recruiter-retention fill's routine success line "same week (counts held)".
    # Any of those painted a real failure purple and told the channel there was
    # nothing to do. Match the phrase the hold path actually writes.
    ("ran, held with a note",
     "It ran, but held back one part it wasn't sure about."),
)

# INCIDENTS THAT ARE NOTICES, NOT WORK (Megan 2026-08-26). A `drop-tableau-stale-`
# key is not a broken report — it is an upstream Tableau feed serving older data
# than it should. Its own alert says so in as many words: "the report that pulled
# it ran and sent normally: nothing dropped, nothing to re-run … If the view looks
# right, the feed behind it is genuinely behind and there is nothing on our side
# to change. Do not re-run … that id is the SOURCE, not a report."
#
# It nonetheless sat open for days (nothing on our side can close it), so the age
# rule below would have painted it red — telling two people that a working report
# needs a code fix, and sending them to open a thread whose own text says there
# is nothing to do. That is the precise way a red circle stops being believed, so
# this check runs BEFORE the age rule rather than after it.
_NO_ACTION_PREFIXES = ("drop-tableau-stale-",)
_NO_ACTION_LINE = ("*Nothing to do.* An upstream Tableau feed is serving older "
                   "data than it should. The report that pulled it ran and sent "
                   "normally. It clears when the feed catches up.")

# INCIDENTS THAT ARE FINDINGS, NOT FAILURES (Megan 2026-09-02). A `finding-` key
# means the run did its WHOLE job and is reporting what it noticed on the board —
# vantura_board_audit's stalled trainees, the cancel-rate's unfilled ICDs.
# notify.py already posts these correctly ("the run itself was fine … nothing to
# re-run and nothing is missing"), and then the generic branches below
# contradicted it inside its own thread: "It failed and the reason isn't in the
# log" (6), "It did not finish" (4). Both are false, and they sat directly under
# a post that had just said the opposite — which teaches people that the triage
# line is noise.
#
# It IS a person's, so NEEDS_YOU stays right; only the sentence was wrong. Like
# the notices above this runs BEFORE the age rule, because a finding also stays
# open for days by its nature: nothing re-runs it, and a re-run would not clear
# it — the audit only ever detects, it never edits the board.
_FINDING_PREFIXES = ("finding-",)
_FINDING_LINE = ("*Needs one of you.* The run itself was fine — this is what it "
                 "FOUND, and it is fixed on the board, not in the code. "
                 "Re-running will not clear it: the audit only detects, it never "
                 "edits. What it found is listed in this thread.")

# After this hour a "waiting on the source" is no longer waiting, it is a
# no-show — the orchestrator has stopped retrying and it is a person's problem.
BACKSTOP_HOUR = 12

# An incident that has been open across a DAY boundary has already had a full
# morning of automatic retries thrown at it and lost. Whatever it is, the loop
# is not going to solve it on day two.
STALE_DAYS = 1

# Same day, but it has already failed again after its automatic retries — the
# retry budget for the morning is spent (MAX_RUN_RETRIES=3 in the orchestrator).
SPENT_REPEATS = 3


# ------------------------------------------------------------------ state ----

def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:  # noqa: BLE001 — a lost state file costs one repeated line
        return {}


def _save_state(st: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, indent=2, sort_keys=True))
    except Exception as e:  # noqa: BLE001
        print("  - couldn't save triage state ({}: {})".format(
            type(e).__name__, str(e)[:60]))


# ------------------------------------------------------------- inspection ----

def report_id(key: str) -> str:
    """`failure-b2b_metrics` -> `b2b_metrics`. Unprefixed keys pass through."""
    for p in ("failure-", "drop-", "standalone-", "finding-"):
        if key.startswith(p):
            return key[len(p):]
    return key


def _log_tail(rid: str, day: dt.date, n: int = 80) -> str:
    """Lowercased tail of that report's orchestrator log for `day`, or "".

    Same file the failure alert reads (output/logs/orch-<date>-<id>.log), so a
    verdict here and the reason in the alert can never disagree about the facts.
    """
    p = REPO_ROOT / "output" / "logs" / f"orch-{day.isoformat()}-{rid}.log"
    try:
        return "\n".join(p.read_text(errors="replace").splitlines()[-n:]).lower()
    except Exception:  # noqa: BLE001 — no log is itself a signal; caller decides
        return ""


# THE TWO AUTOMATIC PATHS, READ FROM schedule_config RATHER THAN ASSUMED.
#
# Both the :pending: line and the :large_purple_circle: line promise the reader
# that something will pick the report up on its own. For most of the schedule
# that is simply not true, and saying it costs a whole morning of fill:
#
#   * a failed run is re-attempted ONLY when `source_type == "tableau"`
#     (day_orchestrator/run.py: `if r.source_type == "tableau" and
#     rs.attempts < MAX_RUN_RETRIES`). An appstream/sheets/email report that
#     fails is TERMINAL on attempt one — nothing re-runs it, ever.
#   * a report held before it ran is re-checked every pass, but only if it has
#     a readiness probe to re-check, i.e. a non-empty `data_sources`.
#
# With neither, "Lucy runs it automatically when it lands" is a false all-clear:
# the day just ends with the tab unfilled. Found 2026-08-27 on
# recruiter_retention_daily (source_type appstream, data_sources []), which the
# channel told two people to ignore at 10:15.
_CFG_PATH = REPO_ROOT / "automations" / "day_orchestrator" / "schedule_config.json"
_CFG_CACHE: Optional[dict] = None


def _reports() -> dict:
    global _CFG_CACHE
    if _CFG_CACHE is None:
        try:
            _CFG_CACHE = json.loads(
                _CFG_PATH.read_text(encoding="utf-8")).get("reports") or {}
        except Exception:  # noqa: BLE001 — unreadable config: claim nothing
            _CFG_CACHE = {}
    return _CFG_CACHE


def reruns_itself(rid: str, *, partial: bool = False) -> bool:
    """Will anything re-run `rid` today without a person asking?

    `partial` is the `drop-` case — the report ran and MISSED a part, so it is
    INCOMPLETE rather than FAILED, and a third automatic path opens:
    `_retry_incomplete_parts` presses the Hub's "retry failed only" button for
    any manifest-verified report (twice, after everything else has run). That
    one never touches a terminal FAILED report, which is why it is not credited
    to a `failure-` key.

    Unknown ids (a `drop-` key naming a source, a manifest id) answer True: this
    only ever DOWNGRADES a promise, and inventing work for an id we can't even
    find in the schedule is the more expensive mistake.
    """
    r = _reports().get(rid)
    if not isinstance(r, dict):
        return True
    if r.get("source_type") == "tableau" or r.get("data_sources"):
        return True
    return partial and (r.get("verify") or {}).get("type") == "manifest"


def _match(tail: str, table: Sequence[Tuple[str, str]]) -> Optional[str]:
    for pat, reason in table:
        if pat in tail:
            return reason
    return None


class Verdict:
    """What one incident is, in the two words the channel needs."""

    __slots__ = ("key", "bucket", "reason", "ts", "line")

    def __init__(self, key: str, bucket: str, reason: str, ts: str = "",
                 line: str = ""):
        self.key, self.bucket, self.reason, self.ts = key, bucket, reason, ts
        # An explicit line, for the cases where the bucket's stock wording would
        # promise something untrue (see _NO_ACTION_PREFIXES).
        self.line = line

    def __repr__(self) -> str:  # pragma: no cover — debugging only
        return f"<{self.key} {self.bucket}: {self.reason}>"


def classify(key: str, *, day: Optional[dt.date] = None,
             opened: str = "", repeats: int = 0,
             now_hour: Optional[int] = None) -> Verdict:
    """Sort one open incident into NEEDS_YOU / LUCY / WAITING.

    The order of the questions is the whole design, and it is biased: an
    incident lands in NEEDS_YOU only when the automatic path is provably out of
    road. Guessing "needs a human" too eagerly sends Megan and Eve to open a
    thread that would have closed itself by 9am, and a red circle that turns out
    to be nothing is exactly how people learn to stop trusting the red circle.
    """
    day = day or dt.date.today()
    now_hour = now_hour if now_hour is not None else dt.datetime.now().hour
    rid = report_id(key)
    tail = _log_tail(rid, day)

    # 0) Notices, not work. Must precede the age rule — these stay open for days
    #    by their nature, and nothing on our side can close them.
    if key.startswith(_NO_ACTION_PREFIXES):
        return Verdict(key, WAITING,
                       "An upstream Tableau feed is running behind.",
                       line=_NO_ACTION_LINE)

    # 0b) Findings, not failures. Must also precede the age rule: it stays open
    #     until a person corrects the board, and no re-run can close it.
    if key.startswith(_FINDING_PREFIXES):
        return Verdict(key, NEEDS_YOU,
                       "The run was fine; it found something to fix on the board.",
                       line=_FINDING_LINE)

    # 1) Open since a previous day. A full morning of retries already lost.
    age = inc._days_open(opened, day) if opened else 0
    if age > STALE_DAYS:
        return Verdict(key, NEEDS_YOU,
                       "Open since {}. Automatic retries have not fixed it."
                       .format(opened), )
    if age == STALE_DAYS:
        return Verdict(key, NEEDS_YOU,
                       "Open since yesterday. Automatic retries have not "
                       "fixed it.")

    # 2) A signature that says re-running is not the fix, whatever the clock is.
    reason = _match(tail, _CODE_CHANGE)
    if reason:
        return Verdict(key, NEEDS_YOU, reason)

    # 3) Retry budget spent today: it re-ran and failed again anyway.
    if repeats >= SPENT_REPEATS:
        return Verdict(key, NEEDS_YOU,
                       "Re-ran {} times today and failed every time."
                       .format(repeats))

    # 4) Past the backstop the loop has stopped trying, so nothing is "pending"
    #    any more — whatever is still open is a person's.
    if now_hour >= BACKSTOP_HOUR:
        reason = (_match(tail, _TRANSIENT) or _match(tail, _WAITING_ON)
                  or "It did not finish.")
        return Verdict(key, NEEDS_YOU,
                       "{} Still not fixed after the noon cut-off.".format(reason))

    # 5) Before the backstop: waiting on a source, or mid-retry.
    reason = _match(tail, _WAITING_ON)
    if reason:
        return _if_it_reruns(key, rid, WAITING, reason)
    reason = _match(tail, _TRANSIENT)
    if reason:
        return _if_it_reruns(key, rid, LUCY, reason)

    # 6) No log, no signature, still early. The loop has budget left, so let it
    #    spend it — this becomes NEEDS_YOU on its own at noon via (4).
    return _if_it_reruns(key, rid, LUCY,
                         "It failed and the reason isn't in the log.")


def _if_it_reruns(key: str, rid: str, bucket: str, reason: str) -> Verdict:
    """`bucket` if something will re-run it on its own; otherwise it is a
    person's — and the line says the one command that fixes it.

    The bucket is not downgraded to spite the loop: it is downgraded because the
    stock :pending:/:large_purple_circle: wording tells the reader to walk away,
    and for a report the orchestrator never retries, walking away IS the outage.
    """
    if reruns_itself(rid, partial=key.startswith("drop-")):
        return Verdict(key, bucket, reason)
    return Verdict(key, NEEDS_YOU, reason,
                   line=("*Needs one of you.* {} Nothing re-runs it on its "
                         "own — `lucy rerun {}`.".format(reason, rid)))


# --------------------------------------------------------------- the line ----

def line_for(v: Verdict) -> str:
    """The one line posted into the thread. Three facts, plain words, no emoji.

    Megan 2026-08-26: "very simple and very clear about what is going on and
    stop with all the fluff and confusion." So each of these is: what is wrong,
    who has it, what you do. Anything that doesn't change the reader's next
    action is not in here — including how the triage decided, which is what a
    module like this is most tempted to explain.
    """
    if v.line:
        return v.line
    if v.bucket == NEEDS_YOU:
        return ("*Needs one of you.* {} Re-running will not fix it."
                .format(v.reason))
    if v.bucket == LUCY:
        return ("*Lucy has this.* {} She re-runs it about every 25 minutes "
                "until noon. Nothing for you to do unless it is still here "
                "after that.".format(v.reason))
    return ("*Waiting on the source.* {} Lucy runs it automatically when it "
            "lands. Nothing for you to do.".format(v.reason))


# ----------------------------------------------------------------- the run ----

# Beyond this, a marker still reading `open` is not a live problem — it is a post
# the roll-over never reached (that needs Lucy, and a laptop-opened incident can
# sit there for good). Grading them would bury today's two real items under a
# week of archaeology. They are counted and named in the summary instead.
STALE_LIMIT_DAYS = 7


def _open_incidents(client, channel: str, day: dt.date,
                    prior: Optional[dict] = None
                    ) -> Tuple[List[dict], List[str], List[str], List[str]]:
    """(gradeable, already-fixed, stale) incidents, read from the CHANNEL.

    Deliberately not off the local index: that file is a per-machine cache, and
    the triage pass has to see incidents opened by Lucy 1, Lucy 2 and the mini
    alike or it will quietly grade only its own machine's failures.

    THE ✅ OUTRANKS THE MARKER TEXT (found in the first dry run, 2026-08-26).
    Six posts in the channel right now say `open` in their marker and wear a
    white check: resolve() re-badges the parent AND adds the reaction, and
    chat.update only touches your own messages — so when the fix lands from a
    different identity than the one that opened the thread, the REACTION is the
    half that survives and the marker text is the half that lies. incident_thread
    already knows this ("the reaction being the half that survives when Slack
    refuses the edit"); triage has to read it the same way round or it puts a red
    circle on six fixed threads and sends two people to open them. A red circle
    that turns out to be nothing is how people learn to stop trusting the red
    circle, so when the two signals disagree, believe the ✅.
    """
    out: List[dict] = []
    fixed: List[str] = []
    stale: List[str] = []
    gated: List[str] = []
    prior = prior or {}
    for m in inc._history(client, channel):
        text = m.get("text") or ""
        mark = inc._MARK_RE.search(text)
        if not mark or mark.group("state") != "open":
            continue
        key = mark.group("key")
        reactions = [r.get("name") for r in (m.get("reactions") or [])]
        if inc.DONE_REACTION in reactions or "RESOLVED" in text:
            fixed.append(key)
            continue
        if inc._days_open(mark.group("date"), day) > STALE_LIMIT_DAYS:
            stale.append(key)
            continue
        # A MARK THIS MODULE DIDN'T PUT THERE BELONGS TO SOMEBODY ELSE, AND IT
        # OUTRANKS US (2026-08-26, both halves found by running this for real).
        #
        #   :large_purple_circle: — notify.py sets it on an approval-gated phase
        #     waiting on a human checkmark, the same purple the Hub's approval
        #     pill shows. It already points at a person AND says which action
        #     they owe: tick the approval. Red would say "needs a code fix"
        #     about a report that is working perfectly and waiting on Megan.
        #
        #   :pending: — mark_working sets it: a PERSON is on this one right now.
        #     Eve was mid-fix on captainship_drafts_review when this pass would
        #     have stripped her mark and painted it red. That is strictly worse
        #     than doing nothing: ":pending: means somebody is on it" is the one
        #     thing stopping two people starting the same ticket (Eve
        #     2026-08-17), and "needs a person" is the vaguer claim of the two.
        #     Somebody already IS that person.
        #
        # `prior` is this module's own state, so a mark TRIAGE assigned is still
        # triage's to update — only another owner's mark is untouchable.
        _mine = (prior.get(key) or {}).get("bucket")
        _theirs = [(r, b) for r, b in ((inc.WAITING_REACTION, WAITING),
                                       (inc.WORKING_REACTION, LUCY))
                   if r in reactions and _mine != b]
        if _theirs:
            gated.append(key)
            continue
        ent = (inc._load_index() or {}).get(key) or {}
        today = ent.get("today") if isinstance(ent.get("today"), dict) else {}
        out.append({
            "key": key,
            "ts": m.get("ts") or "",
            "opened": mark.group("date"),
            "repeats": int(today.get("repeats") or 0)
            if today.get("date") == day.isoformat() else 0,
            "reactions": reactions,
        })
    return out, fixed, stale, gated


def _apply(client, channel: str, ts: str, bucket: str,
           existing: Sequence[str], *, dry_run: bool) -> bool:
    """Put this bucket's reaction on the parent and take the other two off.

    ONE answer per post. A post wearing both :pending: and :red_circle: is worse
    than an unmarked one — it is the state the whole reaction layer exists to
    prevent (see incident_thread._react_done on the ✅/:pending: pair).

    The ✅ is never touched here: a resolved post is not this module's business,
    and _open_incidents can't return one anyway.
    """
    want = BUCKET_REACTION[bucket]
    if want in existing and not any(
            r in existing for r in _ALL_REACTIONS if r != want):
        return False                      # already correct — no API calls
    if dry_run:
        print("    DRY-RUN — would set :{}: (currently {})".format(
            want, ", ".join(existing) or "none"))
        return True
    for r in _ALL_REACTIONS:
        if r != want and r in existing:
            inc._react(client, channel, ts, r, remove=True)
    if want not in existing:
        inc._react(client, channel, ts, want)

    # THE MARK IS READ BACK, BECAUSE ok IS NOT PROOF (Megan 2026-08-27: "this
    # failed and alerted but didn't color code emojis like we set up").
    # failure-recruiter_retention_daily was graded `waiting` at 08:15, _react
    # raised nothing, the log recorded nothing — and the post carried no circle
    # for the rest of the day. _react's only signal is the API's own ok, so a
    # mark that does not stick is invisible to everything: no error, no emoji,
    # and (before the schedule change) no second pass to notice.
    #
    # A post with no circle is worse than a wrong one. A wrong circle is read
    # and corrected; a missing one just quietly drops that incident out of the
    # morning list, which is the one thing this module exists to prevent.
    landed = inc.reactions_now(client, channel, ts)
    if landed is None or want in landed:
        return True
    inc._react(client, channel, ts, want)            # one retry, then say so
    landed = inc.reactions_now(client, channel, ts)
    if landed is not None and want not in landed:
        print("    ⚠ :{}: did NOT land on {} — Slack accepted the call and the "
              "post is still wearing {}. This incident has no answer on it."
              .format(want, ts, ", ".join(landed) or "nothing"))
        return False
    return True


def run(*, day: Optional[dt.date] = None, channel: str = inc.CHANNEL,
        dry_run: bool = False, client=None,
        now_hour: Optional[int] = None) -> Dict[str, List[str]]:
    """Triage every open incident. Returns {bucket: [keys]} for the caller/log.

    Reactions and one thread line are the ONLY things this writes to Slack.
    """
    day = day or dt.date.today()
    client = client or inc._client()

    # Only Lucy, for the same reason mark_working is Lucy-only: Slack lets you
    # remove your OWN reaction and nobody else's, so a circle added under a
    # person's token can never be taken off again when the state changes — it
    # would freeze a stale answer onto the post permanently.
    if not dry_run and not inc.is_lucy(client):
        print("[triage] not running from {} — only Lucy can take these "
              "reactions off again. Queue it on the mini (`lucy incident_triage`)."
              .format(inc.whoami(client) or "this machine"))
        return {}

    st = _load_state()
    found, fixed, stale, gated = _open_incidents(client, channel, day, st)
    out: Dict[str, List[str]] = {NEEDS_YOU: [], LUCY: [], WAITING: []}
    if fixed:
        # THESE ARE FINISHED HERE, NOT JUST COUNTED (Megan 2026-08-26). A post
        # in this state — ✅ on it, marker still `open` — is closed to a person
        # and open to every machine, so it keeps showing up in scans, keeps
        # being a candidate for a wrong circle, and keeps this line growing.
        # Triage has named them since it shipped and nothing ever went back to
        # finish the edit; six were sitting that way the day it launched.
        #
        # This pass is the right owner for it: it already walked the same
        # history (close_stranded reuses the cached scan), it already runs as
        # Lucy, and only the POSTER may chat.update — so anything Lucy opened
        # gets finished here and the rest are named for whoever owns them.
        # close_stranded is narrow and idempotent: it only ever touches a parent
        # that ALREADY carries the ✅, and it never posts, replies or resolves.
        print("  ({} already fixed — ✅ on the post, marker text never "
              "updated: {})".format(len(fixed), ", ".join(sorted(set(fixed)))))
        try:
            done = inc.close_stranded(channel=channel, client=client,
                                      dry_run=dry_run)
            if done.get("closed"):
                print("    {} marker(s) {}: {}".format(
                    len(done["closed"]),
                    "would be finished" if dry_run else "finished",
                    ", ".join(done["closed"])))
            if done.get("not_ours"):
                print("    {} belong to another machine — run `lucy "
                      "incident_close_stranded` there: {}".format(
                          len(done["not_ours"]), ", ".join(done["not_ours"])))
        except Exception as e:  # noqa: BLE001 — bookkeeping never breaks triage
            print("    - couldn't finish stranded markers ({}: {})".format(
                type(e).__name__, str(e)[:80]))
    if stale:
        print("  ({} stale marker(s) older than {} days, never rolled over: "
              "{})".format(len(stale), STALE_LIMIT_DAYS,
                           ", ".join(sorted(set(stale)))))
    if gated:
        print("  ({} already carry someone else's mark (a person on it, or an "
              "approval gate) — left alone: {})".format(
                  len(gated), ", ".join(sorted(set(gated)))))

    for item in found:
        key = item["key"]
        v = classify(key, day=day, opened=item["opened"],
                     repeats=item["repeats"], now_hour=now_hour)
        v.ts = item["ts"]
        out[v.bucket].append(key)
        print("  {:<44} {:<10} {}".format(key[:44], v.bucket, v.reason))

        _apply(client, channel, item["ts"], v.bucket, item["reactions"],
               dry_run=dry_run)

        # The line goes in ONCE per state, not once per pass.
        prev = st.get(key) if isinstance(st.get(key), dict) else {}
        if prev.get("bucket") == v.bucket:
            continue
        if dry_run:
            print("    DRY-RUN — would say: {}".format(line_for(v)))
        else:
            try:
                inc._send(client, channel, [line_for(v)], thread_ts=item["ts"])
            except Exception as e:  # noqa: BLE001 — the reaction is the point
                print("    - couldn't post the triage line ({}: {})".format(
                    type(e).__name__, str(e)[:60]))
        st[key] = {"bucket": v.bucket, "day": day.isoformat(),
                   "reason": v.reason}

    # Forget incidents that are no longer open, so a key that comes back later
    # gets a fresh line instead of being silenced by a stale state entry.
    live = {i["key"] for i in found} | set(gated)
    for k in [k for k in st if k not in live]:
        st.pop(k, None)
    if not dry_run:
        _save_state(st)

    print("\n[triage] {} need you · {} with Lucy · {} waiting on a source"
          .format(len(out[NEEDS_YOU]), len(out[LUCY]), len(out[WAITING])))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Sort the open incidents into needs-you / Lucy / waiting.")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the verdicts, touch nothing in Slack")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--channel", default=inc.CHANNEL)
    ap.add_argument("--hour", type=int,
                    help="pretend it is this hour (testing the noon cut-off)")
    a = ap.parse_args(argv)
    day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    run(day=day, channel=a.channel, dry_run=a.dry_run, now_hour=a.hour)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
