"""One-shot Hub access diagnostic (temporary — safe to delete after debugging).

Why this exists: JD's Hub throws `_read_intake ... PermissionError` and cards
don't send, while the same code works from a plain Terminal Python. This prints
everything needed to tell WHERE access breaks, with no shell quoting (Slack was
mangling inline quotes).

Run from the repo root:
    .venv/bin/python automations/recruiting_report/diag_hub.py
"""
import os
import subprocess
import sys
import traceback
from pathlib import Path

# Make `automations...` importable no matter how this file is launched.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

print("PYTHON :", sys.executable)
print("USER   :", os.environ.get("USER"), "| uid", os.getuid())

tok = Path.home() / ".config" / "recruiting-report" / "oauth-token.json"
print("TOKEN  :", tok)
print("  exists :", tok.exists())
print("  R_OK   :", os.access(str(tok), os.R_OK))
try:
    perms = subprocess.run(["stat", "-f", "%Sp %Su:%Sg", str(tok)],
                           capture_output=True, text=True).stdout.strip()
    print("  perms  :", perms)
except Exception as e:  # noqa: BLE001
    print("  stat err:", e)
try:
    n = len(tok.read_text())
    print("  read   : OK,", n, "bytes")
except Exception as e:  # noqa: BLE001 — this is the whole point: catch the real error
    print("  read   : FAILED ->", type(e).__name__, "|", e)

print("--- intake auth + read ---")
try:
    from automations.recruiting_report import fill
    sh = fill.open_by_key("1eJ3-BeOvbGaWV5XZ8BNgJT9QrgbaToAf9W2PdMABTAw")
    rows = sh.worksheet("Automation Backlog").get_all_records()
    print("INTAKE OK:", len(rows), "rows")
except Exception:  # noqa: BLE001
    traceback.print_exc()
