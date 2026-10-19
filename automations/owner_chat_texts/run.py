"""Text the trackers + the Org WOW board into the owners' iMessage chats.

RUNS ON LUCY 1 — Messages there is signed in as alphaletereporting@gmail.com.
Raf's 2026-08-23 ask:

    Alphalete owners - Real CHAT : all the trackers + Org WOW sales board
    Knocking Chat A-Players      : Org WOW sales board only (was the A-Team
                                   chat until Raf, 2026-09-28)

Sources (nothing is re-captured — no extra Tableau hits):
  * trackers  — the PNGs Lucy 3 already posted to #alphalete-sales today,
                downloaded back out of the thread (slack_fetch)
  * WOW board — rendered from the Org Sales Board sheet via the email's own
                PDF-export engine (board_shot)

Sending reuses b2b_dispositions.text_post (group resolved by NAME every send,
image staged into ~/Pictures so sandboxed Messages can read it). ONE-TIME on
Lucy 1: the first live run pops macOS's "wants to control Messages" consent —
a human must click Allow, and Lucy (alphaletereporting) must already be a
member of both chats.

Usage
  # dry-run (DEFAULT): fetch/render images, resolve both chats, send NOTHING.
  python -m automations.owner_chat_texts.run

  # live: send, then drop per-(item, day) .sent markers (retry-safe).
  python -m automations.owner_chat_texts.run --send

  # one half only
  python -m automations.owner_chat_texts.run --only trackers
  python -m automations.owner_chat_texts.run --only board

  # trackers the 9:00 PDF went out without, once they post (one follow-up PDF)
  python -m automations.owner_chat_texts.run --only late

--send is the ONLY thing that texts anyone. Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Optional

from automations.owner_chat_texts import config as cfg

try:
    from zoneinfo import ZoneInfo
    _CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    _CENTRAL = None


def _today() -> dt.date:
    return (dt.datetime.now(_CENTRAL) if _CENTRAL else dt.datetime.now()).date()


def _past_partial_backstop(day: dt.date) -> bool:
    """True once the wait-for-every-tracker window is over: past
    PDF_PARTIAL_AFTER Central on the day itself, or any run for a prior day
    (yesterday's stragglers are never coming)."""
    now = dt.datetime.now(_CENTRAL) if _CENTRAL else dt.datetime.now()
    if day < now.date():
        return True
    hh, mm = (int(x) for x in cfg.PDF_PARTIAL_AFTER.split(":"))
    return now.time() >= dt.time(hh, mm)


def _marker(key: str, day: dt.date) -> Path:
    """One marker per (item, day): a double text is a duplicate to every owner
    in the chat, not a harmless retry."""
    return cfg.OUTPUT_DIR / day.isoformat() / ("%s.sent" % key)


def _slug(name: str) -> str:
    """A chat name as a marker-file-safe token."""
    return "".join(c if c.isalnum() else "_" for c in (name or "").lower()).strip("_")


def _send_item(key: str, caption: str, png: Path, groups: list, day: dt.date,
               dry_run: bool, out: dict, resend: bool = False) -> None:
    """Send one captioned image to its groups; record per-group results.

    `resend` deliberately ignores today's marker. Only for the case it was
    written for (Megan 2026-08-26): the boards we already texted were built on
    Tableau data that hadn't finished loading, so the owners are holding numbers
    that are simply wrong — NDS Tuesday went out at 744 and settled at 1,075.
    A second text is a duplicate to every owner in the chat, so it has to say
    why it exists; the caption is stamped rather than repeated verbatim."""
    from automations.b2b_dispositions import text_post as tp
    m = _marker(key, day)
    if m.exists() and not dry_run and not resend:
        out["skipped"].append("%s (already sent %s)" % (key,
                              m.read_text().strip()[:19]))
        return
    if resend and m.exists():
        caption = ("UPDATED — " + caption
                   + "\nTableau had not finished loading yesterday when the "
                     "first version went out this morning. These are the "
                     "settled numbers; replace the earlier ones.")
        out["skipped"].append("%s (RESEND over %s)" % (key,
                              m.read_text().strip()[:19]))
    ok = True
    for group in groups:
        # A group is a name needle or a participant-pinned dest dict.
        name = group.get("group", "") if isinstance(group, dict) else group
        # PER-GROUP marker too (2026-10-07, adding Colten's chats): a retry
        # after ONE group failed used to re-text every group that had already
        # got it, since only the item marker existed and it needs all of them.
        gm = _marker("%s__%s" % (key, _slug(name)), day)
        if gm.exists() and not dry_run and not resend:
            out["skipped"].append("%s -> %s (already sent %s)" % (
                key, name, gm.read_text().strip()[:19]))
            continue
        try:
            res = tp.send_to_group(name, caption, [png], dry_run=dry_run,
                                   dest=group if isinstance(group, dict) else None)
            out["sent"].append("%s %s -> %s (chat %s, %s participants)" % (
                "WOULD TEXT" if dry_run else "TEXTED", key, name,
                res.get("chat_id"), res.get("participants")))
            if not dry_run:
                gm.parent.mkdir(parents=True, exist_ok=True)
                gm.write_text(dt.datetime.now().isoformat(timespec="seconds"))
        except Exception as e:  # noqa: BLE001 — one group never blocks the rest
            ok = False
            out["errors"].append("%s -> %s: %s: %s" % (
                key, name, type(e).__name__, str(e)[:200]))
    if ok and not dry_run:
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(dt.datetime.now().isoformat(timespec="seconds"))


def _late_pending_path(day: dt.date) -> Path:
    return cfg.OUTPUT_DIR / day.isoformat() / "trackers_late_pending.json"


def _write_late_pending(day: dt.date, titles: list) -> None:
    p = _late_pending_path(day)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(list(titles)), encoding="utf-8")


