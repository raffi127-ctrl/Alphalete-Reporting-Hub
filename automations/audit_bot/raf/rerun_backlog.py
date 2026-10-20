import sys, json, time
from pathlib import Path
from collections import defaultdict
RT = Path(__file__).parent.resolve()
sys.path.insert(0, str(RT))
from dotenv import load_dotenv
load_dotenv(RT/".env")
import audit
INBOX = RT.parent/"inbox"
DUPES = RT.parent/"inbox_dupes_skipped"
DUPES.mkdir(exist_ok=True)
pend = json.loads((RT/"slack_pending.json").read_text())
def prefix(fn): return "_".join(fn.split("_")[:2])
groups = defaultdict(list)
for f in sorted(INBOX.glob("*")):
    meta = pend.get(prefix(f.name), {})
    key = (meta.get("user","?"), (meta.get("original_name") or f.name).strip().lower())
    groups[key].append((f, meta.get("received_at","")))
keeps, dupes = [], []
for key, items in groups.items():
    items.sort(key=lambda x: x[1])
    keeps.append(items[-1][0]); dupes += [i[0] for i in items[:-1]]
print(f"START: {len(keeps)} to process, {len(dupes)} dupes moved aside", flush=True)
for d in dupes:
    try: d.rename(DUPES/d.name)
    except Exception: pass
ok=fail=0
for i,f in enumerate(keeps,1):
    if not f.exists(): continue
    print(f"[{i}/{len(keeps)}] {f.name}", flush=True)
    try:
        audit.audit_file(f); ok+=1
    except Exception as e:
        fail+=1; print(f"   FAILED: {e}", flush=True)
    time.sleep(2)
print(f"DONE: {ok} graded, {fail} failed", flush=True)
