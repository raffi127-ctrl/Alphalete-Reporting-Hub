"""Fill Raf's per-rep PNL tabs from this week's RH commission sheet.

Maud's Loom 2026-11-24: every time the RH sheet is made or changed, update
"All in One Local Office - Raf" -> Bas- / MJ- / OG- / Algemar-Alphaletes PNL 2026:

  * find the rep's row, go to the week's block ("WE 11/22"), and put
      Brought In = Revenue Brought In (payout tab C)
      Got Paid   = Final Pay (payout tab Q — no NPA / Clawback)
    (blank when $0, e.g. a held new start has Brought In but no Got Paid).
  * a rep on no tab yet goes on the tab of their TRAINER (sales board column
    "Trainer", DN on WE 11.29), into the first EXTRA row: A "Y", B team (board
    "Team", DS), D "Y" if not Entry Level / In Training, E first name, F last.
    Nobody is put on more than one tab. When EXTRA rows run low, more are added.
  * Leader (D) and Team (B) are kept in step with the board for reps on this
    week's sheet.
  * terminated (T all week) -> A "N", but only once the rep has no Brought In /
    Got Paid that week; with money that week it waits for the next run.
  * column A's filter always hides N and EXTRA (re-applied every run).
  * DD lines with no rep (payout tab "No rep on this DD line") -> RAF PNL 2026
    (NEW), row "Extra on DD", the week's column ($0 when there are none).

The tabs have a basic filter (N / EXTRA hidden): values can be written to
hidden rows, formatting needs updateCells (see raf-rep-pnl-tabs memory).

    python -m automations.commission_sheet.rep_pnl <RH sheet id>            # dry run
    python -m automations.commission_sheet.rep_pnl <RH sheet id> --write
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

TABS = ("Bas-Alphaletes PNL 2026", "MJ-Alphaletes PNL 2026",
        "OG-Alphaletes PNL 2026", "Algemar-Alphaletes PNL 2026")
#: Board / sheet nicknames -> the name on the PNL tabs.
ALIASES = {"mj": "Amjad Malhas", "amjad malhas": "Amjad Malhas",
           "bas": "Basil Elhassan", "bas el hassan": "Basil Elhassan",
           "basil": "Basil Elhassan", "algemar": "Algemar Kennel",
           "justin carlos avila": "Justin Avila", "david mcavoy": "David McCavoy"}
NOT_LEADER = ("entry", "in training")
#: rep -> tab when the board has no trainer for them (Maud 2026-11-24)
PLACE = {"ximena lazcano lopez": "Algemar-Alphaletes PNL 2026"}
SUMMARY_TAB, EXTRA_ON_DD = "RAF PNL 2026 (NEW)", "extra on dd"
OFF = "all week — not paid"
MIN_EXTRA = 3                       # keep at least this many EXTRA rows per tab


def _log(m=""):
    print(m, flush=True)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class Tab:
    def __init__(self, ws, values, labels):
        self.ws, self.title = ws, ws.title
        self.v, self.labels = values, labels
        self.rows = []                              # (row, flag, "First Last")
        self.extra = []                             # empty EXTRA rows
        for i, r in enumerate(values[2:], 3):
            r = list(r) + [""] * 6
            flag = str(r[0]).strip().upper()
            name = f"{str(r[4]).strip()} {str(r[5]).strip()}".strip()
            if flag == "EXTRA" and not name:
                self.extra.append(i)
            elif name and flag in ("Y", "N", "EXTRA"):
                self.rows.append((i, flag, name))

    def week_col(self, label):
        """0-based column of 'Brought In' for 'WE m/d' (row 1)."""
        top = self.labels
        for j, x in enumerate(top):
            if " ".join(str(x).split()).lower() == label.lower():
                return j
        return None


def load(sh):
    out = []
    for t in TABS:
        ws = sh.worksheet(t)
        top = ws.get_values("1:1")                # week labels are dates: formatted
        out.append(Tab(ws, ws.get_values(value_render_option="UNFORMATTED_VALUE"),
                       top[0] if top else []))
    return out


def find(tabs, name, col):
    """(tab, row) for a rep: their Y row; else a named EXTRA row (Algemar's
    own); else the row that has the latest week filled in; None if nowhere."""
    from automations.commission_sheet.names import match_person
    everyone = sorted({n for t in tabs for _i, _f, n in t.rows})
    want = ALIASES.get(name.strip().lower(), name)
    m = want if want in everyone else match_person(want, everyone)[0]
    if not m:
        return None
    hits = [(t, i, f) for t in tabs for i, f, n in t.rows if n == m]

    def last_filled(t, i):
        r = t.v[i - 1] if i - 1 < len(t.v) else []
        return max([j for j in range(6, min(len(r), (col or 999))) if str(r[j]).strip()
                    and j % 4 in (2, 3)] or [-1])
    rank = {"Y": 2, "EXTRA": 1, "N": 0}
    hits.sort(key=lambda h: (rank.get(h[2], 0), last_filled(h[0], h[1])), reverse=True)
    return hits[0][0], hits[0][1]


def trainer_info(dd_sunday):
    """{rep key: (trainer, team, level)} from the board after the DD week,
    then the DD week's board (sales board columns 'Trainer' / 'Team')."""
    from automations.terminated_reps import board as BD
    from automations.commission_sheet.pct_payout import _grid, _name_key, _titles, _box_rows
    sh = BD.open_by_key(BD.SHEET_ID)
    by_date = dict(BD.week_tabs(sh, dd_sunday + dt.timedelta(days=7)))
    out = {}
    for d in (dd_sunday + dt.timedelta(days=7), dd_sunday):
        title = by_date.get(d)
        if not title:
            continue
        g = _grid(sh, title)
        lay = BD.find_layout(g)
        ti = _titles(BD, g)
        tc, mc, lc = ti.get("trainer"), ti.get("team"), ti.get("leadership status")
        for r in list(lay.roster_rows) + list(_box_rows(BD, g, lay)):
            for nc in (lay.name_col, lay.box_name_col):
                k = _name_key(BD._cell(g, r, nc))
                if not k or k in out:
                    continue
                tr = str(BD._cell(g, r, tc) or "").strip() if tc else ""
                if tr:
                    out[k] = (tr, str(BD._cell(g, r, mc) or "").strip() if mc else "",
                              str(BD._cell(g, r, lc) or "").strip() if lc else "")
    return out


