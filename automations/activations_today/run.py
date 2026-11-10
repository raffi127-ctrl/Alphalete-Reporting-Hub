"""📆 Activations Scheduled Today — one image in today's Metrics thread.

Raf 2026-11-09: "on the metrics report can we add to the thread a post called
'Activations scheduled Today' ... similar to the order log ... The goal of this
will be that the reps can see what customers they have scheduled for INSTALL
that day and then the reps can reach out to those customers that day."

Source path: Tableau -> ATT Tracker 2.1 - D2D -> PENDING INSTALLS
("Pending Installs (Internet/Video)") -> Crosstab -> Owner Name = <owner>,
Current Install Date = today (Central). See pull.py.

The board is grouped by rep, like the Order Log: a gray band per rep
("Alyssa Moreno • 3 orders") with that rep's customers under it, rows tinted by
Install Status (green on track, yellow self-install missing package, red past
due / JEP). Over 20 rows it splits into two images on one message.

Outward actions are OFF by default:
  (no flag)            pull + render, print what it WOULD post
  --post-slack         post into today's Metrics thread (#alphalete-sales)
  --post-to CHANNEL    post as a plain message to CHANNEL instead (tests: Eve's
                       self-DM D087ZGE2B0F only)
  --probe              list the view's crosstab sheets + describe the export
                       (no image, no post) — run this first on a Lucy
  --csv PATH           skip Tableau, read a crosstab you already have
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from automations.activations_today import pull

DEFAULT_OWNER = "Rafael Hidalgo"
LABEL = "📆 Activations Scheduled Today"
NONE_TEXT = "📆 No Activations Scheduled Today"
REACT = "date"
SPLIT_AT = 20

COLUMNS = ("Customer", "Sale Date", "Install Status", "Product", "Package")

# Install Status -> row tint (hex, pending_png._rgb). Definitions are the ones
# printed on the view itself.
_GREEN, _YELLOW, _RED = "C6EFCE", "FFF2CC", "FFC7CE"


def status_color(status: str, _history=()) -> str:
    s = (status or "").strip().lower()
    if not s:
        return ""
    if "past due" in s or "jep" in s:
        return _RED
    if "on track" in s:
        return _GREEN
    if "self install" in s:          # self-install, package info missing
        return _YELLOW
    return ""


class _Row:
    """One install dressed for box_order_log.pending_png (pre-baked cells)."""
    def __init__(self, cells, status, rep, sale_date, customer):
        self.cells = cells
        self.status = status
        self.history: tuple = ()
        self.rep = rep
        self.sale_date = sale_date
        self.fields = {"Rep Name": rep, "Business Name": customer}


def _short_product(v: str) -> str:
    s = (v or "").strip()
    u = s.upper()
    if u.startswith("NEW INTER"):
        return "New Internet"
    if u.startswith("UPGRADE"):
        return "Upgrade"
    if u == "VIDEO":
        return "Video"
    return s.title() if s.isupper() else s


def build(rows: List[Dict[str, str]], owner: str, day: dt.date) -> Dict:
    from automations.box_order_log import pending as bp
    items = []
    for r in rows:
        sale = pull.parse_date(r.get(pull.SALE_DATE))
        cust = r.get(pull.CUSTOMER, "")
        status = r.get(pull.INSTALL_STATUS, "")
        cells = (cust,
                 sale.strftime("%m/%d/%Y") if sale else "",
                 status or "—",
                 _short_product(r.get(pull.PRODUCT, "")),
                 r.get(pull.PACKAGE, ""))
        items.append(_Row(cells, status, r.get(pull.REP, "") or "(no rep)",
                          sale, cust))
    n = len(items)
    reps = bp.by_rep(items)
    day_txt = day.strftime("%A, %B %d, %Y").replace(" 0", " ")
    subtitle = ("{} — {} install{} scheduled today across {} rep{}. "
                "Reach out to your customers today."
                .format(owner, n, bp.plural(n), len(reps), bp.plural(len(reps))))
    return {"today": day, "count": n, "subtitle": subtitle,
            "title": "Activations Scheduled Today — {}".format(day_txt),
            "columns": COLUMNS, "color_fn": status_color,
            "sections": [{"key": "today", "title": None, "rows": items,
                          "reps": reps,
                          "empty_note": "No installs scheduled today."}]}


def render(work: Dict, out: Path) -> List[Path]:
    """One PNG, or two (split between whole rep bands) past SPLIT_AT rows."""
    from automations.box_order_log import pending_png
    sec = work["sections"][0]
    if work["count"] <= SPLIT_AT or len(sec["reps"]) < 2:
        pending_png.render(work, out)
        return [out]
    reps, total, acc, cut = sec["reps"], work["count"], 0, 1
    for i, (_rep, rrows) in enumerate(reps):
        acc += len(rrows)
        if acc >= total / 2:
            cut = i + 1
            break
    cut = min(cut, len(reps) - 1)
    outs = []
    for i, part in enumerate((reps[:cut], reps[cut:]), 1):
        w = dict(work)
        w["title"] = "{} ({} of 2)".format(work["title"], i)
        w["count"] = sum(len(rs) for _r, rs in part)
        w["sections"] = [dict(sec, rows=[r for _r, rs in part for r in rs],
                              reps=part)]
        p = out.with_name("{}_{}{}".format(out.stem, i, out.suffix))
        pending_png.render(w, p)
        outs.append(p)
    return outs


def probe(csv_path: Optional[Path], owner: str, day: dt.date) -> Path:
    """Describe the view + export so the filters can be confirmed: sheet names,
    header, and whether the default view covers today's installs."""
    if csv_path is None:
        from automations.recruiting_report.opt_phase import list_crosstab_sheets
        from automations.shared.tableau_patchright import tableau_session
        with tableau_session(verbose=True) as page:
            sheets = list_crosstab_sheets(pull.VIEW_URL, page=page, verbose=True)
            print("PROBE sheets: {}".format(sheets))
            wanted = next((s for s in sheets if "install" in s.lower()),
                          pull.WORKSHEET)
            print("PROBE pulling sheet: {!r}".format(wanted))
            csv_path = pull.fetch(owner, day, page=page, worksheet=wanted)
    rows = pull.read_rows(csv_path)
    print("PROBE file: {}".format(csv_path))
    print("PROBE rows: {}".format(len(rows)))
    if rows:
        print("PROBE header: {}".format(list(rows[0].keys())))
        print("PROBE first row: {}".format(rows[0]))
    for col in (pull.OWNER, "Sale Date Week Ending", "Current Install Date Week Ending"):
        vals = Counter(r.get(col, "<missing>") for r in rows)
        print("PROBE {}: {} distinct, top: {}".format(
            col, len(vals), vals.most_common(8)))
    inst = Counter(r.get(pull.INSTALL_DATE, "") for r in rows)
    print("PROBE install dates: {}".format(sorted(inst.items())[:40]))
    mine = pull.owner_rows(rows, owner)
    today = pull.scheduled_on(mine, day)
    print("PROBE {}: {} row(s), {} installing {}".format(
        owner, len(mine), len(today), day))
    for r in today[:10]:
        print("   ", r.get(pull.REP), "|", r.get(pull.CUSTOMER), "|",
              r.get(pull.INSTALL_STATUS))
    return csv_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="activations_today")
    ap.add_argument("--owner", default=DEFAULT_OWNER)
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (default: today CT)")
    ap.add_argument("--csv", default=None, help="Use this crosstab, skip Tableau")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--post-slack", action="store_true")
    ap.add_argument("--post-to", default=None, metavar="CHANNEL")
    ap.add_argument("--dm-user", default=None, metavar="USER_ID",
                    help="Test: Lucy DMs the image to this one person only")
    args = ap.parse_args(argv)

    day = dt.date.fromisoformat(args.day) if args.day else pull.central_today()
    csv_path = Path(args.csv) if args.csv else None
    if args.probe:
        csv_path = probe(csv_path, args.owner, day)
        if not (args.post_slack or args.post_to or args.dm_user):
            return 0

    print("=== {} — {} — {} (Central) ===".format(LABEL, args.owner, day))
    if csv_path is None:
        csv_path = pull.fetch(args.owner, day)
    rows = pull.read_rows(csv_path)
    mine = pull.owner_rows(rows, args.owner)
    today = pull.scheduled_on(mine, day)
    print("  export {} row(s); {} for {}; {} installing today".format(
        len(rows), len(mine), args.owner, len(today)))

    from automations.shared import slack_metrics_post as smp
    do_post = bool(args.post_slack or args.post_to)
    where = (dict(channel_id=args.post_to, top_level=True, mirror=False)
             if args.post_to else {})

    if args.dm_user:
        if not today:
            print("  (none today for {} — nothing to DM)".format(args.owner))
            return 0 if mine else 1
        work = build(today, args.owner, day)
        work["title"] = "[SAMPLE] " + work["title"]
        out = Path(tempfile.gettempdir()) / "activations_today_{}.png".format(day)
        for i, p in enumerate(render(work, out), 1):
            res = smp.dm_user_with_file(
                p, user=args.dm_user,
                comment="SAMPLE (real data, {}) — {} — {} installs{}".format(
                    day, LABEL, len(today), " (part {})".format(i) if i > 1 else ""))
            print("  ✓ DM: {}".format(res))
        return 0

    if not today:
        # Megan's rule: no blank boards, and a "none" only when the export
        # proves it loaded. An owner with pending installs but none today is a
        # real zero; an export with nothing for the owner at all is not.
        if not mine:
            print("✗ export has NO pending installs for {} at all — can't tell "
                  "a real zero from data that didn't load. Posting nothing."
                  .format(args.owner))
            return 1
        if args.post_to:
            print("  (none today — test mode posts nothing)")
            return 0
        res = smp.post_reply_text_only(NONE_TEXT, react_emoji=REACT,
                                       today=day, dry_run=not do_post)
        print("  ✓ Slack ({}): {}".format("LIVE" if do_post else "DRY-RUN", res))
        return 0

    work = build(today, args.owner, day)
    out = Path(tempfile.gettempdir()) / "activations_today_{}.png".format(day)
    pngs = render(work, out)
    print("  ✓ rendered {}".format(", ".join(str(p) for p in pngs)))

    comment = "{} — {} install{}".format(LABEL, len(today),
                                         "" if len(today) == 1 else "s")
    for i, p in enumerate(pngs, 1):
        c = comment if len(pngs) == 1 else "{} ({} of {})".format(comment, i, len(pngs))
        res = smp.post_reply_with_image(
            p, comment=c, react_emoji=None if args.post_to else REACT,
            today=day, dry_run=not do_post, **where)
        print("  ✓ Slack ({}): {}".format("LIVE" if do_post else "DRY-RUN", res))
        if do_post and not res.get("dry_run") and not res.get("ok", True):
            print("✗ Slack post FAILED.")
            return 1
    print("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
