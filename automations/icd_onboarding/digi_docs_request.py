"""Send one person's Digi Docs because somebody asked for it, not on a clock.

Megan, 2026-11-22: "let's build out the ATT courses and Digi Docs on request"
-- and then, on what the courses need: "the quizes are created/sent once they
are added to ownerville / sent the digi docs".

SO THERE IS ONE ACTION HERE, NOT TWO. OwnerVille has no control that creates,
requests, assigns or resends an AT&T course: all 81 controls in a person's Set
Status modal were read on 2026-11-22 and the six course rows are status only,
each offering nothing but "Access Client Training", which is the REP's own
link. Every one of the 139 people on Raf's roster already reads "created but
Sales Rep have not yet completed". The courses arrive WITH the documents, and
completing them is the rep's move, exactly as the UID is ("Sales Rep has not
submitted ATTUID information"). So a request sends the documents, and the
quizzes follow; `from_ownerville` then ticks both columns as OwnerVille
reports them, which is unchanged.

WHAT THIS IS. The run already exists -- `digi_docs.run --both --live --only
"<name>"` works today, and `lucy rerun digi_docs --only "<name>"` already
reaches it, because rerun appends its extra args to the report's base_args.
What did not exist is a way for somebody who does not use a terminal to ask
for it. This turns the ask into a queued job for the machine that holds the
OwnerVille session, and refuses the asks that must not become sends.

GENERATING IS SENDING AND THERE IS NO UNSEND. That is the whole reason this
is more than a one-line enqueue:

  * a person whose Digi Docs column is already filled is REFUSED. The board
    says the documents went; asking again would send a second set.
  * a person already queued or running is REFUSED. Two rows for one name is
    two sends, and the mini would run both.
  * nothing here presses anything itself. It queues, and the existing run
    does the work behind its own gates -- OwnerVille's own section state
    decides whether a bundle may be generated, never the board, because the
    board is a sheet people type in.
  * dry by default, like everything else in this package.

WHOSE MACHINE. Read from the report's own config, never written down here:
digi_docs is pinned to a machine because the OwnerVille session is per-machine
([[feedback_machines_never_depend_on_each_other]]). An office with its own
computer will eventually collect this as an 'Office Jobs' kind instead, which
is where bgc_send already does exactly this dance; that is not built, because
only Raf has a book today and building it now would be building for nobody.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from automations.icd_onboarding import board as B
from automations.icd_onboarding import sheet as S

REPORT_ID = "digi_docs"
ACTION = "rerun"
# The column the board keeps the answer in. A request is refused when it is
# already filled, so this is the one name that must match the board.
COLUMN = "Digi Docs"
# What the cell says while the job waits. Carries the date, so a marker left
# behind by a job that never ran is obvious rather than ageless.
QUEUED_TEXT = B.QUEUED_PREFIX + "digi docs asked for %s"
# Rows the mini has not finished with yet. Matches mini_control's own words.
OPEN_STATUSES = ("queued", "running", "offered")


def _report_machine() -> Optional[str]:
    """The machine digi_docs is pinned to, from the orchestrator's config."""
    from automations.day_orchestrator import registry
    cfg = registry.load_config()
    r = registry.resolve_report(cfg, REPORT_ID)
    if r is None:
        raise RuntimeError(
            "no %r report in the orchestrator config, so there is nothing to "
            "queue against" % REPORT_ID)
    return getattr(r, "machine", None) or None


def args_for(name: str) -> str:
    """The rerun args. Quoted, because rerun splits with shlex and a surname
    with a space in it must survive as ONE argument."""
    import shlex
    return "%s --only %s" % (REPORT_ID, shlex.quote(str(name or "").strip()))


def _client():
    from automations.recruiting_report.fill import _client as gc
    return gc()


def pending(gc, machine: Optional[str]) -> List[Dict]:
    """The rows on that machine's control tab the mini has not finished.

    Read before queueing, because a duplicate row is a duplicate SEND.
    """
    from automations.day_orchestrator import queue_enqueue as Q
    tab = Q.control_tab_for(machine)
    ss = gc.open_by_key(Q.CONTROL_SHEET_ID)
    try:
        ws = ss.worksheet(tab)
    except Exception:                       # noqa: BLE001 -- no tab, no queue
        return []
    rows = ws.get_all_values()
    if not rows:
        return []
    head = [str(h).strip() for h in rows[0]]
    try:
        ai, gi, si = (head.index("Action"), head.index("Args"),
                      head.index("Status"))
    except ValueError:
        return []
    out = []
    for raw in rows[1:]:
        def at(i):
            return str(raw[i] if i < len(raw) else "").strip()
        if at(si).lower() in OPEN_STATUSES:
            out.append({"action": at(ai), "args": at(gi),
                        "status": at(si).lower()})
    return out


