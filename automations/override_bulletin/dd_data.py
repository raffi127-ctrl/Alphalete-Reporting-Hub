"""DD Bulletin data layer — everything the render needs, from the Sheet.

Rules live in DD_SOURCES.md. In short:
  * active ICDs = `Active ICD` YES on `Org DDs Ongoing Report`
  * the podium is NOT derivable from the Org Tree and NOT the flat ORG column.
    Each leader's figure is a SPECIFIC ICD LIST, kept on `Lucy Org Tree` under
    PODIUM ORG LISTS. We sum those lists and check each against its expected
    total. The lists are NOT in the emailed bulletin (that carries only the
    headline and the 7 figures) — they live in the VA's working file.
  * the adoptions / off-book names live in the 'ICD (Special Cases)' section on
    the DD tab (below the headline formulas); they are EXCLUDED from the org
    total but still reported under Tracked Separately. Jacob Dover is NOT one of
    them — he is a normal Active-YES ICD IN the org total
  * Raf's podium figure is the bulletin's "total outside Carlos & Colten" line:
    the headline MINUS Carlos's and Colten's list totals (not his own list sum —
    those disagree by $41,962, and the published line is the subtraction)
  * headline total, AVG DD and Active Owners are ALREADY computed in the tab
    (rows 132 / 135-153 / 155-173) — read them, never recompute
  * CREDICO is the second DD source and is ADDED to an owner's week — but only
    where the tab does not already contain it (the VA folds it in by hand while
    she still owns the tab). `_fold_credico` decides that per owner and reports
    either way; an owner's Credico DD is the WHOLE OFFICE, not their agent rows
  * every name on both sides resolves through the shared ICD Aliases tab
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

from automations.override_bulletin import fill as F

CENTRAL = ZoneInfo("America/Chicago")   # [[project_central-time-for-texas-reports]]

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DD_TAB = "Org DDs Ongoing Report"
TREE_TAB = "Lucy Org Tree"
WOW_WEEKS = 8      # Raf 2026-07-25: show more weeks so the ICD tables fill the
#                    width instead of leaving blank space in the name column.
#                    The rollup stays 4 weeks (it slices weeks[:4] itself).

LEADERS_LABEL = "PODIUM LEADERS"
LISTS_LABEL = "PODIUM ORG LISTS"

_WEEK_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")
_SPLIT_RE = re.compile(r"\(\s*(\d)\s*/\s*(\d)\s*\)")


def week_date(label):
    """The Sunday a '7.19.26' week header names, or None if it isn't one."""
    m = _WEEK_RE.match((label or "").strip())
    if not m:
        return None
    mo, d, y = (int(x) for x in label.strip().split("."))
    try:
        return dt.date(y + 2000 if y < 100 else y, mo, d)
    except ValueError:
        return None


def fmt_week(date):
    """A date as the tab writes it — '7.26.26', no zero padding, no %-m
    (that strftime flag is Mac-only and these run on Windows too)."""
    return "{}.{}.{:02d}".format(date.month, date.day, date.year % 100)


def week_just_ended(today=None):
    """The most recent Sunday on or before today, in CENTRAL time.

    The bulletin goes out Thursday for the week that ended the Sunday before —
    so on Thu 7.30 the tab's newest column must be 7.26."""
    today = today or dt.datetime.now(CENTRAL).date()
    return today - dt.timedelta(days=(today.weekday() + 1) % 7)


