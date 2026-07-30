"""Search the raw Tableau ORG DD Detail crosstab for specific ICD names. LUCY 1.

One question this answers: do the bulletin-only names — Justin Fermin, Marcos
Barbosa, Karrington Moody, Milan Godbolt — have weekly DD data in the Tableau
source, or do they exist ONLY as the single manual figure the VA types onto the
podium list? (DD_SOURCES.md, "Still open on the podium".) If Tableau has them,
they can be wired in as excluded-but-tracked rows and get full four-week history
like Jacob Dover. If it does not, the single manual number is all that exists and
the '—' in Tracked Separately is the honest thing to show.

READ-ONLY. Downloads the `ORG DD Detail` crosstab (the same view the override
fill already uses) and searches every cell for the target names. Writes nothing
to any report tab — results land on a throwaway `_dd_search` tab of the override
workbook, readable from any machine, plus output/override_bulletin/dd_search.csv.

    lucy rerun dd_name_search          # on Lucy 1 (needs Raf's Tableau login)

The crosstab is HIERARCHICAL (empty dimensions collapse per row), so a name and
its amount are not in fixed columns — we match by CONTENT, exactly as
pulls.parse_dd_captain does: any cell equal to a target name marks the row, and
the amount is read from that row's money cells with their dated descriptions.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from automations.override_bulletin import pulls as P
from automations.override_bulletin import fill as F

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DUMP_TAB = "_dd_search"
OUT = Path(__file__).resolve().parents[2] / "output" / "override_bulletin"

# The four whose history is in question. Aliases are resolved too, so a Tableau
# spelling still matches the name the bulletin uses.
TARGETS = ["Justin Fermin", "Marcos Barbosa", "Karrington Moody", "Milan Godbolt"]

# Owners whose tab cell = Tableau part + a Credico deposit (the second DD source).
# Used only as a SAFETY skip-list when Credico can't be pulled, so the populate
# never overwrites their cell with a Tableau-only figure and drops the deposit.
CREDICO_OWNERS = ["Abel Draper", "Jahvid Thompson"]

_WK_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


def _keys(names, aliases):
    """Every name folded to a match key, plus its alias-canonical key — so a
    Tableau spelling that differs only by alias still lands."""
    out = {}
    for n in names:
        out[P._norm_name(n)] = n
        out[P._norm_name(F.canon(n, aliases))] = n
    return out


# Periods to pull. The crosstab's default download carries only the just-closed
# week, so history needs the Period filter: July covers 7.5 / 7.12 / 7.19, June
# covers 6.28. period_candidates() handles the 'Period 2026-7' vs 'Period 7'
# naming drift.
PERIODS = ["Period 2026-7", "Period 2026-6"]


def _mdy(dd_week):
    """'7/19/2026' -> '7.19.26' so it matches the bulletin's week labels."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", dd_week or "")
    return f"{int(m.group(1))}.{int(m.group(2))}.{m.group(3)[-2:]}" if m else (dd_week or "").strip()


