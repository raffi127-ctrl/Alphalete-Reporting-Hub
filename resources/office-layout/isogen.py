#!/usr/bin/env python3
"""Isometric 'dollhouse' render of the Alphalete new office floor plan -> SVG."""
import math

COS = math.cos(math.radians(30))
SIN = math.sin(math.radians(30))
SCALE = 9.0
WALL_H = 8.5
FLR_Z = 1.6
W, D = 104, 64

# ---- compute canvas offset up front ---------------------------------------
def _iso_raw(x, y, z):
    return ((x - y) * COS * SCALE, (x + y) * SIN * SCALE - z * SCALE)

_corners = [_iso_raw(x, y, z) for x in (-1, W + 1) for y in (-1, D + 1)
            for z in (0, FLR_Z + WALL_H)]
_xs = [p[0] for p in _corners]; _ys = [p[1] for p in _corners]
PAD = 70
OX = -min(_xs) + PAD
OY = -min(_ys) + PAD
Wpx = (max(_xs) - min(_xs)) + 2 * PAD
Hpx = (max(_ys) - min(_ys)) + 2 * PAD

def iso(x, y, z):
    px, py = _iso_raw(x, y, z)
    return (px + OX, py + OY)

def pts(coords):
    return " ".join(f"{px:.1f},{py:.1f}" for px, py in coords)

def shade(hexc, f):
    hexc = hexc.lstrip("#")
    r, g, b = int(hexc[0:2], 16), int(hexc[2:4], 16), int(hexc[4:6], 16)
    r = max(0, min(255, int(r * f))); g = max(0, min(255, int(g * f))); b = max(0, min(255, int(b * f)))
    return f"#{r:02x}{g:02x}{b:02x}"

_svg = []
def emit(depth, z, s):
    _svg.append((depth, z, s))

def floor(x0, y0, x1, y1, ztop, color, stroke="#ffffff", sw=1.2, op=1.0):
    # floors are the ground plane — always painted before any vertical element
    top = [iso(x0, y0, ztop), iso(x1, y0, ztop), iso(x1, y1, ztop), iso(x0, y1, ztop)]
    emit(-2e6 + (x0 + y0 + x1 + y1) / 2, ztop,
         f'<polygon points="{pts(top)}" fill="{color}" stroke="{stroke}" '
         f'stroke-width="{sw}" stroke-linejoin="round" opacity="{op}"/>')

def box(x0, y0, x1, y1, z0, z1, color, edge=None, op=1.0, db=0.0):
    sf = shade(color, 0.80); ef = shade(color, 0.62); tf = color
    st = edge or shade(color, 0.5)
    depth = db + (x0 + y0 + x1 + y1) / 2
    ef_pts = [iso(x1, y0, z0), iso(x1, y1, z0), iso(x1, y1, z1), iso(x1, y0, z1)]
    emit(depth, z1, f'<polygon points="{pts(ef_pts)}" fill="{ef}" stroke="{st}" stroke-width="0.5" opacity="{op}"/>')
    sf_pts = [iso(x0, y1, z0), iso(x1, y1, z0), iso(x1, y1, z1), iso(x0, y1, z1)]
    emit(depth, z1, f'<polygon points="{pts(sf_pts)}" fill="{sf}" stroke="{st}" stroke-width="0.5" opacity="{op}"/>')
    tf_pts = [iso(x0, y0, z1), iso(x1, y0, z1), iso(x1, y1, z1), iso(x0, y1, z1)]
    emit(depth + 0.01, z1 + 0.001, f'<polygon points="{pts(tf_pts)}" fill="{tf}" stroke="{st}" stroke-width="0.5" opacity="{op}"/>')

def label(x, y, z, text, size=6.0, color="#2a2f3a", weight="700", anchor="middle", op=1.0):
    px, py = iso(x, y, z)
    emit(9e9, 9e9, f'<text x="{px:.1f}" y="{py:.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" '
         f'font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}" '
         f'opacity="{op}" style="letter-spacing:0.2px">{text}</text>')

# ---- palette ---------------------------------------------------------------
C_SLAB="#c7ccd6"; C_OPEN="#ece5d4"; C_OFFICE="#dbe4f1"; C_CONF="#d3e7dd"
C_SERV="#dfe1e6"; C_RECEP="#f3dfe0"; C_DESK="#b9805a"; C_DESK2="#c8bfb0"
C_CHAIR="#3a4150"; C_WALL="#e9ebef"; C_ACCENT="#e8482b"

