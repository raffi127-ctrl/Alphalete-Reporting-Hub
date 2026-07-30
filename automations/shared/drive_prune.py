"""Keep a Drive review folder from growing forever.

Every review gate uploads ONE dated PDF per day into a folder it reuses (the
folder is found by name and only created if missing, so folders never multiply).
The files do: one per day, per report, forever — 365 a year in each folder, and
nobody ever opens a review PDF from three months ago. It was approved or it
wasn't; the record of that lives in the Slack thread, not here.

So each upload prunes its own folder back to the newest `keep_last` files.

TRASHED, NOT DELETED. Drive's trash holds them ~30 more days, so a mistake here
costs a restore and not a file. Nothing outside the folder is ever touched, and
the gate only ever holds a drive.file token — it physically cannot see, let
alone remove, a file it did not create.
"""
from __future__ import annotations

from typing import Optional


def prune_folder(svc, folder_id: str, keep_last: Optional[int],
                 *, verbose: bool = True) -> int:
    """Trash all but the newest `keep_last` files in `folder_id`.

    `keep_last=None` (or <= 0) disables pruning entirely. Returns how many were
    trashed. Never raises: a folder that can't be tidied must not cost us the
    upload that just succeeded — the link matters, the housekeeping doesn't.
    """
    if not keep_last or keep_last <= 0:
        return 0
    try:
        files = svc.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            spaces="drive", orderBy="createdTime desc",
            fields="files(id,name)", pageSize=1000,
        ).execute().get("files", [])
    except Exception as e:  # noqa: BLE001
        if verbose:
            print(f"  (folder not pruned: {type(e).__name__})", flush=True)
        return 0

    stale = files[keep_last:]
    trashed = 0
    for f in stale:
        try:
            svc.files().update(fileId=f["id"], body={"trashed": True}).execute()
            trashed += 1
        except Exception as e:  # noqa: BLE001 — one stubborn file, not the batch
            if verbose:
                print(f"  (could not trash {f['name']}: {type(e).__name__})",
                      flush=True)
    if trashed and verbose:
        print(f"  tidied Drive: trashed {trashed} review PDF(s) older than the "
              f"last {keep_last}", flush=True)
    return trashed
