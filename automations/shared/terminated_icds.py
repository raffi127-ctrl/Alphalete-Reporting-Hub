"""Canonical list of TERMINATED ICDs, backed by a Google Sheet.

Source of truth: the 'Terminated ICDs' tab in the AUTOMATION MASTER workbook
(1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw — same workbook as 'ICD Aliases',
'Mini Control', 'Hub Activity'). Schema:
  Col A: ICD Name        (as it appears in ownerville — the only required field)
  Col B: Date Terminated (optional, free text e.g. 2026-06-26)
  Col C: Notes           (optional)
  Row 1: headers; data starts at row 2.

Why a Sheet, not JSON: anyone on the team logs a termination in the browser —
no code, no git. The next report run picks it up.

CROSS-REFERENCE THROUGH ALIASES: a name is matched after resolving it through
the 'ICD Aliases' tab, so a report that knows a person by a different name
variant (Tableau spelling, old Sheet-tab name, etc.) still matches a terminated
entry logged under the ownerville name. Both sides resolve to the same canonical
before comparing.

POLICY: this list FLAGS, it never removes. Reports surface terminated ICDs that
still appear on them so a human prunes the section/row — automations never delete
filled data on their own (Megan's 'don't touch user data without confirming').

Public API:
  load_terminated() -> list[dict]              # [{"name","date","notes"}, ...]
  is_terminated(name) -> bool
  terminated_among(names) -> list[dict]        # which of `names` are terminated
  format_flag(hits, report_label) -> str|None  # ready-to-print callout
  alert_terminated(names, report_label) -> (hits, flag)  # check + EMIT the alert
  log_terminated(name, date="", notes="")      # append a row (deduped)

The one-liner every report uses (call once per run, with the names it filled):
  from automations.shared import terminated_icds as ti
  hits, flag = ti.alert_terminated(names, report_label="Daily Recruiting Focus")
  # `flag` (or None) can also be folded into the report's run-manifest note so
  # the orchestrator / mini email surfaces it on unattended runs.
"""
from __future__ import annotations

import logging

from automations.recruiting_report import fill as _fill
from automations.focus_office_att import aliases as _aliases

_log = logging.getLogger("terminated-icds")

TERMINATED_SHEET_ID = "1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw"
TERMINATED_TAB = "Terminated ICDs"

HEADERS = ["ICD Name (as in ownerville)", "Date Terminated (optional)", "Notes (optional)"]


def _open_tab():
    sh = _fill._client().open_by_key(TERMINATED_SHEET_ID)
    return sh.worksheet(TERMINATED_TAB)


def load_terminated() -> list[dict]:
    """Read the tab → [{"name","date","notes"}]. Skips header + blank-name rows.
    Returns [] (with a warning) if the tab can't be opened, so a Sheet hiccup
    never crashes a report's run."""
    try:
        ws = _open_tab()
    except Exception as e:  # noqa: BLE001 — a missing tab must not break a report
        print(f"⚠ Couldn't open '{TERMINATED_TAB}' tab: {e}")
        return []
    rows = ws.get("A2:C1000") or []
    out: list[dict] = []
    for row in rows:
        name = (row[0] if len(row) > 0 else "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "date": (row[1] if len(row) > 1 else "").strip(),
            "notes": (row[2] if len(row) > 2 else "").strip(),
        })
    return out


def _canon(name: str, raw_aliases: dict) -> str:
    """Resolve a name to its canonical form (via the alias table) and normalize,
    so both the logged ownerville name and a report's name variant land on the
    same key for comparison."""
    return _aliases._norm_name(_aliases.alias_to_canonical(name, raw_aliases))


def _index() -> tuple[dict, dict]:
    """Return ({canonical_norm: entry}, raw_aliases). One Sheet read each for
    the terminated list + the alias table — call once per report run, not per
    ICD in a loop."""
    raw_aliases = _aliases.load_aliases()
    idx: dict[str, dict] = {}
    for entry in load_terminated():
        idx[_canon(entry["name"], raw_aliases)] = entry
    return idx, raw_aliases


def is_terminated(name: str) -> bool:
    """True if `name` (alias-resolved) is on the terminated list. Convenience
    for a one-off check; for a whole report use terminated_among() (one read)."""
    idx, raw = _index()
    return _canon(name, raw) in idx


def terminated_among(names) -> list[dict]:
    """Given the ICD names a report is about to fill, return the ones that are
    terminated, each as {"report_name", "name", "date", "notes"} where
    report_name is the name as the report knows it and name is as logged."""
    idx, raw = _index()
    hits: list[dict] = []
    for nm in names:
        entry = idx.get(_canon(nm, raw))
        if entry:
            hits.append({"report_name": nm, **entry})
    return hits


def format_flag(hits: list[dict], report_label: str = "this report") -> str | None:
    """Render the standard callout for a report's output, or None if no hits."""
    if not hits:
        return None
    lines = [f"⚠ {len(hits)} terminated ICD(s) still on {report_label} — remove them:"]
    for h in hits:
        when = f" (terminated {h['date']})" if h.get("date") else ""
        note = f" — {h['notes']}" if h.get("notes") else ""
        lines.append(f"   • {h['report_name']}{when}{note}")
    return "\n".join(lines)


def alert_terminated(names, report_label: str = "this report") -> tuple[list[dict], str | None]:
    """The standard one-call hook for any report: check the names it filled
    against the terminated list and, if any still appear, EMIT the alert to the
    live run output (print) + the logger so the runner sees it. Returns
    (hits, flag_str|None); fold flag_str into the report's manifest note so
    unattended runs surface it in the email too.

    Non-destructive — it only warns. A human removes the section/row. Tolerant:
    any Sheet error inside is swallowed (returns no hits) so the terminated
    check can never break a report's run."""
    try:
        hits = terminated_among(names)
    except Exception as e:  # noqa: BLE001 — advisory check must never fail a run
        print(f"⚠ terminated-ICD check skipped ({e})", flush=True)
        return [], None
    flag = format_flag(hits, report_label)
    if flag:
        print("\n" + flag + "\n", flush=True)
        _log.warning("terminated ICD(s) still on %s: %s", report_label,
                     ", ".join(h["report_name"] for h in hits))
    return hits, flag


def log_terminated(name: str, date: str = "", notes: str = "") -> None:
    """Append a terminated ICD row (deduped on name, case-insensitive). Prints a
    confirmation. Logs the name as given — log it as it appears in ownerville."""
    name = (name or "").strip()
    if not name:
        return
    try:
        ws = _open_tab()
    except Exception as e:  # noqa: BLE001
        print(f"⚠ Couldn't open '{TERMINATED_TAB}' tab to save: {e}")
        return
    for row in (ws.get("A2:A1000") or []):
        if row and (row[0] or "").strip().lower() == name.lower():
            print(f"  ('{name}' already in {TERMINATED_TAB} — skipped)")
            return
    ws.append_row([name, date, notes], value_input_option="RAW")
    print(f"  ✓ Logged terminated ICD: '{name}'")
