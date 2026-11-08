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

# The group: Alphalete GP, Carlos, Evelyn, Lucy, Lucy Reporting, Megan, Nico.
# Opened 2026-11-07 for this: the first group (C0CF6B3TUEB) had only the
# *Lucy* bot account, whose token no Lucy machine holds, and a group DM can't
# take a new member -- so Megan's call was a new group with Lucy Reporting in.
GROUP_DM = "C0CFN3SBFCM"

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
        "rep_activations": "The last 4 weeks per rep (two pictures: this + last week, then the two before): activated, pending, total, canceled/disconnected.",
        "activation_by_week": "The last 4 sales weeks: of the lines sold each week, how many have activated since. Office total + every rep.",
        "churn": "Of the lines that activated 0-30 and 31-60 days ago, how many have disconnected since. Office total (the office churn rate) + every rep. Green 5% or less, yellow up to 10%, red over 10%.",
        "pending_orders": "Every line that's submitted but not activated yet, grouped by rep, with how many days it's been waiting.",
        "activation_rate": "Per rep: % of lines activated, sold 0-30 days ago and 31-60 days ago. Green / yellow / red by the same bars as Carlos's board.",
        "order_log": "Excel file: every line (rep, dates, order #, plan, device, ported from, status), plus a tab per rep. Pay dates are two weeks behind (one week later than the other programs).",
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
    add("compliance", ":shield: Compliance Board",
        "Credico's weekly compliance flags per rep: a ✓ for each thing Credico flagged.",
        "Wednesdays, same *Verizon Metrics* thread.")
    items[-1]["thread_files"] = [board_image.compliance_image(CF, REVIEW_DIR / "compliance.png").name]

    # 12. OPT
    rows = V.weeks(SV, 6, None, quality=QUALITY if QUALITY.exists() else None, compliance=CF)
    add("opt", ":bar_chart: OPT Report Tab (\"Nicolas Murrugarra – Verizon\")",
        "Nico's weekly rows on the OPT report, with the SAME row names as the NDS tabs so DD reads them the same way. "
        "Blank = Credico doesn't send that number yet.",
        "Weekly, with the OPT fill.")
    items[-1]["thread_files"] = [opt_png(rows, REVIEW_DIR / "opt_rows.png").name]

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


def opt_png(rows, out: Path) -> Path:
    """The OPT rows as a picture: a code block wraps on a phone (Megan
    2026-11-07 screenshot). Cells we can't fill yet are BLANK, not our
    internal markers ("(to wire)", "(no file)", "blank@CR")."""
    import html
    from automations.alphalete_org_report import opt_verizon as V
    from automations.tableau_screenshots.email_tracker import _screenshot_html

    def cell(label, v):
        if v in ("later", "blank", "nofile", None):
            return '<td class="nil"></td>'
        return f"<td>{html.escape(V.fmt(label, v))}</td>"

    head = "".join(f"<th>WE {w.month}/{w.day}</th>" for w, _ in rows)
    body = "".join(
        f'<tr><td class="lab">{html.escape(label)}</td>' + "".join(cell(label, vals[label]) for _w, vals in rows) + "</tr>"
        for label, _src, _k in V.ROWS)
    page = f"""<html><head><style>
body{{margin:0;background:#fff;font-family:-apple-system,Helvetica,Arial,sans-serif;color:#222}}
.wrap{{padding:22px;display:inline-block}}
h1{{font:700 20px Georgia;margin:0 0 4px}} .sub{{font-size:12px;color:#666;margin-bottom:12px}}
table{{border-collapse:collapse}} th{{background:#1f2a44;color:#fff;font-size:13px;padding:8px 14px}}
td{{border:1px solid #ddd;padding:7px 14px;text-align:center;font-size:14px;min-width:70px}}
td.lab{{text-align:left;font-weight:600;background:#f6f6f6;min-width:230px}}
td.nil{{background:#fafafa}} .foot{{font-size:11.5px;color:#666;margin-top:10px}}
</style></head><body><div id="card" class="wrap">
<h1>Nicolas Murrugarra – Verizon</h1>
<div class="sub">OPT Report rows, from Credico. Same row names as the NDS tabs.</div>
<table><tr><th></th>{head}</tr>{body}</table>
<div class="foot">Blank = Credico doesn't send that number yet. N/A = not a Verizon product.</div>
</div></body></html>"""
    return _screenshot_html(page, out)


def _post_text(it: Dict) -> str:
    return (f"*{it['title']}*\n{it['what']}\n_When:_ {it['when']}\n"
            ":white_check_mark: approve · :x: change it (reply in this thread)")


def _load_posted() -> Dict:
    try:
        return json.loads(POSTED.read_text())
    except (OSError, ValueError):
        return {}


