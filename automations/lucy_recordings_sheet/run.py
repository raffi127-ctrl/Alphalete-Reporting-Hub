"""LUCY 2nd-round recordings sheet - Raf's ask (Slack, 2026-11-06):
"How many LUCY recordings submitted, % of LUCY recordings submitted vs
interviews done for the month, reps AVG score for the month ... a spreadsheet
I have access to so we can see what owners are submitting and their AVG".

ONE Google Sheet, a Month dropdown on top, two tabs:
  Por dueño : Dueño | Grabaciones | 2nd rounds hechas | % grabadas | Nota promedio
  Por rep   : Rep | Dueño | Grabaciones | Nota promedio
The visible tabs are FORMULAS over hidden 'calc' tabs this script rewrites, so
the dropdown works without a re-run.

SOURCES
  Recordings + scores + rep -> owner: the 2nd-round audit bot on Lucy 1
    (~/2nd-rd-audits/.runtime: completions.jsonl, reps.json, owners.json,
    reports/*.md "Overall X/10"). Read through bot_export.py in the bot's own
    venv, so the counts match Raf's existing scorecard. The owner is the one
    the rep confirmed to Lucy before getting a score. Rejected uploads (not an
    interview) don't count.
  2nd rounds done: the '2nd round retention' sheet (second_round_retention,
    hourly on Lucy 1) - ApplicantStream > Retention - Details (new), column
    "Second Interviews Showed Up", summed per office per month. No extra
    ApplicantStream login. That sheet starts 2026-10-25, so October's count
    is partial and shows blank.

SCHEDULE: 11:00 PM CT nightly on Lucy 1 (the quietest hour; needs the bot's
files, so it stays on Lucy 1).

    python -m automations.lucy_recordings_sheet.run --dry-run
    python -m automations.lucy_recordings_sheet.run --dry-run --from-json export.json
    python -m automations.lucy_recordings_sheet.run --create --share a@b.com
    python -m automations.lucy_recordings_sheet.run            # nightly write
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
BOT_ROOT = Path(os.environ.get("AUDIT_BOT_ROOT", str(Path.home() / "2nd-rd-audits")))
BOT_RUNTIME = BOT_ROOT / ".runtime"

# SANDBOX until Eve says "use the real Sheet". Filled in by --create.
SSID = os.environ.get("LUCY_RECORDINGS_SSID", "")
RETENTION_SSID = "1JF1M-SYYbRnrp0dFr-IKxPiXMPdHPvGomyP6r4aSFZw"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
CT = ZoneInfo("America/Chicago")

# Retention data begins 2026-10-25 -> months before November are incomplete.
FIRST_FULL_INTERVIEW_MONTH = "2026-11"

TAB_OWNER, TAB_REP = "Por dueño", "Por rep"
CALC_OWNER, CALC_REP, MONTHS = "calc dueños", "calc reps", "meses"
NO_OWNER = "(sin dueño confirmado)"
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def log(m):
    print("%s  %s" % (dt.datetime.now(CT).strftime("%H:%M:%S"), m), flush=True)


def month_label(key: str) -> str:
    y, m = key.split("-")
    return "%s %s" % (MONTH_NAMES[int(m) - 1], y)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


# ---------- sources ----------

def load_bot_export(from_json: str | None) -> dict:
    if from_json:
        return json.loads(Path(from_json).read_text(encoding="utf-8"))
    py = BOT_RUNTIME / "venv" / "bin" / "python"
    if not py.exists():
        py = BOT_RUNTIME / "venv" / "Scripts" / "python.exe"
    if not py.exists():
        raise SystemExit("audit bot venv not found under %s - this runs on Lucy 1" % BOT_RUNTIME)
    r = subprocess.run([str(py), str(HERE / "bot_export.py")], cwd=str(BOT_RUNTIME),
                       capture_output=True, text=True, encoding="utf-8", timeout=900)
    if r.returncode != 0:
        raise SystemExit("bot_export failed:\n" + (r.stderr or r.stdout)[-3000:])
    # The bot's modules may print; the JSON is the last line.
    return json.loads(r.stdout.strip().splitlines()[-1])


def _session():
    from google.auth.transport.requests import AuthorizedSession
    from automations.first_round_scorecards.drive_auth import load_credentials
    return AuthorizedSession(load_credentials())


def load_interviews(S) -> tuple[dict, dict]:
    """({(month, office_id): showed}, {office_id: owner name}) from the
    retention sheet's Datos tab."""
    r = S.get("%s/%s/values/Datos!A2:I100000" % (SHEETS, RETENTION_SSID))
    r.raise_for_status()
    done, owner_of = defaultdict(int), {}
    for row in r.json().get("values", []):
        if len(row) < 8:
            continue
        fecha, oid, owner, showed = row[1], row[3], row[4], row[7]
        try:
            n = int(float(showed or 0))
        except ValueError:
            continue
        done[(fecha[:7], oid)] += n
        owner_of[oid] = owner
    return dict(done), owner_of


