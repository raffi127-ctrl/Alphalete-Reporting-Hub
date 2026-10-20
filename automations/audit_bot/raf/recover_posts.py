import time, json, re
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(".env")
import slack_watcher as sw
w=sw.web; BOT=sw._BOT_USER_ID
# index every completion by its audio_filename
by_fn={}
for line in open("completions.jsonl"):
    line=line.strip()
    if not line: continue
    d=json.loads(line); by_fn[d.get("audio_filename","")]=d
now=time.time(); since=int(now-8*3600)
ax=(".m4a",".mp3",".wav",".mp4",".mov",".aac",".m4v")
files=[]; cur=None
while True:
    r=w.files_list(ts_from=since,count=200,**({"cursor":cur} if cur else {}))
    files+=r.get("files",[]); cur=(r.get("response_metadata") or {}).get("next_cursor")
    if not cur: break
def dmch(f):
    for k in ("ims","groups","channels"):
        v=f.get(k) or []
        if v: return v[0]
    return None
def answered(ch,fts):
    if not ch: return None
    try:
        h=w.conversations_history(channel=ch,oldest=str(fts),limit=50,inclusive=True)
        return any((float(m.get("ts",0))>float(fts) and (m.get("user")==BOT or m.get("bot_id"))) for m in h.get("messages",[]))
    except Exception: return None
posted=0; missing=[]; seen=set()
for f in files:
    nm=f.get("name") or ""
    if not nm.lower().endswith(ax): continue
    C=str(f.get("created",0)); U=f.get("user"); ch=dmch(f)
    key=(U,nm.strip().lower())
    if key in seen: continue
    if C.endswith(".0"): C=C[:-2]
    if answered(ch,C) is not False: continue          # already delivered
    expected=f"slack-{C}_{sw.safe_stem(nm)}"
    rec=by_fn.get(expected)
    if not rec or rec.get("rejected") or not rec.get("report_pdf"):
        missing.append((nm,U,expected)); continue
    seen.add(key)
    prefix=f"slack-{C}_000000"
    mp=sw._load_mappings()
    mp[prefix]={"channel":ch,"thread_ts":C,"user":U,"original_name":nm,"received_at":datetime.now().isoformat()}
    sw._save_mappings(mp)
    fixed=dict(rec); fixed["audio_filename"]=f"slack-{C}_000000_{sw.safe_stem(nm)}"
    try:
        ok=sw.post_completion_to_slack(fixed)
        print(f"  {'POSTED' if ok else 'HELD/none'}: {sw._user_display(U)} - {nm}", flush=True); posted+= 1 if ok else 0
    except Exception as e:
        print(f"  FAIL {nm}: {e}", flush=True)
    time.sleep(1)
print(f"DONE recover: delivered {posted}; unmatched pdf {len(missing)}", flush=True)
for nm,u,exp in missing: print(f"  no-pdf: {nm} [{exp}]", flush=True)
