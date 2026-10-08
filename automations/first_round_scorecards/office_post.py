"""1st Round Scorecards -- one scorecard per office, in that office's recruiting channel.

Rafael via Camila, 2026-10-07: "post a scorecard of each office in the slack
of that office with the score and the feedback of the day". Eve: the office's
recruiting channel; the sample goes first to a group DM with Rafael, Camila
and Eve.

One post per office per day, after the day's audits are done: the office's
average, then each interviewer's average with that day's red flags, most
missed must-dos, 2 coaching tips (her latest interview) and a link to every
full audit. #ars-recruiting-numbers keeps the per-interview detail.

Read from the audit docs (board.scores), so the post shows exactly what the
board and the docs say, names already merged ('Same person?' tab).

    python -m automations.first_round_scorecards.office_post --date 2026-10-06            # print only
    python -m automations.first_round_scorecards.office_post --date 2026-10-06 --sample   # group DM Raf+Camila+Eve
    python -m automations.first_round_scorecards.office_post --date 2026-10-06 --post     # the office channels

run.py posts the day by itself once LIVE is on (after Eve's OK to the sample).
An office with no channel here is left out (printed), it still has
#ars-recruiting-numbers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Dict, List

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.first_round_scorecards import board, fathom

# run.py posts to the office channels after the day's post only while this is
# on. Off until Rafael / Camila / Eve OK the sample (Eve, 2026-10-07).
LIVE = False
SAMPLE_TO = ("U045Z8N0ZQC",       # Rafael Hidalgo
             "U07FWSYP3NV",       # Camila Hornos Kraschinsky
             "U088E2KJEV8")       # Eve (Evelyn)
# Office (the owner in Camila's ZOOMS INFO tab, as the audit doc's "Office:"
# says it) -> that office's recruiting channel. lucy_reporting (U0BCG8F9B5Z)
# must be IN the channel: they're private, a post without her = channel_not_found.
# A new office = one line here + invite Lucy.
CHANNELS: Dict[str, str] = {
    "Aya Al-Khafaji": "C0AU7GN2TJ7",          # #aya-al-khafaji-office-recruiting-22992
    "Carlos Hidalgo": "C09L1S3MQ1E",          # #carlos-hidalgo-office-recruiting-11580
    "Colten Wright": "C0AUAPMEF37",           # #colten-wrights-office-recruiting-14733
    "Cyrus Wade": "C0AUC4PAF2A",              # #cyrus-wade-office-recruiting-22815
    "Drew Tepper": "C0C532LA6JY",             # #drew-tepper-recruiting-22583
    "Eveliz Wright": "C0C5TPWLR2R",           # #eveliz-wright-office-recruiting-18404
    "Geoge Delgado": "C0C81LUN0KS",           # #george-delgado-recruiting (ZOOMS INFO spells it Geoge)
    "George Delgado": "C0C81LUN0KS",
    "Haytham Nagi": "C0AUUSCSEV7",            # #haytham-nagi-office-recruiting-22524
    "Isaiah Revelle": "C0AU0G0K2DD",          # #isaiah-revelle-office-recruiting-19717
    "Jacob Dover": "C0B9N1WDBB8",             # #jacob-dover-office-recruiting-23607
    "Jairo Ruiz": "C0C69Q2QWF4",              # #jairo-ruiz-recruiting-21270
    "Jamis Garay": "C0AJNRR4ZC7",             # #jamis-office
    "Max Amed": "C0AH5G7SY66",                # #maxamad-adens-office-recruiting-23066
    "Rafael Hidalgo": "C0AUAS88FGW",          # #rafs-office-recruiting-11280 (all 3 funnels)
    "Raf Hidalgo 2nd funnel": "C0AUAS88FGW",
    "Raf Hidalgo 3rd funnel": "C0AUAS88FGW",
    "Rashad Reed": "C0APEHLHDD2",             # #rashad-reed-office-recruiting-23411
    "Roshan Ahmad": "C0AUUT7JH33",            # #roshan-amin-ahmads-office-recruiting-19833
    "Ryan McSpadden": "C0794R5TLG5",          # #ryan-mcspaddens-office-recruiting-22820
    "Salik Mallick": "C05BPNNJGE7",           # #salik-hammad-recruiting-office-21328
    "Samuel Acay": "C0C6YEBS550",             # #samuel-acay-recruiting
    # Eve, 2026-10-07 (the channels where Camila filed each script)
    "Blue Mendoza": "C0BF3GWFJ73",
    "Christopher Williams": "C0AUE5NCE90",
    "Cody Cannon": "C0ATYN2L73R",
    "David Robinson": "C0C4WPPHD99",          # Dana Iverson's office
    "Ellen Dent": "C0BFQSP25T7",
    "JC Pascual": "C0AUG01KCN6",
    "Joe Logan": "C0AT40DEA3G",
    "Juan Botero": "C0BEULL42LA",
    "Steve McElwee": "C0AUCJ65UFP",
    "Tre Mitchell": "C0AUG0B5SKC",            # Lamar (Tre) Mitchell
}
# Several ZOOMS INFO owners, one office: one post, under this name
SAME_OFFICE = {"Raf Hidalgo 2nd funnel": "Rafael Hidalgo",
               "Raf Hidalgo 3rd funnel": "Rafael Hidalgo",
               "Geoge Delgado": "George Delgado"}
LEDGER = Path(__file__).resolve().parents[2] / "output" / "first_round_scorecards" / "posted.json"


def office_name(office: str) -> str:
    return SAME_OFFICE.get(office, office)


def emoji(score: int) -> str:
    """Camila's board colors (2026-10-05): under 50 red, 50 blue, over 50 green."""
    return "🔴" if score < 50 else ("🔵" if score == 50 else "🟢")