def _alias_canon():
    """name -> canonical, via the ICD Aliases sheet (best effort)."""
    try:
        from automations.focus_office_att.aliases import alias_to_canonical, load_aliases
        raw = load_aliases()
        return lambda n: norm(alias_to_canonical(n, raw) or n)
    except Exception as e:  # noqa: BLE001
        log("ICD Aliases not loaded (%s) - plain name match only" % e)
        return norm


OFFICE_MAPPING = HERE.parent / "recruiting_report" / "office-mapping.json"


def _confirmed_offices() -> list:
    try:
        return json.loads(OFFICE_MAPPING.read_text(encoding="utf-8")).get("confirmed", [])
    except Exception as e:  # noqa: BLE001
        log("office-mapping.json not read (%s)" % e)
        return []


def map_owners_to_offices(owners: list, owner_of: dict) -> dict:
    """bot owner id -> [AppStream office ids].

    1. office-mapping.json 'confirmed' (the Focus Report's owner -> office list).
       AppStream's own owner name is NOT trusted first: it lists Raf as owner
       of test funnels and other ICDs' offices (24153 'Omars funnel', 24279
       'Hasans funnel', ...), which would pile their 2nd rounds onto Raf.
    2. Only for an owner not in that file: AppStream owner name (plain, bot
       alias, ICD Aliases sheet), skipping offices the file gives to someone.
    """
    canon = _alias_canon()
    mapped = defaultdict(set)
    claimed = set()
    for e in _confirmed_offices():
        oid = str(e.get("office_id") or "").strip()
        if not oid:
            continue
        claimed.add(oid)
        for n in (e.get("sheet_tab"), e.get("as_owner")):
            if n:
                mapped[norm(n)].add(oid)
                mapped[canon(n)].add(oid)
    by_name = defaultdict(set)
    for oid, name in owner_of.items():
        if oid in claimed:
            continue
        by_name[norm(name)].add(oid)
        by_name[canon(name)].add(oid)
    out = {}
    for o in owners:
        keys = {norm(o.get("name", "")), canon(o.get("name", ""))}
        for a in o.get("aliases") or []:
            keys |= {norm(a), canon(a)}
        keys.discard("")
        hits = set().union(*(mapped.get(k, set()) for k in keys))
        if not hits:
            hits = set().union(*(by_name.get(k, set()) for k in keys))
        out[o["id"]] = sorted(hits)
    return out


# ---------- build ----------

def build(export: dict, done: dict, owner_of: dict):
    owners = {o["id"]: o.get("name", o["id"]) for o in export["owners"]}
    reps, names = export["reps"], export["names"]
    offices = map_owners_to_offices(export["owners"], owner_of)

    own = defaultdict(lambda: {"n": 0, "scores": []})    # (month, owner name)
    rep = defaultdict(lambda: {"n": 0, "scores": []})    # (month, uid)
    months = set()
    for r in export["records"]:
        ts = r.get("ts") or ""
        if len(ts) < 7:
            continue
        mk = ts[:7]
        months.add(mk)
        uid = r.get("uid") or ""
        oid = (reps.get(uid) or {}).get("owner_id") if uid else None
        oname = owners.get(oid, NO_OWNER) if oid else NO_OWNER
        for b in (own[(mk, oname)], rep[(mk, uid or "?")]):
            b["n"] += 1
            if r.get("score") is not None:
                b["scores"].append(float(r["score"]))

    # Owners in the bot roster with interviews but no recordings still show (0).
    for mk in months:
        for oid, oname in owners.items():
            if any(done.get((mk, x)) for x in offices.get(oid, [])):
                own[(mk, oname)]  # touch -> row with 0 recordings

    name_to_oid = {v: k for k, v in owners.items()}
    owner_rows = []
    for (mk, oname), b in own.items():
        oid = name_to_oid.get(oname)
        ivs = None
        if oid and offices.get(oid) and mk >= FIRST_FULL_INTERVIEW_MONTH:
            ivs = sum(done.get((mk, x), 0) for x in offices[oid])
        pct = (b["n"] / ivs) if ivs else None
        avg = round(sum(b["scores"]) / len(b["scores"]), 1) if b["scores"] else None
        owner_rows.append([month_label(mk), oname, b["n"],
                           "" if ivs is None else ivs,
                           "" if pct is None else round(pct, 4),
                           "" if avg is None else avg])
    rep_rows = []
    for (mk, uid), b in rep.items():
        oid = (reps.get(uid) or {}).get("owner_id")
        avg = round(sum(b["scores"]) / len(b["scores"]), 1) if b["scores"] else None
        rep_rows.append([month_label(mk), names.get(uid) or "(rep sin nombre)",
                         owners.get(oid, NO_OWNER) if oid else NO_OWNER, b["n"],
                         "" if avg is None else avg])
    owner_rows.sort(key=lambda x: (x[0], -x[2], x[1]))
    rep_rows.sort(key=lambda x: (x[0], -x[3], x[1]))
    month_list = [month_label(m) for m in sorted(months, reverse=True)]
    unmatched = sorted(owners[o] for o, offs in offices.items() if not offs)
    return owner_rows, rep_rows, month_list, unmatched


