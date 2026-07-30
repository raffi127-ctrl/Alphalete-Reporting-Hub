"""B2B Dispositions — capture OwnerVille views and post them to Slack.

Cadence (scheduled on Lucy 2, mini-local/Central):
  * 12,1,2,3,4,5,6pm + 6:30pm  ->  Today's Activity + Time Tracker  (both campaigns)
  * 6:30pm only                ->  Territory Stats, one shot per territory

Usage:
  # capture only, save PNGs to output/, post NOTHING (default — the review loop)
  python -m automations.b2b_dispositions.run --which all --dry-run

  # the hourly job (Today's Activity + Time Tracker into their 2 threads)
  python -m automations.b2b_dispositions.run --which hourly --send

  # the 6:30 final: hourly views (tagged Final) + every-territory dispositions
  python -m automations.b2b_dispositions.run --which all --final --send

--dry-run is the DEFAULT. --send is the only thing that touches Slack.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Dict, List, Optional

from automations.b2b_dispositions import capture as cap
from automations.b2b_dispositions import config as cfg
from automations.b2b_dispositions import slack_post as sp

try:
    from zoneinfo import ZoneInfo
    _CENTRAL = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover — zoneinfo is stdlib on 3.9+
    _CENTRAL = None

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output" / "b2b_dispositions"


def _central_now() -> dt.datetime:
    now = dt.datetime.now(_CENTRAL) if _CENTRAL else dt.datetime.now()
    return now


def slot_label(final: bool, now: Optional[dt.datetime] = None) -> str:
    """The caption's time tag, snapped to the nearest scheduled slot so a job
    that fires a few minutes late still reads '1:00 PM', not '1:03 PM'. The
    6:30 final is tagged so the last shot of the day is obvious."""
    now = now or _central_now()
    if final:
        return f"{_fmt12(cfg.FINAL_SLOT)} (Final)"
    # snap to the closest hourly slot
    best = min(cfg.HOURLY_SLOTS,
               key=lambda hm: abs((now.hour * 60 + now.minute)
                                  - (hm[0] * 60 + hm[1])))
    return _fmt12(best)


def _fmt12(hm) -> str:
    h, m = hm
    ampm = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {ampm}"


def _capture_hourly(page, rqst: str, out_dir: Path, slot: str,
                    dry_run: bool) -> List[Dict]:
    """Today's Activity + Time Tracker for both campaigns -> reply specs, split
    by thread. Returns [{thread, caption, path, meta}, ...]."""
    specs = []
    for campaign in cfg.CAMPAIGNS:
        cap.ensure_campaign(page, rqst, campaign)  # sticky global — flip it first
        ta = cap.capture_todays_activity(page, rqst, campaign, out_dir, dump=dry_run)
        tt = cap.capture_time_tracker(page, rqst, campaign, out_dir, dump=dry_run)
        # Today's Activity: ONE shared thread, campaign in the caption.
        specs.append({"thread": cfg.THREAD_TODAYS_ACTIVITY,
                      "caption": f"{ta['tag']} — {slot}", "path": ta["path"],
                      "meta": ta})
        # Time Tracker: a thread PER campaign (Megan 7/29), so the caption is
        # just the time slot.
        specs.append({"thread": f"{cfg.THREAD_TIME_TRACKER} — {tt['tag']}",
                      "caption": slot, "path": tt["path"], "meta": tt})
    return specs


def _capture_dispositions(page, rqst: str, out_dir: Path,
                          dry_run: bool) -> List[Dict]:
    """Territory Stats: one shot per territory per campaign."""
    specs = []
    for campaign in cfg.CAMPAIGNS:
        cap.ensure_campaign(page, rqst, campaign)  # sticky global — flip it first
        terrs = cap.list_territories(page, rqst, campaign)
        tag = cfg.CAMPAIGN_TAG[campaign]
        print(f"  {tag}: {len(terrs)} territories", flush=True)
        for terr in terrs:
            res = cap.capture_territory_stats(page, rqst, campaign, terr,
                                              out_dir, dump=dry_run)
            specs.append({"thread": cfg.THREAD_DISPOSITIONS,
                          "caption": f"{res['tag']} — {res['territory']}",
                          "path": res["path"], "meta": res})
    return specs


def _post_by_thread(specs: List[Dict], today: dt.date, dry_run: bool) -> List[Dict]:
    """Group reply specs by thread and post each group. Thread names are dynamic
    now (Time Tracker splits per campaign), so group by first-seen order rather
    than a fixed list."""
    order = []
    for s in specs:
        if s["thread"] not in order:
            order.append(s["thread"])
    out = []
    for thread in order:
        group = [{"caption": s["caption"], "path": s["path"]}
                 for s in specs if s["thread"] == thread]
        if not group:
            continue
        out.append(sp.post_replies(thread, group, today, dry_run=dry_run))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="B2B Dispositions -> Slack")
    ap.add_argument("--which", choices=["hourly", "dispositions", "all"],
                    default="all", help="hourly = Today's Activity + Time "
                    "Tracker; dispositions = per-territory; all = both")
    ap.add_argument("--final", action="store_true",
                    help="tag the hourly shots as the 6:30 Final")
    ap.add_argument("--send", action="store_true",
                    help="post to the live Slack channels")
    ap.add_argument("--preview", action="store_true",
                    help="DM the captured shots to Megan for review (no channel post)")
    ap.add_argument("--dry-run", action="store_true",
                    help="capture + report only, post nothing (default)")
    ap.add_argument("--headless", action="store_true",
                    help="run the browser headless")
    ap.add_argument("--probe-campaigns", action="store_true",
                    help="scan invD2DClientId ids and log which campaign each maps to")
    args = ap.parse_args(argv)

    if args.probe_campaigns:
        from automations.shared.tableau_patchright import ownerville_session
        with ownerville_session(headless=args.headless) as page:
            try:
                page.set_viewport_size(dict(cap.VIEWPORT))
            except Exception:
                pass
            rqst = cap.capture_rqst(page)
            for cid in range(1, 31):
                url = (f"https://v2.ownerville.com/index.cfm?p={cfg.PAGE_TIME_TRACKER}"
                       f"&rqst={rqst}&invD2DClientId={cid}")
                try:
                    cap._goto(page, url)
                    label, cur = cap.current_campaign(page)
                except Exception as e:  # noqa: BLE001
                    label, cur = f"(err {type(e).__name__})", ""
                print(f"  probe id={cid} -> label={label!r} current={cur!r}",
                      flush=True)
        return 0

    # send -> live channels; preview -> DM Megan; neither -> dry-run (save only).
    dry_run = not (args.send or args.preview)
    today = _central_now().date()
    out_dir = OUTPUT_DIR / today.strftime("%Y-%m-%d")
    slot = slot_label(args.final)

    mode = ("SEND" if args.send else "PREVIEW-DM" if args.preview
            else "DRY-RUN (no Slack)")
    print(f"B2B Dispositions — {mode} — which={args.which} slot={slot!r} "
          f"out={out_dir}", flush=True)

    from automations.shared.tableau_patchright import ownerville_session
    specs: List[Dict] = []
    with ownerville_session(headless=args.headless) as page:
        # Tall viewport so more of each view sits in-frame (a plain screenshot
        # clips only within the viewport). Best-effort — a persistent context can
        # refuse a resize; the clamp in _shoot covers whatever the real size is.
        try:
            page.set_viewport_size(dict(cap.VIEWPORT))
        except Exception:
            pass
        rqst = cap.capture_rqst(page)
        if args.which in ("hourly", "all"):
            specs += _capture_hourly(page, rqst, out_dir, slot, dry_run)
        if args.which in ("dispositions", "all"):
            specs += _capture_dispositions(page, rqst, out_dir, dry_run)

    # Report captures (and flag any that fell back to a full-page shot or whose
    # on-screen campaign didn't match — the two things worth eyeballing).
    for s in specs:
        m = s["meta"]
        flag = []
        if m.get("how") == "full":
            flag.append("FULL-PAGE (crop anchor missed)")
        if not m.get("campaign_ok"):
            flag.append(f"campaign on-screen={m.get('on_screen')!r}")
        note = ("  ⚠ " + "; ".join(flag)) if flag else ""
        print(f"  [{s['thread']}] {s['caption']}  ->  {Path(s['path']).name}{note}",
              flush=True)

    if args.preview:
        res = sp.preview_dm(specs, today)
        print(f"\nPREVIEW — DM'd {len(res.get('sent', []))}/{len(specs)} shot(s) "
              f"to Megan for review. errors={res.get('errors')}", flush=True)
        return 0 if res.get("ok") else 1

    if dry_run:
        print(f"\nDRY-RUN complete — {len(specs)} shot(s) saved to {out_dir}. "
              f"Nothing posted. Review the PNGs, then re-run with --preview/--send.",
              flush=True)
        return 0

    results = _post_by_thread(specs, today, dry_run=False)
    ok = all(r.get("ok") for r in results)
    print(f"\nPosted. ok={ok}", flush=True)
    for r in results:
        print(f"  {r['thread']}: ok={r.get('ok')}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
