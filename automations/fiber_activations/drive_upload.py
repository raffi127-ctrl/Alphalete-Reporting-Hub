"""Upload the 6 PNGs to alphaletereporting's Drive, overwriting same-named files.

Folder: 'Captainship Activations - PNGs' (created/reused by this code via the
drive.file token — see drive_auth.py). Same account, so NO sharing by code.

Overwrite semantics: each PNG name carries the date (…by M.D.png). A file with
the SAME name already in the folder is UPDATED in place (same fileId, link
stays stable); otherwise it's created. So a same-day re-run overwrites the day's
images instead of piling up duplicates.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from automations.fiber_activations import captains as C
from automations.fiber_activations import drive_auth

_FOLDER_MIME = "application/vnd.google-apps.folder"


def _service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=drive_auth.load_credentials(),
                 cache_discovery=False)


def ensure_folder(svc, folder_id: Optional[str] = None) -> str:
    """Return the folder id. Uses configured id if set; else finds the folder by
    name among files this app created, else creates it (printing the id to paste
    into captains.DRIVE_FOLDER_ID)."""
    folder_id = folder_id or C.DRIVE_FOLDER_ID
    if folder_id:
        return folder_id
    q = (f"name = '{C.DRIVE_FOLDER_NAME}' and mimeType = '{_FOLDER_MIME}' "
         f"and trashed = false")
    found = svc.files().list(q=q, spaces="drive",
                             fields="files(id,name)").execute().get("files", [])
    if found:
        return found[0]["id"]
    folder = svc.files().create(
        body={"name": C.DRIVE_FOLDER_NAME, "mimeType": _FOLDER_MIME},
        fields="id").execute()
    fid = folder["id"]
    print(f"  ↪ created Drive folder '{C.DRIVE_FOLDER_NAME}' (id={fid}). "
          f"Paste it into captains.DRIVE_FOLDER_ID to skip the lookup next time.")
    return fid


def _upload_one(svc, folder_id: str, path: Path) -> str:
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(path), mimetype="image/png", resumable=False)
    q = f"name = '{path.name}' and '{folder_id}' in parents and trashed = false"
    existing = svc.files().list(q=q, spaces="drive",
                                fields="files(id)").execute().get("files", [])
    if existing:
        svc.files().update(fileId=existing[0]["id"], media_body=media).execute()
        return "updated"
    svc.files().create(body={"name": path.name, "parents": [folder_id]},
                       media_body=media, fields="id").execute()
    return "created"


def upload_all(paths, folder_id: Optional[str] = None,
               dry_run: bool = False) -> dict:
    """Upload each PNG (overwrite same-name). dry_run only prints the plan and
    does NOT authenticate or call Drive. Returns {filename: 'updated'|'created'|
    'would-upload'}."""
    paths = [Path(p) for p in paths]
    if dry_run:
        return {p.name: "would-upload" for p in paths}
    svc = _service()
    fid = ensure_folder(svc, folder_id)
    results = {}
    for p in paths:
        results[p.name] = _upload_one(svc, fid, p)
    return results
