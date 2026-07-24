"""DD Bulletin data layer — everything the render needs, from the Sheet.

Rules live in DD_SOURCES.md. In short:
  * active ICDs = `Active ICD` YES on `Org DDs Ongoing Report`
  * the podium is NOT derivable from the Org Tree and NOT the flat ORG column.
    Each leader's figure is a SPECIFIC ICD LIST, kept on `Lucy Org Tree` under
    PODIUM ORG LISTS. We sum those lists and check each against its expected
    total. The lists are NOT in the emailed bulletin (that carries only the
    headline and the 7 figures) — they live in the VA's working file.
  * ADOPTIONS (Karrington Moody, Milan Godbolt) and JACOB DOVER are EXCLUDED from
    the org headline but still reported — their numbers must never vanish
  * Raf's podium figure is the bulletin's "total outside Carlos & Colten" line:
    the headline MINUS Carlos's and Colten's list totals (not his own list sum —
    those disagree by $41,962, and the published line is the subtraction)
  * headline total, AVG DD and Active Owners are ALREADY computed in the tab
    (rows 132 / 135-153 / 155-173) — read them, never recompute
  * every name on both sides resolves through the shared ICD Aliases tab
"""
from __future__ import annotations

import re

from automations.override_bulletin import fill as F

WORKBOOK_ID = "1IpDs2BGLByiJCMZ7tAAMFanYVn5DEDVxCYqPGz8Wu6E"
DD_TAB = "Org DDs Ongoing Report"
TREE_TAB = "Lucy Org Tree"
WOW_WEEKS = 4

# Excluded from the ORG headline, still reported (see DD_SOURCES.md).
ADOPTIONS = ["Karrington Moody", "Milan Godbolt"]
SPECIAL = ["Jacob Dover"]

LEADERS_LABEL = "PODIUM LEADERS"
LISTS_LABEL = "PODIUM ORG LISTS"

_WEEK_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}$")
_SPLIT_RE = re.compile(r"\(\s*(\d)\s*/\s*(\d)\s*\)")


def money(s):
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


def load(ws=None, tree_ws=None, aliases=None):
    """Everything the DD render needs. Returns a dict — see module docstring."""
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

    # ---- the headline, read straight off the pre-computed 'Total - Raf' row
    headline = next((money(r[wk_cols[0][0]]) for r in vals
                     if r and "total - raf" in (r[0] or "").strip().lower()
                     and wk_cols[0][0] < len(r)), None)

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
             "note": (r[4] or "").strip() if len(r) > 4 else ""})

    podium, problems = [], []
    for r in _labelled_block(tvals, LEADERS_LABEL, skip=1):
        name = (r[0] or "").strip()
        if not name:
            continue
        minus = [m.strip() for m in ((r[2] or "") if len(r) > 2 else "").split(",")
                 if m.strip()]
        exp_n = _cellf(r, 3)
        exp_wk = _cellf(r, 4)
        wk, tot, missing, manual = 0.0, 0.0, [], []
        partial = False
        row_wk, row_keys = 0.0, set()      # the part backed by a real DD row
        for item in lists.get(name, []):
            row = by_key.get(_key(item["icd"], aliases))
            if row:
                wk += row["weeks"][0]
                tot += row["total"]
                row_wk += row["weeks"][0]
                row_keys.add(row["key"])
            elif item["manual_week"] is not None:
                wk += item["manual_week"]
                tot += item["manual_total"] or 0.0
                manual.append(item["icd"])
                if item["manual_total"] is None:
                    partial = True
                    problems.append(f"{name}: '{item['icd']}' has no 2026 total — "
                                    f"the leader's 2026 figure is understated, so "
                                    f"the card says 'partial'")
            else:
                missing.append(item["icd"])
                problems.append(f"{name}: '{item['icd']}' has no DD row and no "
                                f"manual amount — counted as $0")
        podium.append({"name": name, "loc": (r[1] or "").strip() if len(r) > 1 else "",
                       "minus": minus, "list_week": round(wk, 2),
                       "week": round(wk, 2), "total": round(tot, 2),
                       "row_week": round(row_wk, 2), "row_keys": row_keys,
                       "items": lists.get(name, []), "total_partial": partial,
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
        # Independent cross-check: the same figure reached by adding up every
        # active ICD that is on none of the subtracted lists. If the two routes
        # disagree, a list is wrong — say so rather than publish either one.
        direct = round(sum(r["weeks"][0] for r in icds if r["key"] not in gone), 2)
        p["direct"] = direct
        p["direct_n"] = sum(1 for r in icds if r["key"] not in gone)
        if abs(direct - p["week"]) > 0.5:
            problems.append(
                f"{p['name']}: headline-minus gives ${p['week']:,.2f} but adding "
                f"up the {p['direct_n']} ICDs on no subtracted list gives "
                f"${direct:,.2f} — a list is wrong")

    for p in podium:
        if p["expected_week"] is not None and abs(p["week"] - p["expected_week"]) > 0.5:
            problems.append(f"{p['name']}: computed ${p['week']:,.2f} but the "
                            f"bulletin says ${p['expected_week']:,.2f} "
                            f"(off ${p['week'] - p['expected_week']:,.2f})")
        if p["expected_n"] is not None and p["n_icds"] and p["n_icds"] != p["expected_n"]:
            problems.append(f"{p['name']}: {p['n_icds']} ICDs listed, bulletin "
                            f"says {int(p['expected_n'])}")
        if not p["n_icds"] and not p["minus"]:
            problems.append(f"{p['name']}: no ICD list on {TREE_TAB!r} — "
                            f"transcribe it from the bulletin")
    podium.sort(key=lambda d: -d["week"])
    def _block(start):
        rows = []
        for r in _labelled_block(vals, start):
            lab = (r[0] or "").strip()
            if not lab:
                continue
            rows.append({"name": lab,
                         "total": r[tot_col] if tot_col < len(r) else "",
                         "weeks": [r[i] if i < len(r) else "" for i, _ in wk_cols[:WOW_WEEKS]]})
        return rows
    avg = _block("ORG/CAMPAIGNS")
    active = _block("CAMPAIGNS")

    # ---- the two off-book cases, reported so no number silently disappears.
    # They point in OPPOSITE directions, so each row says which:
    #   Jacob Dover / adoptions with a DD row → IN the org total, on no podium list
    #   bulletin-only names (Justin, Marcos, the adoptions) → ON a podium list,
    #     but with no DD row, so NOT in the org total
    excluded = {_key(n, aliases) for n in ADOPTIONS + SPECIAL}
    tracked = [{**r, "why": "In the organization total; on no leader's podium list."}
               for r in icds if r["key"] in excluded]
    for p in podium:
        for item in p["items"]:
            if _key(item["icd"], aliases) in by_key or item["manual_week"] is None:
                continue
            tracked.append({"name": item["icd"], "campaign": "", "org": p["name"],
                            "total": item["manual_total"] or "",
                            "weeks": [item["manual_week"]] + [""] * (len(weeks) - 1),
                            "why": f"On {p['name'].split()[0]}'s podium list; no DD "
                                   f"row on the tab, so not in the organization total."})
    return {"weeks": weeks, "icds": icds, "podium": podium, "headline": headline,
            "avg": avg, "active_owners": active, "tracked_separately": tracked,
            "org_count": len(icds), "problems": problems}


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
    if d["problems"]:
        print(f"\n⚠ {len(d['problems'])} thing(s) to look at:")
        for p in d["problems"]:
            print(f"  · {p}")
