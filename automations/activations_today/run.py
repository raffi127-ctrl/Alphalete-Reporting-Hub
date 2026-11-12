"""📆 Activations Scheduled Today — one image in today's Metrics thread.

Raf 2026-11-09: "on the metrics report can we add to the thread a post called
'Activations scheduled Today' ... similar to the order log ... The goal of this
will be that the reps can see what customers they have scheduled for INSTALL
that day and then the reps can reach out to those customers that day."

Source path: Tableau -> ATT TRACKER 2.1 - D2D -> ORDER LOG -> 'Sales Board
Original' view -> worksheet 'A.Order Log', last 42 days of sales -> Owner Name =
<owner>, spe.Install Date = today (Central), not activated, not canceled. See
pull.py for why it is not the PENDING INSTALLS view from Dylan's Loom.

The board is grouped by rep, like the Order Log: a gray band per rep
("Alyssa Moreno • 3 orders") with that rep's customers + phone under it.
Problem statuses (past due / jeopardy / hold / issue) are tinted red. Over 20
rows it splits into two images on one message.

Outward actions are OFF by default:
  (no flag)            pull + render, print what it WOULD post
  --post-slack         post into today's Metrics thread (#alphalete-sales)
  --post-to CHANNEL    post as a plain message to CHANNEL instead (tests: Eve's
                       self-DM D087ZGE2B0F only)
  --probe              describe the export (header, statuses, this week's
                       installs) — no image, no post
  --dm-user USER_ID    test: Lucy DMs the image to that one person
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
# Eve 11/10: always ONE image, even past 20 rows.
SPLIT_AT = 10_000

COLUMNS = ("Customer", "Phone", "Sale Date", "Status", "Install", "Package")

# Eve 11/10: row color = install type. Tech Install yellow, Self Install blue.
# Wireless (Raf 11/12, pending lines under the same rep) green.
_YELLOW, _BLUE, _GREEN = "FFF2CC", "DDEBF7", "E2EFDA"
WIRELESS_TAG = "Wireless"


def status_color(install_type: str, _history=()) -> str:
    t = (install_type or "").strip().lower()
    if t.startswith("tech"):
        return _YELLOW
    if t.startswith("self"):
        return _BLUE
    if t == WIRELESS_TAG.lower():
        return _GREEN
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


def count_text(rows) -> str:
    """'18 installs' or '18 installs + 40 wireless pending' (Eve 11/12: the
    first sample said '391 installs' when most were wireless orders)."""
    wl = sum(1 for r in rows if pull.is_wireless(r))
    n = len(rows) - wl
    txt = "{} install{}".format(n, "" if n == 1 else "s")
    return txt + (" + {} wireless pending".format(wl) if wl else "")


def build(rows: List[Dict[str, str]], owner: str, day: dt.date) -> Dict:
    from automations.box_order_log import pending as bp
    items = []
    for r in rows:
        sale = pull.parse_date(r.get(pull.SALE_DATE))
        cust = r.get(pull.CUSTOMER, "")
        status = r.get(pull.STATUS, "")
        wl = pull.is_wireless(r)
        install = WIRELESS_TAG if wl else r.get(pull.TECH, "")
        package = r.get(pull.PACKAGE, "") or _short_product(r.get(pull.PRODUCT, ""))
        if wl and r.get(pull.LINES):
            k = int(r[pull.LINES])
            package = "{} line{}".format(k, "" if k == 1 else "s")
        cells = (cust,
                 r.get(pull.PHONE, ""),
                 sale.strftime("%m/%d/%Y") if sale else "",
                 status or "—",
                 install,
                 package)
        items.append(_Row(cells, install, r.get(pull.REP, "") or "(no rep)",
                          sale, cust))
    n = len(items)
    n_wl = sum(1 for r in rows if pull.is_wireless(r))
    n_in = n - n_wl
    reps = bp.by_rep(items)
    day_txt = day.strftime("%A, %B %d, %Y").replace(" 0", " ")
    if not n:
        subtitle = "{} — no installs scheduled today.".format(owner)
    elif n_wl:
        subtitle = ("{} — {} install{} scheduled today + {} wireless order{} "
                    "still pending, across {} rep{}. Reach out to your "
                    "customers today.".format(
                        owner, n_in, bp.plural(n_in), n_wl, bp.plural(n_wl),
                        len(reps), bp.plural(len(reps))))
    else:
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
    """Describe the export so the source can be checked: header, statuses,
    and the owner's open installs this week (compare with Pending Installs)."""
    if csv_path is None:
        csv_path = pull.fetch(day)
    rows = pull.read_rows(csv_path)
    print("PROBE file: {}".format(csv_path))
    print("PROBE rows: {}".format(len(rows)))
    if rows:
        print("PROBE header: {}".format(list(rows[0].keys())))
    for col in (pull.STATUS, pull.TECH):
        vals = Counter(r.get(col, "<missing>") for r in rows)
        print("PROBE {}: {}".format(col, vals.most_common(15)))
    mine = pull.owner_rows(rows, owner)
    week = [r for r in mine if pull.is_open(r)
            and (pull.parse_date(r.get(pull.INSTALL_DATE)) or dt.date.min)
            >= day - dt.timedelta(days=3)
            and (pull.parse_date(r.get(pull.INSTALL_DATE)) or dt.date.max)
            <= day + dt.timedelta(days=4)]
    print("PROBE {}: {} row(s), {} open installing {}..{}, {} today".format(
        owner, len(mine), len(week), day - dt.timedelta(days=3),
        day + dt.timedelta(days=4), len(pull.scheduled_on(mine, day))))
    for r in sorted(week, key=lambda r: (r.get(pull.REP, ""), r.get(pull.INSTALL_DATE, ""))):
        print("PROBE row:", r.get(pull.REP), "|", r.get(pull.CUSTOMER), "|",
              r.get(pull.SPM), "| sold", r.get(pull.SALE_DATE), "| install",
              r.get(pull.INSTALL_DATE), "|", r.get(pull.STATUS), "|", r.get(pull.TECH))
    return csv_path


