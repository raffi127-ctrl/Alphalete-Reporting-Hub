"""Write the per-company work-queue / audit log to a tab on the intake sheet.

The log is the "don't mess up" safety net: one row per thing that needs action
(below-5★ review, negative Reddit thread, negative search result), with a Status
column the owner works. Behavior that keeps it safe:

  * Creates/writes ONLY the log tab — never the intake tab or anything else.
  * APPEND-ONLY with dedup: a finding already in the tab is left untouched, so
    your Status edits ("Responded", "Resolved") are never overwritten and rows
    never duplicate across weekly runs.
  * Columns are matched by header LABEL, so the tab can be reordered/extended.

Tab name = "<Company> - <Owner>" (e.g. "Alphalete Marketing - Raf Hidalgo") when
the intake row has an Owner, else "<Company> - Log".
"""
from __future__ import annotations

from datetime import date

from automations.brand_audit import sheets
from automations.brand_audit.config import LOG_TAB_OVERRIDES

COLUMNS = ["First Seen", "Type", "Source", "Detail", "Link",
           "Suggested Reply", "Status", "Owner", "Last Updated"]


def log_tab_name(company) -> str:
    # Convention: the log tab is named by ICD Name (e.g. "Rafael Hidalgo"),
    # matching the other Hub reports. Precedence: ICD Name from intake → explicit
    # override → "<Company> - <Owner>" → "<Company> - Log".
    icd = (getattr(company, "icd_name", "") or "").strip()
    if icd:
        return icd
    if company.name in LOG_TAB_OVERRIDES:
        return LOG_TAB_OVERRIDES[company.name]
    owner = (getattr(company, "owner", "") or "").strip()
    return f"{company.name} - {owner}" if owner else f"{company.name} - Log"


def _anchor(row: dict) -> str:
    """Stable identity for dedup — the link, else the detail text."""
    return (row.get("Link") or row.get("Detail") or "").strip()


def build_rows(company, card: dict, today: str | None = None) -> list[dict]:
    today = today or date.today().isoformat()
    owner = (getattr(company, "owner", "") or "").strip()
    rows: list[dict] = []
    seen = set()

    def add(row: dict):
        a = _anchor(row)
        if a and a in seen:
            return
        seen.add(a)
        rows.append(row)

    # 1) below-5★ reviews (with drafted replies)
    for s in card.get("sections", []):
        if s.get("key") != "reviews":
            continue
        for r in s.get("respond", []):
            add({
                "First Seen": today,
                "Type": f"Review {r.get('stars')}★",
                "Source": r.get("site", ""),
                "Detail": (f"{r.get('author') or 'anonymous'} — "
                           f"\"{(r.get('snippet') or '')[:160]}\""),
                "Link": company.google_profile if r.get("site") == "Google" else "",
                "Suggested Reply": r.get("draft", ""),
                "Status": "New",
                "Owner": owner,
                "Last Updated": today,
            })

    # 2) negative findings (Reddit threads, negative search results, etc.)
    for f in card.get("flags", []):
        if f.get("level") != "negative":
            continue
        src = f.get("source", "")
        kind = ("Negative Reddit" if src == "reddit"
                else "Negative Search" if src == "serp"
                else "Negative finding")
        add({
            "First Seen": today,
            "Type": kind,
            "Source": src,
            "Detail": f.get("message", "") + (
                f" — {f.get('detail')}" if f.get("detail") else ""),
            "Link": f.get("url", ""),
            "Suggested Reply": "",
            "Status": "New",
            "Owner": owner,
            "Last Updated": today,
        })
    return rows


def _ensure_ws(sh, company):
    """Find the log tab for this company (exact name, or any tab you pre-created
    that starts with '<Company> -'), else create it. Avoids ever making a
    duplicate log tab."""
    desired = log_tab_name(company)
    try:
        return sh.worksheet(desired)
    except Exception:
        pass
    prefix = f"{company.name} -"
    for ws in sh.worksheets():
        if ws.title.strip().startswith(prefix):
            return ws
    return sh.add_worksheet(title=desired, rows=200, cols=len(COLUMNS) + 2)


def write_log(sheet_id: str, company, card: dict, *, dry_run: bool = False) -> dict:
    rows = build_rows(company, card)
    tab = log_tab_name(company)

    if dry_run:
        return {"dry_run": True, "tab": tab, "would_write": len(rows),
                "rows": rows}

    sh = sheets.open_by_key(sheet_id)
    ws = _ensure_ws(sh, company)
    tab = ws.title
    grid = ws.get_all_values()
    has_data = any(any((c or "").strip() for c in row) for row in grid)

    if not has_data:                   # fresh/blank tab — write the header
        ws.update([COLUMNS], "A1")
        header = COLUMNS
        existing_anchors = set()
    else:
        header = grid[0]
        idx = {h.strip(): i for i, h in enumerate(header)}
        link_i = idx.get("Link")
        detail_i = idx.get("Detail")
        existing_anchors = set()
        for r in grid[1:]:
            link = r[link_i].strip() if link_i is not None and link_i < len(r) else ""
            detail = r[detail_i].strip() if detail_i is not None and detail_i < len(r) else ""
            existing_anchors.add(link or detail)

    # append only genuinely new findings, in the tab's own column order
    to_append = []
    for row in rows:
        if _anchor(row) in existing_anchors:
            continue
        to_append.append([row.get(h, "") for h in header])

    if to_append:
        ws.append_rows(to_append, value_input_option="USER_ENTERED")

    return {"ok": True, "tab": tab, "appended": len(to_append),
            "skipped_existing": len(rows) - len(to_append)}
