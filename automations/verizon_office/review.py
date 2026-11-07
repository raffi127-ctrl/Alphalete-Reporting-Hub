"""Nico's Verizon reports -> the review group DM, one post per report.

    python -m automations.verizon_office.review --build          # laptop: render the examples
    python -m automations.verizon_office.review                  # print what would post
    python -m automations.verizon_office.review --send           # post (as Lucy, from Lucy 4)

Megan 2026-11-07: "send the examples to this group so they can review and
approve them - make it one post per report and if carlos or nico ✅ react to
them that means that they approve them - if they ❌ then you need to respond
with what needs changed - explain the reactions to them as well".

--build runs where the source files are (Megan's laptop: Nico's Credico files
and the Optix read live there) and writes resources/verizon_review/: the
images, the order log, and manifest.json. Those are COMMITTED, so --send can
run on a Lucy, because the group DM has to hear it from Lucy, not Megan.

--send posts the intro, then one post per report, and records each ts in
output/verizon_review_posted.json. A second --send posts only what is missing,
so a retry never doubles a report.

Nothing here is live reporting: these are examples of reports that stay off
until Nico is on Lucy ECO (Megan 2026-11-06).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]
REVIEW_DIR = ROOT / "resources" / "verizon_review"
MANIFEST = REVIEW_DIR / "manifest.json"
POSTED = ROOT / "output" / "verizon_review_posted.json"

# The group: Alphalete GP, Carlos, Evelyn, Lucy, Megan, Nico.
GROUP_DM = "C0CF6B3TUEB"

DAY = dt.date(2026, 11, 6)               # the example day: Friday 11/6
INV = ROOT / "output" / "_verizon_inventory" / "outlook"
SV = INV / "Sales Verification - Verizon Wireless - High Value Acquisitions, Inc. - 20261106.xlsx"
CF = INV / "Compliance Flags - Verizon Wireless - High Value Acquisitions, Inc. - 20261104.xlsx"
QUALITY = ROOT / "output" / "_verizon_inventory" / "raw" / "Quality Scorecard - Verizon Wireless - SCI-WO - 20261103.pdf"
OPTIX_AGG = ROOT / "output" / "verizon_optix_2026-11-06_agg.txt"

INTRO = (
    ":wave: *Nico, Carlos: here are the Verizon reports Lucy has built for Nico's office.*\n"
    "Each post below is ONE report, made from Nico's real numbers for Friday 11/6.\n\n"
    "*How to review (one reaction per post):*\n"
    "• :white_check_mark: = approved, keep it exactly like this\n"
    "• :x: = needs a change. Reply in that post's thread with what to change, "
    "and we'll fix it and re-post it\n\n"
    "Nothing here is live yet. These start the day Nico is set up on Lucy ECO."
)


def _knock_board(out: Path) -> Path:
    from automations.icd_alerts import knocks_map, knocks_post as KP, offices as OF, optix_read as O
    rows = []
    for ln in OPTIX_AGG.read_text().splitlines():
        agent, disp, leads, knocks = ln.split("|")
        leads, knocks = int(leads), int(knocks)
        rows += [{"agent": agent, "latestDisposition": disp, "totalDisposition": "1"}] * (leads - 1)
        rows.append({"agent": agent, "latestDisposition": disp, "totalDisposition": str(knocks - leads + 1)})
    t = O.tally(rows)
    board = knocks_map.to_rows([O.board_row(r, c) for r, c in t["reps"].items()])
    paths, _shape = KP._render(OF.OFFICES["nicolas"], board, DAY, dt.datetime(2026, 11, 6, 21, 30))
    dst = out / "knocks_board.png"
    shutil.copy(paths[0], dst)
    return dst


def _day_lines(day: dt.date) -> Dict[str, int]:
    from automations.verizon_office import parse
    sv = parse.read_sales_verification(SV)
    d = parse.DAYS[(day.weekday() + 1) % 7]
    for w in sv.weeks:
        if w.end - dt.timedelta(days=6) <= day <= w.end:
            return {r.name: r.days.get(d, 0) for r in w.reps if r.days.get(d, 0)}
    return {}


def build() -> List[Dict]:
    from automations.alphalete_org_report import opt_verizon as V
    from automations.icd_alerts import post as P
    from automations.shared import sale_hype as H
    from automations.verizon_office import board, board_image, parse, thread_boards as TB

    if REVIEW_DIR.exists():
        shutil.rmtree(REVIEW_DIR)
    REVIEW_DIR.mkdir(parents=True)
    work = ROOT / "output" / "verizon_office" / "review_build"
    work.mkdir(parents=True, exist_ok=True)
    items: List[Dict] = []

    def add(key, title, what, when, files=(), text=""):
        items.append({"key": key, "title": title, "what": what, "when": when,
                      "files": [Path(f).name for f in files], "text": text})

    # 1. knocks
    add("knocks", ":door: Knocks Board",
        "Every rep's doors, knocks, talk-tos and each Optix disposition, read off "
        "Optix Lead Details on Nico's ECO computer. Time columns are blank on purpose: "
        "Optix doesn't record what time a door was knocked.",
        "All day, on the schedule Nico picks on the Lucy ECO sign-up, plus a final board at night.",
        [_knock_board(REVIEW_DIR)])

    # 2. countdown text
    thu = _day_lines(dt.date(2026, 11, 5))
    top = max(thu, key=thu.get) if thu else ""
    sb = P.scoreboard_text({r: {"Lines": n} for r, n in thu.items()}, [top], campaign="verizon")
    add("countdown", ":iphone: Sales Countdown Text (iMessage)",
        "The day's apps per rep, highest first, with a :fire: on whoever just sold, and the office total. "
        "Example uses Thursday 11/5's real numbers.",
        "Texted to the \"Verizon\" iMessage group (Nico + Carlos) every time the count goes up.",
        text="```" + sb + "```")

    # 3. live app alert
    line = H.hype(top or "Diego Chacon", {"Lines": 2}, DAY, campaign="verizon")
    add("live_apps", ":drop_of_blood: Live App Alerts",
        "When a rep's :drop_of_blood: count goes up in #alphalete-gp-sales, Lucy cheers it in the channel "
        "(each :drop_of_blood: = 1 app, the same count the reps already post).",
        "Live, as the tally moves (afternoon to midnight).",
        text=line)

    # 4. sales board image
    png = board_image.render(SV, REVIEW_DIR / "sales_board.png")
    add("sales_board", ":satellite_antenna: Verizon Sales Board",
        "Apps by rep by day for the week, with this week vs last week on the same days. "
        "From Credico's Sales Verification email.",
        "Daily, about 11:15am, in the day's *Verizon Metrics* thread in #alphalete-gp-sales "
        "(previous-day numbers, like every program).", [png])

    # 5-10. the NDS wireless thread
    whats = {
        "rep_activations": "Last week and this week per rep: activated, pending, total, canceled/disconnected.",
        "pending_orders": "Every line that's submitted but not activated yet, grouped by rep, with how many days it's been waiting.",
        "activation_rate": "Per rep: % of lines activated, sold 0-30 days ago and 31-60 days ago. Green / yellow / red by the same bars as Carlos's board.",
        "order_log": "Excel file: every line (rep, dates, order #, plan, device, ported from, status), plus a tab per rep.",
        "cancels": "Lines Credico canceled in the last 3 days.",
        "disconnects": "Lines that disconnected in the last 3 days.",
    }
    for it in TB.build("Nicolas Murrugarra", SV, DAY, work):
        files = []
        for k, p in enumerate(it["paths"], 1):
            dst = REVIEW_DIR / (f"{it['slug']}_{k}{Path(p).suffix}" if len(it["paths"]) > 1
                                else f"{it['slug']}{Path(p).suffix}")
            shutil.copy(p, dst)
            files.append(dst)
        add(it["slug"], it["label"], whats[it["slug"]],
            "Daily, same *Verizon Metrics* thread, right after the sales board.",
            files, text="" if files else it["comment"])

    # 11. compliance
    head, th = board.compliance_board(parse.read_compliance(CF))
    add("compliance", ":shield: Compliance Board",
        "Credico's weekly compliance flags per rep.",
        "Wednesdays, same *Verizon Metrics* thread.",
        text=head + "\n" + "\n".join(th))

    # 12. OPT
    rows = V.weeks(SV, 4, None, quality=QUALITY if QUALITY.exists() else None, compliance=CF)
    lines = ["%-28s" % "Row" + "".join("%10s" % ("WE " + w.strftime("%m/%d").lstrip("0")) for w, _ in rows)]
    for label, _src, _k in V.ROWS:
        lines.append("%-28s" % label[:28] + "".join("%10s" % V.fmt(label, vals[label]) for _w, vals in rows))
    add("opt", ":bar_chart: OPT Report Tab (\"Nicolas Murrugarra – Verizon\")",
        "Nico's weekly rows on the OPT report, with the SAME row names as the NDS tabs so DD reads them the same way. "
        "Blank = Credico doesn't send that number yet.",
        "Weekly, with the OPT fill.", text="```" + "\n".join(lines) + "```")

    # 13. signed-out DM
    spec = P.SYSTEMS["optix"]
    dm = P.SIGNIN_ASK % ("Nicolas's Local Office", spec["name"], spec["what"], "4:10 PM",
                         spec["why"], spec["how"])
    add("signin_dm", ":lock: Optix Signed-Out DM",
        "If Optix signs out on Nico's ECO computer (Verizon does this about once a day), Lucy sends this "
        "so the knocks board doesn't just go quiet.",
        "A DM to Nico, Megan and Eve, once a day at most, only when it happens.",
        text=dm)

    MANIFEST.write_text(json.dumps({"day": DAY.isoformat(), "items": items}, indent=2, ensure_ascii=False))
    return items


def _post_text(it: Dict) -> str:
    return (f"*{it['title']}*\n{it['what']}\n_When:_ {it['when']}\n"
            ":white_check_mark: approve · :x: change it (reply in this thread)")


def _load_posted() -> Dict:
    try:
        return json.loads(POSTED.read_text())
    except (OSError, ValueError):
        return {}


def send(items: List[Dict], log=print) -> int:
    from automations.shared import slack_metrics_post as S
    client = S._client()
    posted = _load_posted()
    if "intro" not in posted:
        posted["intro"] = client.chat_postMessage(channel=GROUP_DM, text=INTRO)["ts"]
        POSTED.write_text(json.dumps(posted, indent=2))
    for it in items:
        if it["key"] in posted:
            log(f"  already posted: {it['title']}")
            continue
        head = _post_text(it)
        files = [REVIEW_DIR / f for f in it["files"]]
        if files:
            r = client.files_upload_v2(channel=GROUP_DM, initial_comment=head,
                                       file_uploads=[{"file": str(f), "filename": f.name} for f in files])
            ts = _file_ts(client, r)
        else:
            ts = client.chat_postMessage(channel=GROUP_DM, text=head)["ts"]
            client.chat_postMessage(channel=GROUP_DM, thread_ts=ts, text=it["text"])
            # the example rides in the thread so the reaction sits on the
            # report's own post, not on a wall of example text
        posted[it["key"]] = ts
        POSTED.write_text(json.dumps(posted, indent=2))
        log(f"  ✓ {it['title']}")
    return 0


def _file_ts(client, resp) -> str:
    """files_upload_v2 returns the file, not the message: find the share ts."""
    import time
    fid = (resp.get("files") or [resp.get("file") or {}])[0].get("id")
    for _ in range(10):
        info = client.files_info(file=fid)["file"]
        shares = info.get("shares", {})
        for kind in ("private", "public"):
            for s in shares.get(kind, {}).get(GROUP_DM, []):
                return s["ts"]
        time.sleep(1.5)
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="render the examples (laptop)")
    ap.add_argument("--send", action="store_true", help="post to the review group DM as Lucy")
    a = ap.parse_args(argv)
    items = build() if a.build else json.loads(MANIFEST.read_text())["items"]
    if a.send:
        return send(items)
    print(INTRO + "\n")
    for it in items:
        print("-" * 60)
        print(_post_text(it))
        for f in it["files"]:
            print(f"  [attached] {f}")
        if it["text"]:
            print("  [in the thread]\n" + it["text"])
    print("-" * 60 + "\npreview only: nothing posted (--send posts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
