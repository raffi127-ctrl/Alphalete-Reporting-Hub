"""What each Lucy's monitor shows, kept on it. One tick, every minute.

Megan 2026-11-01: "I want the lucy screens to show different things and be on all
the time." Lucy 1 = the live LucyEco page; Lucy 2 = Lucy's photo; Lucy 3 = every Lucy's reports today (each Lucy writes its
line to a shared tab each tick); Lucy 4 = every alert still needing a fix.

Safari, not Chrome: chrome_guard closes a person's Chrome at 4am, and an open one
adopts the reports' launches (reference_browser_profile_collisions).
"""
import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

REPO = Path(__file__).resolve().parents[2]
ALERTS_PAGE = REPO / "output" / "lucy_screens" / "alerts.html"
ALERTS = "alerts"
RUNS = "runs"
RUNS_PAGE = REPO / "output" / "lucy_screens" / "runs.html"
STATUS_TAB = "Screen Status"
STALE_AFTER = 300
PHOTO = "photo"
PHOTO_PAGE = REPO / "output" / "lucy_screens" / "photo.html"
# Lucy 1: the live LucyEco page inside a pink frame. The page itself is public
# (ICDs open it), so it keeps its own look; only this screen gets the frame.
LUCYECO = "lucyeco"
LUCYECO_URL = "https://lucyeco.streamlit.app/lucyeco"
LUCYECO_PAGE = REPO / "output" / "lucy_screens" / "lucyeco.html"
PAGES = {ALERTS: ALERTS_PAGE, RUNS: RUNS_PAGE, PHOTO: PHOTO_PAGE, LUCYECO: LUCYECO_PAGE}
OPENED = REPO / "output" / "lucy_screens" / "opened.txt"
SCREENS = {
    # Measured 2026-11-03 20:10-20:16 CT with Lucy 1 OFF this page: the app
    # stalled exactly as often. One open tab here costs it nothing.
    "Lucy 1": LUCYECO,
    "Lucy 2": PHOTO,
    "Lucy 3": RUNS,
    "Lucy 4": ALERTS,
}
HISTORY_DAYS = 14
IDLE_BEFORE_FRONT = 300
# "_incident · <key> · open 2026-11-01_" is incident_thread.marker(). The newest
# post for a key decides, whatever its state, so a closed one hides older opens.
_MARK = re.compile(r"_incident\s*·\s*([^\s·]+)\s*·\s*(\w+)")
_LINK = re.compile(r"<[^|>]+\|([^>]+)>")


def _title(text: str) -> str:
    line = next((x for x in text.splitlines() if x.strip()), "")
    line = _LINK.sub(r"\1", line).replace("*", "").strip()
    return re.sub(r":[a-z0-9_+-]+:\s*", "", line).strip()


def open_alerts(messages: List[dict]) -> List[dict]:
    """Newest post per incident key, dropping anything marked done. Newest first."""
    seen, out = set(), []
    for m in sorted(messages, key=lambda x: float(x["ts"]), reverse=True):
        text = m.get("text") or ""
        hit = _MARK.search(text)
        if not hit or hit.group(1) in seen:
            continue
        seen.add(hit.group(1))
        if hit.group(2) != "open":
            continue
        marks = [r.get("name") for r in m.get("reactions") or []]
        if "white_check_mark" in marks or "RESOLVED" in text:
            continue
        who = []
        for r in m.get("reactions") or []:
            if r.get("name") == "pending":
                who = [PEOPLE[u] for u in r.get("users") or [] if u in PEOPLE]
        out.append({"title": _title(text), "ts": float(m["ts"]),
                    "working": "pending" in marks, "who": ", ".join(who)})
    return out


# Who may show up as "working on it": the two people who triage this channel.
# Lucy's own id is left out on purpose -- her mark means a Claude session
# placed it, and the person's name is in the thread note instead.
PEOPLE = {"U04G5HJBGFN": "Megan", "U088E2KJEV8": "Eve"}
_NOTE = re.compile(r"Working on it\s*[\u2014-]+\s*([A-Za-z][\w.'-]*)")


