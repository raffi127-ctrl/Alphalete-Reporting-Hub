import time, json
from dotenv import load_dotenv
load_dotenv(".env")
import slack_watcher as sw
w=sw.web; BOT=sw._BOT_USER_ID
pend=sw._load_mappings()
already={(v.get("user"),(v.get("original_name") or "").strip().lower()) for v in pend.values()}
now=time.time(); since=int(now-28800)   # 8h
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
    for a in range(5):
        try:
            h=w.conversations_history(channel=ch,oldest=str(fts),limit=60,inclusive=True)
            for m in h.get("messages",[]):
                if float(m.get("ts",0))<=float(fts): continue
                if m.get("user")!=BOT and not m.get("bot_id"): continue
                if m.get("files"): return True
                if "owner" in (m.get("text") or "").lower(): return True
            return False
        except Exception:
            time.sleep(3*(a+1))
    return None
seen=set(); inj=0; errs=0; idx=0
for f in sorted(files, key=lambda x:x.get("created",0)):
    nm=f.get("name") or ""
    if not nm.lower().endswith(ax): continue
    c=f.get("created",0); U=f.get("user"); ch=dmch(f)
    key=(U,nm.strip().lower())
    if key in already or key in seen: continue
    if c>now-120: continue
    ans=answered(ch,c)
    if ans is None: errs+=1; continue
    if ans is True: continue
    seen.add(key); idx+=1
    try:
        sw.handle_file_shared(f, ch, None, U, f"{c}.{idx:06d}")   # unique 2-seg prefix -> auto-delivers
        inj+=1; print(f"  re-inject: {sw._user_display(U)} - {nm}", flush=True)
    except Exception as e:
        print(f"  FAIL {nm}: {e}", flush=True)
    time.sleep(0.6)
print(f"DONE: re-injected {inj}; reply-check unresolved {errs}", flush=True)