def rows_for(gc, name: str, machine: Optional[str]) -> List[Dict]:
    """Every queue row for this person, newest last, open or finished.

    `pending` answers "may I ask again"; this answers "what became of the ask
    I already made", which needs the rows that are DONE as much as the ones
    that are not.
    """
    from automations.day_orchestrator import queue_enqueue as Q
    tab = Q.control_tab_for(machine)
    ss = gc.open_by_key(Q.CONTROL_SHEET_ID)
    try:
        ws = ss.worksheet(tab)
    except Exception:                       # noqa: BLE001 -- no tab, no rows
        return []
    raw = ws.get_all_values()
    if not raw:
        return []
    head = [str(h).strip() for h in raw[0]]
    try:
        ai, gi, si = (head.index("Action"), head.index("Args"),
                      head.index("Status"))
    except ValueError:
        return []
    fi = head.index("Finished At") if "Finished At" in head else None
    ri = head.index("Result") if "Result" in head else None
    want = args_for(name).lower()
    out = []
    for r in raw[1:]:
        def at(i):
            return str(r[i] if i is not None and i < len(r) else "").strip()
        if at(ai).lower() != ACTION or at(gi).lower() != want:
            continue
        out.append({"status": at(si).lower(), "finished": at(fi),
                    "result": at(ri)})
    return out


def already_asked(gc, name: str, machine: Optional[str]) -> Optional[Dict]:
    """An open row that would already send this person's documents."""
    want = args_for(name).lower()
    bare = str(name or "").strip().lower()
    for r in pending(gc, machine):
        if r["action"].lower() != ACTION:
            continue
        a = r["args"].lower()
        if a == want or (REPORT_ID in a and bare and bare in a):
            return r
    return None


def board_state(office_key: str, week_start: dt.date, name: str) -> str:
    """What the board says about this person's Digi Docs: the cell's text.

    "" means outstanding. Anything else means the documents already went, and
    `request` refuses on it -- the one check that stops a second send.
    """
    ws = S.board_for(office_key, week_start, create=False)
    if ws is None:
        raise RuntimeError("office %r has no board for the week of %s"
                           % (office_key, B.week_label(week_start)))
    grid = S._values(ws)
    if COLUMN not in S.layout(grid):
        raise RuntimeError("that board has no %r column" % COLUMN)
    want = B._fold(name)
    for r in S.rows_of(grid):
        if B._fold("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))) == want:
            if str(r.get(B.TERMINATED_AT) or "").strip():
                raise RuntimeError("%s is marked off the board for that week"
                                   % name)
            return str(r.get(COLUMN) or "").strip()
    raise RuntimeError("%s is not on %s's board for the week of %s"
                       % (name, office_key, B.week_label(week_start)))


def request(office_key: str, name: str, week_start: dt.date, *,
            by: str = "board", dry_run: bool = True, log=print) -> Dict:
    """Ask for one person's Digi Docs. Returns what was done and why.

    Never raises for a refusal -- a refusal is an answer the board shows. It
    raises only when it cannot tell, because a request that silently does
    nothing is the failure this whole package keeps re-learning.
    """
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "why": "no name"}

    said = board_state(office_key, week_start, name)
    if said:
        log("  %s: the board already has %s = %r -- not asking again"
            % (name, COLUMN, said))
        return {"ok": False, "why": "already sent", "cell": said}

    machine = _report_machine()
    gc = _client()
    open_row = already_asked(gc, name, machine)
    if open_row:
        log("  %s: already %s on %s -- one ask is one send"
            % (name, open_row["status"], machine or "the default machine"))
        return {"ok": False, "why": "already queued", "row": open_row}

    args = args_for(name)
    if dry_run:
        log("  would queue on %s: %s %s" % (machine or "the default machine",
                                            ACTION, args))
        return {"ok": True, "queued": False, "machine": machine,
                "action": ACTION, "args": args}

    from automations.day_orchestrator import queue_enqueue as Q
    tab = Q.enqueue(gc, ACTION, args, by=by, machine=machine)
    log("  queued on %s: %s %s" % (tab, ACTION, args))
    return {"ok": True, "queued": True, "machine": machine, "tab": tab,
            "action": ACTION, "args": args}