def _pull(page=None, verbose=True, targets=TARGETS):
    """Download the period crosstabs and fold them into per-name weekly totals.

    Returns (per, all_names). `per` is {name: {'M.D.YY': {raw, clean, rows}}}
    where `clean` drops the ledger/fee lines so it matches what the VA types, and
    `raw` keeps them. Opens its own Tableau session if `page` is None.

    `targets` limits the fold to those names (the default four special cases). Pass
    `targets=None` to keep EVERY owner — the full-org independent re-pull Megan
    asked for (2026-07-30): prove our mapping produces the week's DD without
    reading the VA's tab.
    """
    aliases = F.load_alias_map()
    keys = _keys(targets, aliases) if targets else None
    OUT.mkdir(parents=True, exist_ok=True)

    own = page is None
    ctx = None
    if own:
        from automations.shared.tableau_patchright import tableau_session
        ctx = tableau_session(headless=True, verbose=verbose)
        page = ctx.__enter__()

    header, data, seen_uk = None, [], set()
    try:
        from automations.shared.tableau_patchright import download_crosstab_patchright
        for label in PERIODS:
            got = False
            for cand in P.period_candidates(label):
                csv_path = OUT / f"dd_search_{cand.replace(' ', '_')}.csv"
                url = P._with_filter(P.DD_DETAIL_VIEW, "Period", cand)
                try:
                    download_crosstab_patchright(url, P.DD_DETAIL_SHEET, csv_path,
                                                 page=page, verbose=verbose)
                except Exception as e:  # noqa: BLE001
                    if verbose:
                        print(f"  {cand}: no crosstab ({type(e).__name__})")
                    continue
                rows = P.read_crosstab(csv_path)
                if len(rows) <= 1:
                    if verbose:
                        print(f"  {cand}: empty")
                    continue
                if header is None:
                    header = rows[0]
                uk = P._hdr_col(rows[0], "cl.Unique Key")
                added = 0
                for r in rows[1:]:
                    k = r[uk] if uk is not None and uk < len(r) else None
                    if k and k in seen_uk:
                        continue          # same line in two period pulls — once
                    if k:
                        seen_uk.add(k)
                    data.append(r)
                    added += 1
                if verbose:
                    print(f"  {cand}: {added} new row(s)")
                got = True
                break
            if not got and verbose:
                print(f"  {label}: no period candidate returned rows")
    finally:
        if own and ctx is not None:
            ctx.__exit__(None, None, None)

    header = header or []
    if verbose:
        print(f"-> ORG DD Detail: {len(data)} unique row(s) across {len(PERIODS)} period(s)")

    all_names = set()
    for r in data:
        for c in r:
            s = (c or "").strip()
            if s and re.search(r"[A-Za-z]", s) and not P._num_locale(s) \
               and len(s.split()) <= 4 and "$" not in s:
                all_names.add(s)

    # Columns BY HEADER LABEL (CLAUDE.md). Layout decoded 2026-07-24:
    #   cl.ICD Owner Name = owner   cl.DD Week = week   Total $ to ICD = dollars
    #   cl.Status / cl.Category flag the LEDGER/fee lines the VA's figure excludes.
    oc = P._hdr_col(header, "cl.ICD Owner Name")
    wc = P._hdr_col(header, "cl.DD Week")
    ac = P._hdr_col(header, "Total $ to ICD")
    sc = P._hdr_col(header, "cl.Status")
    cc = P._hdr_col(header, "cl.Category")

    def cell(r, i):
        return r[i].strip() if i is not None and i < len(r) else ""

    # per name -> per week -> totals + a SELF-CHECK on the fee rule. The rule is
    # "drop any line whose Status/Category says 'ledger'"; the fee lines we have
    # seen are small NEGATIVE deductions (Justin -$100 BG check). Two ways it can
    # misfire, both tracked so drift can't be silent (Megan 2026-07-24):
    #   * a POSITIVE line dropped as ledger  -> real DD wrongly excluded (too low)
    #   * a NEGATIVE line KEPT in clean       -> a fee the rule missed (too low)
    per = {}
    for r in data:
        owner_cell = cell(r, oc)
        if keys is not None:
            hit = keys.get(P._norm_name(owner_cell))
        else:
            hit = owner_cell.strip()        # keep EVERY owner (full re-pull)
        if not hit:
            continue
        wk = _mdy(cell(r, wc)) or "(no week)"
        amt = P._num_locale(cell(r, ac)) or 0.0
        ledger = "ledger" in cell(r, sc).lower() or "ledger" in cell(r, cc).lower()
        d = per.setdefault(hit, {}).setdefault(
            wk, {"raw": 0.0, "clean": 0.0, "rows": 0,
                 "dropped_pos": 0.0, "neg_kept": 0.0})
        d["raw"] += amt
        d["rows"] += 1
        if ledger:
            if amt > 0:
                d["dropped_pos"] += amt        # real DD wrongly dropped
        else:
            d["clean"] += amt
            if amt < 0:
                d["neg_kept"] += amt           # a deduction the rule missed
    return per, all_names


