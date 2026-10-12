"""New 1st round script in Slack -> the audits grade on it, nobody has to tell us.

Camila keeps each office's script in a "1st ROUNDS SCRIPT" bookmark folder at
the top of the office's recruiting channel (office_post.CHANNELS). Camila,
2026-10-12: "si un script cambia, yo lo cambio en el slack y la IA va a tomar
el script nuevo?" -- Eve: yes, make it take it on its own.

Once a day, right before the 6 PM grading (run.py), this reads every office
channel's bookmarks. A script file it hasn't seen there yet is read by the
model, which writes that office's grading (the script lines, what each
scorecard item means for it, what it leaves for the 2nd round) into
output/first_round_scorecards/script_overrides.json -- grade.py loads it over
the hand-written OFFICES/FORMATS. Eve + Camila get a group DM saying what
changed. Nothing here can stop the grading: any failure is printed and
DM'd, and the office keeps its old script.

The first time a channel is read, its current file is only remembered (the
code already grades on it). Needs bookmarks:read + files:read on Lucy's token.

    python -m automations.first_round_scorecards.script_watch --list
        # what Lucy sees in each channel (bookmarks + the script picked)
    python -m automations.first_round_scorecards.script_watch --office "Jairo Ruiz" --file x.pdf
        # dry-run: what the model makes of a script file, nothing saved
    python -m automations.first_round_scorecards.script_watch --check
        # the daily pass, by hand (posts the DM, saves the override)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from automations.first_round_scorecards import grade

OUT_DIR = Path(__file__).resolve().parents[2] / "output" / "first_round_scorecards"
LEDGER = OUT_DIR / "script_watch.json"
SCRIPTS_DIR = OUT_DIR.parent / "1st-round-scripts"
TELL = ("U088E2KJEV8",       # Eve (Evelyn)
        "U07FWSYP3NV")       # Camila Hornos Kraschinsky
FOLDER = re.compile(r"script", re.I)
FILE_ID = re.compile(r"\b(F[A-Z0-9]{8,})\b")
READABLE = {"pdf", "docx", "txt", "text", "png", "jpg", "jpeg", "gif", "webp"}


# ---------------------------------------------------------------- Slack side

def channels() -> Dict[str, str]:
    """{channel id: the office's OFFICES key} -- one per channel (Raf's three
    funnels share one)."""
    from automations.first_round_scorecards import office_post
    out: Dict[str, str] = {}
    for owner, ch in office_post.CHANNELS.items():
        office = grade.office_for(owner)
        if ch and office and ch not in out:
            out[ch] = office
    return out


def _bookmarks(client, channel: str) -> List[Dict]:
    return client.api_call("bookmarks.list", params={"channel_id": channel}).get("bookmarks") or []


def _file_id(b: Dict) -> str:
    ent = str(b.get("entity_id") or "")
    if ent.startswith("F"):
        return ent
    m = FILE_ID.search(str(b.get("link") or ""))
    return m.group(1) if m else ""


def pick(bookmarks: List[Dict]) -> Optional[Dict]:
    """The bookmark that is this channel's script now: the newest file inside
    a folder named like "1st ROUNDS SCRIPT", or a file bookmark whose own
    title says script. None = no script file in the bookmarks."""
    folders = {b.get("id") for b in bookmarks
               if FOLDER.search(b.get("title") or "") and not _file_id(b)}
    files = [b for b in bookmarks if _file_id(b)
             and (b.get("parent_id") in folders or FOLDER.search(b.get("title") or ""))]
    if not files:
        return None
    return max(files, key=lambda b: (b.get("date_updated") or b.get("date_created") or 0))


def _download(client, file_id: str) -> tuple:
    """(file info, bytes) for a Slack file, read with Lucy's token."""
    import requests
    info = client.files_info(file=file_id)["file"]
    url = info.get("url_private_download") or info.get("url_private")
    resp = requests.get(url, headers={"Authorization": f"Bearer {client.token}"}, timeout=60)
    resp.raise_for_status()
    if resp.headers.get("content-type", "").startswith("text/html"):
        raise RuntimeError("Slack sent a login page, not the file (files:read missing?)")
    return info, resp.content