def fill(rh_sheet_id, write=False, log=_log):
    from automations.commission_sheet import pct_payout as P
    from automations.recruiting_report.fill import open_by_key
    from automations.shared.workbooks import ALL_IN_ONE_RAF
    rh = open_by_key(rh_sheet_id)
    pay = P._payout_ws(rh).get_values(value_render_option="UNFORMATTED_VALUE")
    raw = rh.worksheet(P.TAB_RAW).get_values()
    ix = {h.strip(): i for i, h in enumerate(raw[0])}
    dds = P.dd_sunday(raw[1:], ix)
    label = f"WE {dds.month}/{dds.day}"
    reps = []
    for r in pay[1:]:
        r = list(r) + [""] * 20
        if r[0] and r[0] != "TOTAL" and str(r[4]) != P.NOTE_EXTRA:
            reps.append((str(r[0]).strip(), _num(r[2]), _num(r[16]), str(r[4])))

    sh = open_by_key(ALL_IN_ONE_RAF)
    tabs = load(sh)
    col = tabs[0].week_col(label)
    if col is None:
        raise RuntimeError(f"no {label!r} block on {TABS[0]!r}")
    writes, adds, unplaced, leader = {}, [], [], []
    trainers = trainer_info(dds)
    prev_off = _prev_off(dds, log)
    seen = set()
    for name, brought, got, rule in reps:
        hit = find(tabs, name, col)
        if not hit:                                 # new: their trainer's tab
            info = trainers.get(P._name_key(name))
            home = find(tabs, info[0], col) if info else None
            forced = PLACE.get(P._name_key(name))
            if forced:
                ft = next(t for t in tabs if t.title == forced)
                team = (info[1] if info else "") or _main_team(ft)
                info = (info[0] if info else "(set by hand)", team, info[2] if info else "")
                home = (ft, None)
            if not home:
                unplaced.append(name + (f" (trainer {info[0]!r} not on a PNL tab)" if info
                                        else " (not on the board — no trainer)"))
                continue
            t = home[0]
            if not t.extra:
                unplaced.append(f"{name} ({t.title} has no EXTRA row left)")
                continue
            i = t.extra.pop(0)
            first, _, last = name.partition(" ")
            lvl = info[2].lower()
            lead = "" if (not lvl or lvl.startswith(NOT_LEADER)) else "Y"
            writes.setdefault(t, []).append((f"A{i}:F{i}", [["Y", info[1], "", lead, first, last]]))
            t.rows.append((i, "Y", name))
            adds.append(f"{name} -> {t.title.split('-')[0]} row {i} (trainer {info[0]}, "
                        f"team {info[1] or '?'}{', leader' if lead else ''})")
            hit = (t, i)
        t, i = hit
        seen.add((t.title, i))
        cur = list(t.v[i - 1]) + [""] * (col + 2) if i - 1 < len(t.v) else [""] * (col + 2)
        want = [round(brought, 2) or "", round(got, 2) or ""]
        if [_num(cur[col]) or "", _num(cur[col + 1]) or ""] != [_num(w) or "" for w in want]:
            a1 = f"{_a1(col)}{i}:{_a1(col + 1)}{i}"
            writes.setdefault(t, []).append((a1, [want]))
        info = trainers.get(P._name_key(name))
        # Team (B) follows the board
        if info and info[1] and str(cur[1]).strip() != info[1] and cur[0] != "":
            writes.setdefault(t, []).append((f"B{i}", [[info[1]]]))
            leader.append(f"{name}: Team {str(cur[1]).strip() or '(blank)'} -> {info[1]}")
        # terminated: N once there's no money that week
        if OFF in rule:
            if brought or got:
                leader.append(f"{name}: terminated, but has money this week — N next week")
            elif str(cur[0]).strip().upper() == "Y":
                writes.setdefault(t, []).append((f"A{i}", [["N"]]))
                leader.append(f"{name}: N (terminated)")
        # Leader (D) follows the board level, for levels we know
        lv = rule.split(" · ")[0].lower()
        if not lv.startswith(("level", "mastermind")) and not lv.startswith(NOT_LEADER) \
                and info and info[2]:
            lv = info[2].lower()
        if lv.startswith(("level", "mastermind")) or lv.startswith(NOT_LEADER):
            d = "Y" if lv.startswith(("level", "mastermind")) else ""
            if str(cur[3]).strip().upper() != d:
                writes.setdefault(t, []).append((f"D{i}", [[d]]))
                leader.append(f"{name}: Leader {'Y' if d else 'blank'}")

    for t in tabs:
        for i, f, nm in t.rows:
            if f == "Y" and (t.title, i) not in seen and P._name_key(nm) in prev_off:
                writes.setdefault(t, []).append((f"A{i}", [["N"]]))
                leader.append(f"{nm}: N (terminated last week, no money this week)")

    extra_dd = round(sum(_num(r[2]) for r in pay[1:]
                         if len(r) > 4 and str(r[4]) == P.NOTE_EXTRA), 2)
    sw = sh.worksheet(SUMMARY_TAB)
    top = sw.get_values("1:1")
    top = top[0] if top else []
    scol = next((j for j, x in enumerate(top)
                 if " ".join(str(x).split()).lower() == label.lower()), None)
    srow = next((k for k, r in enumerate(sw.get_values("A1:A120"), 1)
                 if r and str(r[0]).strip().lower() == EXTRA_ON_DD), None)
    summary = None
    if scol is None or srow is None:
        unplaced.append(f"{SUMMARY_TAB}: no {label!r} column / 'Extra on DD' row")
    else:
        a1 = f"{_a1(scol)}{srow}"
        now = sw.get_values(a1, value_render_option="UNFORMATTED_VALUE")
        now = _num(now[0][0]) if now and now[0] else 0
        cell = sw.get_values(a1)
        if round(now, 2) != extra_dd or not (cell and cell[0] and cell[0][0]):
            summary = (a1, extra_dd)              # $0 when none (Maud 2026-11-24)
        log(f"   rep PNL: Extra on DD ({label}) = ${extra_dd:,.2f}"
            + ("" if summary else " (already there)"))

    tot = next((_num(r[2]) for r in pay[1:] if r and r[0] == "TOTAL"), 0)
    placed = sum(b for nm, b, _g, _r in reps
                 if not any(nm.startswith(u.split(" (")[0]) for u in unplaced))
    log(f"   rep PNL check: on rep tabs ${placed:,.2f} + Extra on DD ${extra_dd:,.2f}"
        f" = ${placed + extra_dd:,.2f} vs payout TOTAL ${tot:,.2f}"
        + ("  ✓" if abs(placed + extra_dd - tot) < 0.01 else "  !! does not match"))

    n = sum(len(w) for w in writes.values())
    log(f"   rep PNL ({label}): {n} cell range(s) to write"
        + (f"; new: {'; '.join(adds)}" if adds else ""))
    for m in leader:
        log(f"   rep PNL: {m}")
    for m in unplaced:
        log(f"   !! rep PNL: {m}")
    if write:
        for t, w in writes.items():
            t.ws.batch_update([{"range": a, "values": v} for a, v in w],
                              value_input_option="USER_ENTERED")
        if summary:
            sw.update(range_name=summary[0], values=[[summary[1]]],
                      value_input_option="USER_ENTERED")
        for t in tabs:
            top_up_extra(sh, t, log)
        hide_n_extra(sh, log)
    return {"writes": n, "adds": adds, "unplaced": unplaced}