def _fee_flags(name, wk, d):
    """Warnings if the fee rule looks like it misfired for this name/week."""
    out = []
    if d.get("dropped_pos", 0) > 0.5:
        out.append(f"⚠ {name} {wk}: dropped ${d['dropped_pos']:,.2f} of POSITIVE "
                   f"lines as 'ledger' — a real DD line may be misclassified; the "
                   f"figure could be too LOW")
    if d.get("neg_kept", 0) < -0.5:
        out.append(f"⚠ {name} {wk}: kept ${d['neg_kept']:,.2f} of NEGATIVE lines "
                   f"in the total — a fee/deduction the 'ledger' rule did not "
                   f"catch; the figure could be too LOW")
    return out


def _newest_week(weeks):
    """The latest 'M.D.YY' key in a week->... dict, by date."""
    def keyf(w):
        return [int(x) for x in w.split(".")] if re.match(r"^\d+\.\d+\.\d+$", w) else [0]
    return max(weeks, key=keyf) if weeks else None


def accumulate(write=False, page=None, verbose=True):
    """Write this week's fees-excluded figure for the special-case names into the
    'ICD (Special Cases)' section on the DD tab, current-week column — the weekly
    step that builds their 4-week history one week at a time (the DD Detail view
    only ever serves the current week). DRY-RUN unless write=True; only ever
    touches the special rows' current-week cell, so it is safe to re-run.
    """
    from automations.override_bulletin import dd_data as D
    from automations.recruiting_report import fill as _fill
    aliases = F.load_alias_map()

    per, _ = _pull(page=page, verbose=verbose)
    figs, flags = {}, []
    for name in TARGETS:
        # Combine the week's deposit-date labels into the week-ending Sunday — the
        # current DD week arrives as Sat+Sun labels and the tab column is their sum
        # (Megan 2026-07-30). Picking the newest single label alone undercounts a
        # special name paid on the Saturday.
        weeks = _regroup_weeks(per.get(name) or {})
        nw = _newest_week(weeks)
        if nw:
            figs[name] = (nw, round(weeks[nw]["clean"], 2))
            flags += _fee_flags(name, nw, weeks[nw])
    for f in flags:
        print(f)

    ws = _fill._client().open_by_key(D.WORKBOOK_ID).worksheet(D.DD_TAB)
    vals = ws.get_all_values()
    hdr = vals[0]
    wcol = next((i for i, h in enumerate(hdr)
                 if re.match(r"^\s*\d{1,2}\.\d{1,2}\.\d{2,4}\s*$", h or "")), None)
    tabweek = hdr[wcol].strip() if wcol is not None else ""
    # locate the 'ICD (Special Cases)' rows by name
    special_rows, on = {}, False
    for i, r in enumerate(vals, 1):
        lab = " ".join((r[0] or "").split()).lower()
        if not on:
            on = lab.startswith("icd (special cases)")
            continue
        nm = (r[0] or "").strip()
        if not nm:
            break
        special_rows[P._norm_name(F.canon(nm, aliases))] = i

    print(f"tab current week = {tabweek!r}; special rows found = {len(special_rows)}")
    wrote = 0
    for name, (wk, amt) in figs.items():
        rk = P._norm_name(F.canon(name, aliases))
        row = special_rows.get(rk)
        if row is None:
            print(f"  ⚠ {name}: no row in the 'ICD (Special Cases)' section — skipped")
            continue
        if wk != tabweek:
            print(f"  ⚠ {name}: Tableau week {wk} != tab week {tabweek} — skipped "
                  f"(the tab has not rolled to this week yet)")
            continue
        if write:
            ws.update_cell(row, wcol + 1, amt)
        print(f"  {'wrote' if write else '[dry-run] would write'} {name}: "
              f"${amt:,.2f} → row {row}, week {tabweek}")
        wrote += 1
    print(f"\n{'wrote' if write else 'would write'} {wrote} figure(s)"
          + ("" if write else "  (pass --write to actually write)"))
    return figs