def _doc_url(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"


def _top(labels: List[str], n: int = 3) -> str:
    return ", ".join(board._tally(labels).split(", ")[:n])


def by_office(rows: List[Dict], day: dt.date) -> Dict[str, List[Dict]]:
    """{office: that day's audit rows, oldest first}. Rows without an office
    (a Zoom not in ZOOMS INFO) can't be placed and are left out."""
    out: Dict[str, List[Dict]] = {}
    for r in sorted(rows, key=lambda r: r.get("time") or ""):
        if r.get("date") == day.isoformat() and r.get("score") is not None and r.get("office"):
            out.setdefault(office_name(r["office"]), []).append(r)
    return out


def office_text(office: str, rows: List[Dict], day: dt.date) -> str:
    scores = [int(r["score"]) for r in rows]
    avg = board._avg(scores)
    lines = [f"📋 *1st Round Scorecard — {office}'s office — {day:%a} {day.month}/{day.day}*",
             f"Office average: *{avg}/100* {emoji(avg)}  ·  {len(rows)} interview"
             f"{'s' if len(rows) != 1 else ''}"]
    people: Dict[str, List[Dict]] = {}
    for r in rows:
        people.setdefault(r["interviewer"], []).append(r)
    order = sorted(people, key=lambda p: (bool(board._NOT_A_PERSON.match(p)),
                                          -board._avg([int(r["score"]) for r in people[p]]), p))
    for name in order:
        mine = people[name]
        a = board._avg([int(r["score"]) for r in mine])
        lines += ["", f"*{name}* — {a}/100 {emoji(a)}  ·  {len(mine)} interview"
                      f"{'s' if len(mine) != 1 else ''}"]
        flags = [f for r in mine for f in r.get("flags") or []]
        missed = [m for r in mine for m in r.get("missed") or []]
        if flags:
            lines.append(f"🚩 Red flags: {_top(flags)}")
        if missed:
            lines.append(f"❌ Most missed: {_top(missed)}")
        tips = next((r["coaching"] for r in reversed(mine) if r.get("coaching")), [])
        if tips:
            lines.append("💡 *Feedback:*")
            lines += [f"• {board._first_sentence(t)}" for t in tips[:2]]
        audits = [f"<{_doc_url(r['doc'])}|{_clock(r.get('time'))}>" for r in mine if r.get("doc")]
        if audits:
            lines.append("📄 Full audits: " + " · ".join(audits))
    return "\n".join(lines)


def _clock(hhmm: str) -> str:
    if not hhmm:
        return "audit"
    return dt.datetime.strptime(hhmm, "%H:%M").strftime("%I:%M %p").lstrip("0")


def posts(rows: List[Dict], day: dt.date) -> List[tuple]:
    """[(office, channel or '', text)] for the day, offices by name."""
    out = []
    for office, mine in sorted(by_office(rows, day).items()):
        out.append((office, CHANNELS.get(office, ""), office_text(office, mine, day)))
    return out


def _ledger() -> Dict:
    try:
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def post_day(rows: List[Dict], day: dt.date, *, sample: bool) -> int:
    """Each office's scorecard in its channel (or all of them in the sample
    group DM). A channel already posted that day is skipped, so a re-run
    never posts an office twice. Returns 1 if any post failed."""
    from automations.shared import slack_metrics_post as smp
    # Lucy's user token on purpose (lucy_reporting), like the day's post
    client = smp._client()
    todo = posts(rows, day)
    if not todo:
        print("OFFICE POSTS: no audited interview with an office that day")
        return 0
    dm = ""
    if sample:
        dm = client.conversations_open(users=",".join(SAMPLE_TO))["channel"]["id"]
        client.chat_postMessage(channel=dm, text=(
            f"👀 *Sample — 1st Round office scorecards for {day:%a} {day.month}/{day.day}*\n"
            "Each message below goes to that office's recruiting channel every day after "
            "6 PM, once the day is audited. Nothing has gone to the offices yet."))
    done = set(_ledger().get("_office_posted", []))
    failed = 0
    for office, channel, text in todo:
        if not sample and not channel:
            print(f"  {office}: NO CHANNEL - not posted (add it to office_post.CHANNELS)")
            continue
        key = f"{day.isoformat()} {channel}"
        if not sample and key in done:
            print(f"  {office}: already posted")
            continue
        try:
            resp = client.chat_postMessage(channel=dm or channel, text=text,
                                           unfurl_links=False, unfurl_media=False)
        except Exception as exc:  # noqa: BLE001
            print(f"  {office}: FAILED {type(exc).__name__}: {exc}")
            failed += 1
            continue
        if not resp.get("ok"):
            failed += 1
            continue
        print(f"  {office}: posted{' (sample)' if sample else ''}")
        if not sample:
            data = _ledger()
            data["_office_posted"] = (data.get("_office_posted", []) + [key])[-400:]
            LEDGER.parent.mkdir(parents=True, exist_ok=True)
            LEDGER.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return 1 if failed else 0


def day_rows(day: dt.date) -> List[Dict]:
    """The week's audit rows with the 'Same person?' merges, like the board."""
    rows = board.scores(board.monday(day))
    return board.apply_merges(rows, board.merges(board.read_same()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.office_post")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today, Central)")
    ap.add_argument("--sample", action="store_true",
                    help="post every office's scorecard in the group DM Rafael + Camila + Eve")
    ap.add_argument("--post", action="store_true", help="LIVE: each office's channel")
    args = ap.parse_args(argv)
    day = (dt.date.fromisoformat(args.date) if args.date
           else dt.datetime.now(dt.timezone.utc).astimezone(fathom.CT).date())
    rows = day_rows(day)
    for office, channel, text in posts(rows, day):
        print(f"\n=== {office} -> {channel or 'NO CHANNEL'} ===\n{text}")
    if not (args.sample or args.post):
        print("\nDRY-RUN: nothing posted")
        return 0
    return post_day(rows, day, sample=args.sample)


if __name__ == "__main__":
    raise SystemExit(main())
