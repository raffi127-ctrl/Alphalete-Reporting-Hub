"""LUCY 2nd-round recordings sheet - Raf's ask (Slack, 2026-11-06):
"How many LUCY recordings submitted, % of LUCY recordings submitted vs
interviews done for the month, reps AVG score for the month ... a spreadsheet
I have access to so we can see what owners are submitting and their AVG".

ONE Google Sheet, a Month dropdown on top, two tabs:
  By Owner : Owner | Recordings | 2nd Rounds Done | % Recorded | Avg Score
  By Rep   : Rep | Owner | Recordings | Avg Score
plus month-total cards on top of each tab. All labels in English (Eve 11/6).
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

# OFFICIAL "LUCY 2nd Round Recordings" - Drive: Alphalete Marketing > ARS >
# AUDITS (Eve moved it there 2026-11-06; owner alphaletereporting).
SSID = os.environ.get("LUCY_RECORDINGS_SSID", "1esRRAWpHo_Drn9vb5rjiC7sNL0pBjSgixw1HGOSlB_Q")
RETENTION_SSID = "1JF1M-SYYbRnrp0dFr-IKxPiXMPdHPvGomyP6r4aSFZw"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
CT = ZoneInfo("America/Chicago")

# Retention data begins 2026-10-25 -> months before November are incomplete.
FIRST_FULL_INTERVIEW_MONTH = "2026-11"

TAB_OWNER, TAB_REP = "By Owner", "By Rep"
CALC_OWNER, CALC_REP, CALC_TOTALS, MONTHS = "calc owners", "calc reps", "calc totals", "months"
HIDDEN_TABS = (CALC_OWNER, CALC_REP, CALC_TOTALS, MONTHS)
# First (Spanish) sandbox layout -> renamed in place by --restyle.
OLD_TAB_NAMES = {"Por dueño": TAB_OWNER, "Por rep": TAB_REP, "calc dueños": CALC_OWNER,
                 "meses": MONTHS}
TITLE = "LUCY · 2nd Round Recordings"
NO_OWNER = "(no owner confirmed)"
NO_NAME = "(no name)"
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
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    from automations.first_round_scorecards.drive_auth import load_credentials
    S = AuthorizedSession(load_credentials())
    # The Sheets read quota (60/min) is shared by every report on this Google
    # account; the first fills died on a 429 (2026-11-06). Wait and retry.
    retry = Retry(total=6, backoff_factor=15, status_forcelist=(429, 500, 502, 503),
                  allowed_methods=None, respect_retry_after_header=True)
    S.mount("https://", HTTPAdapter(max_retries=retry))
    return S


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


# ---------- guessing an owner for reps who never confirmed one ----------
#
# Eve 2026-11-06: reps who never told Lucy their ICD get an owner looked up
# from lists we already have, marked "(auto)" so it's clear Lucy guessed it.
#   1. owner_rep_audit/review_people.json - Slack id -> owner's recruiting
#      channel (matched by Slack id, so name spelling doesn't matter).
#   2. AUTOMATION MASTER 'Knocks Daily' - rep name -> the office they knock
#      for (most recent day wins). Exact full-name match only.
# Nothing found -> stays "(no owner confirmed)".

REVIEW_PEOPLE = HERE.parent / "owner_rep_audit" / "review_people.json"
KNOCKS_SSID, KNOCKS_TAB = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw", "Knocks Daily"
AUTO = " (auto)"


def _owner_index(owner_names: list) -> dict:
    """normalized name / channel slug -> bot owner name."""
    canon = _alias_canon()
    idx = {}
    for n in owner_names:
        for k in {norm(n), canon(n)}:
            if k:
                idx[k] = n
                idx[k.replace(" ", "-")] = n
                idx[k.replace(" ", "-") + "s"] = n      # "maxamad-adens"
    return idx


def _owner_of_label(label: str, idx: dict) -> str:
    # "Carlos Hidalgo - Box" / "Next Horizon Group, Inc. Nii Tagoe"
    base = re.split(r"\s[—–-]\s", label or "")[0]
    for cand in (base, " ".join(norm(base).split()[-2:])):
        hit = idx.get(norm(cand)) or idx.get(norm(cand).replace(" ", "-"))
        if hit:
            return hit
    return ""


def load_guess_sources(S) -> tuple:
    """({slack id: channel slug}, [(date, office label, rep name)])."""
    slack = {}
    try:
        for p in json.loads(REVIEW_PEOPLE.read_text(encoding="utf-8")):
            chans = [c.strip() for c in str(p.get("channels") or "").split(",") if c.strip()]
            if p.get("slack_id") and len(chans) == 1:       # several channels = ambiguous
                slack[p["slack_id"]] = chans[0]
    except Exception as e:  # noqa: BLE001
        log("review_people.json not read (%s)" % e)
    knocks = []
    try:
        r = S.get("%s/%s/values/%s!A2:D200000" % (SHEETS, KNOCKS_SSID, _q(KNOCKS_TAB)))
        r.raise_for_status()
        knocks = [(x[0], x[1], x[3]) for x in r.json().get("values", []) if len(x) >= 4]
    except Exception as e:  # noqa: BLE001
        log("Knocks Daily not read (%s)" % e)
    return slack, knocks


def guess_owners(uids: list, names: dict, owner_names: list, slack: dict, knocks: list) -> dict:
    """uid -> (owner name, source) for the uids we can place."""
    idx = _owner_index(owner_names)
    by_rep = {}
    for day, office, rep_name in sorted(knocks):        # later days overwrite
        own = _owner_of_label(office, idx)
        if own and len(norm(rep_name).split()) >= 2:
            by_rep[norm(rep_name)] = own
    out = {}
    for uid in uids:
        slug = slack.get(uid)
        if slug and idx.get(slug):
            out[uid] = (idx[slug], "slack channel")
            continue
        nm = norm(names.get(uid, ""))
        if len(nm.split()) >= 2 and nm in by_rep:
            out[uid] = (by_rep[nm], "knocks")
    return out


# ---------- build ----------

def build(export: dict, done: dict, owner_of: dict, guesses: dict | None = None):
    owners = {o["id"]: o.get("name", o["id"]) for o in export["owners"]}
    reps, names = export["reps"], export["names"]
    offices = map_owners_to_offices(export["owners"], owner_of)
    name_to_oid = {v: k for k, v in owners.items()}
    guesses = guesses or {}

    def owner_for(uid):
        """(owner name, guessed?) - confirmed owner first, then the guess."""
        oid = (reps.get(uid) or {}).get("owner_id") if uid else None
        if oid:
            return owners.get(oid, NO_OWNER), False
        if uid in guesses:
            return guesses[uid][0], True
        return NO_OWNER, False

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
        oname, _guessed = owner_for(uid)
        for b in (own[(mk, oname)], rep[(mk, uid or "?")]):
            b["n"] += 1
            if r.get("score") is not None:
                b["scores"].append(float(r["score"]))

    # Owners in the bot roster with interviews but no recordings still show (0).
    for mk in months:
        for oid, oname in owners.items():
            if any(done.get((mk, x)) for x in offices.get(oid, [])):
                own[(mk, oname)]  # touch -> row with 0 recordings

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
        oname, guessed = owner_for(uid)
        avg = round(sum(b["scores"]) / len(b["scores"]), 1) if b["scores"] else None
        rep_rows.append([month_label(mk), names.get(uid) or NO_NAME,
                         oname + (AUTO if guessed else ""), b["n"],
                         "" if avg is None else avg])
    # Month totals for the cards: % = recordings of owners whose 2nd rounds we
    # know / those 2nd rounds; score = average over every scored recording.
    totals = []
    for mk in sorted(months):
        lab = month_label(mk)
        recs = [r for r in owner_rows if r[0] == lab]
        known = [r for r in recs if r[3] != ""]
        ivs = sum(r[3] for r in known)
        sc = [x for (m2, _u), b in rep.items() if m2 == mk for x in b["scores"]]
        totals.append([lab, sum(r[2] for r in recs), ivs if known else "",
                       round(sum(r[2] for r in known) / ivs, 4) if ivs else "",
                       round(sum(sc) / len(sc), 1) if sc else "",
                       sum(1 for (m2, u), b in rep.items() if m2 == mk and u != "?" and b["n"])])
    owner_rows.sort(key=lambda x: (x[0], -x[2], x[1]))
    rep_rows.sort(key=lambda x: (x[0], -x[3], x[1]))
    month_list = [month_label(m) for m in sorted(months, reverse=True)]
    unmatched = sorted(owners[o] for o, offs in offices.items() if not offs)
    return owner_rows, rep_rows, totals, month_list, unmatched


# ---------- sheet ----------

def _q(tab):
    return "'%s'" % tab


def _rgb(hexs: str) -> dict:
    h = hexs.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255,
            "blue": int(h[4:6], 16) / 255}


NAVY, HEADER_BG, CARD_BG = _rgb("1F2A44"), _rgb("2E3E61"), _rgb("EEF2FA")
BAND_BG, PICK_BG, NO_OWNER_BG = _rgb("F6F8FC"), _rgb("FFF4CC"), _rgb("F1F1F1")
WHITE, MUTED, LABEL = _rgb("FFFFFF"), _rgb("7A8294"), _rgb("5B6478")
GOOD, MID, LOW = _rgb("C8E6C9"), _rgb("FFE9A8"), _rgb("F6C1C1")

# Rows (0-based): title, month picker + note, gap, card labels, card values,
# gap, table header, data.
R_TITLE, R_PICK, R_CARD_LBL, R_CARD_VAL, R_HDR, R_DATA = 0, 1, 3, 4, 6, 7
MONTH_CELL = "$B$2"
LAST_ROW = 400

# Sheets turns a picked "November 2026" into a DATE, which never equals the
# text month in the calc tabs - so compare against the picker as text.
MONTH_EXPR = 'IF(ISNUMBER(%s), TEXT(%s, "mmmm yyyy"), %s)' % ((MONTH_CELL,) * 3)

# Per visible tab: headers, calc tab + columns, the column that says "no owner"
# (sorted last), recordings column to sort by, % column, score column, and
# the cards: (label, column in 'calc totals', number format).
LAYOUTS = {
    TAB_OWNER: {
        "hdr": ["Owner", "Recordings", "2nd Rounds Done", "% Recorded", "Avg Score"],
        "calc": CALC_OWNER, "cols": "B2:F", "owner_col": "B2:B", "sort": 2,
        "pct": 3, "score": 4, "widths": [250, 150, 150, 150, 150],
        "other": TAB_REP, "other_label": "View by Rep  →",
        "cards": [("RECORDINGS", 2, "0"), ("2ND ROUNDS DONE", 3, "0"),
                  ("% RECORDED", 4, "0%"), ("AVG SCORE", 5, "0.0")],
    },
    TAB_REP: {
        "hdr": ["Rep", "Owner", "Recordings", "Avg Score"],
        "calc": CALC_REP, "cols": "B2:E", "owner_col": "C2:C", "sort": 3,
        "pct": None, "score": 3, "widths": [230, 230, 150, 150],
        "other": TAB_OWNER, "other_label": "←  View by Owner",
        "cards": [("RECORDINGS", 2, "0"), ("REPS RECORDING", 6, "0"),
                  ("AVG SCORE", 5, "0.0")],
    },
}


def table_formula(lay: dict) -> str:
    calc = _q(lay["calc"])
    in_month = "%s!A2:A=%s" % (calc, MONTH_EXPR)
    return ('=IFERROR(SORT(FILTER(%s!%s, %s), FILTER(%s!%s, %s)="%s", TRUE, %d, FALSE), '
            '"No data for this month")'
            % (calc, lay["cols"], in_month, calc, lay["owner_col"], in_month, NO_OWNER, lay["sort"]))


def card_formula(col: int) -> str:
    return ('=LET(v, IFERROR(VLOOKUP(%s, %s!A:F, %d, FALSE), ""), IF(v="", "—", v))'
            % (MONTH_EXPR, _q(CALC_TOTALS), col))


def _sheet_meta(S, ssid) -> list:
    r = S.get("%s/%s" % (SHEETS, ssid), params={
        "fields": "sheets(properties,conditionalFormats,merges,bandedRanges)"})
    r.raise_for_status()
    return r.json()["sheets"]


def _rng(sid, r0, r1, c0, c1):
    return {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
            "startColumnIndex": c0, "endColumnIndex": c1}


def _fmt(sid, r0, r1, c0, c1, fmt: dict, fields: str):
    return {"repeatCell": {"range": _rng(sid, r0, r1, c0, c1),
                           "cell": {"userEnteredFormat": fmt}, "fields": fields}}


def _ensure_tabs(S, ssid) -> dict:
    """Rename the first Spanish tabs, add any missing tab, return title -> id."""
    reqs, have = [], {}
    for sh in _sheet_meta(S, ssid):
        p = sh["properties"]
        title = OLD_TAB_NAMES.get(p["title"], p["title"])
        if title != p["title"]:
            reqs.append({"updateSheetProperties": {
                "properties": {"sheetId": p["sheetId"], "title": title},
                "fields": "title"}})
        have[title] = p["sheetId"]
    for i, t in enumerate((TAB_OWNER, TAB_REP) + HIDDEN_TABS):
        if t not in have:
            reqs.append({"addSheet": {"properties": {"title": t, "index": i,
                                                     "hidden": t in HIDDEN_TABS}}})
    if reqs:
        S.post("%s/%s:batchUpdate" % (SHEETS, ssid), json={"requests": reqs}).raise_for_status()
    ids = {}
    for sh in _sheet_meta(S, ssid):
        ids[sh["properties"]["title"]] = sh["properties"]["sheetId"]
    return ids


def restyle(S, ssid):
    """Wipe and re-lay the two VISIBLE tabs (ours; no hand-entered data lives
    there). The calc tabs are rewritten by write() anyway."""
    ids = _ensure_tabs(S, ssid)
    wipe = []
    for sh in _sheet_meta(S, ssid):
        p = sh["properties"]
        if p["title"] not in LAYOUTS:
            continue
        sid = p["sheetId"]
        for _ in sh.get("conditionalFormats", []):
            wipe.append({"deleteConditionalFormatRule": {"sheetId": sid, "index": 0}})
        for b in sh.get("bandedRanges", []):
            wipe.append({"deleteBanding": {"bandedRangeId": b["bandedRangeId"]}})
        wipe.append({"unmergeCells": {"range": _rng(sid, 0, LAST_ROW, 0, 26)}})
        wipe.append({"updateCells": {"range": _rng(sid, 0, LAST_ROW, 0, 26),
                                     "fields": "userEnteredValue,userEnteredFormat,dataValidation"}})
        wipe.append({"updateSheetProperties": {"properties": {
            "sheetId": sid, "gridProperties": {"frozenRowCount": 0}},
            "fields": "gridProperties.frozenRowCount"}})
    S.post("%s/%s:batchUpdate" % (SHEETS, ssid), json={"requests": wipe}).raise_for_status()

    this_month = month_label(dt.datetime.now(CT).strftime("%Y-%m"))
    vals, reqs = [], []
    for tab, lay in LAYOUTS.items():
        sid, ncol = ids[tab], len(lay["hdr"])
        last = chr(ord("A") + ncol - 1)
        vals += [
            {"range": "%s!A1" % _q(tab), "values": [[TITLE]]},
            # A link to the other tab, top right - the bottom tab bar is easy to miss.
            {"range": "%s!%s1" % (_q(tab), last), "values": [[
                '=HYPERLINK("#gid=%d", "%s")' % (ids[lay["other"]], lay["other_label"])]]},
            {"range": "%s!A2:B2" % _q(tab), "values": [["Month", this_month]]},
            {"range": "%s!A4" % _q(tab), "values": [[c[0] for c in lay["cards"]]]},
            {"range": "%s!A5" % _q(tab), "values": [[card_formula(c[1]) for c in lay["cards"]]]},
            {"range": "%s!A7" % _q(tab), "values": [lay["hdr"]]},
            {"range": "%s!A8" % _q(tab), "values": [[table_formula(lay)]]},
        ]
        ncard = len(lay["cards"])
        reqs += [
            # Base: font, no gridlines, frozen through the table header.
            _fmt(sid, 0, LAST_ROW, 0, ncol,
                 {"textFormat": {"fontFamily": "Roboto", "fontSize": 10},
                  "verticalAlignment": "MIDDLE"},
                 "userEnteredFormat(textFormat,verticalAlignment)"),
            {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {
                "hideGridlines": True, "frozenRowCount": R_HDR + 1}},
                "fields": "gridProperties(hideGridlines,frozenRowCount)"}},
            # Title bar.
            {"mergeCells": {"range": _rng(sid, R_TITLE, R_TITLE + 1, 0, ncol - 1), "mergeType": "MERGE_ALL"}},
            _fmt(sid, R_TITLE, R_TITLE + 1, ncol - 1, ncol,
                 {"backgroundColor": NAVY, "horizontalAlignment": "RIGHT",
                  "padding": {"right": 14},
                  "textFormat": {"fontFamily": "Roboto", "fontSize": 10, "bold": True,
                                 "underline": True, "foregroundColor": _rgb("FFD666")}},
                 "userEnteredFormat(backgroundColor,horizontalAlignment,padding,textFormat)"),
            _fmt(sid, R_TITLE, R_TITLE + 1, 0, ncol - 1,
                 {"backgroundColor": NAVY, "horizontalAlignment": "LEFT",
                  "padding": {"left": 14},
                  "textFormat": {"fontFamily": "Montserrat", "fontSize": 16, "bold": True,
                                 "foregroundColor": WHITE}},
                 "userEnteredFormat(backgroundColor,horizontalAlignment,padding,textFormat)"),
            # Month picker: label + highlighted dropdown; note to the right.
            _fmt(sid, R_PICK, R_PICK + 1, 0, 1,
                 {"horizontalAlignment": "RIGHT",
                  "textFormat": {"fontFamily": "Roboto", "bold": True, "foregroundColor": LABEL}},
                 "userEnteredFormat(horizontalAlignment,textFormat)"),
            _fmt(sid, R_PICK, R_PICK + 1, 1, 2,
                 {"backgroundColor": PICK_BG, "horizontalAlignment": "CENTER",
                  "textFormat": {"fontFamily": "Roboto", "bold": True, "fontSize": 11,
                                 "foregroundColor": NAVY}},
                 "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"),
            {"updateBorders": {"range": _rng(sid, R_PICK, R_PICK + 1, 1, 2),
                               **{side: {"style": "SOLID_MEDIUM", "color": _rgb("E0B84C")}
                                  for side in ("top", "bottom", "left", "right")}}},
            {"setDataValidation": {"range": _rng(sid, R_PICK, R_PICK + 1, 1, 2), "rule": {
                "condition": {"type": "ONE_OF_RANGE",
                              "values": [{"userEnteredValue": "=%s!A1:A" % _q(MONTHS)}]},
                "showCustomUi": True, "strict": True}}},
            {"mergeCells": {"range": _rng(sid, R_PICK, R_PICK + 1, 2, ncol), "mergeType": "MERGE_ALL"}},
            _fmt(sid, R_PICK, R_PICK + 1, 2, ncol,
                 {"horizontalAlignment": "RIGHT", "wrapStrategy": "CLIP",
                  "textFormat": {"fontFamily": "Roboto", "fontSize": 8, "italic": True,
                                 "foregroundColor": MUTED}},
                 "userEnteredFormat(horizontalAlignment,wrapStrategy,textFormat)"),
            # Cards.
            _fmt(sid, R_CARD_LBL, R_CARD_LBL + 1, 0, ncard,
                 {"backgroundColor": CARD_BG, "horizontalAlignment": "CENTER",
                  "verticalAlignment": "BOTTOM",
                  "textFormat": {"fontFamily": "Roboto", "fontSize": 8, "bold": True,
                                 "foregroundColor": MUTED}},
                 "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)"),
            _fmt(sid, R_CARD_VAL, R_CARD_VAL + 1, 0, ncard,
                 {"backgroundColor": CARD_BG, "horizontalAlignment": "CENTER",
                  "verticalAlignment": "TOP",
                  "textFormat": {"fontFamily": "Montserrat", "fontSize": 20, "bold": True,
                                 "foregroundColor": NAVY}},
                 "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)"),
            {"updateBorders": {"range": _rng(sid, R_CARD_LBL, R_CARD_VAL + 1, 0, ncard),
                               "innerVertical": {"style": "SOLID_THICK", "color": WHITE}}},
            # Table header.
            _fmt(sid, R_HDR, R_HDR + 1, 0, ncol,
                 {"backgroundColor": HEADER_BG, "horizontalAlignment": "CENTER",
                  "textFormat": {"fontFamily": "Roboto", "bold": True, "foregroundColor": WHITE}},
                 "userEnteredFormat(backgroundColor,horizontalAlignment,textFormat)"),
            _fmt(sid, R_HDR, R_HDR + 1, 0, 1, {"horizontalAlignment": "LEFT", "padding": {"left": 10}},
                 "userEnteredFormat(horizontalAlignment,padding)"),
            # Data: names left (padded), numbers centered.
            _fmt(sid, R_DATA, LAST_ROW, 0, ncol, {"padding": {"left": 10}},
                 "userEnteredFormat.padding"),
            _fmt(sid, R_DATA, LAST_ROW, 1 if tab == TAB_OWNER else 2, ncol,
                 {"horizontalAlignment": "CENTER"}, "userEnteredFormat.horizontalAlignment"),
            _fmt(sid, R_DATA, LAST_ROW, lay["score"], lay["score"] + 1,
                 {"numberFormat": {"type": "NUMBER", "pattern": "0.0"}},
                 "userEnteredFormat.numberFormat"),
            {"addBanding": {"bandedRange": {"range": _rng(sid, R_DATA, LAST_ROW, 0, ncol),
                                            "rowProperties": {"firstBandColor": WHITE,
                                                              "secondBandColor": BAND_BG}}}},
            {"updateBorders": {"range": _rng(sid, R_HDR, R_HDR + 1, 0, ncol),
                               "bottom": {"style": "SOLID_MEDIUM", "color": NAVY}}},
            # Row heights.
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                     "startIndex": R_TITLE, "endIndex": R_TITLE + 1},
                                           "properties": {"pixelSize": 48}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                     "startIndex": R_PICK, "endIndex": R_PICK + 1},
                                           "properties": {"pixelSize": 32}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                     "startIndex": 2, "endIndex": 3},
                                           "properties": {"pixelSize": 10}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                     "startIndex": R_CARD_LBL, "endIndex": R_CARD_LBL + 1},
                                           "properties": {"pixelSize": 26}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                     "startIndex": R_CARD_VAL, "endIndex": R_CARD_VAL + 1},
                                           "properties": {"pixelSize": 46}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                     "startIndex": 5, "endIndex": 6},
                                           "properties": {"pixelSize": 14}, "fields": "pixelSize"}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "ROWS",
                                                     "startIndex": R_HDR, "endIndex": LAST_ROW},
                                           "properties": {"pixelSize": 30}, "fields": "pixelSize"}},
        ]
        for i, w in enumerate(lay["widths"]):
            reqs.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": w}, "fields": "pixelSize"}})
        for i, (_lbl, _col, pattern) in enumerate(lay["cards"]):
            kind = "PERCENT" if "%" in pattern else "NUMBER"
            reqs.append(_fmt(sid, R_CARD_VAL, R_CARD_VAL + 1, i, i + 1,
                             {"numberFormat": {"type": kind, "pattern": pattern}},
                             "userEnteredFormat.numberFormat"))
        # Conditional formats - the first matching rule wins, so in order:
        # the "no owner" row (gray), score colors, % gradient.
        data = _rng(sid, R_DATA, LAST_ROW, 0, ncol)
        owner_letter = "A" if tab == TAB_OWNER else "B"
        reqs.append({"addConditionalFormatRule": {"rule": {"ranges": [data], "booleanRule": {
            "condition": {"type": "CUSTOM_FORMULA", "values": [
                {"userEnteredValue": '=$%s%d="%s"' % (owner_letter, R_DATA + 1, NO_OWNER)}]},
            "format": {"backgroundColor": NO_OWNER_BG,
                       "textFormat": {"italic": True, "foregroundColor": MUTED}}}}}})
        if tab == TAB_REP:      # an owner Lucy guessed ("... (auto)") reads as a guess
            reqs.append({"addConditionalFormatRule": {"rule": {
                "ranges": [_rng(sid, R_DATA, LAST_ROW, 1, 2)], "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA", "values": [
                        {"userEnteredValue": '=RIGHT($B%d, %d)="%s"' % (R_DATA + 1, len(AUTO.strip()), AUTO.strip())}]},
                    "format": {"textFormat": {"italic": True, "foregroundColor": MUTED}}}}}})
        # Score colors = the live scorecard's cuts: 8+ green, 6-8 yellow, under 6 red.
        score = _rng(sid, R_DATA, LAST_ROW, lay["score"], lay["score"] + 1)
        for cond, values, color in (
                ("NUMBER_GREATER_THAN_EQ", ["8"], GOOD),
                ("NUMBER_BETWEEN", ["6", "7.99"], MID),
                ("NUMBER_LESS", ["6"], LOW)):
            reqs.append({"addConditionalFormatRule": {"rule": {"ranges": [score], "booleanRule": {
                "condition": {"type": cond, "values": [{"userEnteredValue": v} for v in values]},
                "format": {"backgroundColor": color, "textFormat": {"bold": True}}}}}})
        if lay["pct"] is not None:
            pc = lay["pct"]
            reqs.append(_fmt(sid, R_DATA, LAST_ROW, pc, pc + 1,
                             {"numberFormat": {"type": "PERCENT", "pattern": "0%"}},
                             "userEnteredFormat.numberFormat"))
            reqs.append({"addConditionalFormatRule": {"rule": {
                "ranges": [_rng(sid, R_DATA, LAST_ROW, pc, pc + 1)],
                "gradientRule": {
                    "minpoint": {"color": LOW, "type": "NUMBER", "value": "0"},
                    "midpoint": {"color": MID, "type": "NUMBER", "value": "0.25"},
                    "maxpoint": {"color": GOOD, "type": "NUMBER", "value": "0.5"}}}}})
    S.post("%s/%s/values:batchUpdate" % (SHEETS, ssid),
           json={"valueInputOption": "USER_ENTERED", "data": vals}).raise_for_status()
    S.post("%s/%s:batchUpdate" % (SHEETS, ssid), json={"requests": reqs}).raise_for_status()
    log("restyled %s" % ", ".join(LAYOUTS))


def create_sheet(S, share: list) -> str:
    body = {"properties": {"title": "LUCY 2nd Round Recordings (TEST)"},
            "sheets": [{"properties": {"title": t, "hidden": t in HIDDEN_TABS}}
                       for t in (TAB_OWNER, TAB_REP) + HIDDEN_TABS]}
    r = S.post(SHEETS, json=body)
    r.raise_for_status()
    ssid = r.json()["spreadsheetId"]
    restyle(S, ssid)
    for email in share:
        S.post("https://www.googleapis.com/drive/v3/files/%s/permissions" % ssid,
               params={"sendNotificationEmail": "false"},
               json={"type": "user", "role": "writer", "emailAddress": email}).raise_for_status()
    log("created https://docs.google.com/spreadsheets/d/%s" % ssid)
    return ssid


def write(S, ssid, owner_rows, rep_rows, totals, month_list):
    stamp = dt.datetime.now(CT).strftime("%b %d, %Y %I:%M %p CT")
    ids = _ensure_tabs(S, ssid)
    for tab in HIDDEN_TABS:
        if tab in ids:
            S.post("%s/%s/values/%s:clear" % (SHEETS, ssid, _q(tab))).raise_for_status()
    data = [
        {"range": "%s!A1" % _q(CALC_OWNER),
         "values": [["Month", "Owner", "Recordings", "2nd Rounds Done", "% Recorded", "Avg Score"]]
         + owner_rows},
        {"range": "%s!A1" % _q(CALC_REP),
         "values": [["Month", "Rep", "Owner", "Recordings", "Avg Score"]] + rep_rows},
        {"range": "%s!A1" % _q(CALC_TOTALS),
         "values": [["Month", "Recordings", "2nd Rounds Done", "% Recorded", "Avg Score",
                     "Reps Recording"]] + totals},
        {"range": "%s!A1" % _q(MONTHS), "values": [[m] for m in month_list]},
    ]
    note = ("Updated %s  ·  Recordings + scores: LUCY 2nd round audit  ·  "
            "2nd rounds done: ApplicantStream (Second Interviews Showed Up)" % stamp)
    for tab in LAYOUTS:
        data.append({"range": "%s!C2" % _q(tab), "values": [[note]]})
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
    ap.add_argument("--restyle", action="store_true",
                    help="rebuild the two visible tabs' layout (keeps the sheet + link)")
    a = ap.parse_args(argv)

    export = load_bot_export(a.from_json)
    log("bot: %d recording(s), %d rep(s), %d owner(s)"
        % (len(export["records"]), len(export["reps"]), len(export["owners"])))
    S = _session()
    done, owner_of = load_interviews(S)
    log("retention sheet: %d office(s)" % len(owner_of))
    reps = export["reps"]
    no_owner = sorted({r.get("uid") for r in export["records"]
                       if r.get("uid") and not (reps.get(r["uid"]) or {}).get("owner_id")})
    slack, knocks = load_guess_sources(S)
    guesses = guess_owners(no_owner, export["names"],
                           [o.get("name", "") for o in export["owners"]], slack, knocks)
    log("no confirmed owner: %d rep(s); guessed %d (%s)" % (
        len(no_owner), len(guesses),
        ", ".join("%s -> %s [%s]" % (export["names"].get(u, u), o, src)
                  for u, (o, src) in sorted(guesses.items()))))
    owner_rows, rep_rows, totals, month_list, unmatched = build(export, done, owner_of, guesses)
    if unmatched:
        log("owners with NO AppStream office match (2nd rounds blank): " + ", ".join(unmatched))
    no_uid = sum(1 for r in export["records"] if not r.get("uid"))
    if no_uid:
        log("%d recording(s) with no known uploader -> '%s'" % (no_uid, NO_OWNER))

    if a.dry_run:
        cur = month_list[0] if month_list else ""
        log("--- %s, by owner ---" % cur)
        for r in [x for x in owner_rows if x[0] == cur]:
            print("  %-32s grab=%-4s hechas=%-5s pct=%-7s nota=%s" % tuple(r[1:]))
        log("--- %s, by rep (top 15) ---" % cur)
        for r in [x for x in rep_rows if x[0] == cur][:15]:
            print("  %-28s %-28s grab=%-4s nota=%s" % tuple(r[1:]))
        return 0

    ssid = a.sheet
    if a.create:
        ssid = create_sheet(S, a.share)
    if not ssid:
        raise SystemExit("no sheet id - run with --create once, then set SSID")
    if a.restyle and not a.create:
        restyle(S, ssid)
    write(S, ssid, owner_rows, rep_rows, totals, month_list)
    return 0


if __name__ == "__main__":
    sys.exit(main())