def accumulate_all(write=False, page=None, verbose=True):
    """Populate the DD tab's CURRENT-WEEK column for EVERY Active-YES owner from
    OUR Tableau mapping — the switch off the VA hand-fill (Megan 2026-07-30).
    Combined week (Sat+Sun deposit dates) + fees excluded. DRY-RUN unless write=True.

    SKIPS the Credico owners (Abel Draper / Jahvid Thompson): their tab cell is the
    Tableau part PLUS a Credico deposit folded by the separate credico step, so
    overwriting it with the Tableau-only figure would drop the Credico money. Only
    ever writes the current-week cell of an Active-YES row. SANDBOX/dry-run first
    (CLAUDE.md) — this touches the whole week column."""
    from automations.override_bulletin import dd_data as D
    from automations.recruiting_report import fill as _fill
    aliases = F.load_alias_map()

    per, _ = _pull(page=page, verbose=verbose, targets=None)
    per = {o: _regroup_weeks(wk) for o, wk in per.items()}

    ws = _fill._client().open_by_key(D.WORKBOOK_ID).worksheet(D.DD_TAB)
    vals = ws.get_all_values()
    hdr = vals[0]
    wcol = next((i for i, h in enumerate(hdr)
                 if re.match(r"^\s*\d{1,2}\.\d{1,2}\.\d{2,4}\s*$", h or "")), None)
    if wcol is None:
        print("✗ no week column found on the tab")
        return {}
    tabweek = hdr[wcol].strip()

    # our combined-week figure per alias-canonical key
    ourk = {}
    for o, wk in per.items():
        d = wk.get(tabweek)
        if not d:
            continue
        k = P._norm_name(F.canon(o, aliases))
        ourk[k] = round(ourk.get(k, 0) + d["clean"], 2)

    # Fold Credico (the SECOND DD source) so those owners' figure = Tableau part
    # + Credico deposit, exactly as the tab holds it. Same source dd_data uses;
    # if it can't be reached (needs credico_fetch on Lucy 1) those owners come out
    # short and are flagged rather than silently wrong.
    credico_amts, credico_ok = {}, False
    try:
        from automations.credico import report as C
        cowners, _cnotes, _coff = C.pull(tabweek, aliases=aliases, verbose=False)
        credico_amts = {P._norm_name(F.canon(o, aliases)): amt
                        for o, amt in cowners.items()}
        credico_ok = True
    except Exception as e:  # noqa: BLE001
        print(f"⚠ Credico NOT folded ({type(e).__name__}) — Credico owners will be "
              f"short; on Lucy 1 run `lucy rerun credico_fetch` first")

    # Safety: if Credico is UNAVAILABLE, never overwrite a known Credico owner's
    # cell — a Tableau-only figure would drop their deposit. Skip + flag them.
    credico_skip = set() if credico_ok else {
        P._norm_name(F.canon(n, aliases)) for n in CREDICO_OWNERS}

    changes, same, folded, missing, held, wrote = [], 0, [], [], [], 0
    for i, r in enumerate(vals[1:], start=2):
        nm = (r[0] or "").strip()
        if not nm or nm.lower().startswith("total"):
            continue
        if not (len(r) > 1 and r[1].strip().upper() == "YES"):
            continue
        k = P._norm_name(F.canon(nm, aliases))
        if k in credico_skip:
            held.append(nm)
            continue
        tableau = ourk.get(k)
        cred = credico_amts.get(k, 0.0)
        cur = D.money(r[wcol]) if wcol < len(r) else 0.0
        if tableau is None and not cred:
            if abs(cur) > 0.5:
                missing.append((nm, cur))     # tab has a figure, our pull doesn't
            continue
        ours = round((tableau or 0.0) + cred, 2)
        if cred:
            folded.append((nm, tableau or 0.0, cred, ours))
        if abs(ours - cur) > 0.5:
            changes.append((nm, cur, ours))
        else:
            same += 1
        if write:
            ws.update_cell(i, wcol + 1, ours)
            wrote += 1

    print(f"\ntab current week = {tabweek!r}")
    print(f"matches already on the tab: {same}")
    print(f"Credico folded ({'ok' if credico_ok else 'UNAVAILABLE'}): "
          + (", ".join(f"{nm} = ${t:,.0f}+${c:,.0f}" for nm, t, c, _ in folded)
             or "none"))
    if held:
        print(f"HELD (Credico unavailable, not overwritten): {', '.join(held)}")
    if missing:
        print("tab has a figure our pull does NOT (check alias / Active flag):")
        for nm, cur in missing:
            print(f"   {nm}: tab ${cur:,.2f}")
    print(f"would change {len(changes)} cell(s)" if not write
          else f"WROTE {wrote} cell(s)")
    for nm, cur, ours in sorted(changes, key=lambda x: -abs(x[2] - x[1])):
        print(f"   {nm}: tab ${cur:,.2f} -> ours ${ours:,.2f}  "
              f"(Δ ${ours - cur:,.2f})")
    return {"changes": changes, "same": same, "folded": folded,
            "held": held, "missing": missing}


