"""Email the owner whenever a card is published to the shared Hub library.

Fires from dashboard._save_uploaded_report on every successful publish — a
brand-new card AND an edit (re-upload under the same id). The whole point is to
answer "what changed": a new card shows its metadata + a code preview; an edit
shows which metadata fields moved and a unified diff of the script.

Best-effort: the caller wraps build_and_send in try/except so a mail failure
never blocks the publish.
"""
from __future__ import annotations

import datetime as dt
import difflib
import html
import socket

from automations.shared import hub_notify_email

# Keep emails readable — cap the code preview / diff. Uploads that blow past
# this still notify; the body just says how much was elided.
_MAX_PREVIEW_LINES = 150
_MAX_DIFF_LINES = 400

# Metadata keys worth calling out when they change on an edit (in display order).
_TRACKED_META = [
    ("name", "Name"), ("emoji", "Emoji"), ("description", "Description"),
    ("module", "Module"), ("schedule", "Schedule"), ("assignees", "Assignees"),
    ("sheet_url", "Sheet URL"), ("needs_login", "Needs login"),
    ("args", "Args"), ("action_label", "Run-button label"),
]


def _fmt(v) -> str:
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v) if v else "—"
    s = "" if v is None else str(v)
    return s if s.strip() else "—"


def _meta_changes(old: dict, new: dict) -> list[tuple[str, str, str]]:
    """(label, old, new) for each tracked metadata key that actually moved."""
    out = []
    for key, label in _TRACKED_META:
        ov, nv = old.get(key), new.get(key)
        if _fmt(ov) != _fmt(nv):
            out.append((label, _fmt(ov), _fmt(nv)))
    return out


def _clip(lines: list[str], limit: int) -> tuple[list[str], int]:
    if len(lines) <= limit:
        return lines, 0
    return lines[:limit], len(lines) - limit


def _script_diff(old_script: str, new_script: str) -> tuple[list[str], int]:
    diff = list(difflib.unified_diff(
        (old_script or "").splitlines(),
        (new_script or "").splitlines(),
        fromfile="previous", tofile="uploaded", lineterm=""))
    return _clip(diff, _MAX_DIFF_LINES)


# ---- rendering -----------------------------------------------------------

def _rows_html(pairs: list[tuple[str, str]]) -> str:
    tr = ""
    for k, v in pairs:
        tr += (f'<tr><td style="padding:2px 12px 2px 0;color:#666;'
               f'white-space:nowrap;vertical-align:top">{html.escape(k)}</td>'
               f'<td style="padding:2px 0">{html.escape(v)}</td></tr>')
    return f'<table style="border-collapse:collapse;font-size:14px">{tr}</table>'


def _pre_html(text: str, *, color: str = "#111") -> str:
    return (f'<pre style="background:#f6f8fa;border:1px solid #e1e4e8;'
            f'border-radius:6px;padding:10px;overflow-x:auto;font-size:12px;'
            f'line-height:1.45;color:{color};white-space:pre-wrap">'
            f'{html.escape(text)}</pre>')


def _diff_html(diff_lines: list[str]) -> str:
    # Color +/- lines like a code review, everything else plain.
    rows = []
    for ln in diff_lines:
        if ln.startswith("+") and not ln.startswith("+++"):
            bg, col = "#e6ffed", "#22863a"
        elif ln.startswith("-") and not ln.startswith("---"):
            bg, col = "#ffeef0", "#b31d28"
        elif ln.startswith("@@"):
            bg, col = "#f1f8ff", "#005cc5"
        else:
            bg, col = "transparent", "#444"
        rows.append(f'<div style="background:{bg};color:{col}">'
                    f'{html.escape(ln) or "&nbsp;"}</div>')
    return (f'<div style="background:#f6f8fa;border:1px solid #e1e4e8;'
            f'border-radius:6px;padding:10px;overflow-x:auto;font-size:12px;'
            f'line-height:1.45;font-family:ui-monospace,Menlo,Consolas,monospace;'
            f'white-space:pre">{"".join(rows)}</div>')


