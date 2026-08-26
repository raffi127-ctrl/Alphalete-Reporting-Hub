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
This module has no write access to anything but reactions and one thread line.
It does not edit code, does not re-run reports, does not post to any other
channel. That is deliberate and it is the whole reason it was safe to build:
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
    ("held", "It ran, but held back one part it wasn't sure about."),
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
        return Verdict(key, WAITING, reason)
    reason = _match(tail, _TRANSIENT)
    if reason:
        return Verdict(key, LUCY, reason)

    # 6) No log, no signature, still early. The loop has budget left, so let it
    #    spend it — this becomes NEEDS_YOU on its own at noon via (4).
    return Verdict(key, LUCY, "It failed and the reason isn't in the log.")


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
        print("  ({} already fixed — ✅ on the post, marker text never "
              "updated: {})".format(len(fixed), ", ".join(sorted(set(fixed)))))
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