def _col_letter(idx0):
    """0-based column index -> A1 letter(s)."""
    s = ""
    n = idx0 + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def roll_week(ws, due_label=None, dry_run=True, verbose=True):
    """Insert the new week-ending column at the leftmost week position, so nobody
    has to hand-roll the tab (Megan 2026-07-30). The Avg DD / Active Owners rows
    reference the leftmost week column by RELATIVE ref, so a bare insert would
    leave them pointing at the OLD week — we copy those formula cells into the new
    column (PASTE_FORMULA adjusts the ref to the new column), and blank the owner
    DATA rows for the populate to fill. Idempotent: no-op if the leftmost week is
    already the due week. DRY-RUN unless dry_run=False. Run on `_dd_sandbox` first."""
    from automations.override_bulletin import dd_data as D
    vals = ws.get_all_values()
    hdr = vals[0]
    wcol0 = next((i for i, h in enumerate(hdr)
                  if re.match(r"^\s*\d{1,2}\.\d{1,2}\.\d{2,4}\s*$", h or "")), None)
    if wcol0 is None:
        print("✗ no week column found"); return None
    leftmost = hdr[wcol0].strip()
    due = due_label or D.fmt_week(D.week_just_ended())
    if leftmost == due:
        print(f"leftmost week is already {due!r} — no roll needed"); return None

    col = _col_letter(wcol0)                       # current-week column letter
    nrows = len(vals)
    formula_col = ws.get(f"{col}1:{col}{nrows}", value_render_option="FORMULA")
    formula_rows, data_rows = [], []
    for i, cell in enumerate(formula_col, start=1):
        v = (cell[0] if cell else "")
        if i == 1:
            continue                               # header handled separately
        (formula_rows if str(v).startswith("=") else data_rows).append((i, v))

    print(f"\n{'[dry-run] ' if dry_run else ''}roll: insert new column {col} = {due!r}, "
          f"push {leftmost!r} right")
    print(f"  formula cells to re-point (copied so refs follow to {col}): {len(formula_rows)}")
    print(f"  owner/data cells to blank for the populate: "
          f"{sum(1 for _, v in data_rows if str(v).strip() not in ('', '$0.00', '0'))}")
    if dry_run:
        return {"due": due, "insert_at": col, "formula_rows": len(formula_rows),
                "data_rows": len(data_rows)}

    gid = ws.id
    # 1) insert a blank column at the leftmost-week position
    ws.spreadsheet.batch_update({"requests": [{"insertDimension": {
        "range": {"sheetId": gid, "dimension": "COLUMNS",
                  "startIndex": wcol0, "endIndex": wcol0 + 1},
        "inheritFromBefore": False}}]})
    # 2) copy the OLD week column (now shifted to wcol0+1) into the new one,
    #    PASTE_FORMULA so relative refs adjust to the new column
    ws.spreadsheet.batch_update({"requests": [{"copyPaste": {
        "source": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": nrows,
                   "startColumnIndex": wcol0 + 1, "endColumnIndex": wcol0 + 2},
        "destination": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": nrows,
                        "startColumnIndex": wcol0, "endColumnIndex": wcol0 + 1},
        "pasteType": "PASTE_FORMULA"}}]})
    # 3) header + blank the data rows in the new column
    ws.update_cell(1, wcol0 + 1, due)
    blanks = [{"range": f"{col}{i}", "values": [[""]]} for i, _ in data_rows]
    if blanks:
        ws.batch_update(blanks, value_input_option="USER_ENTERED")
    print(f"  ✓ rolled: {col}1={due}, {len(formula_rows)} formulas re-pointed, "
          f"{len(blanks)} data cells blanked")
    return {"due": due, "rolled": True}