# ---- base slab (drawn under everything) ------------------------------------
box(0, 0, W, D, 0, FLR_Z, C_SLAB, db=-3e6)

def room(x0, y0, x1, y1, color, name, sub=None, combined=False, lsize=6.0):
    floor(x0, y0, x1, y1, FLR_Z, color)
    if combined:
        # accent dashed outline marking a merged (wall-removed) office
        o = [iso(x0+0.3,y0+0.3,FLR_Z+0.03), iso(x1-0.3,y0+0.3,FLR_Z+0.03),
             iso(x1-0.3,y1-0.3,FLR_Z+0.03), iso(x0+0.3,y1-0.3,FLR_Z+0.03)]
        emit((x0+y0+x1+y1)/2, FLR_Z+0.03,
             f'<polygon points="{pts(o)}" fill="none" stroke="{C_ACCENT}" '
             f'stroke-width="1.4" stroke-dasharray="4 3" stroke-linejoin="round"/>')
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if name:
        label(cx, cy - (1.2 if sub else 0), FLR_Z + 0.05, name, size=lsize)
        if sub:
            scol = C_ACCENT if combined else "#5b6270"
            label(cx, cy + 1.6, FLR_Z + 0.05, sub, size=lsize - 1.4, weight="600", color=scol)

# ---- low interior partition walls (dollhouse height: see over them) --------
def wall(x0,y0,x1,y1,h=3.4,color=C_WALL,t=0.45):
    if abs(x1-x0) >= abs(y1-y0):
        box(min(x0,x1),y0-t/2,max(x0,x1),y0+t/2,FLR_Z,FLR_Z+h,color)
    else:
        box(x0-t/2,min(y0,y1),x0+t/2,max(y0,y1),FLR_Z,FLR_Z+h,color)
def rwalls(x0,y0,x1,y1,h=3.4):
    wall(x0,y0,x1,y0,h); wall(x0,y1,x1,y1,h); wall(x0,y0,x0,y1,h); wall(x1,y0,x1,y1,h)

# ================= FLOORS + LABELS (match the key map exactly) ==============
# NORTH BAND: stor · break room · hall/IT · MEN / vestibule / WOMEN · Raf · conference
room(0,0,6,18,C_SERV,"STOR","5'×17'",lsize=4.2)
room(6,0,24,18,C_SERV,"BREAK ROOM","15'6 × 20'")
room(24,0,27,18,"#eef1f4",None)                     # narrow hall
room(24,0,27,5,C_SERV,"IT",lsize=3.6)
room(27,0,50,7,C_SERV,"MEN","119",lsize=5.0)
room(27,7,33,11,"#e6eef5",None)                     # fountain vestibule
room(33,7,50,11,C_SERV,None)                        # plumbing-wall zone
room(27,11,50,18,C_SERV,"WOMEN","121",lsize=5.0)
room(50,0,70,18,C_OFFICE,"RAF'S OFFICE","20' × 20'")
room(70,0,104,18,C_CONF,"LARGE CONFERENCE","20' × 49'")
# WEST COLUMN (x0-11): training (combined) · office · Maud's tall corner
room(0,18,11,37,C_OFFICE,"TRAINING","combined · 10'6 × 20'",combined=True,lsize=4.6)
room(0,37,11,47,C_OFFICE,"OFFICE","10'6 × 10'5",lsize=4.6)
room(0,47,11,64,C_OFFICE,"MAUD'S","10'5 × 17'5",lsize=4.6)
# EAST COLUMN (x91-104): Twaddle's · Claude/Megan's
room(91,18,104,29,C_OFFICE,"TWADDLE'S","10'8 × 10'8",lsize=4.2)
room(91,29,104,40,C_OFFICE,"CLAUDE / MEGAN'S","10'8 × 10'8",lsize=3.8)
# RECEPTION / LOBBY (bottom-right)
room(82,40,104,64,C_RECEP,None)
# SOUTH OFFICES (bottom row) start at the west-column edge
sx0,sx1=11,82; ow=(sx1-sx0)/8
south_segs=[(0,1,"OFFICE","12×10'6",0),(1,2,"OFFICE","12×10'6",0),(2,3,"OFFICE","12×10'",0),
            (3,4,"JD'S","12×13'6",0),(4,6,"TRAINING","24' × 9'",1),(6,8,"TRAINING","24' × 10'6",1)]
