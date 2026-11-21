"""Lucy Second Round Scorecards: one thread per owner, in the owner's own
recruiting channel (Raf, Slack 2026-11-16 - "instead of a group chat, a thread
on the recruiting channel ... title it 'Lucy Second Round Scorecards' and tag
the owner inside the thread").

Each morning (with the 8 AM CT run on Lucy 1), for every owner whose reps sent
a counted recording this week:

  parent  "Lucy Second Round Scorecards - <day>"
  reply 1 @owner + yesterday's list for THEIR office (same format as Raf's DM)
  reply 2 one PDF per day, Monday through yesterday (Wednesday -> Mon + Tue;
          Friday -> Mon..Thu; Monday -> all of last week). Counted ones only.
  reply 3 the month-to-date picture (the org email's table), Raf 11:35 "in
          thread we can also post this".

Channels = first_round_scorecards.office_post.CHANNELS (Lucy is already in all
of them). An owner with no channel there is logged and skipped.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path

TITLE = "Lucy Second Round Scorecards"
ROOT = Path(__file__).resolve().parents[2]
LEDGER_DIR = ROOT / "output" / "state" / "lucy_scorecard_threads"
PDF_DIR = ROOT / "output" / "lucy_scorecard_pdfs"
# Bot owner name -> the name the channel list uses, when they differ.
# Raf 11/13: everything of Salik's goes under Hammad; the channel is Salik's.
CHANNEL_ALIASES = {"hammad haque": "Salik Mallick"}
# Owners with no 1st Round Scorecards channel. Kept HERE, not in office_post.CHANNELS,
# so adding one doesn't also start the 1st round post in that channel.
EXTRA_CHANNELS = {
    "Valeria Tristan": "C0C70G1ENPK",     # Eve 2026-11-16
}
# Extra people tagged next to the owner on their thread's list reply.
# Raf 2026-11-19: "can we tag @tiff to this every post please".
EXTRA_TAGS = {
    "Rafael Hidalgo": ["U0B9924FHCL"],    # tiff (Tiffani Brown)
}
PAUSE_S = 1.2


def week_days(yesterday: dt.date) -> list:
    """Monday of yesterday's week .. yesterday. On a Monday, yesterday is
    Sunday -> the whole previous week."""
    mon = yesterday - dt.timedelta(days=yesterday.weekday())
    return [mon + dt.timedelta(days=i) for i in range((yesterday - mon).days + 1)]


def _words(s: str) -> set:
    from automations.lucy_recordings_sheet.run import norm
    return set(norm(s).split())


def channel_for(owner: str, channels: dict | None = None, same: dict | None = None) -> tuple:
    """(channel-list name, channel id) for a bot owner name, or ("", "").
    Every word of the list's name must be in the owner's name, so 'I'm the
    owner, Frank Matos' finds 'Frank Matos'."""
    if channels is None:
        from automations.first_round_scorecards.office_post import CHANNELS, SAME_OFFICE
        channels, same = {**CHANNELS, **EXTRA_CHANNELS}, SAME_OFFICE
    same = same or {}
    alias = CHANNEL_ALIASES.get(re.sub(r"\s+", " ", owner.strip().lower()))
    if alias and alias in channels:
        return alias, channels[alias]
    have = _words(owner)
    hits = [k for k in channels if k not in same and _words(k) and _words(k) <= have]
    if not hits:
        return "", ""
    best = max(hits, key=lambda k: len(_words(k)))
    return best, channels[best]


def slack_tag(name: str, owner_rec: dict | None = None) -> str:
    """<@U...> from the owners file (first + last name exactly), else the
    bot's own record, else the name in bold - never a guessed id."""
    from automations.icd_alerts.offices import slack_id_on_file
    uid = slack_id_on_file(name)
    if not uid and owner_rec:
        for k in ("slack_id", "slack_user_id", "user_id"):
            v = str(owner_rec.get(k) or "")
            if re.fullmatch(r"[UW][A-Z0-9]{8,12}", v):
                uid = v
                break
    return "<@%s>" % uid if uid else "*%s*" % name


def plan(kept: list, export: dict, guesses: dict, yesterday: dt.date) -> dict:
    """owner name -> {day iso: [record, ...]} for counted recordings this week."""
    owners = {o["id"]: o.get("name", o["id"]) for o in export.get("owners") or []}
    reps = export.get("reps") or {}
    days = {d.isoformat() for d in week_days(yesterday)}
    out = defaultdict(lambda: defaultdict(list))
    for r in kept:
        day = (r.get("ts") or "")[:10]
        if day not in days:
            continue
        uid = r.get("uid") or ""
        oid = (reps.get(uid) or {}).get("owner_id") if uid else None
        owner = owners.get(oid) if oid else (guesses[uid][0] if uid in guesses else "")
        if owner:
            out[owner][day].append(r)
    return out


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def _day_label(day: str, long: bool = False) -> str:
    d = dt.date.fromisoformat(day)
    return "%s, %s %d" % (d.strftime("%A" if long else "%a"), d.strftime("%b"), d.day)