def build_and_send(metadata: dict, script_text: str,
                   preimage: dict | None, *, dry_run: bool = False) -> None:
    """preimage: {'script': str, 'metadata': dict} of the row this REPLACED, or
    None for a brand-new card."""
    is_update = preimage is not None
    name = _fmt(metadata.get("name") or metadata.get("id"))
    rid = _fmt(metadata.get("id"))
    who = _fmt(metadata.get("creator"))
    # Build the 12-hour time by hand — %-I is Unix-only and the Hub also runs
    # on Windows (CLAUDE.md: no %-I strftime).
    _now = dt.datetime.now()
    when = (_now.strftime("%b %d, %Y at ")
            + f"{_now.hour % 12 or 12}:{_now.minute:02d} " + _now.strftime("%p"))
    machine = socket.gethostname()

    verb = "updated" if is_update else "published"
    icon = "✏️" if is_update else "🆕"
    subject = (f"{icon} Hub card {verb}: {name}"
               + (f" (by {who})" if who != "—" else ""))

    facts = [
        ("Card", name), ("ID", rid), ("Uploaded by", who), ("When", when),
        ("Machine", machine), ("Module", _fmt(metadata.get("module"))),
        ("Schedule", _fmt(metadata.get("schedule"))),
        ("Assignees", _fmt(metadata.get("assignees"))),
        ("Description", _fmt(metadata.get("description"))),
    ]

    # ---- body: HTML + plaintext, built in parallel ----
    h = [f'<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;'
         f'color:#111;max-width:820px">',
         f'<h2 style="margin:0 0 4px">{icon} Hub card {verb}</h2>',
         f'<p style="margin:0 0 14px;color:#666">Someone {verb} a card in the '
         f'shared Report Library.</p>',
         _rows_html(facts)]
    t = [f"{icon} Hub card {verb}", ""]
    t += [f"{k}: {v}" for k, v in facts]

    if is_update:
        changes = _meta_changes(preimage.get("metadata") or {}, metadata)
        h.append('<h3 style="margin:18px 0 6px">What changed</h3>')
        if changes:
            h.append(_rows_html([(lbl, f"{ov}  →  {nv}")
                                 for lbl, ov, nv in changes]))
            t += ["", "Metadata changes:"]
            t += [f"  {lbl}: {ov} -> {nv}" for lbl, ov, nv in changes]
        else:
            h.append('<p style="color:#666;margin:2px 0">No metadata fields '
                     'changed.</p>')
            t += ["", "Metadata changes: none"]

        diff_lines, elided = _script_diff(
            preimage.get("script") or "", script_text)
        h.append('<h3 style="margin:18px 0 6px">Code changes</h3>')
        if diff_lines:
            h.append(_diff_html(diff_lines))
            t += ["", "Code diff:"] + diff_lines
            if elided:
                note = f"… {elided} more diff line(s) not shown."
                h.append(f'<p style="color:#666;margin:6px 0">{note}</p>')
                t += [note]
        else:
            h.append('<p style="color:#666;margin:2px 0">Code is byte-identical '
                     '— only metadata changed.</p>')
            t += ["", "Code diff: none (script unchanged)"]
    else:
        preview, elided = _clip((script_text or "").splitlines(),
                                _MAX_PREVIEW_LINES)
        total = len((script_text or "").splitlines())
        h.append(f'<h3 style="margin:18px 0 6px">Code ({total} lines)</h3>')
        h.append(_pre_html("\n".join(preview) or "(empty)"))
        t += ["", f"Code ({total} lines):", ""] + preview
        if elided:
            note = f"… {elided} more line(s) not shown."
            h.append(f'<p style="color:#666;margin:6px 0">{note}</p>')
            t += [note]

    h.append('</div>')

    hub_notify_email.send_html(
        subject, "".join(h), "\n".join(t),
        dry_run=dry_run, tag="hub-upload")
