"""What each Lucy's monitor shows, kept on it. One tick, every minute.

Megan 2026-11-01: "I want the lucy screens to show different things and be on all
the time." Lucy 1 = the live LucyEco page; Lucy 2 = every alert still needing a fix; Lucy 3 = every
Lucy's reports today (each Lucy writes its line to a shared tab each tick).

Safari, not Chrome: chrome_guard closes a person's Chrome at 4am, and an open one
adopts the reports' launches (reference_browser_profile_collisions).
"""
import argparse
import datetime as dt
import html
import json
import os
import re
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
PAGES = {ALERTS: ALERTS_PAGE, RUNS: RUNS_PAGE}
SCREENS = {
    "Lucy 1": "https://lucyeco.streamlit.app/lucyeco",
    "Lucy 2": ALERTS,
    "Lucy 3": RUNS,
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
        out.append({"title": _title(text), "ts": float(m["ts"]),
                    "working": "pending" in marks})
    return out


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


def _age(ts: float, now: float) -> str:
    mins = int((now - ts) // 60)
    if mins < 60:
        return f"{mins}m"
    return f"{mins // 60}h" if mins < 1440 else f"{mins // 1440}d"


def page(alerts: Optional[List[dict]], now: float) -> str:
    """alerts=None means Slack could not be read: never drawn as all clear."""
    stamp = dt.datetime.fromtimestamp(now).strftime("%I:%M %p").lstrip("0")
    if alerts is None:
        big, cls, rows = "Can't read Slack right now", "bad", ""
    elif not alerts:
        big, cls, rows = "Nothing needs correcting", "good", ""
    else:
        n = len(alerts)
        big, cls = f"{n} alert{'s' if n != 1 else ''} need correcting", "bad"
        rows = "".join(
            f'<div class="row"><span class="tag {"on" if a["working"] else ""}">'
            f'{"Being worked" if a["working"] else "Needs someone"}</span>'
            f'<span class="t">{html.escape(a["title"])}</span>'
            f'<span class="age">{_age(a["ts"], now)}</span></div>' for a in alerts)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60"><title>Alerts</title><style>
body{{margin:0;background:#faf6ea;color:#2b2415;font:bold 24px Georgia,serif;padding:28px 36px}}
h1{{margin:0 0 4px;font-size:46px}} .good{{color:#2f7a3d}} .bad{{color:#a8281e}}
.sub{{color:#8a6d1f;font-size:20px;margin-bottom:20px}} .stale{{display:none;color:#a8281e}}
.row{{display:flex;align-items:center;gap:18px;background:#fff;border:1px solid #e3d6ad;
border-radius:10px;padding:12px 18px;margin-bottom:8px}}
.t{{flex:1}} .age{{color:#8a6d1f;min-width:60px;text-align:right}}
.tag{{font-size:16px;padding:5px 12px;border-radius:99px;background:#f6d9d4;color:#a8281e;
white-space:nowrap;min-width:125px;text-align:center}} .tag.on{{background:#f3e6b8;color:#7a5c0c}}
</style></head><body><h1 class="{cls}">{html.escape(big)}</h1>
<div class="sub">#claudecorrections-and-requests &middot; updated {stamp}
<span class="stale" id="s"> &middot; THIS SCREEN STOPPED UPDATING</span></div>{rows}
<script>if(Date.now()-{int(now * 1000)}>600000)document.getElementById("s").style.display="inline"</script>
</body></html>"""


def write_alerts() -> None:
    now = time.time()
    try:
        msgs = read_channel()
        if not msgs:  # this channel is never silent for 14 days: an empty read
            raise RuntimeError("Slack returned no messages")  # is not all clear
        alerts = open_alerts(msgs)
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
body{{margin:0;background:#faf6ea;color:#2b2415;font:bold 15px Georgia,serif;padding:18px 22px;box-sizing:border-box;overflow:hidden}}
h1{{margin:0;font-size:34px}} .sub{{color:#8a6d1f;margin:2px 0 12px}}
.stale{{display:none;color:#a8281e}} .cols{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;height:calc(100% - 70px)}}
.col{{background:#fff;border:1px solid #e3d6ad;border-radius:10px;padding:10px 12px;overflow:hidden}}
h2{{margin:0 0 6px;font-size:24px;color:#8a6d1f}} .n{{margin:4px 0 8px}}
.bar{{height:14px;background:#efe6c8;border-radius:99px;overflow:hidden}} .bar i{{display:block;height:100%;background:#b8962e}}
.live{{background:#fbf3d6;border-radius:8px;padding:6px 8px;margin-bottom:6px}} .r{{display:flex;justify-content:space-between;gap:8px}}
.move{{height:6px;margin-top:5px;border-radius:9px;background:repeating-linear-gradient(90deg,#b8962e 0 18px,#efe6c8 18px 36px);background-size:72px 6px;animation:m 2s linear infinite}}
@keyframes m{{to{{background-position:72px 0}}}}
.idle{{color:#8a6d1f;margin-bottom:6px}} .off{{color:#a8281e;font-size:20px}}
.list{{border-top:1px solid #e3d6ad;padding-top:6px;margin-top:6px;font-size:13px;line-height:15px}}
.l{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.l:before{{content:"● "}} .ok:before{{color:#2f7a3d}} .wait:before{{color:#c9b98a}} .bad{{color:#a8281e}}
</style></head><body><h1>Reports Today</h1>
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


def keep_open(target: str) -> None:
    """Open it after a restart; otherwise bring it back in front once it has been
    covered. Megan 2026-11-01: Lucy 1 kept leaving the page as automations ran.
    Holds back while a report runs (a covered Chrome can stall its capture) and
    while a person is using the machine. Plain `open -a` so no new tab each tick."""
    if subprocess.run(["pgrep", "-x", "Safari"],
                      stdout=subprocess.DEVNULL).returncode != 0:
        url = PAGES[target].as_uri() if target in PAGES else target
        subprocess.run(["open", "-a", "Safari", url], check=False)
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
    keep_open(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