def who_from_thread(client, ts: str) -> str:
    """The name in the newest "Working on it -- X" reply, else ''. One
    conversations.replies per worked ticket; there are rarely more than two."""
    from automations.shared import incident_thread as I, slack_retry
    try:
        r = slack_retry.read(client.conversations_replies, channel=I.CHANNEL,
                             ts="%.6f" % ts, limit=200)
    except Exception:  # noqa: BLE001
        return ""
    for m in sorted(r.get("messages") or [], key=lambda x: float(x["ts"]), reverse=True):
        hit = _NOTE.search(m.get("text") or "")
        if hit:
            return hit.group(1)
    return ""


def fill_who(alerts: List[dict]) -> None:
    from automations.shared import incident_thread as I
    client = None
    for a in alerts:
        if a["working"] and not a.get("who"):
            client = client or I._client()
            a["who"] = who_from_thread(client, a["ts"]) or "someone"


def read_channel() -> List[dict]:
    """Newest pages back to the cutoff. No `oldest`: Slack twice answered that
    with an empty list and no error (2026-11-01), so stop on the ts ourselves."""
    from automations.shared import incident_thread as I, slack_retry
    client, msgs, cursor = I._client(), [], None
    cutoff = time.time() - HISTORY_DAYS * 86400
    while True:
        kw = dict(channel=I.CHANNEL, limit=200)
        if cursor:
            kw["cursor"] = cursor
        r = slack_retry.read(client.conversations_history, **kw)
        page_msgs = r.get("messages") or []
        msgs.extend(page_msgs)
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor or not page_msgs or float(page_msgs[-1]["ts"]) < cutoff:
            return [m for m in msgs if float(m["ts"]) >= cutoff]


# Pink, every screen. Megan 2026-11-25: "can we make the others have more
# pink/girly screens". Problems stay true red and done stays green, so the
# pink never hides what a screen is saying.
PINK_BG = ("radial-gradient(ellipse at 50% 30%,#fff6f9 0%,#fde4ec 55%,#f8cddd 100%)"
           " fixed")
_BULBS = ("#ff7eb3", "#e8b64c", "#ffffff", "#f06598", "#9fd8c0", "#ffc2d9")


def lights(now: float) -> str:
    """Twinkle lights along the top while Lucy 2 shows Christmas Lucy (Nov 25 -
    Jan 1), so the four screens match. Empty the rest of the year."""
    if not is_christmas(dt.date.fromtimestamp(now)):
        return ""
    bulbs = "".join(
        f'<i style="background:{_BULBS[k % 6]};box-shadow:0 0 8px {_BULBS[k % 6]};'
        f'animation-delay:{(k % 5) * 0.45:.2f}s"></i>' for k in range(32))
    return ('<style>.lights{position:fixed;top:0;left:0;right:0;height:22px;display:flex;'
            'justify-content:space-around;border-top:2px solid #3d6b4f;pointer-events:none;z-index:5}'
            '.lights i{width:10px;height:15px;border-radius:50%;margin-top:2px;'
            'animation:tw 2.4s ease-in-out infinite}@keyframes tw{50%{opacity:.35}}</style>'
            f'<div class="lights">{bulbs}</div>')


def lucyeco_page(now: float) -> str:
    """Refreshes hourly: picks up the lights coming and going, and a fresh read."""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="3600"><title>LucyEco</title><style>