def money(s):
    # Sheet cells arrive as text, but openpyxl hands back real numbers — take
    # either rather than crashing on a float (Credico's TransAmt is numeric).
    if isinstance(s, bool):
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    s = (s or "").replace("$", "").replace(",", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return 0.0


def _key(s, aliases):
    """Canonical match key: strip any '(1/2)' marker, resolve through ICD
    Aliases, then drop a trailing state suffix ('Carlos Hidalgo TX')."""
    s = _SPLIT_RE.sub("", s or "")
    n = F.canon(s, aliases)
    return re.sub(r"\b(tx|fl|mi)\b\s*$", "", n).strip()


def _labelled_block(vals, start_label, stop_labels=(), skip=0):
    """Rows of a block, found BY LABEL in column A (never by index — inserting a
    week column or a row must not move it). `skip` drops that many header rows
    between the label and the data. The block ends at the first blank column A."""
    out, on = [], False
    for r in vals:
        a = " ".join((r[0] or "").split()).lower() if r else ""
        if not on:
            if a == start_label.lower():
                on = True
                continue
        else:
            if not a or any(a == s.lower() for s in stop_labels):
                break
            if skip:
                skip -= 1
                continue
            out.append(r)
    return out


def _cellf(r, i):
    return money(r[i]) if i < len(r) and (r[i] or "").strip() else None


def _fold_credico(credico, week_label, by_key, aliases, problems, blocking):
    """Add each owner's Credico DD to their week — or verify it is already there.

    Credico is the second DD source (DD_SOURCES.md): its direct deposits are
    ADDED to an owner's weekly figure, and an owner's Credico DD is the WHOLE
    OFFICE. But the tab we read is the VA's, and while she is still filling it
    she has already folded Credico in — for 7.19.26 Abel's cell is $6,578.00
    against a $6,058.00 Credico office, the $520.00 gap being the Tableau part.
    Adding on top of that would double-count her work.

    So the tab decides, per owner, which of the two situations we are in:
      * cell >= Credico  -> already folded in. Verify and report the split;
        change nothing.
      * cell <  Credico  -> the cell holds the Tableau part only, so ADD.
        BLOCKING, because the headline is read off the tab and therefore does
        NOT contain what we just added.
      * no row at all    -> a Credico-only owner. Reported and rendered under
        Tracked Separately, never folded silently into a total that lacks them.

    Returns the render/report block, or None when Credico is switched off.
    """
    if credico is False or credico is None:
        return None
    info = {"week": week_label, "lines": [], "notes": [], "offices": [],
            "owners": {}, "added": 0.0, "missing": []}
    if credico is True or credico == "auto":
        try:
            from automations.credico import report as C
            owners, notes, offices = C.pull(week_label, aliases=aliases,
                                            verbose=False)
        except Exception as e:  # noqa: BLE001
            # Credico posts on its OWN (weird) schedule, so "not available yet" is
            # NOT a send-stopper (Megan 2026-07-30): the bulletin still goes out,
            # carries a small "Credico not available this week" note, and an alert
            # fires to #claudecorrections. It is re-captured the moment Credico
            # posts. So: pending flag, a NOTE, never blocking.
            msg = (f"Credico not available this week ({type(e).__name__}) — "
                   f"the bulletin sent without it; on Lucy 1 `lucy rerun "
                   f"credico_fetch` then re-send to fold it in")
            problems.append(msg)
            info["error"] = msg
            info["pending"] = True
            return info
    else:
        owners, notes, offices = credico, [], []
    info["notes"], info["offices"], info["owners"] = list(notes), offices, dict(owners)

    for owner, amt in sorted(owners.items(), key=lambda kv: -kv[1]):
        row = by_key.get(_key(owner, aliases))
        if row is None:
            info["missing"].append({"owner": owner, "amount": amt})
            msg = (f"{owner}: ${amt:,.2f} of Credico DD but NO row on the DD tab "
                   f"— not in the organization total; shown under Tracked "
                   f"Separately so the money stays visible")
            problems.append(msg)
            blocking.append(msg)
            info["lines"].append(f"{owner} — ${amt:,.2f}, no row on the DD tab")
            continue
        cell = row["weeks"][0]
        if cell + 0.5 >= amt:
            row["credico"] = amt
            info["lines"].append(
                f"{row['name']} — ${cell:,.2f} already includes Credico "
                f"${amt:,.2f} (Tableau part ${cell - amt:,.2f})")
        else:
            row["weeks"][0] = round(cell + amt, 2)
            row["credico"] = amt
            row["credico_added"] = amt
            info["added"] = round(info["added"] + amt, 2)
            info["lines"].append(
                f"{row['name']} — ${cell:,.2f} on the tab + ${amt:,.2f} Credico "
                f"= ${row['weeks'][0]:,.2f} (ADDED)")
            msg = (f"{row['name']}: the tab shows ${cell:,.2f} but Credico alone "
                   f"is ${amt:,.2f}, so Credico was ADDED (${row['weeks'][0]:,.2f}). "
                   f"The ORG. TOTAL DD headline is read off the tab and does NOT "
                   f"contain that ${amt:,.2f}")
            problems.append(msg)
            blocking.append(msg)
    return info


def load(ws=None, tree_ws=None, aliases=None, credico="auto"):
    """Everything the DD render needs. Returns a dict — see module docstring.

    `credico` is "auto" (pull it, and report rather than crash if it isn't there),
    False (skip it), or a ready-made {owner name: amount} dict for testing."""
    from automations.recruiting_report import fill as _fill
    if ws is None or tree_ws is None:
        sh = _fill._client().open_by_key(WORKBOOK_ID)
        ws = ws or sh.worksheet(DD_TAB)
        tree_ws = tree_ws or sh.worksheet(TREE_TAB)
    aliases = F.load_alias_map() if aliases is None else aliases
    vals = ws.get_all_values()
    hdr = vals[0]
    wk_cols = [(i, h.strip()) for i, h in enumerate(hdr) if _WEEK_RE.match((h or "").strip())]
    weeks = [w for _, w in wk_cols[:WOW_WEEKS]]
    tot_col = next((i for i, h in enumerate(hdr) if "total dd" in (h or "").lower()), 4)

    icds, by_key = [], {}
    for r in vals[1:]:
        nm = (r[0] or "").strip()
        if not nm or nm.lower().startswith("total"):
            continue
        if len(r) > 1 and r[1].strip().upper() != "YES":
            continue
        row = {"name": nm, "key": _key(nm, aliases),
               "campaign": (r[2] or "").strip() if len(r) > 2 else "",
               "org": (r[3] or "").strip() if len(r) > 3 else "",
               "total": money(r[tot_col]) if tot_col < len(r) else 0.0,
               "weeks": [money(r[i]) if i < len(r) else 0.0 for i, _ in wk_cols[:WOW_WEEKS]]}
        icds.append(row)
        by_key[row["key"]] = row

    # ---- ICD (Special Cases): the adoptions / off-book names, kept in Megan's
    # labeled 'ICD (Special Cases)' section BELOW the Total rows on the DD tab.
    # They are NOT Active-YES and sit outside SUM(F2:F131), so the scan above
    # skips them and they never touch the headline — but the podium lists
    # reference them, so they go into by_key (a leader's list finds them like any
    # ICD, and the Adoption? flag still keeps them out of ORGANIC), and they
    # render in Tracked Separately with whatever weekly history has accumulated.
    special, _on = [], False
    for r in vals:
        lab = " ".join((r[0] or "").split()).lower()
        if not _on:
            _on = lab.startswith("icd (special cases)")
            continue
        nm = (r[0] or "").strip()
        if not nm:
            break                        # first blank column A ends the block
        row = {"name": nm, "key": _key(nm, aliases),
               "campaign": (r[2] or "").strip() if len(r) > 2 else "",
               "org": (r[3] or "").strip() if len(r) > 3 else "",
               "total": money(r[tot_col]) if tot_col < len(r) else 0.0,
               "weeks": [money(r[i]) if i < len(r) else 0.0 for i, _ in wk_cols[:WOW_WEEKS]],
               "special": True}
        special.append(row)
        by_key.setdefault(row["key"], row)

    # `blocking` is the subset of `problems` that must stop a SEND — a figure we
    # know is wrong, as opposed to one we know is incomplete and label as such.
    problems, blocking = [], []

    # ---- is the newest column actually THIS week's? The week the bulletin
    # carries is POSITIONAL — the leftmost week header on the tab — and nothing
    # in this pipeline rolls it; the tab is opened by hand. So a week nobody has
    # opened yet leaves LAST week's column in front and the bulletin republishes
    # a week that already went out, with no error anywhere (Eve 2026-07-30: the
    # 7.19 bulletin, published by hand on the 23rd, went out again on the 30th
    # because 7.26 had never been added). Stale column = BLOCKING: a wrong week
    # on the page is a wrong figure, not a short one.
    _newest = week_date(weeks[0]) if weeks else None
    _due = week_just_ended()
    if _newest and _newest != _due:
        msg = ("the newest week column on '{}' is {} but the week that just "
               "ended is {} — nothing here rolls the tab, so this would "
               "republish a week that already went out. Add the {} column and "
               "fill it first.".format(DD_TAB, weeks[0],
                                       fmt_week(_due), fmt_week(_due)))
        problems.append(msg)
        blocking.append(msg)

    # ---- the headline, read straight off the pre-computed 'Total - Raf' row
    headline = next((money(r[wk_cols[0][0]]) for r in vals
                     if r and "total - raf" in (r[0] or "").strip().lower()
                     and wk_cols[0][0] < len(r)), None)

    # ---- Credico, the second DD source, BEFORE the podium: a topped-up week
    # has to reach the leader lists that sum it.
    credico_info = _fold_credico(credico, weeks[0] if weeks else "", by_key,
                                 aliases, problems, blocking)

    # ---- the podium: per-leader ICD LISTS off `Lucy Org Tree`, summed directly.
    # Not derivable from the Org Tree or the ORG column (a previous build burned
    # hours proving that), and NOT in the emailed bulletin either — that carries
    # only the headline and the 7 figures. The lists were reconstructed and are
    # validated against those published figures to the penny. This just adds up.
    tvals = tree_ws.get_all_values()
    lists = {}                                   # leader -> [list rows]
    for r in _labelled_block(tvals, LISTS_LABEL, skip=1):
        leader = (r[0] or "").strip()
        icd = (r[1] or "").strip() if len(r) > 1 else ""
        if not leader or not icd:
            continue
        lists.setdefault(leader, []).append(
            {"icd": icd, "manual_week": _cellf(r, 2), "manual_total": _cellf(r, 3),
             "note": (r[4] or "").strip() if len(r) > 4 else "",
             "adoption": ((r[5] or "").strip().upper() == "YES") if len(r) > 5 else False})

    podium = []
    for r in _labelled_block(tvals, LEADERS_LABEL, skip=1):
        name = (r[0] or "").strip()
        if not name:
            continue
        minus = [m.strip() for m in ((r[2] or "") if len(r) > 2 else "").split(",")
                 if m.strip()]
        exp_n = _cellf(r, 3)
        exp_wk = _cellf(r, 4)
        wk, tot, missing, manual = 0.0, 0.0, [], []
        organic, adoptions = 0.0, []      # organic = the total LESS adoptions
        partial = False
        members = []                       # the list itself, for the breakdown
        row_wk, row_keys = 0.0, set()      # the part backed by a real DD row
        for item in lists.get(name, []):
            row = by_key.get(_key(item["icd"], aliases))
            if row:
                wk += row["weeks"][0]
                tot += row["total"]
                # A SPECIAL row (adoption / off-book) counts toward the leader's
                # shown total but is NOT part of the headline base, so it must NOT
                # go into row_wk / row_keys — those feed the 'headline minus this
                # org' subtraction for Raf, and subtracting money the headline
                # never contained is exactly the $41,962 error we corrected.
                if not row.get("special"):
                    row_wk += row["weeks"][0]
                    row_keys.add(row["key"])
                members.append({"name": item["icd"], "week": row["weeks"][0],
                                "adoption": item["adoption"]})
                if item["adoption"]:
                    adoptions.append(item["icd"])
                else:
                    organic += row["weeks"][0]
            elif item["manual_week"] is not None:
                wk += item["manual_week"]
                tot += item["manual_total"] or 0.0
                manual.append(item["icd"])
                members.append({"name": item["icd"], "week": item["manual_week"],
                                "adoption": item["adoption"]})
                if item["adoption"]:
                    adoptions.append(item["icd"])
                else:
                    organic += item["manual_week"]
                if item["manual_total"] is None:
                    partial = True
                    problems.append(f"{name}: '{item['icd']}' has no 2026 total — "
                                    f"the leader's 2026 figure is understated, so "
                                    f"the card says 'partial'")
            else:
                missing.append(item["icd"])
                msg = (f"{name}: '{item['icd']}' has no DD row and no manual "
                       f"amount — counted as $0")
                problems.append(msg)
                blocking.append(msg)
        podium.append({"name": name, "loc": (r[1] or "").strip() if len(r) > 1 else "",
                       "minus": minus, "list_week": round(wk, 2),
                       "week": round(wk, 2), "total": round(tot, 2),
                       "row_week": round(row_wk, 2), "row_keys": row_keys,
                       "items": lists.get(name, []), "total_partial": partial,
                       "members": members,
                       "organic": round(organic, 2), "adoptions": adoptions,
                       "n_icds": len(lists.get(name, [])), "expected_n": exp_n,
                       "expected_week": exp_wk, "missing": missing, "manual": manual})

    # 'Minus orgs' leaders take the headline less those orgs ("total outside of
    # Carlos & Colten"). Subtract only each org's ROW-BACKED portion: the headline
    # is the sum of the active DD rows, so the bulletin-only names in those lists
    # (Justin, Marcos, the adoptions) were never in it and cannot come out of it.
    # The VA's sheet subtracts the full list total, which understated Raf by
    # $41,962.00 on 7.19.26 — see DD_SOURCES.md. Corrected here on purpose.
    by_name = {p["name"]: p for p in podium}
    for p in podium:
        if not p["minus"]:
            continue
        gone = set()
        for m in p["minus"]:
            gone |= by_name[m]["row_keys"] if m in by_name else set()
        p["week"] = round((headline or 0.0)
                          - sum(by_name[m]["row_week"] for m in p["minus"]
                                if m in by_name), 2)
        p["total"] = None                        # no 2026 equivalent of that line
        p["organic"] = p["week"]                 # no list, so nothing to strip
        # A 'minus orgs' leader has no transcribed list, but his org is the WHOLE
        # organization — so for the breakdown it IS everyone earning this week,
        # which is exactly how the VA's own working file lists Raf (38 ICDs
        # totalling the headline). Derived, not transcribed, because a hand list
        # of 38 names would need re-typing every week.
        p["members"] = [{"name": r["name"], "week": r["weeks"][0], "adoption": False}
                        for r in icds if r["weeks"][0]]
        # Independent cross-check: the same figure reached by adding up every
        # active ICD that is on none of the subtracted lists. If the two routes
        # disagree, a list is wrong — say so rather than publish either one.
        direct = round(sum(r["weeks"][0] for r in icds if r["key"] not in gone), 2)
        p["direct"] = direct
        p["direct_n"] = sum(1 for r in icds if r["key"] not in gone)
        if abs(direct - p["week"]) > 0.5:
            msg = (f"{p['name']}: headline-minus gives ${p['week']:,.2f} but "
                   f"adding up the {p['direct_n']} ICDs on no subtracted list "
                   f"gives ${direct:,.2f} — a list is wrong")
            problems.append(msg)
            blocking.append(msg)

    for p in podium:
        if p["expected_week"] is not None and abs(p["week"] - p["expected_week"]) > 0.5:
            # NON-blocking since 2026-07-30: DD now comes from OUR mapping, so the
            # leader figure IS the sum of the leader's list off our-populated
            # column. The tree's 'expected week' cell is a HAND-TYPED reference
            # that lags a week until someone rolls it — it can no longer be an
            # independent source, so a difference is a note, not a send-stopper.
            # The real money guards stay blocking: a listed ICD with no DD row,
            # the direct-list reconciliation, and the headline read off the tab.
            problems.append(
                f"{p['name']}: computed ${p['week']:,.2f}; the tree's manual "
                f"reference says ${p['expected_week']:,.2f} "
                f"(off ${p['week'] - p['expected_week']:,.2f}) — reference lags, "
                f"not a block")
        if p["expected_n"] is not None and p["n_icds"] and p["n_icds"] != p["expected_n"]:
            # Count only, and never blocking — the money is checked separately
            # and to the penny. Name the members worth $0 this week: a count
            # that is off by N is almost always N people the VA left off her
            # list because they earned nothing, and a bare "19 vs 18" sends the
            # next person hunting through the whole list to work that out.
            # (Carlos's was settled that way: Benjamin Burden, $0 all year.)
            zeros = [i["icd"] for i in p["items"]
                     if (by_key.get(_key(i["icd"], aliases)) or {}).get("weeks",
                                                                       [1])[0] == 0]
            problems.append(
                f"{p['name']}: {p['n_icds']} ICDs listed, bulletin says "
                f"{int(p['expected_n'])} — the money still reconciles"
                + (f"; worth $0 this week, so the likeliest difference: "
                   f"{', '.join(zeros)}" if zeros else ""))
        if not p["n_icds"] and not p["minus"]:
            msg = (f"{p['name']}: no ICD list on {TREE_TAB!r} — transcribe it "
                   f"from the bulletin")
            problems.append(msg)
            blocking.append(msg)
    podium.sort(key=lambda d: -d["week"])
    def _block(start, what):
        rows = []
        for r in _labelled_block(vals, start):
            lab = (r[0] or "").strip()
            if not lab:
                continue
            wk = [r[i] if i < len(r) else "" for i, _ in wk_cols[:WOW_WEEKS]]
            tot = r[tot_col] if tot_col < len(r) else ""
            row = {"name": lab, "total": tot, "weeks": wk}
            # A 2026 total of ZERO with non-zero weeks is impossible under any
            # reading of the column, so it is a source error, not a fact. Found
            # 2026-07-24: 'Khalil's Org Active Owners' reads 0 against 4 active
            # owners in each of the last four weeks. We can't derive the right
            # number (the column is inconsistent — Colten's total is 6 against 8
            # this week), so it is shown in RED and reported rather than
            # published as if it were true.
            if money(tot) == 0 and any(money(w) for w in wk):
                row["suspect_total"] = True
                problems.append(
                    f"{what}: '{lab}' has a 2026 total of {tot or '(blank)'!s} but "
                    f"{', '.join(str(w) for w in wk if money(w))} in the weeks — "
                    f"impossible, so it is printed in red. Fix the cell on "
                    f"{DD_TAB!r}; we do not recompute this block")
            rows.append(row)
        return rows
    avg = _block("ORG/CAMPAIGNS", "AVG DD")
    active = _block("CAMPAIGNS", "Active Owners")

    # The tab's OWN total rows ('Total - Raf', 'Total - Carlos'). READ, never
    # recomputed — they cover ICDs our Active-YES list leaves out, which is why
    # the VA's 2026 total runs about $1M above the sum of the rows we print.
    # Summing our own visible rows instead would quietly publish a smaller
    # number than the one everybody already knows.
    totals = [{"name": (r[0] or "").strip(),
               "total": r[tot_col] if tot_col < len(r) else "",
               "weeks": [r[i] if i < len(r) else "" for i, _ in wk_cols[:WOW_WEEKS]]}
              for r in vals
              if r and (r[0] or "").strip().lower().startswith("total - ")]

    # Tracked Separately is ONLY names that sit OUTSIDE the org total. Jacob
    # Dover is NOT one — he is a normal Active-YES ICD counted in the headline
    # (Megan 2026-07-24: "he's in the org"), so he already appears in the All-ICDs
    # table like everyone else and does not belong here. What belongs: the
    # 'ICD (Special Cases)' rows (adoptions / off-book, excluded from the total),
    # carrying their own weekly history from the DD tab, and any Credico-only
    # owner with no DD row.
    tracked = []
    for r in special:
        tracked.append({**r, "why": (f"{r['org']} · not in the total"
                                     if r.get("org") else "not in the total")})
    for p in podium:
        for item in p["items"]:
            if _key(item["icd"], aliases) in by_key or item["manual_week"] is None:
                continue
            tracked.append({"name": item["icd"], "campaign": "", "org": p["name"],
                            "total": item["manual_total"] or "",
                            "weeks": [item["manual_week"]] + [""] * (len(weeks) - 1),
                            "why": f"{p['name'].split()[0]}'s org · not in the total"})
    # A Credico owner with no DD row is the third way money can sit outside the
    # roll-up. DD_SOURCES: "these owners are often absent from the main list and
    # must be ADDED" — so they are SHOWN rather than dropped, and flagged above.
    for m in (credico_info or {}).get("missing", []):
        tracked.append({"name": m["owner"], "campaign": "Credico", "org": "",
                        "total": "", "weeks": [m["amount"]] + [""] * (len(weeks) - 1),
                        "why": "Credico deposits · not in the total"})
    return {"weeks": weeks, "icds": icds, "podium": podium, "headline": headline,
            "avg": avg, "active_owners": active, "tracked_separately": tracked,
            "totals": totals, "org_count": len(icds), "problems": problems,
            "blocking": blocking, "credico": credico_info,
            "credico_pending": bool(credico_info and credico_info.get("pending"))}


if __name__ == "__main__":
    d = load()
    print(f"week {d['weeks'][0]}  headline ${d['headline']:,.2f}  "
          f"{d['org_count']} active ICDs")
    print("\npodium:")
    for p in d["podium"]:
        exp = ("" if p["expected_week"] is None
               else ("  ✓" if abs(p["week"] - p["expected_week"]) <= 0.5
                     else f"  ✗ bulletin ${p['expected_week']:,.2f}"))
        t = "—" if p["total"] is None else f"${p['total']:,.2f}"
        src = f"{p['n_icds']} ICDs" if p["n_icds"] else "headline − " + ", ".join(p["minus"])
        print(f"  {p['name']:18} ${p['week']:>12,.2f}   2026 {t:>16}   {src}{exp}")
    print(f"\nexcluded from roll-up but tracked ({len(d['tracked_separately'])}):")
    for t in d["tracked_separately"]:
        wk = t["weeks"][0]
        wk = f"${wk:,.2f}" if isinstance(wk, (int, float)) else str(wk or "—")
        tt = t["total"]
        tt = f"${tt:,.2f}" if isinstance(tt, (int, float)) else str(tt or "—")
        print(f"  {t['name'][:40]:42} {wk:>13}   2026 {tt:>15}   {t['why']}")
    print(f"\nAVG DD rows: {len(d['avg'])}   Active-owner rows: {len(d['active_owners'])}")
    c = d.get("credico")
    print("\ncredico: " + ("not folded in" if not c else
                           (c.get("error") or f"week {c['week']}, "
                            f"{len(c['offices'])} office(s)")))
    for line in (c or {}).get("lines", []):
        print(f"  · {line}")
    for line in (c or {}).get("notes", []):
        print(f"  · {line}")
    if d["problems"]:
        print(f"\n⚠ {len(d['problems'])} thing(s) to look at "
              f"({len(d['blocking'])} would BLOCK a send):")
        for p in d["problems"]:
            print(f"  {'✗' if p in d['blocking'] else '·'} {p}")
