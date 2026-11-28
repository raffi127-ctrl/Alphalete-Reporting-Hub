"""Send today's text bundles as one PDF each (see config.py for the why).

    python -m automations.text_bundles.run --due            # what launchd runs
    python -m automations.text_bundles.run --bundle morning # DRY RUN: what would go
    python -m automations.text_bundles.run --bundle weeks --send --final
    ... --dm U046G04P5LG   Slack-DM the PDF instead of texting (preview)

--due: for each bundle whose tick is this minute (+-7), send if every part
expected today has arrived, or if this is its LAST tick (then whatever is
there). Once per bundle per day (store SENT marker; --force resends).
Never touches Messages itself: it writes a manifest + outbox ticket and the
Lucy 2 poller texts it, like every other report. Python 3.9-safe.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from automations.text_bundles import config as C
from automations.text_bundles import pdf as PDF
from automations.text_bundles import store as ST


def _log(m: str) -> None:
    print("[bundles] " + m, flush=True)


def due(now: dt.datetime, slack_min: int = 7) -> List[Tuple[str, bool]]:
    """[(bundle, is_final_tick)] whose tick is within `slack_min` of now."""
    out = []
    for name, b in C.BUNDLES.items():
        if now.weekday() not in b["weekdays"]:
            continue
        ticks = b["ticks"]
        for i, (h, m) in enumerate(ticks):
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if abs((now - t).total_seconds()) <= slack_min * 60:
                out.append((name, i == len(ticks) - 1))
                break
    return out


def missing(bundle: str, got: Dict, day: dt.date) -> List[str]:
    return [label for pid, label, days in C.BUNDLES[bundle]["parts"]
            if day.weekday() in days and pid not in got]


def _teams_part(day: dt.date) -> Optional[Dict]:
    """The NDS Sales Board's Teams box, shot now (the weeks bundle)."""
    try:
        from automations.sales_boards.teams_box import render_teams_box
        png = render_teams_box("NDS Sales Board",
                               ST.bundle_dir("weeks", day) / "teams__0.png", log=_log)
        return {"text": "", "images": [str(png)]}
    except Exception as e:  # noqa: BLE001 -- the tables still go out
        _log("teams box failed (%s: %s) -- PDF without it" % (type(e).__name__, str(e)[:160]))
        return None


def assemble(bundle: str, day: dt.date) -> Tuple[List[Tuple[str, str, List[str]]], Dict]:
    got = ST.parts(bundle, day)
    if bundle == "weeks" and any(k in got for k in ("nds_week1", "vz_week1", "nds_weeks", "vz_weeks")):
        t = _teams_part(day)
        if t:
            got["teams"] = t
    pages = []
    for pid, label, _days in C.BUNDLES[bundle]["parts"]:
        rec = got.get(pid)
        if not rec or not (rec.get("images") or (rec.get("text") or "").strip()):
            continue
        text = rec.get("text") or ""
        # A picture's text is just its caption: use it as the heading.
        if rec.get("images") and "\n" not in text.strip():
            heading, body = (text.strip() or label), ""
        else:
            heading, body = label, text
        pages.append((heading, body, rec.get("images") or []))
    return pages, got


def send_bundle(bundle: str, day: dt.date, *, final: bool, send: bool,
                force: bool = False, dm: Optional[str] = None) -> int:
    b = C.BUNDLES[bundle]
    if ST.is_sent(bundle, day) and not force and not dm:
        _log("%s: already sent today -- nothing to do" % bundle)
        return 0
    pages, got = assemble(bundle, day)
    gap = missing(bundle, got, day)
    _log("%s: have %s; missing %s" % (bundle, sorted(got) or "nothing", gap or "nothing"))
    if gap and not final and not force:
        _log("%s: waiting for the missing part(s) -- next tick" % bundle)
        return 0
    if not pages:
        _log("%s: nothing arrived today -- no PDF" % bundle)
        if send:
            ST.mark_sent(bundle, day, "empty")
        return 0
    title = "%s — %s %d" % (b["label"], day.strftime("%B"), day.day)
    out = ST.bundle_dir(bundle, day) / ("%s %s.pdf" % (b["label"], day.strftime("%-m-%-d")))
    PDF.build(pages, out)
    _log("%s: built %s (%d page(s))" % (bundle, out.name, len(pages)))
    if dm:
        from automations.shared import slack_metrics_post as smp
        smp.dm_user_with_file(out, user=dm, comment=title, file_name=out.name)
        _log("%s: DM'd to %s (texted nobody)" % (bundle, dm))
        return 0
    if not send:
        _log("%s: DRY RUN -- would text %r to %s" % (bundle, title, b["groups"]))
        return 0
    from automations.b2b_dispositions import run as bd_run
    from automations.b2b_dispositions import text_post as tp
    from automations.day_orchestrator import text_outbox as tob
    spec = {"kind": C.kind(bundle), "title": title,
            "by_campaign": {C.TEXT_CAMPAIGN: [str(out)]}}
    if not tp.spec_has_routes(spec):
        _log("%s: no route for %s/%s -- not queued" % (bundle, C.TEXT_CAMPAIGN, spec["kind"]))
        return 1
    mp = tp.write_manifest(spec, bd_run.OUTPUT_DIR / day.isoformat(),
                           "%s-%s" % (spec["kind"], dt.datetime.now().strftime("%H%M")))
    tob.drop(mp, by="text_bundles", day=day.isoformat())
    ST.mark_sent(bundle, day, "%d pages%s" % (len(pages), " (missing: %s)" % ", ".join(gap) if gap else ""))
    _log("%s: queued %s for %s" % (bundle, mp.name, b["groups"]))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--due", action="store_true", help="send the bundle(s) due now")
    ap.add_argument("--bundle", choices=sorted(C.BUNDLES))
    ap.add_argument("--send", action="store_true", help="queue the text (default: dry run)")
    ap.add_argument("--final", action="store_true", help="send even with parts missing")
    ap.add_argument("--force", action="store_true", help="resend today's")
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--dm", default=None, metavar="U...")
    a = ap.parse_args(argv)
    now = dt.datetime.now()
    day = dt.date.fromisoformat(a.date) if a.date else now.date()
    if a.due:
        todo = due(now)
        if not todo:
            _log("no bundle due at %s" % now.strftime("%H:%M"))
            return 0
        rc = 0
        for name, final in todo:
            rc |= send_bundle(name, day, final=final, send=True, force=a.force)
        return rc
    if not a.bundle:
        ap.error("--bundle or --due")
    return send_bundle(a.bundle, day, final=a.final, send=a.send, force=a.force, dm=a.dm)


if __name__ == "__main__":
    sys.exit(main())