def read_late_pending(day: dt.date) -> Optional[list]:
    """Tracker titles the 9:00 PDF went out WITHOUT and the chat hasn't got
    yet. None = the main PDF hasn't been sent today (nothing to judge yet);
    [] = nothing owed."""
    if not _marker("trackers_pdf", day).exists():
        return None
    p = _late_pending_path(day)
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text(encoding="utf-8")) or [])
    except Exception:  # noqa: BLE001 — a corrupt file owes nothing
        return []


def late_status(day: dt.date) -> tuple:
    """(ready, reason) for the late pass — what readiness asks before running
    owner_chat_texts_late_send. Ready when a tracker the 9:00 PDF missed is now
    in the Slack thread, when nothing is owed (the run is a no-op), or past
    LATE_CUTOFF (it stops waiting). Not ready while the main PDF hasn't gone
    out, or while every owed tracker is still missing."""
    now = dt.datetime.now(_CENTRAL) if _CENTRAL else dt.datetime.now()
    hh, mm = (int(x) for x in cfg.LATE_CUTOFF.split(":"))
    past = day < now.date() or (day == now.date() and now.time() >= dt.time(hh, mm))
    pending = read_late_pending(day)
    if pending is None:
        if past:
            return True, "past %s — main tracker PDF never sent; nothing to follow up" % cfg.LATE_CUTOFF
        return False, "main tracker PDF not sent yet"
    if not pending:
        return True, "the 9:00 PDF had every tracker — nothing late"
    from automations.owner_chat_texts.slack_fetch import thread_status
    present, _missing = thread_status(day)
    landed = [t for t in pending if t in present]
    if landed:
        return True, "late tracker(s) posted: %s" % ", ".join(landed)
    if past:
        return True, "past %s — %s never posted; giving up for today" % (
            cfg.LATE_CUTOFF, ", ".join(pending))
    return False, "waiting on late %s (until %s)" % (", ".join(pending),
                                                     cfg.LATE_CUTOFF)


def _run_late(day: dt.date, out_dir: Path, dry_run: bool, out: dict) -> None:
    """Text the trackers the 9:00 PDF was missing, as ONE short follow-up PDF,
    once they're in the Slack thread. One follow-up a day (marker
    'trackers_late'); whatever is still missing then stays missing."""
    from automations.owner_chat_texts.slack_fetch import fetch_tracker_pngs
    from automations.owner_chat_texts import pdf_build
    pending = read_late_pending(day)
    if pending is None:
        out["skipped"].append("late (main tracker PDF not sent today)")
        return
    if not pending:
        out["skipped"].append("late (nothing was missing from the 9:00 PDF)")
        return
    try:
        found, missing = fetch_tracker_pngs(day, out_dir / "late")
        late = [(s, p) for s, p in found
                if (s.get("title") or s.get("id")) in pending]
        out["missing"] = [t for t in pending if t in missing]
        if not late:
            out["skipped"].append("late (still not posted: %s)"
                                  % ", ".join(pending))
            return
        titles = [s.get("title") or s.get("id") for s, _p in late]
        pdf = pdf_build.build(late, out_dir / "late", day)
        _send_item("trackers_late", cfg.late_pdf_caption(day, titles), pdf,
                   cfg.TRACKER_GROUPS, day, dry_run, out)
        if not dry_run and _marker("trackers_late", day).exists():
            _write_late_pending(day, [t for t in pending if t not in titles])
    except Exception as e:  # noqa: BLE001
        out["errors"].append("late: %s: %s" % (type(e).__name__, str(e)[:240]))