def coverage(csv_path: Optional[Path], day: dt.date) -> int:
    """Read-only (Eve 11/10, "fiber teams"): every owner with open installs in
    the next 7 days, and whether a Metrics thread already carries the board.
    Owners marked NO THREAD are the ones nobody sees today."""
    from automations.office_metrics import offices as om
    if csv_path is None:
        csv_path = pull.fetch(day)
    rows = pull.read_rows(csv_path)
    has = {o.owner.strip().casefold() for k, o in om.OFFICES.items()
           if not o.nds and k not in om.SECTION_OVERRIDES}
    has.add(DEFAULT_OWNER.casefold())                # Raf: daily_metrics
    extra = [c for c in (rows[0].keys() if rows else [])
             if "captain" in c.lower() or c.lower() in ("office", "icd")]
    per = {}
    for r in rows:
        d = pull.parse_date(r.get(pull.INSTALL_DATE))
        if d and day <= d <= day + dt.timedelta(days=6) and pull.is_open(r):
            k = r.get(pull.OWNER, "").strip()
            e = per.setdefault(k, {"n": 0, "today": 0,
                                   "x": " | ".join(r.get(c, "") for c in extra)})
            e["n"] += 1
            e["today"] += d == day
    print("COVERAGE {} rows; extra cols {}".format(len(rows), extra))
    for k, e in sorted(per.items(), key=lambda kv: (kv[0].casefold() in has, -kv[1]["n"])):
        print("COVERAGE {:<10} {:<28} week={:>3} today={:>3}  {}".format(
            "thread" if k.casefold() in has else "NO THREAD", k, e["n"], e["today"], e["x"]))
    return 0


# --------------------------------------------------- Pending Orders thread ---
# Raf 2026-11-12, after the 391-row sample: "one that shows fiber installs only
# and then a separate one that is both but when it gets long, we separate it".
# Dylan: "break it up into separate screenshots ... alphabetically". Eve: in its
# OWN thread next to Metrics (like the Order Log), so Metrics doesn't flood; the
# Metrics thread gets one pointer line.
PENDING_TITLE = "⏳ Pending Orders"
PENDING_MAX_NAMES = 20   # same cap as the Order Log index (MAX_INDEX_NAMES)


def name_groups(reps, max_names: int = PENDING_MAX_NAMES):
    """[(label, [(rep, rows)])] — reps A-Z cut into posts of <= max_names
    reps (Order Log rule). Label = 'A–F' by first letters; '' if one post."""
    groups = [reps[i:i + max_names] for i in range(0, len(reps), max_names)] or [[]]
    if len(groups) == 1:
        return [("", groups[0])]

    def first(rep):
        return (rep.strip()[:1] or "?").upper()

    def label(g):
        a, b = first(g[0][0]), first(g[-1][0])
        return a if a == b else "{}–{}".format(a, b)
    return [(label(g), g) for g in groups]


