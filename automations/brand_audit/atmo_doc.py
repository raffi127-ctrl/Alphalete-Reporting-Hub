"""Write the weekly rep shout-out names into the Monday ATMO print (Google Doc).

Companion to rep_shoutouts.py. Besides DMing the list, Maud wants the reps'
names printed on the Monday ATMO outline — as a bulleted list under the
"Google Review S/O's & Money!" line — so they get read out at the Monday
meeting (Megan, 2026-08-07). Format is "Name x N" (the count only when > 1,
e.g. "Willie x 2"); a single mention is just the name.

Target: "Fiber - Local Office Checklist - Raf", the "Atmo Print" tab.

STRICTLY NON-DESTRUCTIVE (Megan: "NOTHING else on the sheet should ever get
deleted"). Each week it deletes ONLY the bullets IT wrote last week — the
paragraphs directly under the anchor line that are nested DEEPER than it (its
own sub-bullets) — and stops at the very first paragraph that isn't one of
those (e.g. the next top-level bullet "Promote Texas De Brazil Competition").
Everything else in the doc is never touched. If the anchor line can't be found,
it writes nothing and raises — it never guesses where to edit.

AUTH: needs the Google Docs scope (documents). The recruiting/sheets tokens are
spreadsheets-only, so this needs its OWN one-time authorization:
    python -m automations.brand_audit.atmo_doc --authorize
Until that token exists (has_token() is False) the writer is inert and
rep_shoutouts just does the Slack DM.

ROLLOUT GUARD: _DOC_WRITE_ENABLED stays False until the delete/insert plan has
been verified in --dry-run against the real doc structure (preview-before-
rollout). While False, live writes are refused even with a token; dry-run
(read-only planning) always works.
"""
from __future__ import annotations

import re
from pathlib import Path

# A nested bullet we're willing to replace: empty (the placeholder) or a
# shout-out entry — a name, optionally " x N". Anything else nested under the
# anchor is FOREIGN prose we must never delete (we stop at it instead).
_OURS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 .'’\-]*(?: x \d+)?$")


def _is_ours(text: str) -> bool:
    t = text.strip()
    return t == "" or (len(t) <= 40 and bool(_OURS_RE.match(t)))

# The doc + tab Maud circled. Tab id is stable (from the doc URL ?tab=...).
DOC_ID = "18iXRqlV6-343H0Y8ozLonKZHB_HuyaJBYTWPVh4Yw1M"
TAB_ID = "t.z8lov94yp2dj"                 # "Atmo Print"
# Substring that identifies the recognition line we hang the names under. Kept
# loose (no apostrophe/emoji) so smart-quote or wording tweaks don't break it.
ANCHOR_SUBSTRING = "Google Review S/O"

GDOCS_SCOPES = ["https://www.googleapis.com/auth/documents"]

# Reuse the existing Desktop OAuth *client* (same file the Sheets/GBP tokens
# use); only the scope + saved token differ.
_OAUTH_CLIENT_PATH = Path.home() / ".config" / "recruiting-report" / "oauth-client.json"
GDOCS_TOKEN_PATH = Path.home() / ".config" / "brand-audit" / "gdocs-token.json"

# Flip to True only after the plan has been dry-run-verified against the live
# doc (see module docstring). Guards against an untested destructive edit.
_DOC_WRITE_ENABLED = True


def has_token() -> bool:
    return GDOCS_TOKEN_PATH.exists()