# ---------- sheet ----------

def _tab_ids(S, ssid) -> dict:
    r = S.get("%s/%s" % (SHEETS, ssid), params={"fields": "sheets.properties"})
    r.raise_for_status()
    return {s["properties"]["title"]: s["properties"]["sheetId"] for s in r.json()["sheets"]}


def _q(tab):
    return "'%s'" % tab


def create_sheet(S, share: list) -> str:
    body = {"properties": {"title": "LUCY 2nd Round Recordings (TEST)"},
            "sheets": [{"properties": {"title": t, "hidden": t in (CALC_OWNER, CALC_REP, MONTHS)}}
                       for t in (TAB_OWNER, TAB_REP, CALC_OWNER, CALC_REP, MONTHS)]}
    r = S.post(SHEETS, json=body)
    r.raise_for_status()
    ssid = r.json()["spreadsheetId"]
    ids = _tab_ids(S, ssid)
    this_month = month_label(dt.datetime.now(CT).strftime("%Y-%m"))
    pct_col = {"startColumnIndex": 3, "endColumnIndex": 4}
    reqs = []
    layouts = {
        TAB_OWNER: (["Dueño", "Grabaciones", "2nd rounds hechas", "% grabadas", "Nota promedio"],
                    "=IFERROR(SORT(FILTER(%s!B2:F, %s!A2:A=$B$1), 2, FALSE), \"Sin datos para este mes\")"
                    % (_q(CALC_OWNER), _q(CALC_OWNER)), 4),
        TAB_REP: (["Rep", "Dueño", "Grabaciones", "Nota promedio"],
                  "=IFERROR(SORT(FILTER(%s!B2:E, %s!A2:A=$B$1), 3, FALSE), \"Sin datos para este mes\")"
                  % (_q(CALC_REP), _q(CALC_REP)), 3),
    }
    vals = []
    for tab, (hdr, formula, score_col) in layouts.items():
        vals.append({"range": "%s!A1:B1" % _q(tab), "values": [["Mes:", this_month]]})
        vals.append({"range": "%s!A4" % _q(tab), "values": [hdr]})
        vals.append({"range": "%s!A5" % _q(tab), "values": [[formula]]})
        sid = ids[tab]
        reqs += [
            {"setDataValidation": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 1, "endColumnIndex": 2},
                "rule": {"condition": {"type": "ONE_OF_RANGE",
                                       "values": [{"userEnteredValue": "=%s!A1:A" % _q(MONTHS)}]},
                         "showCustomUi": True, "strict": True}}},
            {"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": 0, "endColumnIndex": 2},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 12}}},
                "fields": "userEnteredFormat.textFormat"}},
            {"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 3, "endRowIndex": 4,
                          "startColumnIndex": 0, "endColumnIndex": len(hdr)},
                "cell": {"userEnteredFormat": {
                    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                    "horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat(textFormat,backgroundColor,horizontalAlignment)"}},
            {"updateSheetProperties": {"properties": {"sheetId": sid,
                                                      "gridProperties": {"frozenRowCount": 4}},
                                       "fields": "gridProperties.frozenRowCount"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 2},
                "properties": {"pixelSize": 220}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 2, "endIndex": len(hdr)},
                "properties": {"pixelSize": 140}, "fields": "pixelSize"}},
            {"repeatCell": {
                "range": {"sheetId": sid, "startRowIndex": 4, "endRowIndex": 400,
                          "startColumnIndex": 1 if tab == TAB_OWNER else 2,
                          "endColumnIndex": len(hdr)},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.horizontalAlignment"}},
            {"repeatCell": {
                "range": dict({"sheetId": sid, "startRowIndex": 4, "endRowIndex": 400},
                              startColumnIndex=score_col, endColumnIndex=score_col + 1),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.0"}}},
                "fields": "userEnteredFormat.numberFormat"}},
        ]
        # Score colors = the live scorecard's cuts: 8+ green, 6-8 yellow, under 6 red.
        rng = {"sheetId": sid, "startRowIndex": 4, "endRowIndex": 400,
               "startColumnIndex": score_col, "endColumnIndex": score_col + 1}
        for cond, val, color in (("NUMBER_GREATER_THAN_EQ", "8", (0.72, 0.88, 0.72)),
                                 ("NUMBER_BETWEEN", None, (1, 0.9, 0.6)),
                                 ("NUMBER_LESS", "6", (0.96, 0.7, 0.7))):
            values = ([{"userEnteredValue": "6"}, {"userEnteredValue": "7.99"}]
                      if val is None else [{"userEnteredValue": val}])
            reqs.append({"addConditionalFormatRule": {"rule": {
                "ranges": [rng],
                "booleanRule": {"condition": {"type": cond, "values": values},
                                "format": {"backgroundColor": dict(zip(("red", "green", "blue"), color))}}}}})
    reqs.append({"repeatCell": {
        "range": dict({"sheetId": ids[TAB_OWNER], "startRowIndex": 4, "endRowIndex": 400}, **pct_col),
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
        "fields": "userEnteredFormat.numberFormat"}})
    S.post("%s/%s/values:batchUpdate" % (SHEETS, ssid),
           json={"valueInputOption": "USER_ENTERED", "data": vals}).raise_for_status()
    S.post("%s/%s:batchUpdate" % (SHEETS, ssid), json={"requests": reqs}).raise_for_status()
    for email in share:
        S.post("https://www.googleapis.com/drive/v3/files/%s/permissions" % ssid,
               params={"sendNotificationEmail": "false"},
               json={"type": "user", "role": "writer", "emailAddress": email}).raise_for_status()
    log("created https://docs.google.com/spreadsheets/d/%s" % ssid)
    return ssid


def write(S, ssid, owner_rows, rep_rows, month_list):
    stamp = dt.datetime.now(CT).strftime("%b %d, %Y %I:%M %p CT")
    for tab in (CALC_OWNER, CALC_REP, MONTHS):
        S.post("%s/%s/values/%s:clear" % (SHEETS, ssid, _q(tab))).raise_for_status()
    data = [
        {"range": "%s!A1" % _q(CALC_OWNER),
         "values": [["Mes", "Dueño", "Grabaciones", "2nd rounds hechas", "% grabadas", "Nota"]] + owner_rows},
        {"range": "%s!A1" % _q(CALC_REP),
         "values": [["Mes", "Rep", "Dueño", "Grabaciones", "Nota"]] + rep_rows},
        {"range": "%s!A1" % _q(MONTHS), "values": [[m] for m in month_list]},
    ]
    note = ("Actualizado: %s · Grabaciones y notas: LUCY 2nd round audit · "
            "2nd rounds hechas: ApplicantStream (Second Interviews Showed Up)" % stamp)
    for tab in (TAB_OWNER, TAB_REP):
        data.append({"range": "%s!A2" % _q(tab), "values": [[note]]})
    S.post("%s/%s/values:batchUpdate" % (SHEETS, ssid),
           json={"valueInputOption": "RAW", "data": data}).raise_for_status()
    log("wrote %d owner row(s), %d rep row(s), %d month(s)"
        % (len(owner_rows), len(rep_rows), len(month_list)))


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="read + print, write nothing")
    ap.add_argument("--from-json", help="use a saved bot_export.py output instead of the bot")
    ap.add_argument("--create", action="store_true", help="make a new sheet first")
    ap.add_argument("--share", action="append", default=[], help="email to share a new sheet with")
    ap.add_argument("--sheet", default=SSID, help="sheet id to write")
    a = ap.parse_args(argv)

    export = load_bot_export(a.from_json)
    log("bot: %d recording(s), %d rep(s), %d owner(s)"
        % (len(export["records"]), len(export["reps"]), len(export["owners"])))
    S = _session()
    done, owner_of = load_interviews(S)
    log("retention sheet: %d office(s)" % len(owner_of))
    owner_rows, rep_rows, month_list, unmatched = build(export, done, owner_of)
    if unmatched:
        log("owners with NO AppStream office match (2nd rounds blank): " + ", ".join(unmatched))
    no_uid = sum(1 for r in export["records"] if not r.get("uid"))
    if no_uid:
        log("%d recording(s) with no known uploader -> '%s'" % (no_uid, NO_OWNER))

    if a.dry_run:
        cur = month_list[0] if month_list else ""
        log("--- %s, por dueño ---" % cur)
        for r in [x for x in owner_rows if x[0] == cur]:
            print("  %-32s grab=%-4s hechas=%-5s pct=%-7s nota=%s" % tuple(r[1:]))
        log("--- %s, por rep (top 15) ---" % cur)
        for r in [x for x in rep_rows if x[0] == cur][:15]:
            print("  %-28s %-28s grab=%-4s nota=%s" % tuple(r[1:]))
        return 0

    ssid = a.sheet
    if a.create:
        ssid = create_sheet(S, a.share)
    if not ssid:
        raise SystemExit("no sheet id - run with --create once, then set SSID")
    write(S, ssid, owner_rows, rep_rows, month_list)
    return 0


if __name__ == "__main__":
    sys.exit(main())
