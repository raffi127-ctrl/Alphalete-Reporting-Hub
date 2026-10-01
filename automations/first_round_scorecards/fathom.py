"""Read the day's 1st round recordings from Fathom.

ONE API KEY PER RECORDING ACCOUNT. A Fathom key only sees the meetings of the
account it belongs to, so every Zoom account that records 1st rounds needs its
key in the creds file (Rafael, 2026-09-29: the main funnel will start
recording too, one interviewer per slot).

Creds file -- gitignored, never in the repo (the repo is public):
    ~/.config/recruiting-report/fathom-creds.json   (pushed to the mini with
        `set_cred_file fathom-creds <json>`)
    <repo>/fathom-creds.json                        (Eve's Windows copy)
shape:
    {"fathom_api_key": "<key>"}                       one account, or
    {"fathom_api_keys": ["<key>", "<key>", ...]}      several

Every other account's key is read from Camila's ZOOMS INFO tab (zooms.py), so
a Zoom she adds there is picked up with no creds push (Camila 2026-10-01, ~16
accounts; live in the channel the same day, Eve). SHEET_KEYS_LIVE = True
puts them back to dry-runs / Eve's DM only.
"""
from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
API = "https://api.fathom.ai/external/v1/meetings"
REPO_ROOT = Path(__file__).resolve().parents[2]
SHEET_KEYS_LIVE = True
CRED_PATHS = (Path.home() / ".config" / "recruiting-report" / "fathom-creds.json",
              REPO_ROOT / "fathom-creds.json")


def api_keys(*, with_sheet: bool = SHEET_KEYS_LIVE) -> List[str]:
    keys = _file_keys()
    if with_sheet:
        from automations.first_round_scorecards import zooms
        keys += [z["key"] for z in zooms.accounts().values() if z.get("key")]
    keys = list(dict.fromkeys(keys))
    if not keys:
        raise SystemExit("no Fathom key on this machine -- push it with "
                         "`set_cred_file fathom-creds {\"fathom_api_key\": \"...\"}`")
    return keys


def _file_keys() -> List[str]:
    for path in CRED_PATHS:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            keys = list(data.get("fathom_api_keys") or [])
            if data.get("fathom_api_key"):
                keys.insert(0, data["fathom_api_key"])
            keys = [k.strip() for k in keys if str(k).strip()]
            if keys:
                return keys
    return []


def _get(key: str, params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Api-Key": key})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except urllib.error.URLError:
            if attempt == 2:
                raise
        time.sleep(5 * (attempt + 1))
    return {}


def _utc(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def meetings_on(day: dt.date, *, with_sheet: bool = SHEET_KEYS_LIVE) -> List[Dict]:
    """Every recording that STARTED on `day` (Central), across every key,
    with its transcript, oldest first."""
    start = dt.datetime.combine(day, dt.time(0), CT).astimezone(dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    seen, out = set(), []
    for key in api_keys(with_sheet=with_sheet):
        cursor = None
        while True:
            params = {"created_after": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      # a recording is saved after it ends: leave room for one
                      # that ran late into the night
                      "created_before": (end + dt.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "include_transcript": "true"}
            if cursor:
                params["cursor"] = cursor
            try:
                page = _get(key, params)
            except urllib.error.HTTPError as exc:
                if exc.code != 401:
                    raise
                # one mistyped key in the sheet (ZOOM 6, 10/1) must not sink
                # every other account's interviews
                print(f"Fathom key ...{key[-6:]} rejected (401) - its account is skipped")
                break
            for m in page.get("items") or []:
                began = m.get("recording_start_time") or m.get("created_at")
                if not began or m.get("recording_id") in seen:
                    continue
                if not (start <= _utc(began) < end):
                    continue
                seen.add(m.get("recording_id"))
                out.append(m)
            cursor = page.get("next_cursor")
            if not cursor:
                break
    out.sort(key=lambda m: m.get("recording_start_time") or "")
    return out


def start_ct(m: Dict) -> dt.datetime:
    return _utc(m.get("recording_start_time") or m["created_at"]).astimezone(CT)


def minutes(m: Dict) -> int:
    try:
        return round((_utc(m["recording_end_time"]) - _utc(m["recording_start_time"])).total_seconds() / 60)
    except Exception:  # noqa: BLE001
        return 0


def transcript_text(m: Dict) -> str:
    """'[00:12:29] Speaker: text' per line."""
    lines = []
    for row in m.get("transcript") or []:
        who = (row.get("speaker") or {}).get("display_name") or "Unknown"
        lines.append(f"[{row.get('timestamp', '')}] {who}: {row.get('text', '').strip()}")
    return "\n".join(lines)