def authorize() -> None:
    """One-time interactive OAuth for the Docs scope. Opens a browser — sign in
    as an account that can EDIT the Fiber Local Office Checklist doc."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not _OAUTH_CLIENT_PATH.exists():
        raise RuntimeError(
            f"OAuth client not found at {_OAUTH_CLIENT_PATH}. Ask Megan for "
            "oauth-client.json (same file the Sheets/GBP tokens use).")
    flow = InstalledAppFlow.from_client_secrets_file(
        str(_OAUTH_CLIENT_PATH), GDOCS_SCOPES)
    creds = flow.run_local_server(
        port=0, prompt="consent",
        authorization_prompt_message=(
            "Opening your browser to authorize Google Docs access.\n"
            "➡  Sign in as an account that can EDIT the 'Fiber - Local Office "
            "Checklist - Raf' doc, and approve.\n"
            "If it doesn't open, copy this URL:\n{url}"),
        success_message="Done — close this tab and return to the terminal.")
    GDOCS_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GDOCS_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"✓ Saved Docs token to {GDOCS_TOKEN_PATH}")


def _service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    if not GDOCS_TOKEN_PATH.exists():
        raise RuntimeError(
            f"No Docs token at {GDOCS_TOKEN_PATH}. Run the one-time "
            "authorization:  python -m automations.brand_audit.atmo_doc --authorize")
    creds = Credentials.from_authorized_user_file(str(GDOCS_TOKEN_PATH), GDOCS_SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            GDOCS_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError("Docs token invalid and can't refresh — re-run "
                               "python -m automations.brand_audit.atmo_doc --authorize")
    return build("docs", "v1", credentials=creds, cache_discovery=False)


# ── doc structure helpers ────────────────────────────────────────────────────
def _find_tab(doc: dict, tab_id: str) -> dict | None:
    """The tab whose id == tab_id, searching nested child tabs."""
    def walk(tabs):
        for t in tabs or []:
            props = t.get("tabProperties", {})
            if props.get("tabId") == tab_id:
                return t
            hit = walk(t.get("childTabs"))
            if hit:
                return hit
        return None
    return walk(doc.get("tabs"))


def _para_text(el: dict) -> str:
    para = el.get("paragraph")
    if not para:
        return ""
    out = []
    for pe in para.get("elements", []):
        tr = pe.get("textRun")
        if tr:
            out.append(tr.get("content", ""))
    return "".join(out)


# Indent (points) of the anchor's own list level and the sub-bullet level we
# write at. The Atmo list defines level 0 at indentStart 36 / firstLine 18 and
# level 1 (the ○ sub-bullet) at 72 / 54. Setting a paragraph's indent to the
# level-1 magnitudes is what visually nests it — the Docs API won't let us set
# bullet.nestingLevel directly (leading-tab nesting is silently absorbed on
# insert here), and indent is what Megan asked for ("make sure the bullet
# indents"). We therefore also DETECT our prior bullets by indent, not by the
# nestingLevel field (which stays 0).
_SUB_INDENT_START = {"magnitude": 72, "unit": "PT"}
_SUB_INDENT_FIRST = {"magnitude": 54, "unit": "PT"}


def _is_list_item(el: dict) -> bool:
    para = el.get("paragraph")
    return bool(para) and "bullet" in para


def _indent_pt(el: dict) -> float:
    """Left indent of a paragraph in points (0 if unset)."""
    ps = (el.get("paragraph") or {}).get("paragraphStyle", {})
    return ((ps.get("indentStart") or {}).get("magnitude")) or 0


def _plan(content: list[dict]) -> tuple[int, float, list[tuple[int, int]]]:
    """From a tab's body content, locate the anchor line and the sub-bullets we
    previously wrote under it.

    Returns (anchor_end_index, anchor_indent_pt, delete_ranges) where
    delete_ranges is the list of (startIndex, endIndex) of our own prior
    sub-bullets — the ONLY thing we ever delete. Raises if the anchor line
    isn't found (never edits blindly)."""
    anchor_i = None
    for i, el in enumerate(content):
        if "paragraph" not in el:
            continue
        if ANCHOR_SUBSTRING.lower() in _para_text(el).lower():
            anchor_i = i
            break
    if anchor_i is None:
        raise RuntimeError(
            f"Anchor line ({ANCHOR_SUBSTRING!r}) not found in the Atmo Print "
            "tab — refusing to edit. Did the line move or get renamed?")
    anchor_el = content[anchor_i]
    anchor_indent = _indent_pt(anchor_el)
    anchor_end = anchor_el["endIndex"]
    deletes = []
    for el in content[anchor_i + 1:]:
        if "paragraph" not in el:
            break                          # a table/section boundary — stop
        # Mine = a list item indented DEEPER than the anchor. The next
        # same-or-less-indented bullet (a real sibling announcement) or any
        # non-list paragraph is NOT mine and ends the region.
        if not _is_list_item(el) or _indent_pt(el) <= anchor_indent:
            break
        # Extra guard: only replace an empty placeholder or a shout-out-shaped
        # entry. If a deeper bullet holds real prose (someone parked a note
        # here), STOP — never delete it.
        if not _is_ours(_para_text(el)):
            break
        deletes.append((el["startIndex"], el["endIndex"]))
    return anchor_end, anchor_indent, deletes


# The single bullet written when a week had no rep-naming reviews (Megan:
# "enter 'No New Reviews' if there are 0"). Name-shaped so next week's run
# replaces it cleanly.
EMPTY_LABEL = "No New Reviews"


