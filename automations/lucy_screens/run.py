"""What each Lucy's monitor shows, kept on it. One tick, every minute.

Megan 2026-11-01: "I want the lucy screens to show different things and be on all
the time." Lucy 1 = the live LucyEco page; Lucy 2 = every alert still needing a fix.

Safari, not Chrome: chrome_guard closes a person's Chrome at 4am, and an open one
adopts the reports' launches (reference_browser_profile_collisions).
"""
import argparse
import datetime as dt
import html
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
SCREENS = {
    "Lucy 1": "https://lucyeco.streamlit.app/lucyeco",
    "Lucy 2": ALERTS,
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
    from automations.shared import incident_thread as I, slack_retry
    client, msgs, cursor = I._client(), [], None
    oldest = str(time.time() - HISTORY_DAYS * 86400)
    while True:
        kw = dict(channel=I.CHANNEL, oldest=oldest, limit=200)
        if cursor:
            kw["cursor"] = cursor
        r = slack_retry.read(client.conversations_history, **kw)
        msgs.extend(r.get("messages") or [])
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return msgs


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
    except Exception as e:  # noqa: BLE001 — shown on the screen, not swallowed
        print(f"slack read failed: {type(e).__name__}: {str(e)[:120]}")
        alerts = None
    ALERTS_PAGE.parent.mkdir(parents=True, exist_ok=True)
    tmp = ALERTS_PAGE.with_suffix(".tmp")
    tmp.write_text(page(alerts, now), encoding="utf-8")
    tmp.replace(ALERTS_PAGE)


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
        url = ALERTS_PAGE.as_uri() if target == ALERTS else target
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
    target = SCREENS.get(machine_name())
    if target is None:
        print(f"no screen set for {machine_name()}")
        return 0
    if target == ALERTS:
        write_alerts()
    keep_open(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
