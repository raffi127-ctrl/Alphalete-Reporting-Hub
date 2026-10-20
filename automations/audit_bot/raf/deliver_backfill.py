import json, re, time
from dotenv import load_dotenv
load_dotenv(".env")
import slack_watcher as sw

def comps_by_prefix():
    c={}
    for line in open("completions.jsonl"):
        line=line.strip()
        if not line: continue
        d=json.loads(line); fn=d.get("audio_filename","")
        m=re.match(r"^(slack-\d+)_", fn)
        if m: c.setdefault(m.group(1), []).append(d)
    return c

delivered=0
for rnd in range(8):
    pend=sw._load_mappings()
    single=[k for k in pend if re.match(r"^slack-\d+$", k)]
    if not single:
        print("all single-seg keys cleared", flush=True); break
    comps=comps_by_prefix()
    for k in list(single):
        info=sw._load_mappings().get(k)
        if not info: continue
        cands=[r for r in comps.get(k, []) if r.get("report_pdf") and not r.get("rejected")]
        if not cands:
            continue  # still grading — retry next round
        rec=cands[0]
        if len(cands)>1:
            stem=sw.safe_stem(info.get("original_name") or "").lower().split(".")[0]
            for r in cands:
                if stem and stem in r.get("audio_filename","").lower(): rec=r; break
        C=k.split("slack-",1)[1]; newkey=f"slack-{C}_000000"
        mp=sw._load_mappings(); mp[newkey]=dict(info); mp.pop(k,None); sw._save_mappings(mp)
        fixed=dict(rec); fixed["audio_filename"]=re.sub(r"^slack-\d+_", newkey+"_", rec["audio_filename"], count=1)
        try:
            ok=sw.post_completion_to_slack(fixed)
            print(f"  {'DELIVERED' if ok else 'held/askowner'}: {sw._user_display(info.get('user'))} - {info.get('original_name')}", flush=True)
            delivered+= 1 if ok else 0
        except Exception as e:
            print(f"  FAIL {info.get('original_name')}: {e}", flush=True)
        time.sleep(1)
    left=[k for k in sw._load_mappings() if re.match(r"^slack-\d+$", k)]
    if not left: break
    print(f"  {len(left)} still grading — wait 60s (round {rnd+1})", flush=True); time.sleep(60)
print(f"DONE: delivered {delivered}", flush=True)
