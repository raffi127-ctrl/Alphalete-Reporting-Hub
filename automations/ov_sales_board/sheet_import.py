"""Copy what is typed on our Alphalete SALES BOARD sheet into the new Sales Board artifact (Eve 2026-11-20).

For now the sheet is the only place people type: roll call, the rep extras (Trainer, Drug Test, Direct
Deposit, A-Play, Location, Gas Bonus, Add applied to), the weekly goal and the New Starts/Raf box. This
reads them and writes one JSON file per artifact database document; a Claude session then writes those
files into the artifact's database (ArtifactData batch, `file_path` per document).

    rollcall/<YYYY-MM-DD>   {marks: {<OwnerVille id>: code}}     one per day, last --weeks weeks
    meta/profiles           {reps: {<OwnerVille id>: {trainer, drug, dd, aplay, location, gas, addto}}}
    meta/goals              {office: <sheet 'Goal' row>, teams: {}}
    newstarts/<Monday>      {rows: [{name, trainer, email, orientation, location, team, rc[6], reason, notes, gender}],
                             board: [{name, fs, start, trainer, team, location, rc[6]}]}  every rep row on the sheet
                             this week; the page lists the ones OwnerVille does not have (Eve 11/20)
    meta/sync               {at}

Sheet reps are matched to OwnerVille ids by name against the board's data.json; the ones that do not
match (not in OwnerVille yet) are printed. Columns and rows are found by their labels.

    python -m automations.ov_sales_board.sheet_import --data automations/ov_sales_board/artifact_test/data.json --weeks 1
"""
import argparse
import datetime as dt
import json
import os
import re
import time
import unicodedata

from automations.recruiting_report.fill import _client
from automations.alphalete_sales_board import config as C, fill as F, week_roll as W
from automations.rep_sales_fill import board as B

FIELDS = {"trainer": "trainer", "drug": "drug test", "dd": "direct deposit", "aplay": "a-play",
          "location": "location", "gas": "gas bonus", "addto": "add applied"}
NS_FIELDS = {"trainer": "trainers", "email": "email", "orientation": "ran orientation", "location": "location",
             "team": "team", "reason": "reason lost", "notes": "notes", "gender": "gender"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"\b(gp|rt|roadtrip|nc)\b", "", s)
    return " ".join(re.sub(r"[^a-z ]", "", s).split())


def name_index(data):
    names = {}
    for pk, p in data["people"].items():
        names.setdefault(norm(p.get("name", "")), pk)
    for src in (data["saleNames"], data["names"]):
        for pk, n in src.items():
            names.setdefault(norm(n), pk)
    return names


def find(names, n):
    k = norm(n)
    if k in names:
        return names[k]
    t = k.split()
    if len(t) >= 2:
        hits = {pk for kk, pk in names.items() if kk.split()[:1] == t[:1] and kk.split()[-1:] == t[-1:]}
        if len(hits) == 1:
            return hits.pop()
    return None


def label_cols(g, row):
    return {" ".join(B.cell(g, row, c).split()).lower(): c for c in range(1, len(g[row - 1]) + 1)
            if B.cell(g, row, c).strip()}


# The bridge: a sheet in alphaletemarketing's Drive, shared with the account the Lucys' Sheets token
# uses (raffi127), because the cloud agent reads Drive as alphaletemarketing (Eve 2026-11-20).
BRIDGE_SHEET_ID = "1UfyUveaWQMFgFtXVzVsBTHtYKj1VPLTA0l4rAWRogo8"