def mark_queued(office_key: str, week_start: dt.date, names: List[str], *,
                dry_run: bool = True, log=print) -> int:
    """Write QUEUED: into each person's Digi Docs cell, and tint it.

    WHY THE BOARD AND NOT JUST THE QUEUE. The panel is the only surface an
    admin reads, and a request that leaves no mark there looks exactly like
    one that was never made -- so the same person gets asked for twice by the
    next person to open the board. It is an ASK, not an answer: `plan` and
    `write_step` both treat it as outstanding (board.answered), so the real
    date lands on top of it the moment the send actually reports.

    The tint is the suggested-amber, never the green a finished step gets:
    green here would say the documents had gone.
    """
    ws = S.board_for(office_key, week_start, create=False)
    if ws is None:
        raise RuntimeError("office %r has no board for the week of %s"
                           % (office_key, B.week_label(week_start)))
    grid = S._values(ws)
    cols = S.layout(grid)
    if COLUMN not in cols:
        raise RuntimeError("that board has no %r column" % COLUMN)
    want = {B._fold(n) for n in names}
    stamp = QUEUED_TEXT % dt.date.today().strftime("%m/%d/%Y")
    a1 = S._a1(cols[COLUMN] + 1)
    writes, cells = [], []
    for r in S.rows_of(grid):
        key = B._fold("%s %s" % (r.get("Name", ""), r.get("Last Name", "")))
        if key not in want:
            continue
        if str(r.get(COLUMN) or "").strip():
            continue              # already answered, or already marked
        at = "%s%d" % (a1, S.row_number(r))
        writes.append({"range": at, "values": [[stamp]]})
        cells.append(at)
    log("  %d cell(s) to mark queued" % len(writes))
    if dry_run or not writes:
        return 0
    ws.batch_update(writes)
    ws.format(cells, {"backgroundColor": B.SUGGESTED})
    return len(writes)


def stale_asks(office_key: str, week_start: dt.date, *, gc=None,
               machine: Optional[str] = None) -> List[Dict]:
    """People whose QUEUED: never became anything. Reads only.

    A marker says "asked for, not yet done" and is deliberately an ASK, so
    the real date lands on top of it when the send reports. That is also why
    a request that DIES leaves the marker sitting there for ever: nothing
    clears an ask, and the sweep will not, because an ask is not an answer.
    The only clue was the date going stale, which nobody watches.

    DEAD IS READ OFF THE QUEUE, NOT OFF A CLOCK. A job still queued or
    running is simply not finished, however old it looks. One that FINISHED
    and left the cell still an ask either failed, or succeeded and the
    hourly OwnerVille scan has not written the date yet -- so a finished row
    only counts once the scan has had its hour. A marker with no row at all
    (the tab gets trimmed) counts once its date is in the past.
    """
    ws = S.board_for(office_key, week_start, create=False)
    if ws is None:
        return []
    grid = S._values(ws)
    if COLUMN not in S.layout(grid):
        return []
    gc = gc or _client()
    machine = machine or _report_machine()
    today = dt.date.today()

    out = []
    for r in S.rows_of(grid):
        said = str(r.get(COLUMN) or "").strip()
        if not said.startswith(B.QUEUED_PREFIX):
            continue
        if str(r.get(B.TERMINATED_AT) or "").strip():
            continue              # off the board; the marker goes with them
        who = ("%s %s" % (r.get("Name", ""), r.get("Last Name", ""))).strip()
        rows = rows_for(gc, who, machine)
        open_rows = [x for x in rows if x["status"] in OPEN_STATUSES]
        if open_rows:
            continue              # still waiting its turn, or running now
        if rows:
            why = ("the job finished and no date came back"
                   + (" (%s)" % rows[-1]["result"] if rows[-1]["result"]
                      else ""))
            when = _marker_date(said)
            # Give the hourly scan its chance before calling it a failure.
            if when is not None and when >= today and not rows[-1]["finished"]:
                continue
        else:
            when = _marker_date(said)
            if when is None or when >= today:
                continue          # asked today, no row yet -- too early to say
            why = "no job was ever queued for them"
        out.append({"name": who, "row": S.row_number(r), "cell": said,
                    "why": why})
    return out