def _main_team(t):
    import collections
    c = collections.Counter(str((list(t.v[i - 1]) + [""] * 2)[1]).strip()
                            for i, f, _n in t.rows if f == "Y")
    c.pop("", None)
    return c.most_common(1)[0][0] if c else ""


def _prev_off(dds, log=_log):
    """Name keys marked 'T all week' on LAST week's RH sheet."""
    try:
        from automations.commission_sheet import pct_payout as P
        from automations.commission_sheet.drive_auth import service
        from automations.commission_sheet.weekly_drop import our_sheets
        from automations.recruiting_report.fill import open_by_key
        prev = [f for w, f in our_sheets(service()) if w == dds - dt.timedelta(days=7)]
        if not prev:
            return set()
        v = P._payout_ws(open_by_key(prev[0]["id"])).get_values()
        return {P._name_key(r[0]) for r in v[1:] if len(r) > 4 and OFF in str(r[4])}
    except Exception as e:                          # noqa: BLE001
        log(f"   rep PNL: last week's sheet not read ({type(e).__name__}: {e})")
        return set()


def hide_n_extra(sh, log=_log):
    """Column A filter hides N and EXTRA, over every rep + EXTRA row (Maud
    2026-11-24). Keeps the other columns' filters; rows are not re-sorted."""
    meta = sh.fetch_sheet_metadata(
        {"fields": "sheets(properties(title,sheetId),basicFilter)"})
    reqs = []
    for s in meta["sheets"]:
        title = s["properties"]["title"]
        if title not in TABS:
            continue
        bf = s.get("basicFilter") or {"range": {"sheetId": s["properties"]["sheetId"],
                                                "startRowIndex": 1, "startColumnIndex": 0}}
        col_a = sh.worksheet(title).get_values("A1:A400")
        last = max([k for k, r in enumerate(col_a, 1)
                    if r and str(r[0]).strip().upper() in ("Y", "N", "EXTRA")] or [2])
        rng = dict(bf["range"], endRowIndex=max(last, bf["range"].get("endRowIndex", 0)))
        specs = [x for x in bf.get("filterSpecs", []) if x.get("columnIndex") != 0]
        specs.insert(0, {"columnIndex": 0,
                         "filterCriteria": {"hiddenValues": ["EXTRA", "N"]}})
        # no sortSpecs: re-sending them re-sorts the rows on every pass
        new = {"range": rng, "filterSpecs": specs}
        reqs.append({"setBasicFilter": {"filter": new}})
    if reqs:
        sh.batch_update({"requests": reqs})
        log(f"   rep PNL: N / EXTRA filtered out on {len(reqs)} tab(s)")