def write_bridge(docs):
    """One row per database document: collection | doc_id | JSON. The cloud agent writes each row as-is."""
    ws = _client().open_by_key(BRIDGE_SHEET_ID).sheet1
    # ov_pull.py's rows (the OwnerVille data.json pieces) stay; only this script's rows are replaced.
    keep = [(r + ["", "", ""])[:3] for r in ws.get_all_values()[1:] if r and r[0] in ("file", "filemeta")]
    rows = [["collection", "doc_id", "json"]] + [[c, d, json.dumps(b, separators=(",", ":"), ensure_ascii=False)]
                                                  for c, d, b in docs] + keep
    for r in rows:
        if len(r[2]) > 49000:
            raise SystemExit("%s/%s is %d characters, over a sheet cell's limit" % (r[0], r[1], len(r[2])))
    ws.clear()
    ws.update(values=rows, range_name="A1", value_input_option="RAW")
    print("bridge sheet: %d documents written" % (len(rows) - 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="the board's data.json: key reps by OwnerVille id. Without it reps are keyed "
                                   "by name (byName) and the board page matches the names itself")
    ap.add_argument("--bridge", action="store_true",
                    help="also write every document into the bridge sheet the daily cloud agent reads")
    ap.add_argument("--weeks", type=int, default=1, help="weeks of roll call to copy, newest first")
    ap.add_argument("--out", default="output/ov_sales_board/sheet_seed")
    a = ap.parse_args()
    data = json.load(open(a.data, encoding="utf-8")) if a.data else None
    names = name_index(data) if data else None
    book = _client().open_by_key(C.SPREADSHEET_ID)
    titles = [w.title for w in book.worksheets()]
    os.makedirs(a.out, exist_ok=True)
    today = dt.date.today()
    this_mon = dt.date.fromisoformat(data["thisMon"]) if data else today - dt.timedelta(days=today.weekday())
    rc, prof, unmatched, goal, news, board = {}, {}, set(), None, [], []
    for w in range(a.weeks):
        mon = this_mon - dt.timedelta(days=7 * w)
        sun = mon + dt.timedelta(days=6)
        t = F.TN.find(titles, F.tab_title(sun))
        if not t:
            print("no tab for WE", sun)
            continue
        g = book.worksheet(t).get_all_values()
        time.sleep(2)
        last = B.last_rep_row(g)
        rcs = [c for c in range(1, len(g[2]) + 1) if B.cell(g, 3, c).strip().lower() == "roll call"][:7]
        head = label_cols(g, 1)
        sun_apps = B.day_blocks(g).get("Sunday", {}).get("Apps")
        def hcol(lab):
            return next((cc for h, cc in head.items() if h.startswith(lab)), None)
        for r in range(4, last + 1):
            n = B.cell(g, r, 3).strip()
            if not n:
                continue
            if w == 0:
                marks = [B.cell(g, r, c).strip() for c in rcs]
                if "T" not in marks:
                    board.append({"name": re.sub(r"\s*\(.*?\)", "", n).strip(), "rc": marks[:6],
                                  **{k: (B.cell(g, r, hcol(lab)).strip() if hcol(lab) else "")
                                     for k, lab in (("fs", "field status"), ("start", "start date"), ("trainer", "trainer"),
                                                    ("team", "team"), ("location", "location"))}})
            pk = find(names, n) if names else norm(n)
            if not pk:
                unmatched.add(re.sub(r"\s*\(.*?\)", "", n))
                continue
            seen_t = False
            for i, c in enumerate(rcs):
                v = B.cell(g, r, c).strip()
                if not v:
                    continue
                if v == "T":                      # T sits on every day after the termination: keep the first
                    if seen_t:
                        continue
                    seen_t = True
                rc.setdefault((mon + dt.timedelta(days=i)).isoformat(), {})[pk] = v
            if sun_apps and B.cell(g, r, sun_apps).strip().upper() == "F":
                rc.setdefault(sun.isoformat(), {})[pk] = "F"
            if w == 0:
                d = {}
                for k, lab in FIELDS.items():
                    c = next((cc for h, cc in head.items() if h.startswith(lab)), None)
                    v = B.cell(g, r, c).strip() if c else ""
                    if v:
                        d[k] = v
                if d:
                    prof[pk] = d
        if w == 0:
            goal = next((x.strip() for r in range(last + 1, len(g) + 1) if B.cell(g, r, 3).strip().lower() == "goal"
                         for x in g[r - 1][3:12] if x.strip()), None)
            title, first, end = W.new_starts_box(g, last + 1)
            if title:
                nh = label_cols(g, title + 1)
                nrc = [c for c in range(1, len(g[title + 1]) + 1)
                       if B.cell(g, title + 2, c).strip().lower() == "roll call"][:6]
                for r in range(first, end + 1):
                    n = B.cell(g, r, 3).strip()
                    if not n:
                        continue
                    row = {"name": n, "rc": [B.cell(g, r, c).strip() for c in nrc]}
                    for k, lab in NS_FIELDS.items():
                        c = next((cc for h, cc in nh.items() if h.startswith(lab)), None)
                        row[k] = B.cell(g, r, c).strip() if c else ""
                    news.append(row)
    at = dt.datetime.now().strftime("%-m/%-d %H:%M") if os.name != "nt" else dt.datetime.now().strftime("%#m/%#d %H:%M")
    key = "marks" if names else "byName"
    docs = [("rollcall", iso, {key: m, "at": at, "from": "sheet"}) for iso, m in sorted(rc.items())]
    docs.append(("meta", "profiles", {("reps" if names else "byName"): prof, "at": at}))
    docs.append(("meta", "goals", {"office": int(float(goal)) if goal and re.match(r"^[\d.]+$", goal) else None,
                                   "teams": {}, "at": at}))
    docs.append(("newstarts", this_mon.isoformat(), {"rows": news, "board": board, "at": at}))
    docs.append(("meta", "sync", {"at": at}))
    for coll, doc_id, body in docs:
        name = {"rollcall": "rc_%s.json" % doc_id, "newstarts": "newstarts_%s.json" % doc_id}.get(coll, doc_id + ".json")
        json.dump(body, open(os.path.join(a.out, name), "w"))
    if a.bridge:
        write_bridge(docs)
    print("days", len(rc), "marks", sum(len(m) for m in rc.values()), "profiles", len(prof),
          "goal", goal, "new starts", len(news))
    print("not in OwnerVille data:", ", ".join(sorted(unmatched)) or "-")


if __name__ == "__main__":
    main()
