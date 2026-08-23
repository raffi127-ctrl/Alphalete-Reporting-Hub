"""Text the trackers + the Org WOW board into the owners' iMessage chats.

RUNS ON LUCY 1 — Messages there is signed in as alphaletereporting@gmail.com.
Raf's 2026-08-23 ask:

    Alphalete owners - Real CHAT : all the trackers + Org WOW sales board
    Alphalete A-Team chat        : Org WOW sales board only

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

--send is the ONLY thing that texts anyone. Python 3.9-safe (Lucy runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
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


def _marker(key: str, day: dt.date) -> Path:
    """One marker per (item, day): a double text is a duplicate to every owner
    in the chat, not a harmless retry."""
    return cfg.OUTPUT_DIR / day.isoformat() / ("%s.sent" % key)


def _send_item(key: str, caption: str, png: Path, groups: list, day: dt.date,
               dry_run: bool, out: dict) -> None:
    """Send one captioned image to its groups; record per-group results."""
    from automations.b2b_dispositions import text_post as tp
    m = _marker(key, day)
    if m.exists() and not dry_run:
        out["skipped"].append("%s (already sent %s)" % (key,
                              m.read_text().strip()[:19]))
        return
    ok = True
    for group in groups:
        try:
            res = tp.send_to_group(group, caption, [png], dry_run=dry_run)
            out["sent"].append("%s %s -> %s (chat %s, %s participants)" % (
                "WOULD TEXT" if dry_run else "TEXTED", key, group,
                res.get("chat_id"), res.get("participants")))
        except Exception as e:  # noqa: BLE001 — one group never blocks the rest
            ok = False
            out["errors"].append("%s -> %s: %s: %s" % (
                key, group, type(e).__name__, str(e)[:200]))
    if ok and not dry_run:
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text(dt.datetime.now().isoformat(timespec="seconds"))


def run(only: Optional[str] = None, *, day: Optional[dt.date] = None,
        dry_run: bool = True, force: bool = False) -> dict:
    day = day or _today()
    out_dir = cfg.OUTPUT_DIR / day.isoformat()
    out = {"day": day.isoformat(), "dry_run": dry_run,
           "sent": [], "skipped": [], "errors": [], "missing": []}

    if only in (None, "trackers"):
        from automations.owner_chat_texts.slack_fetch import fetch_tracker_pngs
        try:
            found, missing = fetch_tracker_pngs(day, out_dir)
            out["missing"] = missing              # late/failed on Lucy 3 — flagged
            for spec, png in found:               # send what IS there
                _send_item("tracker_%s" % spec["id"],
                           cfg.tracker_caption(spec, day), png,
                           cfg.TRACKER_GROUPS, day, dry_run, out)
        except Exception as e:  # noqa: BLE001 — trackers down must not block the board
            out["errors"].append("trackers: %s: %s" % (type(e).__name__,
                                                       str(e)[:240]))

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
                           cfg.BOARD_GROUPS, day, dry_run, out)
            except Exception as e:  # noqa: BLE001
                out["errors"].append("board: %s: %s" % (type(e).__name__,
                                                        str(e)[:240]))

    # ok = EVERYTHING due was delivered (or would be, on a dry run). A tracker
    # missing from the Slack thread or a board data-gate HOLD is not an error,
    # but it IS undelivered — return non-ok so the scheduled run exits 1 and
    # the orchestrator retries later in the morning. Retries are safe: each
    # delivered item has a per-day .sent marker, so only the stragglers send.
    held = [s for s in out["skipped"] if s.startswith("board (HOLD")]
    out["ok"] = not (out["errors"] or out["missing"] or held)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Text trackers + Org WOW board to the owner iMessage chats")
    ap.add_argument("--send", action="store_true",
                    help="actually text the chats (default: dry-run — fetch, "
                         "render, resolve groups, send nothing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="already the default; --send wins if both are passed")
    ap.add_argument("--only", choices=["trackers", "board"], default=None)
    ap.add_argument("--force", action="store_true",
                    help="skip the board data-completeness gate (testing)")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (default: today Central)")
    args = ap.parse_args(argv)

    day = dt.date.fromisoformat(args.day) if args.day else _today()
    dry = not args.send
    print("Owner chat texts — %s — day=%s%s" % (
        "DRY-RUN (no texts)" if dry else "SEND", day.isoformat(),
        " only=%s" % args.only if args.only else ""), flush=True)

    res = run(args.only, day=day, dry_run=dry, force=args.force)
    for line in res["sent"]:
        print("  " + line, flush=True)
    for line in res["skipped"]:
        print("  skipped %s" % line, flush=True)
    if res["missing"]:
        print("  ⚠ not in today's Slack thread yet: %s" %
              ", ".join(res["missing"]), flush=True)
    for line in res["errors"]:
        print("  ERROR %s" % line, flush=True)

    if res["ok"] and not dry and res["sent"]:
        try:  # the Hub must never fail a delivered text
            from automations.day_orchestrator import hub_publish
            rid, title = {
                "trackers": ("owner_chat_texts_trackers",
                             "Owner Chat Texts — Trackers (iMessage)"),
                "board": ("owner_chat_texts_board",
                          "Owner Chat Texts — WOW Board (iMessage)"),
            }.get(args.only, ("owner_chat_texts", "Owner Chat Texts (iMessage)"))
            hub_publish.publish_done(rid, title, status="success")
        except Exception:  # noqa: BLE001
            pass
    if res["ok"]:
        print("=== done%s ===" % (" (dry-run)" if dry else ""), flush=True)
    elif not res["errors"]:
        print("  not everything delivered yet — exiting 1 so the scheduler "
              "retries; delivered items are marker-protected from re-sends.",
              flush=True)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
