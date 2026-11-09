import base64, io, json, sys, os
from PIL import Image
S, OUT = sys.argv[1], sys.argv[2]
def thumb(t):
    if not os.path.exists(f"{S}/f1/f{int(t):03d}_{t:05.1f}s.jpg"): return None   # frames are local-only, not in git
    im = Image.open(f"{S}/f1/f{int(t):03d}_{t:05.1f}s.jpg"); im.thumbnail((200, 356))
    b = io.BytesIO(); im.save(b, "JPEG", quality=62); return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

# id, name, floor, seconds-in-video, frame, what's in it, rect (x0,y0,x1,y1)
def P(x0,y0,x1,y1): return (x0*10+40,y0*10+40,x1*10+40,y1*10+40)
R = [
 ("L",  "Lobby",              "carpet", "0–20s",  18, "Glass double doors with the big 500 number. Open carpeted area with two couches, one on the side wall and one on the back wall, around a centered coffee table, chairs along the entry wall, and a small reception desk with an iMac by Al's window, facing the door. Al's Office is on your right as you walk in, with a pass-through window into the lobby.", P(58,17,76,40)),
 ("O",  "Al's Office",             "carpet", "8–11s · 29–37s", 33, "It's the room behind the lobby window (same guy in the hoodie in both shots). Dark L-shaped desk with an iMac, set so the person at it faces the lobby window, and two guest chairs across the desk. Tall outside window with blinds behind.", P(58,0,76,17)),
 ("A",  "ATMO","carpet", "56–69s", 63, "ATMO room. Dry-erase boards on the outside wall and the side wall. Inside window looks into Office 2; outside windows with blinds; two ceiling lights.", P(24,0,42,17)),
 ("O2", "Office 2",           "vinyl",  "71–79s", 73, "Same setup as Al's Office: L-shaped desk, a chair behind it facing the hall and two chairs across. Plank floor. Window on its wall looks into ATMO.", P(42,0,58,17)),
 ("K",  "Break room",         "vinyl",  "38–55s", 41, "Wood cabinets and counter along both side walls, small sink, steel fridge, rolling whiteboard.", P(40,23,58,40)),
 ("MS", "Mop sink / storage", "carpet", "99–101s",100, "Storage room at the very end of the hall, against the end wall. Tablet charging station along the end wall, mop sink in the back corner. Window with blinds.", P(15,23,24,40)),
 ("M",  "Men's restroom",     "vinyl",  "89–95s", 92, "Single-person men's room on the far side of the fountains from the second office. Grab bars, wall sink and mirror.", P(34,23,40,40)),
 ("F",  "Water fountains",    "vinyl",  "not filmed", None, "Little inlet off the hall between the two restrooms, with the water fountains.", P(30,23,34,30)),
 ("W",  "Women's restroom",   "vinyl",  "115–120s", 118, "Single-person women's room right next to the second office. Sign on the door, grab bar, wall sink.", P(24,23,30,40)),
 ("E",  "Office 3",           "vinyl",  "102–107s",105,"Small interview room: desk with a chair behind it and two chairs across. Needs some work. Same size as the mop sink / storage room across the hall. Electrical panel and an empty TV bracket on the wall. Plank floor.", P(15,0,24,17)),
]
rooms = [dict(id=i,name=n,floor=f,t=t,img=thumb(fr) if fr is not None else None,note=no,r=r) for i,n,f,t,fr,no,r in R]