def top_up_extra(sh, t, log=_log):
    """Keep at least MIN_EXTRA empty EXTRA rows: copy the last one below itself."""
    ws = t.ws
    v = ws.get_values("A1:F400")
    extra = [i for i, r in enumerate(v, 1)
             if r and str(r[0]).strip().upper() == "EXTRA"
             and not "".join(str(x) for x in (list(r) + [""] * 6)[4:6]).strip()]
    if not extra or len(extra) >= MIN_EXTRA:
        return 0
    need, last = MIN_EXTRA - len(extra), extra[-1]
    src = {"sheetId": ws.id, "startRowIndex": last - 1, "endRowIndex": last}
    sh.batch_update({"requests": [
        {"insertDimension": {"range": {"sheetId": ws.id, "dimension": "ROWS",
                                       "startIndex": last - 1, "endIndex": last - 1 + need},
                             "inheritFromBefore": False}},
        {"copyPaste": {"source": {**src, "startRowIndex": last - 1 + need,
                                  "endRowIndex": last + need},
                       "destination": {"sheetId": ws.id, "startRowIndex": last - 1,
                                       "endRowIndex": last - 1 + need},
                       "pasteType": "PASTE_NORMAL"}}]})
    log(f"   rep PNL: {need} EXTRA row(s) added on {t.title}")
    return need


def _a1(col0):
    from openpyxl.utils import get_column_letter
    return get_column_letter(col0 + 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sheet_id", help="this week's RH sheet id")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    fill(a.sheet_id, write=a.write)
    return 0


if __name__ == "__main__":
    sys.exit(main())
