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

SCHEDULE: 8:00 AM CT daily on Lucy 1 (needs the bot's files). Moved from 11 PM
(Eve 2026-11-06): by 8 the 7:07 AM retention pass has re-read yesterday's late
2nd rounds, so yesterday is complete. --email then mails Raf the month summary.

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


NEW_STARTS_WEEKS = 4


def closed_weeks(today: dt.date, n: int = NEW_STARTS_WEEKS) -> list:
    """The last n finished Sun-Sat weeks, as their Sundays, oldest first."""
    sun = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    return [sun - dt.timedelta(days=7 * i) for i in range(n, 0, -1)]


def load_new_starts(S) -> list:
    """Rows of the retention sheet's 'New Starts' tab. Empty if it can't be read:
    the recordings report still goes out, without this table."""
    try:
        r = S.get("%s/%s/values/%s!A2:H100000" % (SHEETS, RETENTION_SSID, _q("New Starts")))
        r.raise_for_status()
        return r.json().get("values", [])
    except Exception as e:  # noqa: BLE001
        log("New Starts tab not read (%s) - table left out" % e)
        return []


def new_starts_table(rows: list, weeks: list, owners: list, offices: dict) -> tuple:
    """([owner, scheduled, started, %, started per week, training scheduled,
    training showed], weeks that have data).
    Best show ratio first; owners with nothing scheduled are left out.
    Training (cols G/H, Raf 2026-11-12) is the TRAINING calendar, kept apart
    from new starts, never added in (Eve: separate). An owner who only books
    on Training still shows, with "—" for the new start %.
    Per week = over the weeks THAT owner has loaded; an owner with fewer weeks
    than the table gets "(N wk)" after the name (Eve 2026-11-10: a half-loaded
    owner must not look like 100% over 4 weeks)."""
    wanted = {w.isoformat() for w in weeks}
    sched, started, seen = defaultdict(int), defaultdict(int), set()
    tsched, tshow = defaultdict(int), defaultdict(int)
    office_weeks = defaultdict(set)
    for row in rows:
        if len(row) < 6 or row[0] not in wanted:
            continue
        try:
            s, h = int(float(row[4] or 0)), int(float(row[5] or 0))
        except ValueError:
            continue
        seen.add(row[0])
        office_weeks[row[2]].add(row[0])
        sched[row[2]] += s
        started[row[2]] += h
        try:
            tsched[row[2]] += int(float(row[6] or 0)) if len(row) > 6 else 0
            tshow[row[2]] += int(float(row[7] or 0)) if len(row) > 7 else 0
        except ValueError:
            pass
    out = []
    n = max(len(seen), 1)
    for o in owners:
        ids = offices.get(o["id"]) or []
        s, h = sum(sched[x] for x in ids), sum(started[x] for x in ids)
        ts, th = sum(tsched[x] for x in ids), sum(tshow[x] for x in ids)
        if s or ts:
            k = len(set().union(*(office_weeks[x] for x in ids))) or n
            name = o.get("name", o["id"]) + ("" if k >= n else " (%d wk)" % k)
            out.append([name, s, h, round(h / s, 4) if s else None, round(h / k, 1), ts, th])
    out.sort(key=lambda r: (-(r[3] if r[3] is not None else -1), -r[1], -r[5], r[0]))
    return out, sorted(seen)


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


# ---------- guard: what does NOT count as a recording ----------
#
# Raf 2026-11-07: the board goes to the whole org so the owners compete, so a
# recording sent twice, or a fake one ("a 2min recording or something"), must
# not count. Dropped recordings leave the count AND the average score. The
# audit bot already refuses audio under 5 minutes when ffprobe can read it; this
# catches what got past that.

MIN_RECORDING_SECONDS = 5 * 60
# Same rep, same length to the second = the same audio exported again (a re-save
# changes the file's bytes, so the fingerprint alone misses it).
SAME_LENGTH_SECONDS = 1.0
TOO_SHORT, DUPLICATE = "too short", "sent twice"


def apply_guard(records: list) -> tuple:
    """(records that count, [(record, reason)] that don't), oldest first, so the
    first send of a recording is the one that counts. No readable length or
    fingerprint = it counts: we only drop what we can prove."""
    kept, dropped = [], []
    seen_fp, lengths = {}, defaultdict(list)
    for r in sorted(records, key=lambda x: x.get("ts") or ""):
        secs, fp, uid = r.get("seconds"), r.get("fp"), r.get("uid") or ""
        if secs is not None and secs < MIN_RECORDING_SECONDS:
            dropped.append((r, TOO_SHORT))
            continue
        twin = next((x for x in lengths[uid] if abs(secs - x[0]) <= SAME_LENGTH_SECONDS),
                    None) if secs is not None and uid else None
        if fp and fp in seen_fp:
            r["matched"] = "same file as %s" % seen_fp[fp]
            dropped.append((r, DUPLICATE))
            continue
        if twin:
            r["matched"] = "same length as %s (%.1f s)" % (twin[1], twin[0])
            dropped.append((r, DUPLICATE))
            continue
        if fp:
            seen_fp[fp] = r.get("file") or "?"
        if secs is not None and uid:
            lengths[uid].append((secs, r.get("file") or "?"))
        kept.append(r)
    return kept, dropped


def _log_guard(export: dict, dropped: list, month_prefix: str) -> None:
    names = export.get("names") or {}
    mine = [(r, why) for r, why in dropped if (r.get("ts") or "").startswith(month_prefix)]
    log("guard: %d recording(s) not counted (%d this month)" % (len(dropped), len(mine)))
    for r, why in mine:
        secs = r.get("seconds")
        log("  not counted [%s] %s  %s  %s  %s  %s" % (
            why, (r.get("ts") or "")[:16], names.get(r.get("uid") or "") or NO_NAME,
            "?" if secs is None else "%.1f min" % (secs / 60), r.get("file") or "",
            r.get("matched") or ""))


def _log_lengths(records: list, month_prefix: str) -> None:
    """How long this month's counted recordings are, shortest first - what the
    minimum is judged against."""
    secs = sorted(r["seconds"] for r in records
                  if r.get("seconds") is not None and (r.get("ts") or "").startswith(month_prefix))
    unknown = sum(1 for r in records
                  if r.get("seconds") is None and (r.get("ts") or "").startswith(month_prefix))
    log("lengths this month: %d known, %d unknown; shortest (min): %s" % (
        len(secs), unknown, ", ".join("%.1f" % (s / 60) for s in secs[:25])))


# ---------- build ----------

def owner_rank_key(row: list) -> tuple:
    """Highest % Recorded first (Raf 2026-11-07: "push the guys based on a %"; Eve
    2026-11-09). Ties: more recordings, then name. No % known, then the "no owner"
    row, go last. row = [month, owner, recordings, 2nd rounds, %, score]."""
    pct = row[4]
    return (row[1] == NO_OWNER, pct == "", -(pct or 0), -row[2], row[1])


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
    owner_rows.sort(key=lambda x: (x[0],) + owner_rank_key(x))
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
        "calc": CALC_OWNER, "cols": "B2:F", "owner_col": "B2:B", "sort": 4, "then": 2,
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
    then = ", %d, FALSE" % lay["then"] if lay.get("then") else ""
    return ('=IFERROR(SORT(FILTER(%s!%s, %s), FILTER(%s!%s, %s)="%s", TRUE, %d, FALSE%s), '
            '"No data for this month")'
            % (calc, lay["cols"], in_month, calc, lay["owner_col"], in_month, NO_OWNER, lay["sort"], then))


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


# ---------- email to Raf ----------
#
# Eve 2026-11-06: send Raf the report "when the info is as up to date as
# possible" -> the 8:00 AM CT run, after the 7:07 AM retention pass has
# re-read yesterday's late 2nd rounds. Plain HTML, no images.

# Raf + Colten tried it first (Raf + Eve 2026-11-09). Raf 2026-11-11 "send to
# everyone" -> the daily agent passes --email-org (Alphalete Org Owners).
TRIAL_TO = ["raffi127@gmail.com", "coltenwrightsc@gmail.com", "alphaletemarketing@gmail.com"]
ORG_SENT_DIR = HERE.parents[1] / "output" / "state" / "lucy_recordings_org_sent"


def _cell_color(v, cuts):
    if v == "" or v is None:
        return ""
    good, mid = cuts
    return "#C8E6C9" if v >= good else "#FFE9A8" if v >= mid else "#F6C1C1"


def date_range() -> str:
    """'Nov 1 – Nov 5' - the 1st of the month through yesterday (CT)."""
    y = dt.datetime.now(CT).date() - dt.timedelta(days=1)
    first = y.replace(day=1)
    a, b = "%s %d" % (first.strftime("%b"), first.day), "%s %d" % (y.strftime("%b"), y.day)
    return a if a == b else "%s – %s" % (a, b)


# Raf 2026-11-10: the 4-week new start % as a column (and card) of the first
# table. main() fills this from new_starts_table(); empty = column shows "—".
NEW_START_PCT = {}
# Raf 2026-11-11: "New starts last 4 weeks" next to the % -> the started count.
NEW_START_COUNT = {}


def ns_pct_by_owner(table: list) -> dict:
    """{owner name: started/scheduled} from new_starts_table, plus "" = total.
    The "(N wk)" note stays on the name in the detail table only."""
    out = {re.sub(r" \(\d+ wk\)$", "", r[0]): r[3] for r in table if r[3] is not None}
    s, h = sum(r[1] for r in table), sum(r[2] for r in table)
    if s:
        out[""] = round(h / s, 4)
    return out


def ns_count_by_owner(table: list) -> dict:
    """{owner name: started} from new_starts_table, plus "" = total."""
    out = {re.sub(r" \(\d+ wk\)$", "", r[0]): r[2] for r in table}
    if table:
        out[""] = sum(r[2] for r in table)
    return out


# One-day notes at the top of the email, keyed by CT date (Eve 2026-11-11).
DAY_NOTES = {
    "2026-11-12": (
        "Updated: the New Starts table now also shows the Training calendar, in its own "
        "columns. Some offices book new starts on Training, so New Starts alone was missing them."),
    "2026-11-11": (
        "Heads up: in today's email, the New Start % column is missing some offices "
        "for a few owners. It will be complete in tomorrow's email. These changes have "
        "to be tested before they go out, a couple of test runs failed along the way, "
        "and each run ties up Lucy for about 2.5 hours, so we're rolling it out step by step."),
}


def day_note_html() -> str:
    note = DAY_NOTES.get(dt.datetime.now(CT).date().isoformat())
    if not note:
        return ""
    return ('<div style="background:#FDECEC;border-left:5px solid #D9534F;padding:10px 14px;'
            'margin:6px 0;font-size:13px;color:#1F2A44">%s</div>' % note)


def build_email_html(month: str, totals: list, owner_rows: list, ssid: str,
                     show_link: bool = True, new_start_pct: dict = None,
                     new_start_count: dict = None) -> str:
    ns = NEW_START_PCT if new_start_pct is None else new_start_pct
    nc = NEW_START_COUNT if new_start_count is None else new_start_count
    t = next((x for x in totals if x[0] == month), [month, 0, "", "", "", 0])
    fmt_pct = lambda v: "—" if v == "" or v is None else "%d%%" % round(v * 100)
    fmt_num = lambda v: "—" if v == "" else str(v)
    cards = [("Recordings", fmt_num(t[1])), ("2nd Rounds Done", fmt_num(t[2])),
             ("% Recorded", fmt_pct(t[3])), ("Avg Score", fmt_num(t[4])),
             ("New Start % (4 wk)", fmt_pct(ns.get(""))),
             ("New Starts (4 wk)", fmt_num(nc.get("", "")))]
    card_html = "".join(
        '<td style="background:#EEF2FA;padding:12px 8px;text-align:center;width:16%%">'
        '<div style="font-size:11px;color:#7A8294;font-weight:bold">%s</div>'
        '<div style="font-size:24px;color:#1F2A44;font-weight:bold">%s</div></td>' % c
        for c in cards)
    rows = sorted((r for r in owner_rows if r[0] == month), key=owner_rank_key)
    body = []
    for i, r in enumerate(rows):
        bg = "#F1F1F1" if r[1] == NO_OWNER else ("#F6F8FC" if i % 2 else "#FFFFFF")
        pct_bg = _cell_color(r[4], (0.5, 0.25))
        sc_bg = _cell_color(r[5], (8, 6))
        nsv = ns.get(r[1])
        ns_bg = _cell_color(nsv, (0.5, 0.25)) if nsv is not None else ""
        body.append(
            '<tr style="background:%s"><td style="padding:6px 10px">%s</td>'
            '<td style="text-align:center">%s</td><td style="text-align:center">%s</td>'
            '<td style="text-align:center;background:%s">%s</td>'
            '<td style="text-align:center;background:%s;font-weight:bold">%s</td>'
            '<td style="text-align:center;background:%s">%s</td>'
            '<td style="text-align:center;font-weight:bold">%s</td></tr>'
            % (bg, r[1], r[2], fmt_num(r[3]), pct_bg or bg, fmt_pct(r[4]),
               sc_bg or bg, fmt_num(r[5]), ns_bg or bg, fmt_pct(nsv),
               fmt_num(nc.get(r[1], ""))))
    link = "https://docs.google.com/spreadsheets/d/%s" % ssid
    button = ('<p style="margin:16px 0"><a href="%s" style="background:#E0B84C;color:#1F2A44;padding:10px 16px;'
              'text-decoration:none;font-weight:bold;border-radius:4px">Open the full sheet (by rep)</a></p>'
              % link) if show_link else ""
    rule = ('<p style="margin:12px 0;font-size:12px;color:#5B6478">Recordings sent more than once, or '
            'under %d minutes, don\'t count.</p>' % (MIN_RECORDING_SECONDS // 60))
    return (
        '<div style="font-family:Roboto,Arial,sans-serif;max-width:680px">'
        '<div style="background:#1F2A44;color:#fff;padding:14px 16px;font-size:18px;font-weight:bold">'
        'LUCY · 2nd Round Recordings</div>' + day_note_html() +
        '<div style="background:#FFF4CC;border-left:5px solid #E0B84C;padding:10px 14px;margin:6px 0">'
        '<span style="font-size:22px;font-weight:bold;color:#1F2A44">%s</span>'
        '<span style="font-size:14px;color:#5B6478;padding-left:8px">· Month to date</span></div>'
        '<table style="width:100%%;border-collapse:separate;border-spacing:4px"><tr>%s</tr></table>'
        '<table style="width:100%%;border-collapse:collapse;font-size:13px;margin-top:10px">'
        '<tr style="background:#2E3E61;color:#fff"><th style="text-align:left;padding:8px 10px">Owner</th>'
        '<th>Recordings</th><th>2nd Rounds Done</th><th>%% Recorded</th><th>Avg Score</th>'
        '<th>New Start %% (4 wk)</th><th>New Starts (4 wk)</th></tr>%s</table>'
        '%s%s</div>' % (date_range(), card_html, "".join(body), rule, button))


def new_starts_html(table: list, weeks_seen: list) -> str:
    if not table or not weeks_seen:
        return ""
    first = dt.date.fromisoformat(weeks_seen[0])
    last = dt.date.fromisoformat(weeks_seen[-1]) + dt.timedelta(days=6)
    span = "%s %d – %s %d" % (first.strftime("%b"), first.day, last.strftime("%b"), last.day)
    n = len(weeks_seen)
    body = []
    for i, r in enumerate(table):
        bg = "#F6F8FC" if i % 2 else "#FFFFFF"
        body.append(
            '<tr style="background:%s"><td style="padding:6px 10px">%s</td>'
            '<td style="text-align:center">%s</td><td style="text-align:center">%s</td>'
            '<td style="text-align:center;background:%s;font-weight:bold">%s</td>'
            '<td style="text-align:center">%s</td>%s</tr>'
            % (bg, r[0], r[1], r[2], _cell_color(r[3], (0.5, 0.25)), _pct(r[3]), r[4],
               _training_tds(r)))
    s, h = sum(r[1] for r in table), sum(r[2] for r in table)
    tot = ["Total", s, h, h / s if s else None, round(h / n, 1),
           sum(r[5] for r in table if len(r) > 5), sum(r[6] for r in table if len(r) > 6)]
    body.append(
        '<tr style="background:#EEF2FA;font-weight:bold"><td style="padding:6px 10px">Total</td>'
        '<td style="text-align:center">%d</td><td style="text-align:center">%d</td>'
        '<td style="text-align:center">%s</td><td style="text-align:center">%s</td>%s</tr>'
        % (s, h, _pct(tot[3]), tot[4], _training_tds(tot)))
    return (
        '<div style="font-family:Roboto,Arial,sans-serif;max-width:680px;margin-top:22px">'
        '<div style="background:#1F2A44;color:#fff;padding:12px 16px;font-size:16px;font-weight:bold">'
        'New Starts · Last %d Weeks</div>'
        '<div style="padding:8px 2px;font-size:13px;color:#5B6478">%s</div>'
        '<table style="width:100%%;border-collapse:collapse;font-size:13px">'
        '<tr style="background:#2E3E61;color:#fff"><th style="text-align:left;padding:8px 10px">Owner</th>'
        '<th>Scheduled</th><th>Started</th><th>%% Started</th><th>Avg Started / Week</th>'
        '<th style="background:%s">Training Scheduled</th><th style="background:%s">Training Showed</th>'
        '</tr>%s</table>'
        '<div style="padding:6px 2px;font-size:12px;color:#5B6478">Training = the Training calendar in '
        'AppStream, shown apart from New Starts (some offices book new starts there).</div></div>'
        % (n, span, TRAINING_HEAD, TRAINING_HEAD, "".join(body)))


TRAINING_HEAD = "#4A5A7E"   # a shade lighter: these columns are a separate calendar


def _pct(v) -> str:
    return "—" if v is None else "%d%%" % round(v * 100)


def _training_tds(r) -> str:
    """The two Training cells; "—" for a table built before G/H existed."""
    ts = r[5] if len(r) > 5 else "—"
    th = r[6] if len(r) > 6 else "—"
    return ('<td style="text-align:center;border-left:2px solid #C9D2E3">%s</td>'
            '<td style="text-align:center">%s</td>' % (ts, th))


def send_email(to: list, month: str, totals: list, owner_rows: list, ssid: str,
               show_link: bool = True, extra_html: str = "") -> None:
    from email.message import EmailMessage
    from automations.org_sales_board.screenshot_email import FROM_ADDR, send
    msg = EmailMessage()
    msg["Subject"] = "LUCY 2nd Round Recordings — %s (month to date)" % date_range()
    msg["From"] = FROM_ADDR
    msg["To"] = ", ".join(to)
    msg.set_content("LUCY 2nd Round Recordings - %s, month to date." % month + (
        " Open the sheet: https://docs.google.com/spreadsheets/d/%s" % ssid if show_link else ""))
    msg.add_alternative(build_email_html(month, totals, owner_rows, ssid, show_link) + extra_html,
                        subtype="html")
    send(msg)
    log("emailed '%s' to %s" % (msg["Subject"], ", ".join(to)))


# ---------- yesterday's list (Raf 2026-11-11) ----------
#
# "JD thinks we submitted more recordings than the report is saying" -> every
# morning, the list of who sent a recording the day before. Every recording
# shows, the ones that don't count too (with why), so a missing one is easy to
# spot. Day = the audit's finish time on Lucy 1 (CT), like the month report.

COUNTED = "Counted"


def yesterday_rows(kept: list, dropped: list, export: dict, guesses: dict, day: str) -> list:
    """[time, rep, owner, minutes, score, status] for recordings finished on
    `day` (YYYY-MM-DD), oldest first."""
    owners = {o["id"]: o.get("name", o["id"]) for o in export.get("owners") or []}
    reps, names = export.get("reps") or {}, export.get("names") or {}

    def owner_for(uid):
        oid = (reps.get(uid) or {}).get("owner_id") if uid else None
        if oid:
            return owners.get(oid, NO_OWNER)
        return guesses[uid][0] if uid in guesses else NO_OWNER

    rows = []
    for r, status in [(r, COUNTED) for r in kept] + [(r, "Not counted: " + why) for r, why in dropped]:
        ts = r.get("ts") or ""
        if ts[:10] != day:
            continue
        uid = r.get("uid") or ""
        secs = r.get("seconds")
        try:
            t = dt.datetime.fromisoformat(ts[:19]).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            t = ""
        rows.append([ts, t, names.get(uid) or NO_NAME, owner_for(uid),
                     "" if secs is None else int(round(secs / 60)),
                     "" if r.get("score") is None else r["score"], status])
    rows.sort(key=lambda x: x[0])
    return [x[1:] for x in rows]


# Lucy's own group DM with Raf, JD, Bas, Algemar and Eve (Eve 2026-11-11). Raf's
# existing DM (C0CGXQFPTAQ) has the OTHER Lucy, not lucy_reporting, and a group
# DM can't take new people -> Lucy opens this one by its members.
YESTERDAY_DM = ",".join([
    "U045Z8N0ZQC",   # Rafael Hidalgo
    "U05094TTPKQ",   # JD Mascorro (NOT the look-alike U068T4LA0C8)
    "U067WLPK92T",   # Bas (basboosmahdi; NOT U09TWLG53EZ, also "Bas")
    "U09MXMU76MB",   # Algemar Kennel
    "U088E2KJEV8",   # Eve
])
# Raf wants HIS office under control, not the org. Eve 2026-11-11: JD, Basil
# and Algemar are leaders INSIDE Raf's office, not owners - the owner is Raf.
# Matched on the bot's owner name (accents/case ignored, every word must be there).
YESTERDAY_OWNERS = ("rafael hidalgo",)


def in_yesterday_scope(owner: str, wanted=YESTERDAY_OWNERS) -> bool:
    """Raf's office owners, plus recordings with no owner: a rep of ours the bot
    can't place lands there, which is exactly the 'we sent more' gap."""
    if owner == NO_OWNER:
        return True
    words = set(norm(owner).split())
    return any(set(w.split()) <= words for w in wanted)


def short_name(name: str) -> str:
    """Raf 2026-11-12: first name + last name's initial, capitalized the same
    for everyone ('ANDRES MEJIA' / 'savannah moreno' -> 'Andres M.' / 'Savannah M.')."""
    if not name or name == NO_NAME:
        return name
    words = name.split()
    first = "-".join(w[:1].upper() + w[1:].lower() for w in words[0].split("-"))
    return first if len(words) == 1 else "%s %s." % (first, words[-1][:1].upper())


def yesterday_text(day: str, rows: list) -> str:
    """Slack message: one block per owner, one line per recording."""
    d = dt.date.fromisoformat(day)
    label = "%s, %s %d" % (d.strftime("%A"), d.strftime("%b"), d.day)
    counted = [r for r in rows if r[5] == COUNTED]
    head = ["*LUCY · Recordings Sent Yesterday · Raf's Office — %s*" % label]
    if not rows:
        return head[0] + "\nNo recordings were sent to LUCY this day."
    head.append("*%d counted* · %d rep(s) · %d not counted" % (
        len(counted), len({r[1] for r in counted}), len(rows) - len(counted)))
    by_owner = defaultdict(list)
    for r in rows:
        by_owner[r[2]].append(r)
    out = head
    # Raf 2026-11-11 (on the first post): numbers instead of bullets, no
    # length, name first then the time.
    n = 0
    for own in sorted(by_owner, key=lambda o: (o == NO_OWNER, o)):
        rs = by_owner[own]
        out.append("")
        out.append("*%s* (%d)" % (own, sum(1 for r in rs if r[5] == COUNTED)))
        for r in rs:
            n += 1
            bits = [short_name(r[1]), r[0]]
            if r[4] != "":
                bits.append("score %s" % r[4])
            mark = ":white_check_mark:" if r[5] == COUNTED else ":x: " + r[5].replace("Not counted: ", "")
            out.append("%d. %s %s" % (n, " · ".join(bits), mark))
    out.append("")
    out.append("_Recordings sent twice, or under %d min, don't count. Missing one? Reply here "
               "with the rep's name and the time it was sent._" % (MIN_RECORDING_SECONDS // 60))
    return "\n".join(out)


def post_yesterday(target: str, day: str, rows: list, edit_ts: str = "") -> None:
    """Posts as Lucy: the Lucy Reporting USER token on purpose (no bot app on
    Lucy 1). target = a channel/DM id, or user ids (U..., comma separated):
    one = a 1-to-1 test DM, several = the group DM with those people."""
    from automations.shared.slack_metrics_post import _client
    client = _client()
    channel = target
    if target.startswith(("U", "W")):
        channel = client.conversations_open(users=target)["channel"]["id"]
    if edit_ts:
        # Fix a list already in the DM in place - never a second post.
        resp = client.chat_update(channel=channel, ts=edit_ts, text=yesterday_text(day, rows))
        log("edited yesterday's list in place (%d recording(s)) ts=%s ok=%s"
            % (len(rows), edit_ts, resp.get("ok")))
        return
    resp = client.chat_postMessage(channel=channel, text=yesterday_text(day, rows),
                                   unfurl_links=False)
    log("posted yesterday's list (%d recording(s)) to %s ts=%s" % (len(rows), target, resp.get("ts")))


# ---------- "who's your owner?" (Raf 2026-11-12) ----------
#
# A rep in the "(no owner confirmed)" block: Raf doesn't know them either ->
# "message them with me in the chat and I'm sure they'll respond". Lucy opens a
# group DM with the rep + Raf (+ Eve, who maps the answer) and asks. Once per
# rep, ever: a rep who keeps sending recordings must not get asked every day.

ASK_WITH = ("U045Z8N0ZQC", "U088E2KJEV8")   # Rafael Hidalgo, Eve
ASKED_DIR = HERE.parents[1] / "output" / "state" / "lucy_recordings_owner_asked"


def no_owner_reps(kept: list, dropped: list, export: dict, guesses: dict, day: str) -> list:
    """[(uid, name, first time)] of reps with no owner (not even a guess) who
    sent a recording on `day`, oldest first. No uid = nobody to message."""
    reps = export.get("reps") or {}
    seen = {}
    for r in list(kept) + [r for r, _ in dropped]:
        ts, uid = r.get("ts") or "", r.get("uid") or ""
        if ts[:10] != day or not uid.startswith(("U", "W")):
            continue
        if (reps.get(uid) or {}).get("owner_id") or uid in guesses:
            continue
        if uid not in seen or ts < seen[uid]:
            seen[uid] = ts
    out = []
    for uid, ts in sorted(seen.items(), key=lambda x: x[1]):
        try:
            t = dt.datetime.fromisoformat(ts[:19]).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            t = ""
        out.append((uid, (export.get("names") or {}).get(uid) or "", t))
    return out


def ask_owner_text(name: str, day: str, time: str) -> str:
    d = dt.date.fromisoformat(day)
    first = short_name(name).split()[0] if name and name != NO_NAME else ""
    when = "%s, %s %d" % (d.strftime("%A"), d.strftime("%b"), d.day) + (" at %s" % time if time else "")
    return ("Hi%s! LUCY got your 2nd round recording on %s, but we don't know which "
            "office you're with. Who is your owner? Just reply here :slightly_smiling_face:"
            % (" " + first if first else "", when))


def ask_owners(reps: list, day: str) -> None:
    """One group DM per rep (rep + Raf + Eve), once per rep."""
    from automations.shared.slack_metrics_post import _client
    client = None
    for uid, name, time in reps:
        mark = ASKED_DIR / uid
        if mark.exists():
            log("owner question: %s (%s) already asked %s - skipping"
                % (name, uid, mark.read_text(encoding="utf-8").strip()))
            continue
        client = client or _client()
        try:
            ch = client.conversations_open(users=",".join((uid,) + ASK_WITH))["channel"]["id"]
            resp = client.chat_postMessage(channel=ch, text=ask_owner_text(name, day, time))
        except Exception as e:  # noqa: BLE001
            log("owner question NOT sent to %s (%s): %s" % (name, uid, e))
            continue
        ASKED_DIR.mkdir(parents=True, exist_ok=True)
        mark.write_text(dt.datetime.now(CT).isoformat(), encoding="utf-8")
        log("owner question sent to %s (%s) in %s ts=%s" % (name, uid, ch, resp.get("ts")))


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
    ap.add_argument("--email", action="store_true", help="after writing, email the report to Raf + Colten")
    ap.add_argument("--email-org", action="store_true",
                    help="after writing, email the whole org (Alphalete Org Owners), once a day")
    ap.add_argument("--email-to", help="after writing, email THESE addresses (comma separated) the org version (test)")
    ap.add_argument("--restyle", action="store_true",
                    help="rebuild the two visible tabs' layout (keeps the sheet + link)")
    ap.add_argument("--yesterday-slack", nargs="?", const=YESTERDAY_DM,
                    help="also post who sent a recording yesterday, as Lucy (default: Raf's "
                         "group DM; pass a user id U... to test in a 1-to-1 DM)")
    ap.add_argument("--yesterday-edit", metavar="TS",
                    help="with --yesterday-slack: rewrite the list already posted at this ts "
                         "instead of posting a new one")
    ap.add_argument("--ask-owners-only", action="store_true",
                    help="only send the 'who's your owner?' DMs for --day (no list, no sheet)")
    ap.add_argument("--day", help="with --yesterday-slack / --dry-run: list this day (YYYY-MM-DD) instead of yesterday")
    a = ap.parse_args(argv)

    export = load_bot_export(a.from_json)
    log("bot: %d recording(s), %d rep(s), %d owner(s)"
        % (len(export["records"]), len(export["reps"]), len(export["owners"])))
    export["records"], dropped = apply_guard(export["records"])
    kept_all = list(export["records"])
    this_month = dt.datetime.now(CT).strftime("%Y-%m")
    _log_guard(export, dropped, this_month)
    _log_lengths(export["records"], this_month)
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
    ns_weeks = closed_weeks(dt.datetime.now(CT).date())
    ns_table, ns_seen = new_starts_table(
        load_new_starts(S), ns_weeks, export["owners"],
        map_owners_to_offices(export["owners"], owner_of))
    log("new starts: %d owner(s), weeks with data: %s (wanted %s)" % (
        len(ns_table), ", ".join(ns_seen) or "none", ", ".join(w.isoformat() for w in ns_weeks)))
    extra_html = new_starts_html(ns_table, ns_seen)
    NEW_START_PCT.clear()
    NEW_START_PCT.update(ns_pct_by_owner(ns_table))
    NEW_START_COUNT.clear()
    NEW_START_COUNT.update(ns_count_by_owner(ns_table))
    if unmatched:
        log("owners with NO AppStream office match (2nd rounds blank): " + ", ".join(unmatched))
    no_uid = sum(1 for r in export["records"] if not r.get("uid"))
    if no_uid:
        log("%d recording(s) with no known uploader -> '%s'" % (no_uid, NO_OWNER))

    day = a.day or (dt.datetime.now(CT).date() - dt.timedelta(days=1)).isoformat()
    y_all = yesterday_rows(kept_all, dropped, export, guesses, day)
    y_rows = [r for r in y_all if in_yesterday_scope(r[2])]
    mine = sorted(o.get("name", "") for o in export["owners"]
                  if in_yesterday_scope(o.get("name", "")))
    log("yesterday list owners: %s (%d of %d recording(s) org-wide)" % (
        ", ".join(mine) or "NONE MATCHED", len(y_rows), len(y_all)))
    log("--- recordings sent %s: %d (%d counted) ---" % (
        day, len(y_rows), sum(1 for r in y_rows if r[5] == COUNTED)))
    for r in y_rows:
        print("  %-9s %-28s %-28s %4s min  score=%-5s %s" % tuple(r))
    unknown = no_owner_reps(kept_all, dropped, export, guesses, day)
    if a.ask_owners_only:
        log("asking %d rep(s) with no owner for %s" % (len(unknown), day))
        ask_owners(unknown, day)
        return 0
    if a.dry_run:
        print(yesterday_text(day, y_rows))
        for uid, name, time in unknown:
            log("would ask %s (%s) who their owner is: %s" % (name, uid, ask_owner_text(name, day, time)))
    elif a.yesterday_slack:
        # Before the sheet write: a 429 on the sheet must not cost the group
        # their morning list.
        try:
            post_yesterday(a.yesterday_slack, day, y_rows, a.yesterday_edit or "")
        except Exception as e:  # noqa: BLE001
            log("yesterday list NOT posted: %s" % e)
        # Only with the real group list, never on a test or an in-place edit.
        if a.yesterday_slack == YESTERDAY_DM and not a.yesterday_edit:
            ask_owners(unknown, day)

    if a.dry_run:
        cur = month_list[0] if month_list else ""
        log("--- %s, by owner ---" % cur)
        for r in [x for x in owner_rows if x[0] == cur]:
            print("  %-32s grab=%-4s hechas=%-5s pct=%-7s nota=%s" % tuple(r[1:]))
        log("--- %s, by rep (top 15) ---" % cur)
        for r in [x for x in rep_rows if x[0] == cur][:15]:
            print("  %-28s %-28s grab=%-4s nota=%s" % tuple(r[1:]))
        log("--- new starts, last %d weeks ---" % len(ns_seen))
        for r in ns_table:
            print("  %-32s sched=%-4s started=%-4s pct=%-7s avg=%s" % tuple(r))
        return 0

    ssid = a.sheet
    if a.create:
        ssid = create_sheet(S, a.share)
    if not ssid:
        raise SystemExit("no sheet id - run with --create once, then set SSID")
    if a.restyle and not a.create:
        restyle(S, ssid)
    write(S, ssid, owner_rows, rep_rows, totals, month_list)
    if a.email or a.email_to or a.email_org:
        # The report covers through yesterday: on the 1st, that's last month.
        month = month_label((dt.datetime.now(CT).date() - dt.timedelta(days=1)).strftime("%Y-%m"))
        if a.email_to:
            send_email([x.strip() for x in a.email_to.split(",") if x.strip()], month, totals,
                       owner_rows, ssid, show_link=False, extra_html=extra_html)
        elif a.email_org:
            return _send_org(month, totals, owner_rows, ssid, extra_html)
        else:
            send_email(TRIAL_TO, month, totals, owner_rows, ssid, extra_html=extra_html)
    return 0


def _send_org(month: str, totals: list, owner_rows: list, ssid: str, extra_html: str = "") -> int:
    """Whole org, at most once a day: a rerun must never mail ~56 people again.
    No sheet button: the sheet isn't shared with the owners."""
    from automations.org_sales_board.screenshot_email import resolve_distro
    lock = ORG_SENT_DIR / ("%s.sent" % dt.datetime.now(CT).strftime("%Y-%m-%d"))
    if lock.exists():
        log("org email already went out today (%s) - not sending again" % lock.name)
        return 0
    to = resolve_distro()
    if not to:
        log("org email NOT sent: no distro")
        return 1
    send_email(to, month, totals, owner_rows, ssid, show_link=False, extra_html=extra_html)
    ORG_SENT_DIR.mkdir(parents=True, exist_ok=True)
    lock.write_text(dt.datetime.now(CT).isoformat(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
