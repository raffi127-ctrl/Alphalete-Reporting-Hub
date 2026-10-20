import time, json
from dotenv import load_dotenv
load_dotenv(".env")
import slack_watcher as sw
w=sw.web; BOT=sw._BOT_USER_ID
pend=sw._load_mappings()
already={(v.get("user"),(v.get("original_name") or "").strip().lower()) for v in pend.values()}
now=time.time(); since=int(now-3600)   # last hour covers the move window
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
    for _ in range(2):
        try:
            h=w.conversations_history(channel=ch,oldest=str(fts),limit=50,inclusive=True)
            return any((float(m.get("ts",0))>float(fts) and (m.get("user")==BOT or m.get("bot_id"))) for m in h.get("messages",[]))
        except Exception:
            time.sleep(3)
    return None
seen=set(); inj=0
for f in sorted(files, key=lambda x:x.get("created",0)):
    nm=f.get("name") or ""
    if not nm.lower().endswith(ax): continue
    c=f.get("created",0); U=f.get("user"); ch=dmch(f)
    key=(U,nm.strip().lower())
    if key in already or key in seen: continue
    if c>now-120: continue
    if answered(ch,c) is not False: continue
    seen.add(key)
    # FIXED prefix: pass decimal so _slack_prefix_for makes two segments -> auto-posts
    try:
        sw.handle_file_shared(f, ch, None, U, f"{c}.000000"); inj+=1
        print(f"  re-injected(fixed): {sw._user_display(U)} - {nm}", flush=True)
    except Exception as e:
        print(f"  FAIL {nm}: {e}", flush=True)
    time.sleep(1)
print(f"DONE gapscan: {inj} re-injected (will grade+auto-post)", flush=True)