def format_labels(ranked: list[tuple[str, int]]) -> list[str]:
    """'Name x N' when N>1 (Maud's convention), just 'Name' for a single. An
    empty week returns the single EMPTY_LABEL bullet."""
    if not ranked:
        return [EMPTY_LABEL]
    return [f"{name} x {count}" if count > 1 else name for name, count in ranked]


def write_shoutouts(ranked: list[tuple[str, int]], *, dry_run: bool = True) -> dict:
    """Replace last week's shout-out bullets under the anchor line with this
    week's `ranked` names. Read-only + returns a plan when dry_run; performs the
    edit otherwise. Never deletes anything but its own prior sub-bullets."""
    labels = format_labels(ranked)
    svc = _service()
    doc = svc.documents().get(
        documentId=DOC_ID, includeTabsContent=True).execute()
    tab = _find_tab(doc, TAB_ID)
    if not tab:
        raise RuntimeError(f"Tab {TAB_ID} not found in doc {DOC_ID}.")
    content = tab["documentTab"]["body"]["content"]
    anchor_end, anchor_indent, deletes = _plan(content)
    plan = {"labels": labels, "delete_count": len(deletes),
            "anchor_end": anchor_end, "dry_run": dry_run}
    if dry_run:
        return plan
    if not _DOC_WRITE_ENABLED:
        plan["skipped"] = ("doc write not enabled yet — verify the plan in "
                           "--dry-run against the live doc, then flip "
                           "_DOC_WRITE_ENABLED")
        return plan

    loc = {"tabId": TAB_ID}
    # 1) Delete our prior sub-bullets, highest index first so earlier indices
    #    stay valid. (Only these ranges — nothing else.)
    reqs = []
    for start, end in sorted(deletes, key=lambda r: r[0], reverse=True):
        reqs.append({"deleteContentRange": {"range": {
            "segmentId": "", "startIndex": start, "endIndex": end, **loc}}})
    if reqs:
        svc.documents().batchUpdate(
            documentId=DOC_ID, body={"requests": reqs}).execute()

    # 2) Re-read (indices shifted after the delete), then insert the new names as
    #    nested bullets. A single leading TAB per line makes createParagraphBullets
    #    put them at nesting level anchor+1 (it counts leading tabs, then eats them).
    doc = svc.documents().get(documentId=DOC_ID, includeTabsContent=True).execute()
    content = _find_tab(doc, TAB_ID)["documentTab"]["body"]["content"]
    anchor_end, anchor_indent, _ = _plan(content)
    text = "".join(f"{lbl}\n" for lbl in labels)
    insert_at = anchor_end
    rng = {"startIndex": insert_at, "endIndex": insert_at + len(text), **loc}
    # Insert the names, make them bullets (they join the anchor's list at the
    # top level), then indent them to the sub-bullet level so they sit UNDER the
    # recognition line. Leading-tab nesting is absorbed on insert here, so we
    # nest via indentation, which is what actually renders.
    svc.documents().batchUpdate(documentId=DOC_ID, body={"requests": [
        {"insertText": {"location": {"index": insert_at, **loc}, "text": text}}]}
    ).execute()
    svc.documents().batchUpdate(documentId=DOC_ID, body={"requests": [
        {"createParagraphBullets": {
            "range": dict(rng), "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}},
        {"updateParagraphStyle": {
            "range": dict(rng),
            "paragraphStyle": {"indentStart": _SUB_INDENT_START,
                               "indentFirstLine": _SUB_INDENT_FIRST},
            "fields": "indentStart,indentFirstLine"}}]}
    ).execute()
    plan["posted"] = f"{len(labels)} names written"
    return plan


def main(argv=None) -> int:
    import argparse
    import sys
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="brand_audit.atmo_doc")
    p.add_argument("--authorize", action="store_true",
                   help="one-time interactive OAuth for the Docs scope")
    p.add_argument("--dry-run", action="store_true",
                   help="read the doc and print the edit plan; write nothing")
    args = p.parse_args(argv)
    if args.authorize:
        authorize()
        return 0
    # Demo/verify with the current live tally.
    from automations.brand_audit import rep_shoutouts as rs
    from automations.brand_audit.config import DEFAULT_COMPANY
    from automations.brand_audit import intake
    company = intake.find_company(DEFAULT_COMPANY)
    ranked = rs.tally(rs.reviews_in_window(company)) if company else []
    out = write_shoutouts(ranked, dry_run=not args.authorize and (args.dry_run or True))
    print("labels:", out.get("labels"))
    print("would delete", out.get("delete_count"), "prior sub-bullet(s)")
    if out.get("skipped"):
        print("skipped:", out["skipped"])
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