def _marker_date(text: str) -> Optional[dt.date]:
    """The date inside a QUEUED: cell, or None when it cannot be read.

    None is never treated as stale: a marker nobody can date is not evidence
    that anything failed.
    """
    import re
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(text or ""))
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def clear_stale(office_key: str, week_start: dt.date, *, dry_run: bool = True,
                log=print, gc=None, machine: Optional[str] = None) -> int:
    """Turn a dead QUEUED: into a NEEDS: that says what happened.

    NOT back to blank. Blank is what "nobody has asked yet" looks like, and
    a request that died is a different thing: somebody asked, it did not
    happen, and the next person to look should be told rather than left to
    ask again and wonder. It stays an ASK either way, so the real date still
    lands on top of it if the documents do go.
    """
    stale = stale_asks(office_key, week_start, gc=gc, machine=machine)
    if not stale:
        log("  no stale requests on the week of %s" % B.week_label(week_start))
        return 0
    for s in stale:
        log("  %-24s %s" % (s["name"], s["why"]))
    if dry_run:
        log("  (dry run -- %d marker(s) left as they are)" % len(stale))
        return 0
    ws = S.board_for(office_key, week_start, create=False)
    grid = S._values(ws)
    a1 = S._a1(S.layout(grid)[COLUMN] + 1)
    writes = [{"range": "%s%d" % (a1, s["row"]),
               "values": [[B.ASK_PREFIX + "digi docs were asked for and did "
                           "not go -- ask again"]]} for s in stale]
    ws.batch_update(writes)
    ws.format(["%s%d" % (a1, s["row"]) for s in stale],
              {"backgroundColor": B.UNSURE})
    log("  marked %d request(s) as needing another ask" % len(writes))
    return len(writes)


def request_many(office_key: str, names: List[str], week_start: dt.date, *,
                 by: str = "board", dry_run: bool = True, log=print) -> Dict:
    """Ask for several people at once -- one JOB EACH, never one wide run.

    Megan, 2026-11-22: the panel checks people off and sends to all of them.

    ONE PERSON PER JOB IS THE POINT, not a limitation to work around. The run
    refuses `--only` unless it matches exactly one person -- "a scoped run
    that silently widens is the whole thing --only exists to prevent" -- and
    that guarantee is worth more than saving a browser launch: each job is
    gated on its own, reports its own result, and one person's failure can
    never send somebody else a second set of documents.

    Every refusal is per person and none of them stops the rest: a board where
    half the selection was already sent should still send the other half, and
    say which was which.
    """
    out = {"queued": [], "refused": [], "machine": None}
    for name in names:
        got = request(office_key, name, week_start, by=by, dry_run=dry_run,
                      log=log)
        out["machine"] = got.get("machine") or out["machine"]
        if got.get("ok"):
            out["queued"].append(name)
        else:
            out["refused"].append({"name": name, "why": got.get("why"),
                                   "cell": got.get("cell")})
    if out["queued"]:
        mark_queued(office_key, week_start, out["queued"], dry_run=dry_run,
                    log=log)
    log("  %d queued, %d refused" % (len(out["queued"]), len(out["refused"])))
    return out


def main(argv=None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Ask for one person's Digi Docs (and so their AT&T "
                    "courses). DRY by default.")
    p.add_argument("--office", default="raf", help="the office key")
    p.add_argument("--name", action="append", default=[],
                   help="'First Last', as the board spells them. Repeat it "
                        "for several people -- each becomes its own job.")
    p.add_argument("--week", default="", help="the week's Sunday, YYYY-MM-DD. "
                                             "Default: this week.")
    p.add_argument("--by", default="cli", help="who asked")
    p.add_argument("--send", action="store_true",
                   help="actually queue it. Without this, nothing is queued.")
    p.add_argument("--sweep", action="store_true",
                   help="instead of asking: find requests that died and mark "
                        "them as needing another ask.")
    a = p.parse_args(argv)

    week = (dt.date.fromisoformat(a.week) if a.week
            else B.week_start_of(dt.date.today()))
    if a.sweep:
        clear_stale(a.office, week, dry_run=not a.send)
        return 0
    if not a.name:
        p.error("--name, or --sweep")
    got = request_many(a.office, a.name, week, by=a.by, dry_run=not a.send)
    for r in got["refused"]:
        print("refused %-24s %s%s" % (r["name"], r["why"],
                                      " (%s)" % r["cell"] if r.get("cell")
                                      else ""))
    if not a.send:
        print("\n(dry run -- nothing queued. --send to ask for real.)")
    # Nobody queued is a failure worth an exit code: a request that quietly
    # did nothing is the shape this package keeps re-learning.
    return 0 if got["queued"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