for a,b,nm,lab,comb in south_segs:
    room(sx0+a*ow,52,sx0+b*ow,64,C_OFFICE,nm,lab,combined=bool(comb),lsize=4.2)
# OPEN OFFICE (kept empty) + walkway west of the east offices
room(11,18,82,52,C_OPEN,None)
room(82,18,91,40,C_OPEN,None)
label(47.5,23.5,FLR_Z+0.05,"OPEN OFFICE",size=7.4,color="#8a7c56")
label(47.5,26.5,FLR_Z+0.05,"34'9 × 96'  ·  open floor",size=5.0,weight="600",color="#a2946f")

# ---- interior partition walls (all enclosed rooms; open office stays open) --
for _r in [(0,0,6,18),(6,0,24,18),(24,0,27,18),(27,0,50,7),(27,7,33,11),(27,11,50,18),
           (50,0,70,18),(70,0,104,18),(0,18,11,37),(0,37,11,47),(0,47,11,64),
           (91,18,104,29),(91,29,104,40),(82,40,104,64)]:
    rwalls(*_r)
for a,b,nm,lab,comb in south_segs:
    rwalls(sx0+a*ow,52,sx0+b*ow,64)

# ---- structural pillars (immovable columns) down the open-office centerline -
for _px in (23,47,68):
    box(_px-0.8,34.2,_px+0.8,35.8,FLR_Z,FLR_Z+9.0,"#aab0b9")
label(47.5,41.5,FLR_Z+0.05,"▲ 3 structural pillars — fixed",size=4.4,weight="700",color="#8a909b")

# ================= FIXED BUILT-INS ==========================================
# break-room island + built-in sink counter (east wall)
box(18,4,20,12.5,FLR_Z,FLR_Z+3.0,"#b7bcc4"); label(19,8,FLR_Z+3.2,"ISLAND",size=3.2,color="#5b6270",weight="700")
box(22,2,24,16,FLR_Z,FLR_Z+3.2,"#c4cdd8")
# restroom: water fountains on vestibule east wall + center plumbing chase (wet wall)
box(30.7,7.7,32.5,10.3,FLR_Z,FLR_Z+2.6,"#cfe0ea")
box(33,8.3,50,9.7,FLR_Z,FLR_Z+3.6,"#6b7280")
# reception: enclosed back room + built-in desk (wall to wall) + glass upper
wall(82,44.4,104,44.4,3.4)                                  # enclosed-room south wall
label(93,42.4,FLR_Z+0.05,"ENCLOSED ROOM",size=3.6,color="#8a6a6f",weight="800")
box(82,44.9,104,46.8,FLR_Z,FLR_Z+3.0,"#a98a63"); label(93,46.0,FLR_Z+3.2,"BUILT-IN DESK",size=3.8,color="#7a5f3c",weight="700")
box(82,44.4,104,44.75,FLR_Z+3.0,FLR_Z+7.0,"#bfe0ea",op=0.32)
label(94,55,FLR_Z+0.05,"LOBBY",size=6.2,color="#7a5f60",weight="800")
# CONFERENCE — long 18-person boardroom table (8 per side + 1 at each end)
box(74,7,100,11,FLR_Z,FLR_Z+2.5,"#9c7a52")                  # table top
label(87,9,FLR_Z+2.7,"SEATS 18",size=3.4,color="#ffffff",weight="800")
# Chair backs run taller than the 2.5' table top so the far row stays visible. The table
# is one long box sorting by its centroid, so pin each row's depth either side of it.
_TBL=(74+7+100+11)/2
for _i in range(8):
    _cx = 75 + _i*(99-75)/7
    box(_cx-0.55,5.4,_cx+0.55,6.6,FLR_Z,FLR_Z+3.4,C_CHAIR,db=_TBL-0.5-(_cx+6))   # far row: behind
    box(_cx-0.55,11.4,_cx+0.55,12.6,FLR_Z,FLR_Z+3.4,C_CHAIR,db=_TBL+0.5-(_cx+12))# near row: in front
