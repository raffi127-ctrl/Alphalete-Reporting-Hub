"""Capture one Tableau Country Tracker and text it to its iMessage group(s).

RUNS ON LUCY 2. Two things force that (both proven in production):
  * the iMessage groups + the one-time "control Messages" grant live on Lucy 2;
  * Lucy 2 already reaches Tableau (att_order_log pulls crosstabs there daily via
    tableau_patchright), so re-capturing the board here needs no cross-machine
    file transfer of the mini's PNG.

Invoked BY THE POLLER (the identity that holds the Messages grant): the mini
queues `text_tracker <id>` onto Lucy 2's control tab the moment the board posts to
Slack, and the poller runs this as a subprocess, which inherits the grant — the
same inheritance run_b2b_dispositions relies on.

Usage
  # dry-run (DEFAULT): capture the board, resolve the groups, send NOTHING.
  python -m automations.tracker_texts.run --tracker b2b_att_country

  # live: capture + text to each routed group, then drop a per-day .sent marker.
  python -m automations.tracker_texts.run --tracker b2b_box --send

--send is the ONLY thing that texts anyone. Everything else resolves + reports.
Python 3.9-safe (Lucy 2's runtime).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Optional

from automations.tracker_texts import config as cfg
from automations.tableau_screenshots import pages as pages_mod
from automations.b2b_dispositions import text_post as tp

try:
    from zoneinfo import ZoneInfo
    _CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    _CENTRAL = None


def _today() -> dt.date:
    return (dt.datetime.now(_CENTRAL) if _CENTRAL else dt.datetime.now()).date()


def _sent_marker(tracker_id: str, day: dt.date) -> Path:
    """One marker per (tracker, day). The control queue retries, and a double text
    is a duplicate to ~20 leaders, not a harmless re-run — so a completed send is
    recorded and never repeated the same day."""
    return cfg.OUTPUT_DIR / day.isoformat() / f"{tracker_id}.sent"


def send_tracker(tracker_id: str, *, day: Optional[dt.date] = None,
                 dry_run: bool = True, headless: bool = False) -> dict:
    """Capture one tracker board and text it to every group it's routed to.

    Returns a result dict; never raises for a routing/idempotency skip (those are
    normal outcomes), only for a genuine capture or send failure.
    """
    day = day or _today()
    spec = pages_mod.by_id(tracker_id)
    if spec is None:
        raise SystemExit(
            f"--tracker: no tableau tracker with id {tracker_id!r}. "
            f"Known: {[p['id'] for p in pages_mod.PAGES]}")

    groups = cfg.route_for(tracker_id)
    result = {"tracker": tracker_id, "title": spec.get("title"), "day": day.isoformat(),
              "groups": groups, "dry_run": dry_run, "sent": [], "errors": [],
              "ok": False}
    if not groups:
        result["ok"] = True
        result["skipped"] = "not routed for texting"
        return result

    marker = _sent_marker(tracker_id, day)
    if marker.exists() and not dry_run:
        result["ok"] = True
        result["skipped"] = "already texted %s" % marker.read_text().strip()[:40]
        return result

    # A stray human Chrome on Lucy 2 breaks the patchright capture, exactly as it
    # does for the other browser reports — close it first (best-effort).
    try:
        from automations.day_orchestrator import chrome_guard
        chrome_guard.close_stray_chrome()
    except Exception:  # noqa: BLE001 — a guard must never sink the run
        pass

    # Capture the SAME board tableau_screenshots posts (same view, same crop), into
    # this report's own output dir so it can't collide with the mini's image cache.
    out_dir = cfg.OUTPUT_DIR / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    from automations.tableau_screenshots import capture as cap
    from automations.shared.tableau_patchright import tableau_session
    with tableau_session(headless=headless, allow_form_login=False,
                         verbose=True) as page:
        png = cap.capture_page(page, spec, out_dir, verbose=True)
    result["image"] = str(png)

    text = cfg.caption(spec, day)
    result["text"] = text
    for group in groups:
        try:
            res = tp.send_to_group(group, text, [png], dry_run=dry_run)
            res["group"] = group
            result["sent"].append(res)
        except Exception as e:  # noqa: BLE001 — one group's failure never blocks the rest
            result["errors"].append("%s: %s: %s" % (group, type(e).__name__,
                                                    str(e)[:200]))

    result["ok"] = not result["errors"]
    if result["ok"] and not dry_run:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(dt.datetime.now().isoformat(timespec="seconds"))
    return result


def _describe(res: dict) -> str:
    lines = []
    verb = "WOULD TEXT" if res.get("dry_run") else "TEXTED"
    if res.get("skipped"):
        return "  skipped %s (%s)" % (res.get("tracker"), res["skipped"])
    lines.append("  %s: %s" % (res.get("tracker"), res.get("text")))
    if res.get("image"):
        lines.append("    image : %s" % res["image"])
    for s in res.get("sent", []):
        lines.append("    %s %s  (chat %s, %s participants, name=%r)" % (
            verb, s.get("group"), s.get("chat_id"), s.get("participants"),
            s.get("resolved_name")))
    for e in res.get("errors", []):
        lines.append("    ERROR %s" % e)
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Text a Tableau Country Tracker to "
                                             "its iMessage group(s).")
    ap.add_argument("--tracker", required=True,
                    help="tableau_screenshots pages.py id (e.g. b2b_att_country, "
                         "b2b_box)")
    ap.add_argument("--send", action="store_true",
                    help="actually text the groups (default: dry-run — capture + "
                         "resolve groups, send nothing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture + resolve groups, send NOTHING. This is already "
                         "the default; the flag exists so the poller (and a human) "
                         "can state it explicitly. --send wins if both are passed.")
    ap.add_argument("--headless", action="store_true",
                    help="run the capture browser headless")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (default: today Central)")
    args = ap.parse_args(argv)

    day = dt.date.fromisoformat(args.day) if args.day else _today()
    dry = not args.send
    print("Tracker texts — %s — tracker=%s day=%s" % (
        "DRY-RUN (no texts)" if dry else "SEND", args.tracker, day.isoformat()),
        flush=True)
    try:
        res = send_tracker(args.tracker, day=day, dry_run=dry, headless=args.headless)
    except Exception as e:  # noqa: BLE001
        print("  FAILED: %s: %s" % (type(e).__name__, str(e)[:240]), flush=True)
        return 1
    print(_describe(res), flush=True)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