# ---------------------------------------------------------------- the model

def _docx_text(data: bytes) -> str:
    """Plain text of a .docx (stdlib: the runners have no python-docx)."""
    with zipfile.ZipFile(BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml).replace("&amp;", "&").replace("&quot;", '"') \
        .replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">")


def content_block(name: str, kind: str, data: bytes) -> Dict:
    """The script file as a message block the model can read."""
    kind = (kind or Path(name).suffix.lstrip(".")).lower()
    if kind == "pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                               "data": base64.b64encode(data).decode()}}
    if kind in ("png", "jpg", "jpeg", "gif", "webp"):
        mt = "image/jpeg" if kind in ("jpg", "jpeg") else f"image/{kind}"
        return {"type": "image", "source": {"type": "base64", "media_type": mt,
                                            "data": base64.b64encode(data).decode()}}
    text = _docx_text(data) if kind == "docx" else data.decode("utf-8", "replace")
    return {"type": "text", "text": f"THE NEW SCRIPT ({name})\n{text}"}


ITEM_KEYS = [k for k, _, _ in grade.ITEMS]
PORTION_KEYS = [k for k, _ in grade.PORTIONS]
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["is_first_round_script", "not_script_reason", "changes", "lines", "keys",
                 "not_in_first_round", "rules", "mon_fri_ok"],
    "properties": {
        "is_first_round_script": {"type": "boolean"},
        "not_script_reason": {"type": "string"},
        "changes": {"type": "array", "items": {"type": "string"}},
        "lines": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["portion", "text"],
            "properties": {"portion": {"type": "string", "enum": PORTION_KEYS},
                           "text": {"type": "string"}}}},
        "keys": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["portion", "key"],
            "properties": {"portion": {"type": "string", "enum": PORTION_KEYS},
                           "key": {"type": "string"}}}},
        "not_in_first_round": {"type": "array", "items": {"type": "string", "enum": ITEM_KEYS}},
        "rules": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["item", "rule"],
            "properties": {"item": {"type": "string", "enum": ITEM_KEYS},
                           "rule": {"type": "string"}}}},
        "mon_fri_ok": {"type": "boolean"},
    },
}


def prompt(office: str) -> str:
    """What the model gets besides the file: the scorecard, the script
    portions, and how this office is graded today (its old script)."""
    now = grade.build(office)
    items = "\n".join(f"- {k} ({'red flag: YES is bad' if kind == 'red' else 'must-do'}): {q}"
                      for k, q, kind in grade.ITEMS)
    portions = "\n".join(f"- {k}: \"{t}\"" for k, t in grade.PORTIONS)
    return f"""You keep the grading of 1st round job interviews (Zoom group interviews for a door-to-door sales company) in line with each office's interview script. The office "{office}" just put up a new version of its 1st round script (attached). Read it and write how interviews for this office must be graded from now on.

THE SCORECARD (11 items, the same for every office -- never add or rename one)
{items}

THE SCRIPT PORTIONS an interviewer can skip (the standard script's wording)
{portions}

HOW THIS OFFICE IS GRADED TODAY (its current script and rules)
{now['script']}
{now['rules']}
Items not in this office's 1st round today: {', '.join(sorted(now['na'])) or 'none'}.

WHAT TO WRITE
- lines: each script portion THIS script has, with its line copied word for word from the new script (shorten long ones with "..." but never reword). Leave out a portion the script doesn't have (e.g. no pay in the 1st round = no pay_entry / pay_assistant / pay_executive).
- keys: for each portion in lines, the KEY pieces that make it "said" (missing one = skipped), in a few words.
- not_in_first_round: scorecard items this script leaves for the 2nd round (pay, schedule, commute...), so an interviewer is not marked down for them.
- rules: one rule for EVERY one of the 11 items, how to answer it strictly YES or NO for this script. Spell out this script's own numbers, days and hours (e.g. off_script_pay: which pay numbers are right; mon_fri: if the script itself says Monday to Friday, saying it is NOT a flag). Keep the rules that don't change as they are today.
- mon_fri_ok: true only if the script itself says Monday to Friday with no Saturdays.
- changes: plain, short English bullets for the hiring managers -- what is graded differently from today (new pay numbers, new hours, a new wrap-up, a part moved to the 2nd round...). Empty list if this file grades exactly like today (same script, maybe re-uploaded).
- If the file is not a 1st round interview script (a 2nd round script, a flyer, an empty page), set is_first_round_script to false and say what it is in not_script_reason; fill the rest with empty lists."""