html,body{{height:100%;margin:0;overflow:hidden}}
body{{background:{PINK_BG};display:flex;flex-direction:column;padding:30px 26px 22px;box-sizing:border-box}}
h1{{margin:0 0 12px;text-align:center;font:700 44px "Snell Roundhand","Brush Script MT",cursive;line-height:1;color:#c2185b}}
iframe{{flex:1;width:100%;border:0;border-radius:18px;background:#fff;
box-shadow:0 0 0 6px #fff,0 0 0 9px #f39bbd,0 12px 30px rgba(194,24,91,.18)}}
</style></head><body>{lights(now)}<h1>LucyEco &#127872;</h1>
<iframe src="{LUCYECO_URL}?embed=true"></iframe></body></html>"""


def write_lucyeco() -> None:
    LUCYECO_PAGE.parent.mkdir(parents=True, exist_ok=True)
    LUCYECO_PAGE.write_text(lucyeco_page(time.time()), encoding="utf-8")


def _age(ts: float, now: float) -> str:
    mins = int((now - ts) // 60)
    if mins < 60:
        return f"{mins}m"
    return f"{mins // 60}h" if mins < 1440 else f"{mins // 1440}d"


def _rows(items: List[dict], now: float) -> str:
    if not items:
        return '<div class="none">none</div>'
    return "".join(
        f'<div class="row"><span class="t">{html.escape(a["title"])}</span>'
        + (f'<span class="who">{html.escape(a["who"])}</span>' if a.get("who") else "")
        + f'<span class="age">{_age(a["ts"], now)}</span></div>' for a in items)


def page(alerts: Optional[List[dict]], now: float) -> str:
    """alerts=None means Slack could not be read: never drawn as all clear.

    TWO SECTIONS (Megan 2026-11-03): the alerts nobody has picked up, then the
    ones somebody is already on (the :pending: mark from incident_thread
    --working). The headline counts only the first -- that is the number that
    still needs a person."""
    stamp = dt.datetime.fromtimestamp(now).strftime("%I:%M %p").lstrip("0")
    sections = ""
    if alerts is None:
        big, cls = "Can't read Slack right now", "bad"
    else:
        todo = [a for a in alerts if not a["working"]]
        working = [a for a in alerts if a["working"]]
        if not todo:
            big, cls = "Nothing needs correcting", "good"
        else:
            n = len(todo)
            big, cls = f"{n} alert{'s' if n != 1 else ''} need{'' if n != 1 else 's'} correcting", "bad"
        if alerts:
            sections = (
                f'<h2 class="bad">Alerts ({len(todo)})</h2>{_rows(todo, now)}'
                f'<h2 class="work">Being worked on ({len(working)})</h2>{_rows(working, now)}')
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60"><title>Alerts</title><style>
html{{min-height:100%}}
body{{margin:0;background:{PINK_BG};color:#4a1f33;font:bold 24px Georgia,serif;padding:40px 36px 28px}}
h1{{margin:0 0 4px;font-size:46px}} .good{{color:#2f7a3d}} .bad{{color:#b3122e}} .work{{color:#a3164f}}
h2{{font-size:28px;margin:26px 0 10px;padding-bottom:6px;border-bottom:2px solid #f3bfd3}}
.sub{{color:#b0477a;font-size:20px;margin-bottom:20px}} .stale{{display:none;color:#b3122e}}
.row{{display:flex;align-items:center;gap:18px;background:#fff;border:1px solid #f3bfd3;
border-radius:14px;padding:12px 18px;margin-bottom:8px;box-shadow:0 2px 8px rgba(224,90,141,.10)}}
.t{{flex:1}} .age{{color:#b0477a;min-width:60px;text-align:right}}
.none{{color:#b0477a;font-weight:normal;padding:4px 18px}}
.who{{font-size:18px;padding:5px 14px;border-radius:99px;background:#fbd3e2;color:#a3164f;white-space:nowrap}}
</style></head><body>{lights(now)}<h1 class="{cls}">{html.escape(big)}</h1>
<div class="sub">&#127872; #claudecorrections-and-requests &middot; updated {stamp}
<span class="stale" id="s"> &middot; THIS SCREEN STOPPED UPDATING</span></div>{sections}
<script>if(Date.now()-{int(now * 1000)}>600000)document.getElementById("s").style.display="inline"</script>
</body></html>"""


def write_alerts() -> None:
    now = time.time()
    try:
        msgs = read_channel()
        if not msgs:  # this channel is never silent for 14 days: an empty read
            raise RuntimeError("Slack returned no messages")  # is not all clear
        alerts = open_alerts(msgs)
        fill_who(alerts)
    except Exception as e:  # noqa: BLE001
        print(f"slack read failed: {type(e).__name__}: {str(e)[:120]}")
        if ALERTS_PAGE.exists():
            return  # keep the last good list; its own stale warning takes over
        alerts = None
    ALERTS_PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ALERTS_PAGE.with_suffix(".tmp")
    tmp.write_text(page(alerts, now), encoding="utf-8")
    tmp.replace(ALERTS_PAGE)


# --- Lucy 3: every Lucy's reports today ------------------------------------
_GOOD = {"DONE"}
_WAIT = {"PENDING", "STILL_TRYING"}
# The batch itself (shown as its reports) and this screen are not reports.
_NOT_REPORTS = {"automations.lucy_screens.run", "automations.day_orchestrator.run"}
_RUN_MOD = re.compile(r"-m\s+(automations\.[\w.]+\.run)\b(.*)")


def _seconds(etime: str) -> int:
    days, _, rest = etime.strip().rpartition("-")
    parts = [int(x) for x in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return int(days or 0) * 86400 + parts[0] * 3600 + parts[1] * 60 + parts[2]


def _names() -> dict:
    """module -> display name, from the schedule. Several entries can share one
    module (office metrics), so the args pick between them where they can."""
    cfg = json.loads((REPO / "automations" / "day_orchestrator"
                      / "schedule_config.json").read_text(encoding="utf-8"))
    out = {}
    for rid, e in (cfg.get("reports") or cfg).items():
        cmd = e.get("command") if isinstance(e, dict) else None
        if cmd:
            out.setdefault(cmd[0], []).append(
                (e.get("base_args") or [], e.get("display_name") or rid))
    return out


def running_now(ps_out: str, names: dict) -> List[dict]:
    """Reports running this second, parents only (a wrapper and its child are one)."""
    out, seen = [], set()
    for line in ps_out.splitlines():
        parts = line.strip().split(None, 1)
        hit = _RUN_MOD.search(parts[1]) if len(parts) == 2 else None
        if not hit or hit.group(1) in _NOT_REPORTS:
            continue
        mod, args = hit.group(1), hit.group(2).split()
        options = names.get(mod) or []
        best = next((n for b, n in options if b and all(x in args for x in b)), None)
        name = best or (options[0][1] if len(options) == 1 else
                        mod.split(".")[1].replace("_", " ").title())
        if name not in seen:
            seen.add(name)
            out.append({"name": name, "secs": _seconds(parts[0])})
    return sorted(out, key=lambda x: -x["secs"])


def snapshot(day: Optional[str] = None) -> dict:
    day = day or dt.date.today().isoformat()
    path = REPO / "output" / "day_state" / f"{day}.json"
    reports = []
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        for rid, r in (data.get("reports") or {}).items():
            if r.get("status") != "SKIPPED":
                reports.append({"name": r.get("display_name") or rid,
                                "status": r.get("status")})
    ps = subprocess.run(["ps", "-axo", "etime=,command="], stdout=subprocess.PIPE,
                        text=True).stdout
    return {"day": day, "at": time.time(), "reports": reports,
            "running": running_now(ps, _names())}


def _status_ws():
    from automations.day_orchestrator.control_books import HEARTBEAT_BOOK
    from automations.recruiting_report.fill import open_by_key
    import gspread
    book = open_by_key(HEARTBEAT_BOOK)
    try:
        return book.worksheet(STATUS_TAB)
    except gspread.WorksheetNotFound:
        return book.add_worksheet(STATUS_TAB, rows=20, cols=3)


def publish(machine: str) -> None:
    """This Lucy's line on the shared tab, found by machine name in column A."""
    ws = _status_ws()
    names = ws.col_values(1)
    row = names.index(machine) + 1 if machine in names else len(names) + 1
    ws.update([[machine, json.dumps(snapshot())]], f"A{row}:B{row}",
              value_input_option="RAW")


def read_fleet() -> dict:
    return {r[0]: json.loads(r[1]) for r in _status_ws().get_all_values()
            if len(r) > 1 and r[0] and r[1]}


def _clock(secs: int) -> str:
    return f"{secs // 3600}h {secs % 3600 // 60}m" if secs >= 3600 else f"{secs // 60}m"


def _column(machine: str, snap: Optional[dict], now: float) -> str:
    title = f"<h2>{html.escape(machine)}</h2>"
    if not snap or now - snap.get("at", 0) > STALE_AFTER:
        return f'<div class="col">{title}<div class="off">No update from this Lucy</div></div>'
    reports = snap.get("reports") or []
    finished = [r for r in reports if r["status"] not in _WAIT]
    pct = round(100 * len(finished) / len(reports)) if reports else 0
    bar = (f'<div class="bar"><i style="width:{pct}%"></i></div>'
           f'<div class="n">{len(finished)} of {len(reports)} reports finished</div>')
    live = "".join(
        f'<div class="live"><div class="r"><span>{html.escape(r["name"])}</span>'
        f'<b>{_clock(r["secs"])}</b></div><div class="move"></div></div>'
        for r in snap.get("running") or []) or '<div class="idle">Nothing running right now</div>'
    order = sorted(reports, key=lambda r: (
        0 if r["status"] not in _GOOD | _WAIT else 1 if r["status"] in _WAIT else 2))
    rows = "".join(
        f'<div class="l {"ok" if r["status"] in _GOOD else "wait" if r["status"] in _WAIT else "bad"}">'
        f'{html.escape(r["name"])}</div>' for r in order)
    return f'<div class="col">{title}{bar}{live}<div class="list">{rows}</div></div>'


def runs_page(fleet: dict, now: float) -> str:
    from automations.shared.fleet import RUNNERS
    stamp = dt.datetime.fromtimestamp(now).strftime("%I:%M %p").lstrip("0")
    cols = "".join(_column(m, fleet.get(m), now) for m in RUNNERS)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60"><title>Reports Today</title><style>
html,body{{height:100%}}
body{{margin:0;background:{PINK_BG};color:#4a1f33;font:bold 15px Georgia,serif;padding:28px 22px 18px;box-sizing:border-box;overflow:hidden}}
h1{{margin:0;font:700 40px "Snell Roundhand","Brush Script MT",cursive;line-height:1;color:#c2185b}} .sub{{color:#b0477a;margin:2px 0 10px}}
.stale{{display:none;color:#b3122e}} .cols{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;height:calc(100% - 80px)}}
.col{{background:#fff;border:1px solid #f3bfd3;border-radius:14px;padding:10px 12px;overflow:hidden;box-shadow:0 2px 10px rgba(224,90,141,.12)}}
h2{{margin:0 0 6px;font-size:24px;color:#d6337f}} .n{{margin:4px 0 8px}}
.bar{{height:14px;background:#f8d7e4;border-radius:99px;overflow:hidden}} .bar i{{display:block;height:100%;background:linear-gradient(90deg,#f39bbd,#e05a8d)}}
.live{{background:#fdeaf1;border-radius:10px;padding:6px 8px;margin-bottom:6px}} .r{{display:flex;justify-content:space-between;gap:8px}}
.move{{height:6px;margin-top:5px;border-radius:9px;background:repeating-linear-gradient(90deg,#e05a8d 0 18px,#f8d7e4 18px 36px);background-size:72px 6px;animation:m 2s linear infinite}}
@keyframes m{{to{{background-position:72px 0}}}}
.idle{{color:#b0477a;margin-bottom:6px}} .off{{color:#b3122e;font-size:20px}}
.list{{border-top:1px solid #f3bfd3;padding-top:6px;margin-top:6px;font-size:13px;line-height:15px}}
.l{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.l:before{{content:"● "}} .ok:before{{color:#2f7a3d}} .wait:before{{color:#c9bcc2}} .bad{{color:#b3122e}}
</style></head><body>{lights(now)}<h1>Reports Today &#127872;</h1>
<div class="sub">Red = problem &middot; grey = still to run &middot; green = done &middot; updated {stamp}
<span class="stale" id="s"> &middot; THIS SCREEN STOPPED UPDATING</span></div>
<div class="cols">{cols}</div>
<script>if(Date.now()-{int(now * 1000)}>600000)document.getElementById("s").style.display="inline"</script>
</body></html>"""


def write_runs() -> None:
    try:
        fleet = read_fleet()
    except Exception as e:  # noqa: BLE001
        print(f"status read failed: {type(e).__name__}: {str(e)[:120]}")
        return  # keep the last good page; its stale warning takes over
    RUNS_PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUNS_PAGE.with_suffix(".tmp")
    tmp.write_text(runs_page(fleet, time.time()), encoding="utf-8")
    tmp.replace(RUNS_PAGE)


def _report_running() -> bool:
    out = subprocess.run(["pgrep", "-f", r"automations\..*\.run"],
                         stdout=subprocess.PIPE, text=True).stdout.split()
    return any(int(p) != os.getpid() for p in out)


def _idle_seconds() -> float:
    """Since a person last touched this machine. Unreadable = 0, so we hold back."""
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], stdout=subprocess.PIPE,
                         text=True).stdout
    hit = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(hit.group(1)) / 1e9 if hit else 0


def _marker(boot: str, target: str, version: str = "") -> str:
    return f"{boot} {target} {version}".rstrip()


def _needs_open(target: str, boot: str, opened: str, version: str = "") -> bool:
    """Once per restart, per page, and per look of the photo. "Safari is running"
    can't stand in for this: Safari was already open on Lucy 3, so her page never
    appeared (2026-11-01)."""
    return opened != _marker(boot, target, version)


def _photo_version(target: str) -> str:
    """A new look for Lucy 2's photo (Christmas, Jan 2's swap back) opens it once
    more. The plain page had no refresh of its own, so Safari kept showing the old
    one until a restart (2026-11-25). The other pages refresh themselves: ""."""
    if target != PHOTO or not PHOTO_PAGE.exists():
        return ""
    return hashlib.sha1(PHOTO_PAGE.read_bytes()).hexdigest()[:10]


CHRISTMAS_PAGE = Path(__file__).with_name("christmas.html")


def is_christmas(today: dt.date) -> bool:
    """Nov 25 through Jan 1. Megan 2026-11-25: a girly Christmas Lucy, pink Santa
    hat, on Lucy 2's screen. Jan 2 she goes back to the everyday photo by herself."""
    return (today.month, today.day) >= (11, 25) or (today.month, today.day) <= (1, 1)


def write_photo(today: Optional[dt.date] = None) -> None:
    # Inside the page: Safari won't load a local image from another folder, so a
    # file:// src drew nothing on Lucy 2 (2026-11-01).
    PHOTO_PAGE.parent.mkdir(parents=True, exist_ok=True)
    if is_christmas(today or dt.date.today()):
        raw = (REPO / "resources" / "lucy-photo-hires.png").read_bytes()
        img = "data:image/png;base64," + base64.b64encode(raw).decode()
        page = CHRISTMAS_PAGE.read_text(encoding="utf-8").replace("__PHOTO__", img)
        PHOTO_PAGE.write_text(page, encoding="utf-8")
        return
    raw = (REPO / "resources" / "lucy-avatar.png").read_bytes()
    img = "data:image/png;base64," + base64.b64encode(raw).decode()
    # The refresh lets a new version of this page (and Jan 2's swap back) show up
    # without waiting for a restart: keep_open only re-opens Safari after one.
    PHOTO_PAGE.write_text(
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta http-equiv="refresh" content="600"><title>Lucy</title><style>'
        "html,body{height:100%;margin:0;background:#fde4ec}"
        "body{display:flex;align-items:center;justify-content:center}"
        f'img{{height:80vh;border-radius:50%}}</style></head><body><img src="{img}">'
        "</body></html>", encoding="utf-8")


def keep_display_on() -> None:
    """Megan 2026-11-23: Lucy 1's monitor went black while the Mac was up, on AC,
    SleepDisabled=1, and this job ticking clean. `pmset disablesleep 1` stops the
    SYSTEM sleeping, not the display's own sleep timer, and nothing here held the
    display. Each tick asks for 90s of no display sleep; ticks are 60s apart, so
    the overlap keeps it on for good.

    -d only, never -u: -u declares a person at the machine, which can reset the
    idle clock keep_open waits on before bringing the page back. Its own session,
    so launchd doesn't kill it with this tick's process group."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.Popen(["/usr/bin/caffeinate", "-d", "-t", "90"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


VIEWER_SRC = Path(__file__).with_name("viewer.js")
VIEWER_APP = REPO / "output" / "lucy_screens" / "Lucy Screen.app"
VIEWER_STAMP = REPO / "output" / "lucy_screens" / "viewer.sha"


def _viewer_running() -> bool:
    return subprocess.run(["pgrep", "-f", f"{VIEWER_APP}/Contents/MacOS/"],
                          stdout=subprocess.DEVNULL).returncode == 0


def viewer(page_file: Path) -> Optional[Path]:
    """The full-screen window this Lucy's page shows in (viewer.js), built on this
    Mac once per version and page. Megan 2026-11-25: in Safari Lucy 2 "is showing
    as a webpage and not just a fully screen desktop like image", then "the others"
    the same. None = Safari, as before."""
    if sys.platform != "darwin":
        return None
    src = VIEWER_SRC.read_text(encoding="utf-8").replace(
        "__PAGE__", json.dumps(str(page_file)))
    sha = hashlib.sha1(src.encode("utf-8")).hexdigest()[:10]
    built = VIEWER_STAMP.read_text(encoding="utf-8") if VIEWER_STAMP.exists() else ""
    if built == sha and (VIEWER_APP / "Contents" / "MacOS").is_dir():
        return VIEWER_APP
    if _viewer_running():  # an older build: the new one takes its place
        subprocess.run(["pkill", "-f", f"{VIEWER_APP}/Contents/MacOS/"], check=False)
    script = VIEWER_STAMP.with_name("viewer.js")
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(src, encoding="utf-8")
    shutil.rmtree(VIEWER_APP, ignore_errors=True)
    done = subprocess.run(["osacompile", "-l", "JavaScript", "-s", "-o",
                           str(VIEWER_APP), str(script)],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if done.returncode != 0:
        print(f"viewer build failed: {done.stderr.strip()[:160]}")
        return None
    VIEWER_STAMP.write_text(sha, encoding="utf-8")
    return VIEWER_APP


def keep_open(target: str) -> None:
    """Open it after a restart; otherwise bring it back in front once it has been
    covered. Megan 2026-11-01: Lucy 1 kept leaving the page as automations ran.
    Holds back while a report runs (a covered Chrome can stall its capture) and
    while a person is using the machine. Plain `open -a` so no new tab each tick.
    Each page shows full screen in its own window (viewer), not a Safari tab.

    The viewer keeps ITSELF in front (Megan 2026-11-25: "we need these screens to
    run up front all the time - the working screens are mostly all I see"), so
    here it is only started when it isn't running. Never `open` a running one:
    that re-shows it over a person using the machine. It floats over the reports
    without holding them back -- measured 2026-11-25: a real Chrome under it
    stayed 'visible' and kept drawing ~60 frames/s, never throttled."""
    app = viewer(PAGES[target]) if target in PAGES else None
    if app is not None:
        if not _viewer_running():
            subprocess.run(["open", str(app)], check=False)
        return
    boot = subprocess.run(["sysctl", "-n", "kern.boottime"], stdout=subprocess.PIPE,
                          text=True).stdout.strip()
    opened = OPENED.read_text(encoding="utf-8") if OPENED.exists() else ""
    running = subprocess.run(["pgrep", "-x", "Safari"],
                             stdout=subprocess.DEVNULL).returncode == 0
    version = _photo_version(target)
    if not running or _needs_open(target, boot, opened, version):
        url = PAGES[target].as_uri() if target in PAGES else target
        subprocess.run(["open", "-a", "Safari", url], check=False)
        OPENED.parent.mkdir(parents=True, exist_ok=True)
        OPENED.write_text(_marker(boot, target, version), encoding="utf-8")
    elif not _report_running() and _idle_seconds() > IDLE_BEFORE_FRONT:
        subprocess.run(["open", "-a", "Safari"], check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true",
                    help="write the alerts page only, open nothing")
    a = ap.parse_args()
    if a.preview:
        write_alerts()
        print(ALERTS_PAGE)
        return 0
    from automations.shared.hub_identity import machine_name
    machine = machine_name()
    try:
        publish(machine)
    except Exception as e:  # noqa: BLE001 — never stops this Lucy's own screen
        print(f"status publish failed: {type(e).__name__}: {str(e)[:120]}")
    target = SCREENS.get(machine)
    if target is None:
        return 0  # no page chosen yet; it still reports its runs to Lucy 3
    if target == ALERTS:
        write_alerts()
    elif target == RUNS:
        write_runs()
    elif target == PHOTO:
        write_photo()
    elif target == LUCYECO:
        write_lucyeco()
    keep_display_on()
    keep_open(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