def post_pending_thread(mine, owner: str, day: dt.date, *, dry_run: bool,
                        channel_id: Optional[str] = None,
                        sample_reps: int = 0,
                        max_names: int = PENDING_MAX_NAMES,
                        sample: bool = False) -> int:
    """Eve 11/12 "como el order log": one channel post per group of <= 20
    reps; in its thread the FIRST reply is a 'Tap your name' index, then one
    small image per rep (name + its image in ONE reply), so nobody scrolls a
    giant picture. Fiber = installs today; Wireless = every open order."""
    import time
    from automations.box_order_log import pending as bp
    from automations.box_order_log import pending_png
    from automations.shared import slack_metrics_post as smp
    rows = pull.board_rows(mine, day)
    work = build(rows, owner, day)
    reps = work["sections"][0]["reps"]
    if sample_reps:
        reps = reps[:sample_reps]
    groups = name_groups(reps, max_names)
    day_txt = day.strftime("%A, %B %d, %Y").replace(" 0", " ")
    md = "{}/{}".format(day.month, day.day)
    tmp = Path(tempfile.gettempdir()) / "pending_orders_{}".format(day)
    tmp.mkdir(parents=True, exist_ok=True)
    print("  pending: {} — {} post(s): {}".format(
        count_text(rows), len(groups),
        ", ".join("{} {} reps".format(l or "all", len(g)) for l, g in groups)))
    if not rows or dry_run:
        return 0

    client = smp._client()
    tag = "[SAMPLE] " if sample else ""

    def _text(thread_ts, text):
        r = client.chat_postMessage(channel=channel_id, thread_ts=thread_ts,
                                    text=text, unfurl_links=False,
                                    unfurl_media=False)
        return r["ts"]

    def _upload(path, name) -> str:
        for _ in range(3):
            try:
                r = client.files_upload_v2(file=str(path), filename=name)
                f = r.get("file") or (r.get("files") or [{}])[0]
                return f.get("permalink", "")
            except Exception as e:  # noqa: BLE001  (rate limit -> wait)
                print("  retry {}: {}".format(name, e))
                time.sleep(20)
        return ""

    def _link(ts) -> str:
        return client.chat_getPermalink(channel=channel_id,
                                        message_ts=ts)["permalink"]

    for label, part in groups:
        span = " — reps {}".format(label) if label else ""
        title = "{}{} *Pending Orders {}{}*".format(tag, PENDING_TITLE[:1], md, span)
        ts = _text(None, "{}\nOpen the thread 👇 and tap your name".format(title))
        index_ts = _text(ts, "👉 *Tap your name:* (names loading...)")
        links = []
        for rep, rr in part:
            k_wl = sum(1 for x in rr if x.cells[4] == WIRELESS_TAG)
            k_in = len(rr) - k_wl
            w = dict(work, count=len(rr),
                     title="Pending Orders — {} — {}".format(rep, day_txt),
                     subtitle="{} — {} install{} today + {} wireless order{} "
                              "not activated yet.".format(
                                  rep, k_in, bp.plural(k_in), k_wl, bp.plural(k_wl)),
                     sections=[dict(work["sections"][0], rows=rr,
                                    reps=[(rep, rr)])])
            png = tmp / "{}.png".format("".join(c for c in rep if c.isalnum()) or "rep")
            pending_png.render(w, png)
            url = _upload(png, "{} - Pending Orders {}.png".format(rep, md))
            r_ts = _text(ts, "*{}* — {} order{}{}".format(
                rep, len(rr), bp.plural(len(rr)),
                "\n<{}|{} - Pending Orders>".format(url, rep) if url else ""))
            links.append((rep, _link(r_ts)))
            time.sleep(1)
        index = "\n".join("• <{}|{}>".format(u, rep) for rep, u in links)
        try:
            client.chat_update(channel=channel_id, ts=index_ts,
                               text="👉 *Tap your name:*\n" + index)
        except Exception as e:  # noqa: BLE001
            print("  ⚠ index update failed, posting new: {}".format(e))
            index_ts = _text(ts, "👉 *Tap your name:*\n" + index)
        try:
            client.chat_update(channel=channel_id, ts=ts,
                               text="{}\n👉 <{}|Find your name here>".format(
                                   title, _link(index_ts)))
        except Exception as e:  # noqa: BLE001
            print("  ⚠ could not link the post to its index: {}".format(e))
        print("  ✓ posted {} ({} reps)".format(label or "all", len(links)))
    return 0