def read_script(office: str, block: Dict, client=None) -> Dict:
    """The model's reading of a new script file (see SCHEMA)."""
    import anthropic
    if client is None:
        from automations.brand_audit import credentials
        client = anthropic.Anthropic(api_key=credentials.anthropic_api_key())
    body = {"output_config": {"effort": "high",
                              "format": {"type": "json_schema", "schema": SCHEMA}}}
    resp = client.messages.create(
        model=grade.MODEL, max_tokens=16000,
        messages=[{"role": "user", "content": [block, {"type": "text", "text": prompt(office)}]}],
        extra_body=body)
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"the model stopped early ({resp.stop_reason})")
    return json.loads("".join(b.text for b in resp.content if getattr(b, "type", "") == "text"))


def to_override(ans: Dict) -> Dict:
    """The model's answer -> grade.py's override shape, or ValueError when it
    isn't whole (then the office keeps its old script)."""
    lines = {}
    for x in ans["lines"]:
        if x["portion"] in lines:
            raise ValueError(f"portion {x['portion']} twice")
        if not x["text"].strip():
            raise ValueError(f"portion {x['portion']} has no line")
        lines[x["portion"]] = x["text"].strip()
    if len(lines) < 3:
        raise ValueError(f"only {len(lines)} script portions found")
    keys = {x["portion"]: x["key"].strip() for x in ans["keys"] if x["portion"] in lines}
    missing = [k for k in lines if not keys.get(k)]
    if missing:
        raise ValueError(f"no key pieces for {', '.join(missing)}")
    rules = {}
    for x in ans["rules"]:
        if x["item"] in rules:
            raise ValueError(f"rule for {x['item']} twice")
        rules[x["item"]] = x["rule"].strip()
    missing = [k for k in ITEM_KEYS if not rules.get(k)]
    if missing:
        raise ValueError(f"no rule for {', '.join(missing)}")
    return {"na": sorted(set(ans["not_in_first_round"])),
            "drop": [k for k in PORTION_KEYS if k not in lines],
            "lines": lines, "keys": keys, "rules": rules,
            "mon_fri_ok": bool(ans["mon_fri_ok"])}


# ---------------------------------------------------------------- the pass

def _load(path: Path) -> Dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(path: Path, data: Dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def _tell(client, text: str) -> None:
    dm = client.conversations_open(users=",".join(TELL))["channel"]["id"]
    client.chat_postMessage(channel=dm, text=text, unfurl_links=False)


def changed_text(office: str, name: str, changes: List[str]) -> str:
    bullets = "\n".join(f"• {c}" for c in changes)
    return (f"📄 *New 1st round script for {office}'s office* ({name})\n"
            f"From today's audits on, interviews for this office are graded on it. "
            f"What changed:\n{bullets}")


def apply(office: str, info: Dict, data: bytes, *, save: bool = True) -> Dict:
    """Read one script file; {status: changed|same|not_script|failed, text}.
    `save` writes the override + a copy of the file."""
    name = info.get("name") or info.get("title") or "script"
    try:
        ans = read_script(office, content_block(name, info.get("filetype") or "", data))
        if not ans["is_first_round_script"]:
            return {"status": "not_script", "text": (
                f"📄 A file in {office}'s script folder isn't a 1st round script ({name}): "
                f"{ans['not_script_reason']} -- the audits keep the old script.")}
        override = to_override(ans)
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "text": (
            f"⚠️ {office}'s script folder has a new file ({name}) but I couldn't read it "
            f"({type(exc).__name__}: {exc}). The audits keep the old script.")}
    if not ans["changes"]:
        return {"status": "same", "override": override, "text": ""}
    if save:
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = dt.date.today().isoformat()
        (SCRIPTS_DIR / f"{office.lower()} - script {stamp}{Path(name).suffix}").write_bytes(data)
        all_ = _load(grade.OVERRIDES)
        all_[office] = {**override, "file": name, "applied": stamp, "changes": ans["changes"]}
        _save(grade.OVERRIDES, all_)
    return {"status": "changed", "override": override,
            "text": changed_text(office, name, ans["changes"])}