def search(page=None, verbose=True):
    per, all_names = _pull(page=page, verbose=verbose)
    out = [["TARGET", "DD WEEK", "VA FIGURE (fees excl.)", "RAW (fees incl.)", "ROWS"]]
    for name in TARGETS:
        weeks = per.get(name)
        if not weeks:
            near = sorted(n for n in all_names
                          if name.split()[0].lower() in n.lower()
                          or name.split()[-1].lower() in n.lower())
            out.append([name, "NOT FOUND", "", "",
                        ("near: " + ", ".join(near[:4])) if near else ""])
            continue
        first = True
        for wk in sorted(weeks, key=lambda w: [int(x) for x in w.split(".")]
                         if re.match(r"^\d+\.\d+\.\d+$", w) else [0]):
            d = weeks[wk]
            out.append([name if first else "", wk,
                        f"${round(d['clean'],2):,.2f}", f"${round(d['raw'],2):,.2f}",
                        str(d["rows"])])
            first = False
    out.append([""])
    out.append(["note", "VA FIGURE = Total $ to ICD minus ledger/fee lines; "
                "should match the bulletin's manual figure.", "", "", ""])
    # Self-check: surface any week where the fee rule looks like it misfired.
    flags = [f for name in TARGETS for wk, d in (per.get(name) or {}).items()
             for f in _fee_flags(name, wk, d)]
    for f in flags:
        out.append([f, "", "", "", ""])
    if verbose:
        for r in out:
            print(" | ".join(str(c) for c in r))

    _dump(out)
    print(f"\n✓ {len(out)} row(s) → '{DUMP_TAB}' tab")
    return per


def _tab_week_column(week_label):
    """{owner_norm: DD figure} from the DD tab's column for `week_label` — the
    REFERENCE we compare our independent pull against. Megan 2026-07-30 asked us
    NOT to source the bulletin from the VA's tab; this reads the tab only so we
    can see whether our own pull reproduces it, never as an input."""
    from automations.override_bulletin import dd_data as D
    from automations.recruiting_report import fill as _fill
    aliases = F.load_alias_map()
    ws = _fill._client().open_by_key(D.WORKBOOK_ID).worksheet(D.DD_TAB)
    vals = ws.get_all_values()
    hdr = vals[0]
    col = next((i for i, h in enumerate(hdr) if (h or "").strip() == week_label), None)
    out = {}
    if col is not None:
        for r in vals[1:]:
            nm = (r[0] or "").strip()
            if not nm or nm.lower().startswith("total"):
                continue
            out[P._norm_name(F.canon(nm, aliases))] = (
                D.money(r[col]) if col < len(r) else 0.0)
    return out, col