def pending_pointer_text(rows) -> str:
    """The one line the Metrics thread gets instead of the long images."""
    return ("{} — {} → see today's *Pending Orders* thread in this channel "
            "(by rep, A–Z).".format(PENDING_TITLE, count_text(rows)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="activations_today")
    ap.add_argument("--coverage", action="store_true",
                    help="read-only: owners with installs this week, with/without a thread")
    ap.add_argument("--owner", default=DEFAULT_OWNER)
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (default: today CT)")
    ap.add_argument("--csv", default=None, help="Use this crosstab, skip Tableau")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--post-slack", action="store_true")
    ap.add_argument("--post-to", default=None, metavar="CHANNEL")
    ap.add_argument("--dm-user", default=None, metavar="USER_ID",
                    help="Test: Lucy DMs the image to this one person only")
    ap.add_argument("--with-wireless", action="store_true",
                    help="Raf 11/12: add every pending wireless line under its "
                         "rep (OFF until Eve OKs the sample)")
    ap.add_argument("--pending-sample", type=int, default=0, metavar="N",
                    help="Test (Eve 11/12): only the Pending Orders thread, first "
                         "N reps, to --post-to (Eve's self-DM); nothing else")
    ap.add_argument("--max-names", type=int, default=PENDING_MAX_NAMES)
    args = ap.parse_args(argv)

    day = dt.date.fromisoformat(args.day) if args.day else pull.central_today()
    csv_path = Path(args.csv) if args.csv else None
    if args.coverage:
        return coverage(csv_path, day)
    if args.probe:
        csv_path = probe(csv_path, args.owner, day)
        if not (args.post_slack or args.post_to or args.dm_user):
            return 0

    print("=== {} — {} — {} (Central) ===".format(LABEL, args.owner, day))
    if csv_path is None:
        csv_path = pull.fetch(day)
    rows = pull.read_rows(csv_path)
    mine = pull.owner_rows(rows, args.owner)
    if args.pending_sample:
        if not args.post_to:
            print("✗ --pending-sample needs --post-to (Eve: U088E2KJEV8)")
            return 2
        from automations.shared import slack_metrics_post as smp
        ch = smp._postable_channel(smp._client(), args.post_to)  # U… -> DM id
        fiber = pull.scheduled_on(mine, day)
        if fiber:   # 1) what the Metrics thread keeps showing (unchanged)
            fw = build(fiber, args.owner, day)
            fw["title"] = "[SAMPLE — Metrics thread, as today] " + fw["title"]
            fp = Path(tempfile.gettempdir()) / "activations_today_fiber_{}.png".format(day)
            render(fw, fp)
            smp.post_reply_with_image(
                fp, comment="[SAMPLE — Metrics thread, unchanged] {} — {}".format(
                    LABEL, count_text(fiber)),
                today=day, channel_id=ch, top_level=True, mirror=False)
        smp._client().chat_postMessage(
            channel=ch,
            text="[SAMPLE — this line would go in the Metrics thread, under "
                 "the fiber-only image]\n"
                 + pending_pointer_text(pull.board_rows(mine, day)))
        rc = post_pending_thread(mine, args.owner, day, dry_run=False,
                                 channel_id=ch, sample=True,
                                 sample_reps=args.pending_sample,
                                 max_names=args.max_names)
        print("  fiber-only Metrics image unchanged: {} install(s) today".format(len(fiber)))
        return rc
    today = (pull.board_rows(mine, day) if args.with_wireless
             else pull.scheduled_on(mine, day))
    print("  export {} row(s); {} for {}; {} on the board{}".format(
        len(rows), len(mine), args.owner, len(today),
        " (incl. {} pending wireless)".format(
            sum(1 for r in today if pull.is_wireless(r)))
        if args.with_wireless else ""))

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
            res = smp.dm_user_with_file(  # Lucy 4 has no bot token: metrics token
                p, user=args.dm_user, as_bot=False,
                comment="SAMPLE (real data, {}) — {} — {}{}".format(
                    day, LABEL, count_text(today), " (part {})".format(i) if i > 1 else ""))
            print("  ✓ DM: {}".format(res))
        return 0

    if not today:
        # Megan's rule: no blank boards, and a "none" only when the export
        # proves it loaded. The view is org-wide, so an export holding orders
        # for ANY office proves it loaded — a small office with no open orders
        # is a real zero (same rule as 6+ Days Out). An empty export is not.
        if not rows:
            print("✗ export is EMPTY — can't tell a real zero from data that "
                  "didn't load. Posting nothing.")
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

    comment = "{} — {}".format(LABEL, count_text(today))
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