box(72.0,8.4,73.1,9.6,FLR_Z,FLR_Z+3.4,C_CHAIR,db=_TBL-0.5-81.55)                 # far-end chair
box(100.5,8.4,101.6,9.6,FLR_Z,FLR_Z+3.4,C_CHAIR,db=_TBL+0.5-110.05)              # near-end chair
# conference built-in counter along the right (east) wall
box(102.1,2.5,103.6,15.5,FLR_Z,FLR_Z+3.0,"#b7bcc4")
label(102.9,9.0,FLR_Z+3.2,"COUNTER",size=3.0,color="#5b6270",weight="700")
# interior glass window in the conference's west wall — looks into Raf's office
box(69.7,3.5,70.3,14.5,FLR_Z+1.6,FLR_Z+3.4,"#bfe0ea",op=0.55,db=0.3)

# ---- perimeter walls -------------------------------------------------------
box(0,-1.0,W,0,FLR_Z,FLR_Z+WALL_H,C_WALL)          # north (tall, solid demising)
box(-1.0,0,0,D,FLR_Z,FLR_Z+WALL_H,C_WALL)          # west (tall, solid demising)
# south + east = exterior GLASS / windows (low glass curb so we can see in)
box(0,D,W,D+0.5,FLR_Z,FLR_Z+1.3,"#bfe0ea",op=0.55)
box(W,0,W+0.5,D,FLR_Z,FLR_Z+1.3,"#bfe0ea",op=0.55)
for _gx in range(4,int(W),8):
    box(_gx,D+0.15,_gx+0.3,D+0.45,FLR_Z,FLR_Z+2.6,"#7fb8d4",op=0.6)
for _gy in range(4,int(D),8):
    box(W+0.15,_gy,W+0.45,_gy+0.3,FLR_Z,FLR_Z+2.6,"#7fb8d4",op=0.6)

# ---- painter sort + write --------------------------------------------------
_svg.sort(key=lambda t: (t[0], t[1]))
body = "\n".join(s for _, _, s in _svg)

# ---- title + legend (screen space) ----------------------------------------
def sw_rect(x,y,c): return f'<rect x="{x}" y="{y}" width="11" height="11" rx="2" fill="{c}"/>'
legend_items=[("Private office",C_OFFICE),("Open office",C_OPEN),("Conference",C_CONF),
              ("Reception",C_RECEP),("Service / BOH",C_SERV),("Exterior glass","#bfe0ea")]
lg=[]
ly=Hpx-24
lx=28
for name,c in legend_items:
    lg.append(sw_rect(lx,ly-9,c))
    lg.append(f'<text x="{lx+16}" y="{ly}" font-family="Inter,Segoe UI,Arial,sans-serif" '
              f'font-size="11" fill="#4a505c">{name}</text>')
    lx+=18+ max(70, len(name)*6.4)
lg.append(f'<rect x="{lx}" y="{ly-9}" width="11" height="11" rx="2" fill="none" '
          f'stroke="{C_ACCENT}" stroke-width="1.4" stroke-dasharray="3 2"/>')
lg.append(f'<text x="{lx+16}" y="{ly}" font-family="Inter,Segoe UI,Arial,sans-serif" '
          f'font-size="11" fill="{C_ACCENT}" font-weight="600">Combined (wall removed)</text>')
legend="\n".join(lg)

title=(f'<text x="28" y="40" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="24" '
       f'font-weight="800" fill="#2a2f3a" letter-spacing="0.5">ALPHALETE</text>'
       f'<text x="28" y="60" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12.5" '
       f'font-weight="600" fill="#8a909c" letter-spacing="2.5">NEW OFFICE — LAYOUT CONCEPT</text>')

svg_doc = f'''<svg viewBox="0 0 {Wpx:.0f} {Hpx:.0f}" xmlns="http://www.w3.org/2000/svg" role="img">
<title>Alphalete new office — isometric layout</title>
<desc>Isometric cutaway of the new Alphalete office floor plan with furnished rooms, merged offices, and reception built-in desk.</desc>
<rect x="0" y="0" width="{Wpx:.0f}" height="{Hpx:.0f}" fill="#f5f6f8"/>
{body}
{title}
{legend}
</svg>'''

open("/private/tmp/claude-501/-Users-megan-1st-Claude-Folder/de840332-a406-47e2-ab31-cb468bebf93c/scratchpad/office.svg","w").write(svg_doc)
print("size px", int(Wpx), int(Hpx), "| polys", len(_svg))