def _group_client(log=print):
    """The Lucy token that can SEE the group. The group's Lucy is *Lucy*
    (U0BCFGCR5PV, the bot token), not *Lucy Reporting* (U0BCG8F9B5Z, the
    user token every Lucy posts metrics with) -- 11/7 first send died on
    channel_not_found with the user token. Ask each; never guess."""
    from automations.shared import slack_metrics_post as S
    for name, make in (("user", S._client), ("bot", S._bot_client)):
        try:
            c = make()
            try:
                c.conversations_info(channel=GROUP_DM)
            except Exception as e:  # noqa: BLE001
                # A posting token without mpim:read can still post; only a
                # token that CAN look and can't find the group is ruled out.
                if "missing_scope" not in str(e):
                    raise
            log(f"  posting as {c.auth_test().get('user')} ({name} token)")
            return c
        except Exception as e:  # noqa: BLE001 — missing token / can't see it
            log(f"  {name} token can't post there: {str(e)[:120]}")
    raise SystemExit("✗ no Lucy token on this machine can see the review group "
                     f"{GROUP_DM} — invite that Lucy, or run where the bot token is")


# ROUND 2 (2026-11-07): the reports Carlos ❌'d, fixed, plus the first new
# one from his "What's missing" list. Its own posted-file, so round 1's
# record never says these already went out.
ROUND2_KEYS = ("rep_activations", "order_log", "opt", "activation_by_week", "churn")
ROUND2_CHANGED = {
    "rep_activations": "Now shows 4 weeks (pay is two weeks behind).",
    "order_log": "Pay dates moved one week later.",
    "opt": "Now a 6-week view.",
    "activation_by_week": "NEW, from Carlos's \"What's missing\" list.",
    "churn": "NEW, from Carlos's \"What's missing\" list (churn rates + churn by rep in one board).",
}
ROUND2_INTRO = (
    ":repeat: *Round 2: the fixes you asked for.* Same as before: "
    ":white_check_mark: = approved, :x: = reply in that post's thread with what to change.\n\n"
    "• *Verizon Sales Board*: Carlos's own build now fills the Vantura 'Verizon Sales Board' tab "
    "from Credico and posts the day + week pictures into the Verizon Metrics thread, so ours is gone.\n"
    "• Still waiting on a ✅ from *both* of you (from round 1, above): Live App Alerts, Pending Orders "
    "(Carlos), Canceled Orders, Disconnected Orders, Compliance Board (both).\n"
    "• Coming next from \"What's missing\": churn, revenue and the tier ranking. We're getting the "
    "Verizon pay + tier numbers first."
)


def send(items: List[Dict], log=print, rnd: int = 1) -> int:
    global POSTED
    client = _group_client(log)
    if rnd == 2:
        POSTED = ROOT / "output" / "verizon_review_posted_round2.json"
        items = [dict(it, what=ROUND2_CHANGED.get(it["key"], "") + " " + it["what"])
                 for it in items if it["key"] in ROUND2_KEYS]
    posted = _load_posted()
    if "intro" not in posted:
        posted["intro"] = client.chat_postMessage(
            channel=GROUP_DM, text=ROUND2_INTRO if rnd == 2 else INTRO)["ts"]
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
            if (it.get("text") or "").strip():     # a picture-only example has none (OPT, round 2)
                client.chat_postMessage(channel=GROUP_DM, thread_ts=ts, text=it["text"])
            # the example rides in the thread so the reaction sits on the
            # report's own post, not on a wall of example text
        _thread_files(client, it, ts)
        posted[it["key"]] = ts
        POSTED.write_text(json.dumps(posted, indent=2))
        log(f"  ✓ {it['title']}")
    return 0


def _thread_files(client, it: Dict, parent_ts: str) -> None:
    files = [REVIEW_DIR / f for f in it.get("thread_files") or []]
    if files:
        client.files_upload_v2(channel=GROUP_DM, thread_ts=parent_ts,
                               file_uploads=[{"file": str(f), "filename": f.name} for f in files])


def replace(key: str, parent_ts: str, old_reply: str, log=print) -> int:
    """Swap a report's example in its EXISTING thread: delete Lucy's old reply,
    post the new one. Same post, so any reaction already on it stays."""
    items = {it["key"]: it for it in json.loads(MANIFEST.read_text())["items"]}
    it = items[key]
    client = _group_client(log)
    if old_reply:
        client.chat_delete(channel=GROUP_DM, ts=old_reply)
    if it.get("text"):
        client.chat_postMessage(channel=GROUP_DM, thread_ts=parent_ts, text=it["text"])
    _thread_files(client, it, parent_ts)
    log(f"  ✓ replaced the example under {it['title']}")
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
    ap.add_argument("--round", type=int, default=1, help="2 = post only the round-2 fixes")
    ap.add_argument("--replace", metavar="KEY", help="re-post one report's example in its thread")
    ap.add_argument("--parent", help="--replace: the report post's ts")
    ap.add_argument("--old-reply", default="", help="--replace: Lucy's old reply to delete")
    a = ap.parse_args(argv)
    if a.replace:
        return replace(a.replace, a.parent, a.old_reply)
    items = build() if a.build else json.loads(MANIFEST.read_text())["items"]
    if a.send:
        return send(items, rnd=a.round)
    print(INTRO + "\n")
    for it in items:
        print("-" * 60)
        print(_post_text(it))
        for f in it["files"]:
            print(f"  [attached] {f}")
        for f in it.get("thread_files") or []:
            print(f"  [in the thread] {f}")
        if it["text"]:
            print("  [in the thread]\n" + it["text"])
    print("-" * 60 + "\npreview only: nothing posted (--send posts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