def check(*, client=None, today: Optional[dt.date] = None) -> int:
    """The daily pass. Returns how many offices got a new script."""
    from automations.shared import slack_metrics_post as smp
    client = client or smp._client()
    today = today or dt.date.today()
    seen = _load(LEDGER)
    if seen.get("_checked") == today.isoformat():
        return 0
    n = 0
    for ch, office in channels().items():
        try:
            b = pick(_bookmarks(client, ch))
        except Exception as exc:  # noqa: BLE001
            print(f"script watch: {office}: bookmarks not read ({type(exc).__name__}: {exc})")
            continue
        if not b:
            continue
        fid = _file_id(b)
        stamp = str(b.get("date_updated") or b.get("date_created") or "")
        was = seen.get(ch)
        if was and was.get("file") == fid and was.get("stamp") == stamp:
            continue
        seen[ch] = {"file": fid, "stamp": stamp, "office": office, "title": b.get("title")}
        if not was:              # first look: the code already grades on this one
            print(f"script watch: {office}: remembered {b.get('title')!r}")
            continue
        try:
            info, data = _download(client, fid)
        except Exception as exc:  # noqa: BLE001
            del seen[ch]         # retry tomorrow
            print(f"script watch: {office}: download failed ({type(exc).__name__}: {exc})")
            continue
        res = apply(office, info, data)
        print(f"script watch: {office}: {res['status']}")
        if res["status"] == "changed":
            n += 1
        if res["status"] == "failed":
            del seen[ch]
        if res["text"]:
            try:
                _tell(client, res["text"])
            except Exception as exc:  # noqa: BLE001
                print(f"script watch: DM failed ({type(exc).__name__}: {exc})")
    seen["_checked"] = today.isoformat()
    _save(LEDGER, seen)
    if n:
        grade.load_overrides()
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="first_round_scorecards.script_watch")
    ap.add_argument("--list", action="store_true", help="what Lucy sees in each channel")
    ap.add_argument("--check", action="store_true", help="the daily pass (DMs + saves)")
    ap.add_argument("--office", help="with --file: dry-run one script file")
    ap.add_argument("--file", help="a local script file (pdf, docx, txt, image)")
    args = ap.parse_args(argv)
    if args.file:
        office = grade.office_for(args.office or "") or args.office or ""
        p = Path(args.file)
        res = apply(office, {"name": p.name, "filetype": p.suffix.lstrip(".")},
                    p.read_bytes(), save=False)
        print(res["status"])
        print(res["text"])
        print(json.dumps(res.get("override"), indent=1, ensure_ascii=False))
        return 0 if res["status"] in ("changed", "same") else 1
    if args.check:
        print(f"{check()} office(s) with a new script")
        return 0
    from automations.shared import slack_metrics_post as smp
    client = smp._client()
    for ch, office in channels().items():
        try:
            bms = _bookmarks(client, ch)
        except Exception as exc:  # noqa: BLE001
            print(f"{office} ({ch}): FAILED {type(exc).__name__}: {exc}")
            continue
        b = pick(bms)
        print(f"{office} ({ch}): script = {b.get('title') if b else 'NONE FOUND'}")
        for x in bms:
            print(f"    {x.get('id')} parent={x.get('parent_id')} type={x.get('type')} "
                  f"file={_file_id(x) or '-'} {x.get('title')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