LBL2D = {"O": (668, 80), "O2": (540, 80), "L": (710, 302)}
SHORT = {"MS": '<tspan x="{cx}" dy="-8">Mop sink</tspan><tspan x="{cx}" dy="18">storage</tspan>', "W": "Women's", "M": "Men's", "F": "Fountains"}
def svg():
    o = []
    for rm in rooms:
        x0,y0,x1,y1 = rm["r"]; cx,cy=(x0+x1)/2,(y0+y1)/2
        if rm["id"]=="F":
            lab=f'<text x="{cx+4}" y="{cy}" transform="rotate(-90 {cx+4} {cy})" class="rn rn-s">Fountains</text>'
        else:
            cls=" rn-m" if rm["id"] in ("W","M") else ""
            lx,ly=LBL2D.get(rm["id"],(cx,cy+5)); lab=f'<text x="{lx}" y="{ly}" class="rn{cls}">{SHORT.get(rm["id"], rm["name"]).replace("{cx}", str(cx))}</text>'
        o.append(f'<g class="room" data-id="{rm["id"]}" tabindex="0" role="button" aria-label="{rm["name"]}">'
                 f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" class="fl-{rm["floor"]}"/>'
                 f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" class="hit"/>' + lab + '</g>')
    return "\n".join(o)

cards = "\n".join(
 f'''<article class="card" id="c-{r["id"]}" data-id="{r["id"]}">
  {f'<img src="{r["img"]}" alt="Video frame: {r["name"]}" width="100" height="178">' if r["img"] else '<div class="noimg">From you, not in the video</div>'}
  <div class="cb"><div class="ch"><h3>{r["name"]}</h3></div>
  <p>{r["note"]}</p><div class="meta"><span>{"Carpet" if r["floor"]=="carpet" else "Plank vinyl"}</span><span>{"Video " + r["t"] if r["img"] else "Added from your description"}</span></div></div>
</article>''' for r in rooms)

# windows seen from inside (outside wall = top edge + east end)
win = [(640,780),(480,600),(375,450)]
winsvg = '<rect x="500" y="130" width="90" height="24" rx="2" class="desk"/><rect x="566" y="80" width="24" height="50" rx="2" class="desk"/><rect x="532" y="104" width="16" height="16" rx="4" class="chair"/><rect x="516" y="165" width="16" height="16" rx="4" class="chair"/><rect x="548" y="165" width="16" height="16" rx="4" class="chair"/><rect x="288" y="43" width="80" height="7" fill="var(--sheet)" stroke="var(--ink)" stroke-width="1.5"/><rect x="283" y="70" width="7" height="110" fill="var(--sheet)" stroke="var(--ink)" stroke-width="1.5"/><text x="206" y="332" transform="rotate(-90 206 332)" class="rn rn-s" text-anchor="middle">Tablets</text><rect x="680" y="240" width="60" height="22" rx="2" class="desk"/><rect x="702" y="219" width="16" height="16" rx="4" class="chair"/><rect x="670" y="414" width="80" height="22" rx="6" class="chair"/><rect x="624" y="316" width="22" height="80" rx="6" class="chair"/><rect x="716" y="165" width="16" height="16" rx="4" class="chair"/><rect x="748" y="165" width="16" height="16" rx="4" class="chair"/><rect x="693" y="340" width="34" height="32" rx="3" class="desk"/><rect x="780" y="268" width="16" height="16" rx="4" class="chair"/><rect x="780" y="378" width="16" height="16" rx="4" class="chair"/><rect x="780" y="401" width="16" height="16" rx="4" class="chair"/><rect x="192" y="290" width="20" height="85" rx="2" class="desk"/><rect x="700" y="130" width="90" height="24" rx="2" class="desk"/><rect x="766" y="80" width="24" height="50" rx="2" class="desk"/><rect x="692" y="104" width="16" height="16" rx="4" class="chair"/><rect x="202.0" y="100" width="66.0" height="24" rx="2" class="desk"/><rect x="227.0" y="68.0" width="16" height="16" rx="4" class="chair"/><rect x="208.85" y="144.0" width="16" height="16" rx="4" class="chair"/><rect x="245.15" y="144.0" width="16" height="16" rx="4" class="chair"/><rect x="193" y="412" width="24" height="24" fill="var(--graphite)" opacity=".5"/><rect x="340" y="340" width="40" height="100" fill="var(--line)"/><rect x="444" y="290" width="22" height="146" fill="var(--graphite)" opacity=".35"/><rect x="594" y="290" width="22" height="146" fill="var(--graphite)" opacity=".35"/>' + "".join(f'<line x1="{a}" y1="40" x2="{b}" y2="40" class="win"/>' for a,b in win) + \
         '<line x1="670" y1="210" x2="770" y2="210" class="win"/><line x1="460" y1="80" x2="460" y2="170" class="win"/><line x1="200" y1="440" x2="270" y2="440" class="win"/>'
# doors: (x,y,orientation) small gaps on walls
doors = [(640,210,"h"),(540,210,"h"),(340,210,"h"),(235,270,"h"),(530,270,"h"),(340,310,"v"),(380,310,"v"),(210,210,"h")]
dsvg = "".join(f'<rect x="{x-14}" y="{y-4}" width="28" height="8" class="door"/>' if o=="h" else f'<rect x="{x-4}" y="{y-14}" width="8" height="28" class="door"/>' for x,y,o in doors)

html = open(f"{S}/template.html").read()
html = html.replace("@@ROOMS@@", svg()).replace("@@CARDS@@", cards).replace("@@WIN@@", winsvg).replace("@@DOORS@@", dsvg).replace("@@ISO@@", open(f"{S}/iso500.svg").read())
open(OUT,"w").write(html); print(len(html)//1024, "KB")