def run(only: Optional[str] = None, *, day: Optional[dt.date] = None,
        dry_run: bool = True, force: bool = False,
        resend: bool = False, owe: Optional[list] = None) -> dict:
    day = day or _today()
    out_dir = cfg.OUTPUT_DIR / day.isoformat()
    out = {"day": day.isoformat(), "dry_run": dry_run,
           "sent": [], "skipped": [], "errors": [], "missing": []}

    if only in (None, "trackers"):
        from automations.owner_chat_texts.slack_fetch import fetch_tracker_pngs
        from automations.owner_chat_texts import pdf_build
        try:
            found, missing = fetch_tracker_pngs(day, out_dir)
            out["missing"] = missing              # late/failed on Lucy 3 — flagged
            if not found:
                raise RuntimeError("none of the trackers are in today's Slack "
                                   "thread yet")
            # ONE PDF, not nine messages (Raf 8/23). A PDF can't trickle in
            # stragglers, so: wait while trackers are still missing (exit 1 →
            # the scheduler retries), and from PDF_PARTIAL_AFTER send what's
            # there with the gaps named in the caption.
            if missing and not (force or _past_partial_backstop(day)):
                out["skipped"].append(
                    "trackers (WAITING — %d/%d posted; one PDF sends when all "
                    "are in, or partial after %s)" % (
                        len(found), len(found) + len(missing),
                        cfg.PDF_PARTIAL_AFTER))
            else:
                pdf = pdf_build.build(found, out_dir, day)
                was_sent = _marker("trackers_pdf", day).exists()
                _send_item("trackers_pdf",
                           cfg.trackers_pdf_caption(day, missing), pdf,
                           cfg.TRACKER_GROUPS, day, dry_run, out,
                           resend=resend)
                # What THIS send left out is what the late pass owes the chat.
                if not was_sent and _marker("trackers_pdf", day).exists():
                    _write_late_pending(day, missing)
        except Exception as e:  # noqa: BLE001 — trackers down must not block the board
            out["errors"].append("trackers: %s: %s" % (type(e).__name__,
                                                       str(e)[:240]))

    if only == "late":
        # --owe: mark trackers as owed by hand — for a day whose partial PDF
        # went out before the late pass existed (Carlos 2026-10-13, NDS).
        if owe and not dry_run and _marker("trackers_pdf", day).exists():
            have = read_late_pending(day) or []
            _write_late_pending(day, have + [t for t in owe if t not in have])
        _run_late(day, out_dir, dry_run, out)

    if only in (None, "board"):
        # Same completeness rule as the board email: don't show the owners a
        # board that is short of yesterday. data_gate reads the SHEET, so it
        # works from Lucy 1 (the fill manifest is mini-local and always stale
        # here). --force overrides for testing.
        hold = ""
        if not force:
            try:
                from automations.org_sales_board import data_gate
                gate_ok, why = data_gate.gate()
                if not gate_ok:
                    hold = why
            except Exception as e:  # noqa: BLE001 — a broken gate reads as HOLD
                hold = "data gate unreadable: %s: %s" % (type(e).__name__,
                                                         str(e)[:160])
        if hold:
            out["skipped"].append("board (HOLD — %s)" % hold)
        else:
            try:
                from automations.owner_chat_texts.board_shot import capture_wow_board
                png = capture_wow_board(out_dir)
                _send_item("wow_board", cfg.board_caption(day), png,
                           cfg.BOARD_GROUPS, day, dry_run, out,
                           resend=resend)
            except Exception as e:  # noqa: BLE001
                out["errors"].append("board: %s: %s" % (type(e).__name__,
                                                        str(e)[:240]))

    # ok = EVERYTHING due was delivered (or would be, on a dry run). The PDF
    # still WAITING on missing trackers, or a board data-gate HOLD, is not an
    # error but it IS undelivered — return non-ok so the scheduled run exits 1
    # and the orchestrator retries later in the morning. Retries are safe: each
    # delivered item has a per-day .sent marker. A PARTIAL PDF sent past the
    # backstop counts as delivered (the caption names the gaps), so `missing`
    # alone doesn't fail the run once the send has happened.
    undelivered = [s for s in out["skipped"]
                   if s.startswith(("board (HOLD", "trackers (WAITING"))]
    out["ok"] = not (out["errors"] or undelivered)
    return out


LATE_REPORT_ID = "owner_chat_texts_late_send"