def _wk_sort(w):
    return [int(x) for x in w.split(".")] if re.match(r"^\d+\.\d+\.\d+$", w) else [0]


def _week_ending(mdy):
    """A Tableau DD-week date label ('7.25.26') -> its week-ending SUNDAY label
    ('7.26.26'). The current DD week arrives as SEPARATE deposit-date labels
    (Sat 7.25 + Sun 7.26); the tab's single 'week ending 7.26.26' column is their
    SUM. Grouping by the Sunday is what makes our pull reproduce the tab — taking
    only the newest single label drops everyone paid on the Saturday (Megan
    2026-07-30: it was pulling an incomplete week)."""
    import datetime as _dt
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*$", mdy or "")
    if not m:
        return mdy
    yr = int(m.group(3)); yr = yr if yr > 99 else 2000 + yr
    d = _dt.date(yr, int(m.group(1)), int(m.group(2)))
    sun = d + _dt.timedelta(days=(6 - d.weekday()))   # Mon=0..Sun=6 -> this week's Sun
    return f"{sun.month}.{sun.day}.{str(sun.year)[-2:]}"


def _regroup_weeks(wk):
    """{daily 'M.D.YY' -> totals} -> {week-ending Sunday 'M.D.YY' -> summed totals}."""
    out = {}
    for lbl, d in wk.items():
        se = _week_ending(lbl)
        acc = out.setdefault(se, {"raw": 0.0, "clean": 0.0, "rows": 0,
                                  "dropped_pos": 0.0, "neg_kept": 0.0})
        for k in ("raw", "clean", "rows", "dropped_pos", "neg_kept"):
            acc[k] += d.get(k, 0)
    return out


def compare_all(page=None, verbose=True, week=None):
    """Independent FULL-ORG re-pull from OUR Tableau mapping (ORG DD Detail),
    every owner — grouped into week-ending SUNDAYS and lined up against the DD
    tab as a reference. Answers Megan's 2026-07-30 question: does our own mapping
    pull the correct current week's DD, without leaning on the VA's hand-filled
    numbers? Dumps to `_dd_repull`. EXPECTED residual diffs, none of them a pull
    error: Credico owners (Abel Draper / Jahvid Thompson) — the tab folds their
    Credico deposit on top of the Tableau part; and a few names the tab spells
    with a suffix/middle name the alias map doesn't yet unify (Rafael Hidalgo TX,
    Carlos Hidalgo TX, Roshan Amin Ahmad) — the money is there under the plain
    name."""
    per, _ = _pull(page=page, verbose=verbose, targets=None)
    # Regroup each owner's daily deposit labels into week-ending Sundays.
    per = {o: _regroup_weeks(wk) for o, wk in per.items()}
    weeks_seen = sorted({w for wk in per.values() for w in wk}, key=_wk_sort)
    newest = week or (weeks_seen[-1] if weeks_seen else None)
    if verbose:
        print(f"\nweeks present in our pull: {weeks_seen}")
        print(f"comparing week: {newest}")
    tabmap, tabcol = _tab_week_column(newest) if newest else ({}, None)
    aliases = F.load_alias_map()

    out = [["OWNER", f"OUR DD {newest} (fees excl.)", "OUR RAW (incl. fees)",
            f"TAB {newest} (reference)", "DIFF our-tab", "LINES"]]
    names = sorted((n for n in per if newest in per[n]),
                   key=lambda n: -(per[n][newest]["clean"]))
    our_total, matched, mism = 0.0, 0, []
    for nm in names:
        d = per[nm][newest]
        clean = round(d["clean"], 2)
        our_total += clean
        tabv = tabmap.get(P._norm_name(F.canon(nm, aliases)))
        diff = None if tabv is None else round(clean - tabv, 2)
        if diff is not None:
            if abs(diff) <= 0.5:
                matched += 1
            else:
                mism.append((nm, clean, tabv, diff))
        out.append([nm, f"${clean:,.2f}", f"${round(d['raw'], 2):,.2f}",
                    "" if tabv is None else f"${tabv:,.2f}",
                    "" if diff is None else f"${diff:,.2f}", str(d["rows"])])
    out.append([""])
    out.append([f"OUR pull total ({newest})", f"${round(our_total, 2):,.2f}",
                "", "", "", f"{len(names)} owners"])
    out.append([f"matched tab to the cent", str(matched), "of",
                str(sum(1 for n in names
                        if tabmap.get(P._norm_name(F.canon(n, aliases))) is not None)),
                "", ""])
    for nm, c, t, dff in mism:
        out.append([f"≠ {nm}", f"ours ${c:,.2f}", f"tab ${t:,.2f}",
                    f"diff ${dff:,.2f}", "", ""])

    if verbose:
        for r in out:
            print(" | ".join(str(c) for c in r))
    _dump(out, tab="_dd_repull")
    print(f"\n✓ {len(out)} row(s) → '_dd_repull' tab; newest week pulled = {newest}")
    return per, newest