def build_pdfs(owner_plan: dict, names: dict, today: dt.date, run_bot) -> dict:
    """(owner, day) -> pdf path, made in the bot's venv. run_bot(script, args)
    returns the helper's stdout."""
    from automations.lucy_recordings_sheet.run import short_name
    jobs, where = [], {}
    for owner, by_day in owner_plan.items():
        for day, recs in sorted(by_day.items()):
            recs = sorted(recs, key=lambda r: r.get("ts") or "")
            pdfs = [r["pdf"] for r in recs if r.get("pdf")]
            if not pdfs:
                continue
            out = PDF_DIR / today.isoformat() / ("%s_%s.pdf" % (_safe(owner), day))
            rows = []
            for r in recs:
                if not r.get("pdf"):
                    continue
                try:
                    t = dt.datetime.fromisoformat(r["ts"][:19]).strftime("%I:%M %p").lstrip("0")
                except ValueError:
                    t = ""
                sc = r.get("score")
                rows.append([short_name(names.get(r.get("uid") or "") or "(no name)"), t,
                             "—" if sc is None else "%g/10" % sc])
            jobs.append({"out": str(out), "owner": owner, "day": day, "rows": rows, "pdfs": pdfs})
            where[(owner, day)] = (out, len(pdfs))
    if not jobs:
        return {}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(jobs, fh)
    res = json.loads(run_bot("bot_pdfs.py", [fh.name]).strip().splitlines()[-1])
    for out, why in (res.get("failed") or {}).items():
        print("[owner threads] no PDF %s: %s" % (Path(out).name, why), flush=True)
    made = set(res.get("made") or [])
    return {k: v for k, v in where.items() if str(v[0]) in made}


def render_png(page_html: str, out: Path) -> Path | None:
    """The month-to-date email as a picture (headless Chrome)."""
    try:
        from patchright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001
        from playwright.sync_api import sync_playwright
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".html")
    tmp.write_text('<html><head><meta charset="utf-8"></head><body style="margin:0;'
                   'background:#fff"><div id="m" style="width:720px;padding:16px">%s</div>'
                   '</body></html>' % page_html, encoding="utf-8")
    with sync_playwright() as p:
        browser = None
        for kw in ({"channel": "chrome"}, {}):
            try:
                browser = p.chromium.launch(headless=True, **kw)
                break
            except Exception:  # noqa: BLE001
                continue
        if browser is None:
            return None
        try:
            page = browser.new_page(device_scale_factor=2, viewport={"width": 760, "height": 900})
            page.goto(tmp.as_uri(), wait_until="networkidle")
            page.query_selector("#m").screenshot(path=str(out))
        finally:
            browser.close()
    return out


def _ledger(today: dt.date) -> tuple:
    path = LEDGER_DIR / ("%s.json" % today.isoformat())
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return path, {}


def post(client, owner_plan: dict, pdfs: dict, list_text, month_png: Path | None,
         yesterday: dt.date, export: dict, today: dt.date, test_to: str = "",
         only: str = "", log=print) -> int:
    """Posts each owner's thread. test_to = a user id: every thread goes to
    Lucy's DM with that person instead, with the owner's name instead of a tag.
    list_text(owner) -> the yesterday list for that owner's office."""
    recs = {o.get("name", ""): o for o in export.get("owners") or []}
    ledger_path, ledger = _ledger(today)
    days = [d.isoformat() for d in week_days(yesterday)]
    span = (_day_label(days[0]) if len(days) == 1
            else "%s – %s" % (_day_label(days[0]), _day_label(days[-1])))
    test_dm = ""
    if test_to:
        test_dm = client.conversations_open(users=test_to)["channel"]["id"]
    posted = 0
    for owner in sorted(owner_plan):
        if only and not (_words(only) <= _words(owner)):
            continue
        name, channel = channel_for(owner)
        if not channel:
            log("[owner threads] %s: no recruiting channel on file - skipped" % owner)
            continue
        if not test_to and owner in ledger:
            log("[owner threads] %s: already posted today (ts %s) - skipped"
                % (owner, ledger[owner].get("ts")))
            continue
        files = [(d, pdfs[(owner, d)]) for d in days if (owner, d) in pdfs]
        if not files:
            log("[owner threads] %s: no scorecard PDF this week - skipped" % owner)
            continue
        where = test_dm or channel
        # The owner's own name first (Hammad sits in Salik's channel), then the channel's.
        tag = slack_tag(owner, recs.get(owner))
        if not tag.startswith("<@"):
            tag = slack_tag(name)
        tag = " ".join([tag] + ["<@%s>" % u for u in EXTRA_TAGS.get(owner, [])])
        if test_to:
            tag = "*%s* (test: would tag %s)" % (owner, tag.replace("<@", "").replace(">", ""))
        head = "*%s* — %s" % (TITLE, _day_label(today.isoformat(), long=True))
        if test_to:
            head += "\n_(test - goes to %s's recruiting channel)_" % name
        parent = client.chat_postMessage(channel=where, text=head)
        ts = parent["ts"]
        time.sleep(PAUSE_S)
        client.chat_postMessage(channel=where, thread_ts=ts, unfurl_links=False,
                                text="%s\n\n%s" % (tag, list_text(owner)))
        time.sleep(PAUSE_S)
        uploads = [{"file": str(p), "filename": p.name,
                    "title": "%s · 2nd Round Scorecards (%d)" % (_day_label(d), n)}
                   for d, (p, n) in files]
        client.files_upload_v2(channel=where, thread_ts=ts, file_uploads=uploads,
                               initial_comment="Scorecards this week, one PDF per day (%s):" % span)
        if month_png and month_png.exists():
            time.sleep(PAUSE_S)
            client.files_upload_v2(channel=where, thread_ts=ts, file=str(month_png),
                                   filename=month_png.name, title="Week to date",
                                   initial_comment="Week to date, all offices:")
        posted += 1
        log("[owner threads] %s -> %s ts=%s (%d PDF(s))" % (owner, where, ts, len(files)))
        if not test_to:
            ledger[owner] = {"channel": channel, "ts": ts}
            LEDGER_DIR.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text(json.dumps(ledger, indent=1), encoding="utf-8")
        time.sleep(PAUSE_S)
    return posted