def _late_manifest(res: dict) -> None:
    """The late pass's own account of what it delivered, for delivery_check.

    WHY (2026-10-17). It had no verify and wrote no manifest, so a clean run
    could only answer UNKNOWN and failure-owner_chat_texts_late_send stayed
    open on days it had nothing to do. Its job is ONLY what the 9:00 PDF left
    out: nothing owed = delivered (nothing to send); owed and texted =
    delivered; owed and still not in the Slack thread = NOT delivered (named,
    alert=False -- the readiness gate already chases it). A run with errors
    writes nothing and exits 1. Never allowed to fail the run."""
    try:
        from automations.shared import run_manifest
        still = [s for s in res.get("skipped", [])
                 if s.startswith("late (still not posted")]
        if res.get("errors"):
            return
        if still:
            run_manifest.write_manifest(
                LATE_REPORT_ID, kind="tracker", alert=False,
                failed=list(res.get("missing") or ["late tracker(s)"]),
                note=still[0])
            return
        sent = list(res.get("sent") or [])
        why = next((s for s in res.get("skipped", []) if s.startswith("late (")),
                   "")
        run_manifest.write_manifest(
            LATE_REPORT_ID, kind="tracker", succeeded=sent,
            note=("texted the late tracker(s)" if sent else why or "nothing owed"))
    except Exception as e:  # noqa: BLE001
        print("  (manifest write failed: %s — the run itself was fine)"
              % type(e).__name__, flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Text trackers + Org WOW board to the owner iMessage chats")
    ap.add_argument("--send", action="store_true",
                    help="actually text the chats (default: dry-run — fetch, "
                         "render, resolve groups, send nothing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="already the default; --send wins if both are passed")
    ap.add_argument("--only", choices=["trackers", "board", "late"], default=None,
                    help="late = text the trackers the 9:00 PDF was missing, "
                         "once they post (scheduler: owner_chat_texts_late_send)")
    ap.add_argument("--force", action="store_true",
                    help="skip the board data-completeness gate (testing)")
    ap.add_argument("--resend", action="store_true",
                    help="send again even though today's marker says it already "
                         "went out. For the day the SOURCE was wrong: the owners "
                         "are holding numbers built on a Tableau extract that "
                         "hadn't finished loading. The resent caption says so — "
                         "a second text is a duplicate to every owner in the "
                         "chat, never a silent one.")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (default: today Central)")
    ap.add_argument("--owe", action="append", default=None, metavar="TITLE",
                    help="with --only late --send: mark a tracker title (e.g. "
                         "'NDS Tracker') as owed to the chat today, so the late "
                         "pass sends it once it posts. Repeatable.")
    args = ap.parse_args(argv)

    day = dt.date.fromisoformat(args.day) if args.day else _today()
    dry = not args.send
    print("Owner chat texts — %s — day=%s%s" % (
        "DRY-RUN (no texts)" if dry else "SEND", day.isoformat(),
        " only=%s" % args.only if args.only else ""), flush=True)

    res = run(args.only, day=day, dry_run=dry, force=args.force,
              resend=args.resend, owe=args.owe)
    for line in res["sent"]:
        print("  " + line, flush=True)
    for line in res["skipped"]:
        print("  skipped %s" % line, flush=True)
    if res["missing"]:
        print("  ⚠ not in today's Slack thread yet: %s" %
              ", ".join(res["missing"]), flush=True)
    for line in res["errors"]:
        print("  ERROR %s" % line, flush=True)

    # The late follow-up has no Hub half of its own: the trackers pill already
    # went green on the 9:00 PDF.
    if res["ok"] and not dry and res["sent"] and args.only != "late":
        try:  # the Hub must never fail a delivered text
            from automations.day_orchestrator import hub_publish
            # The Hub card is a PHASE card (Megan 2026-08-23: "2 colors"):
            # phases = ["owner_chat_texts_trackers", "owner_chat_texts_board"],
            # so each half publishes ITS OWN id — the strings must match the
            # card's phases exactly or the pill sticks mid-colour
            # [[reference_phase_pill_id_match]]. Listing them in `phases` is
            # also what stops the second id auto-registering a phantom card.
            # A full run (no --only) delivered both halves, so it lights both.
            halves = {
                "trackers": [("owner_chat_texts_trackers",
                              "Owner Chat Texts — Trackers (iMessage)")],
                "board": [("owner_chat_texts_board",
                           "Owner Chat Texts — WOW Board (iMessage)")],
            }.get(args.only) or [
                ("owner_chat_texts_trackers",
                 "Owner Chat Texts — Trackers (iMessage)"),
                ("owner_chat_texts_board",
                 "Owner Chat Texts — WOW Board (iMessage)"),
            ]
            for rid, title in halves:
                hub_publish.publish_done(rid, title, status="success")
        except Exception:  # noqa: BLE001
            pass
    if args.only == "late" and not dry:
        _late_manifest(res)
    if res["ok"]:
        print("=== done%s ===" % (" (dry-run)" if dry else ""), flush=True)
    elif not res["errors"]:
        print("  not everything delivered yet — exiting 1 so the scheduler "
              "retries; delivered items are marker-protected from re-sends.",
              flush=True)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