def _dump(rows, tab=DUMP_TAB):
    """Mirror the result to a throwaway tab so it is readable from any machine
    (same pattern as credico.report._dump_to_sheet). Never touches a report tab."""
    from automations.recruiting_report import fill as _fill
    sh = _fill._client().open_by_key(WORKBOOK_ID)
    ncol = max((len(r) for r in rows), default=1)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except Exception:  # noqa: BLE001
        ws = sh.add_worksheet(title=tab, rows=max(100, len(rows) + 20), cols=ncol)
    if len(rows) > ws.row_count:
        ws.add_rows(len(rows) - ws.row_count + 10)
    last_col = chr(ord("A") + ncol - 1)
    ws.update(values=[[str(c) for c in r] for r in rows],
              range_name=f"A1:{last_col}{len(rows)}", value_input_option="RAW")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Search / accumulate DD for the "
                                             "special-case names (Lucy 1)")
    ap.add_argument("--accumulate", action="store_true",
                    help="write this week's fees-excluded figure into the DD "
                         "tab's 'ICD (Special Cases)' section (dry-run without "
                         "--write)")
    ap.add_argument("--write", action="store_true",
                    help="with --accumulate, actually write to the tab")
    ap.add_argument("--all", action="store_true",
                    help="full-org independent re-pull: every owner's DD from OUR "
                         "Tableau mapping, compared week-for-week to the tab "
                         "(reference only) → '_dd_repull' tab")
    ap.add_argument("--week", default=None,
                    help="with --all, compare a specific week label e.g. 7.26.26 "
                         "(default: the newest week our pull returns)")
    ap.add_argument("--populate", action="store_true",
                    help="populate the tab's current-week column for EVERY "
                         "Active-YES owner from our mapping (dry-run without "
                         "--write) — the switch off the VA hand-fill")
    ap.add_argument("--roll", action="store_true",
                    help="insert the new week-ending column on the DD tab if the "
                         "week just ended isn't its leftmost week (dry-run without "
                         "--write)")
    ap.add_argument("--sandbox", action="store_true",
                    help="target the '_dd_sandbox' tab instead of the live DD tab "
                         "(for --populate / --roll testing)")
    a = ap.parse_args(argv)
    try:
        if a.roll:
            from automations.override_bulletin import dd_data as D
            from automations.recruiting_report import fill as _fill
            tab = "_dd_sandbox" if a.sandbox else D.DD_TAB
            ws = _fill._client().open_by_key(D.WORKBOOK_ID).worksheet(tab)
            roll_week(ws, dry_run=not a.write)
        elif a.populate:
            accumulate_all(write=a.write)
        elif a.all:
            compare_all(week=a.week)
        elif a.accumulate:
            accumulate(write=a.write)
        else:
            search()
    except Exception as e:  # noqa: BLE001
        print(f"✗ {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
