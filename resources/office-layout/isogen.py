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
room(0,18,11,37,C_OFFICE,"TRAINING","10'6 × 20'",lsize=4.6)
room(0,37,11,47,C_OFFICE,"OFFICE","10'6 × 10'5",lsize=4.6)
room(0,47,11,64,C_OFFICE,"MAUD'S","10'5 × 17'5",lsize=4.6)
# EAST COLUMN (x91-104): Twaddle's · Claude/Megan's
room(91,18,104,29,C_OFFICE,"TWADDLE'S","10'8 × 10'8",lsize=4.2)
room(91,29,104,40,C_OFFICE,"CLAUDE / MEGAN'S","10'8 × 10'8",lsize=3.8)
# RECEPTION / LOBBY (bottom-right)
room(82,40,104,64,C_RECEP,None)
# SOUTH OFFICES (bottom row) start at the west-column edge
sx0,sx1=11,82; ow=(sx1-sx0)/8
south_segs=[(0,1,"OFFICE","12×10'6",0),(1,2,"OFFICE","12×10'6",0),(2,3,"BAS","12×10'",0),
            (3,4,"JD'S","12×13'6",0),(4,6,"TRAINING","24' × 9'",0),(6,8,"TRAINING","24' × 10'6",0)]
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
# furniture helpers (defined before first use — conference uses schair)
def sdesk(x0,y0,x1,y1,col="#8a5a3c"): box(x0,y0,x1,y1,FLR_Z,FLR_Z+2.5,col)
def schair(cx,cy,col,s=1.3,h=1.9,db=0.0,face='S'):
    # low seat + a clearly taller back on the side away from `face`, so it reads as a chair
    r=s/2; bk=0.26
    box(cx-r,cy-r,cx+r,cy+r,FLR_Z,FLR_Z+0.75,col,db=db)                 # seat (low)
    if   face=='S': d=(cx-r,cy-r,cx+r,cy-r+bk)          # faces camera, back to the north
    elif face=='N': d=(cx-r,cy+r-bk,cx+r,cy+r)          # back to the south
    elif face=='W': d=(cx+r-bk,cy-r,cx+r,cy+r)          # back to the east
    else:           d=(cx-r,cy-r,cx-r+bk,cy+r)          # face E, back to the west
    box(d[0],d[1],d[2],d[3],FLR_Z,FLR_Z+h,shade(col,1.14),db=db+0.02)   # back, drawn just in front
def scred(x0,y0,x1,y1,col="#6f6a63"): box(x0,y0,x1,y1,FLR_Z,FLR_Z+2.4,col)
def tv(pos,along,wall,w=4.2,z0=1.45,z1=3.32,col="#20252b",db=0.0):
    # wall-mounted screen: `pos` is the wall coordinate (y for N/S, x for E/W), `along` the
    # centre along the wall. A thin dark panel + light bezel, on the wall's inner face.
    t=0.16
    if   wall=='N': r=(along-w/2,pos+0.26,along+w/2,pos+0.26+t)
    elif wall=='S': r=(along-w/2,pos-0.26-t,along+w/2,pos-0.26)
    elif wall=='W': r=(pos+0.26,along-w/2,pos+0.26+t,along+w/2)
    else:           r=(pos-0.26-t,along-w/2,pos-0.26,along+w/2)   # E
    _wb=db+(2.2 if wall in ('N','W') else 0.0)                            # far walls: draw in front of the wall
    box(r[0],r[1],r[2],r[3],FLR_Z+z0-0.12,FLR_Z+z1+0.12,"#454b54",db=_wb)  # bezel
    box(r[0],r[1],r[2],r[3],FLR_Z+z0,FLR_Z+z1,col,db=_wb+0.01)             # screen

# CONFERENCE — long 14-person boardroom table (6 per side + 1 at each end)
_CCH="#9e3b32"                                              # red chairs
box(74,6.6,100,11.4,FLR_Z,FLR_Z+2.5,"#8a5a3c")              # table top
label(87,9,FLR_Z+2.7,"SEATS 14",size=3.4,color="#ffffff",weight="800")
# Chair backs run taller than the 2.5' table top so the far row stays visible. The table
# is one long box sorting by its centroid, so pin each row's depth either side of it.
_TBL=(74+6.6+100+11.4)/2
for _i in range(6):
    _cx = 76 + _i*(98-76)/5
    schair(_cx,5.6,_CCH,s=1.15,h=2.9,face='S',db=_TBL-0.5-(_cx+5.6))    # far row faces the table
    schair(_cx,12.4,_CCH,s=1.15,h=2.9,face='N',db=_TBL+0.5-(_cx+12.4))  # near row faces the table
schair(72.55,9.0,_CCH,s=1.15,h=2.9,face='E',db=_TBL-0.5-81.55)         # far-end chair
schair(101.05,9.0,_CCH,s=1.15,h=2.9,face='W',db=_TBL+0.5-110.05)       # near-end chair
# conference built-in counter along the right (east) wall
box(102.1,2.5,103.6,15.5,FLR_Z,FLR_Z+3.0,"#b7bcc4")
label(102.9,9.0,FLR_Z+3.2,"COUNTER",size=3.0,color="#5b6270",weight="700")
# interior glass window in the conference's west wall — looks into Raf's office
box(69.7,3.5,70.3,14.5,FLR_Z+1.6,FLR_Z+3.4,"#bfe0ea",op=0.55,db=0.3)

# ================= FURNISHED ROOMS =========================================
# Simplified furniture for the rooms built out in the studio. The studio draws each room
# in its own local frame (wall 1 = west, 2 = north ...) which is NOT the building's frame,
# so this is a re-draw in plan coordinates, not a port — orientation comes from each room's
# real neighbours. Floor pieces only: the dollhouse walls are 3.4' tall, so wall-mounted
# screens, art and posters have nothing to hang on at this scale.

# --- 4 · RAF'S (50,0,70,18): backs the north wall, looks out the south entry ---
_RD="#9e3b32"; _RW="#5c4033"
_CO="#5a5f68"                                               # couch on the west wall, facing east
box(50.20,2.40,53.10,7.70,FLR_Z,FLR_Z+0.50,shade(_CO,0.80))      # base plinth (ties it together)
box(50.20,2.40,51.20,7.70,FLR_Z+0.50,FLR_Z+2.45,_CO)            # back panel
box(50.20,2.40,53.10,3.05,FLR_Z+0.50,FLR_Z+1.65,shade(_CO,0.96)) # arm (north)
box(50.20,7.05,53.10,7.70,FLR_Z+0.50,FLR_Z+1.65,shade(_CO,0.96)) # arm (south)
box(51.20,3.05,53.10,7.05,FLR_Z+0.50,FLR_Z+1.10,shade(_CO,1.22)) # seat cushions
scred(50.2,0.2,51.9,1.8,_RD)                                # mini fridge, NW corner
box(66.6,0.2,68.9,1.2,FLR_Z,FLR_Z+5.0,"#9aa2ac")            # corner bookcase, NE
box(68.9,0.2,69.8,1.7,FLR_Z,FLR_Z+5.0,"#9aa2ac")
box(64.6,1.2,66.4,3.4,FLR_Z,FLR_Z+0.4,"#3a4150")            # walking pad
sdesk(57.2,4.7,64.2,6.9,_RW); sdesk(62.0,2.5,64.2,4.7,_RW)  # L-desk + return
schair(60.2,3.5,_RD,s=1.35,h=2.2)                          # Raf (exec chair)
schair(58.8,8.3,_RD,s=1.15,h=1.6,face='N'); schair(62.2,8.3,_RD,s=1.15,h=1.6,face='N')  # guests, facing the desk
_ocx,_ocy,_OT=56.2,13.6,"#7a5333"                           # oval table, 6 seats
_ov=[(_ocx+2.6*math.cos(2*math.pi*i/40.0), _ocy+1.5*math.sin(2*math.pi*i/40.0)) for i in range(40)]
_od=_ocx+_ocy
for _zz,_cc,_dd in ((2.2,shade(_OT,0.62),_od+0.30),(2.4,_OT,_od+0.32)):
    emit(_dd,_zz,'<polygon points="%s" fill="%s" stroke="%s" stroke-width="0.5"/>'
         % (pts([iso(_x,_y,FLR_Z+_zz) for _x,_y in _ov]), _cc, shade(_OT,0.5)))
for _cx,_cy,_cf in ((52.4,13.6,'E'),(60.0,13.6,'W'),(54.8,11.3,'S'),
                   (57.6,11.3,'S'),(54.8,15.9,'N'),(57.6,15.9,'N')):
    _bh=(_cx+_cy)<_od                                        # north/far side sits behind the table
    schair(_cx,_cy,_RD,s=1.0,h=1.5,face=_cf,db=(_od+0.32+(-0.6 if _bh else 0.6))-(_cx+_cy))
# wall art on the north wall behind Raf (canvases), biased to draw in front of the wall
for _ax,_ac in ((52.7,_RD),(54.5,"#7a5333"),(56.3,"#8a9099")):
    box(_ax,0.10,_ax+1.4,0.24,FLR_Z+1.9,FLR_Z+3.25,"#3a3a3a",db=3.0)         # frame
    box(_ax+0.09,0.12,_ax+1.31,0.28,FLR_Z+2.0,FLR_Z+3.15,_ac,db=3.02)        # canvas

# --- 3 · MAUD'S (0,47,11,64): exterior glass south, entry east, walls 1/2 solid.
# Her studio frame IS the building's frame here, so this is her actual layout mapped
# across (studio 10.42 x 17.42 -> plan 11 x 17), not an approximation.
def _mx(x): return x*(11.0/10.42)
def _my(y): return 47.0+y*(17.0/17.42)
_MG="#9aa0a8"; _MD="#4a5260"; _MN="#2f4260"; _MG2="#3d5175"
box(_mx(0.18),_my(0.30),_mx(1.05),_my(3.60),FLR_Z,FLR_Z+3.1,_MG)      # corner shelf, walls 1/2 corner
sdesk(_mx(4.50),_my(4.00),_mx(6.70),_my(9.20),_MD)                    # L-desk main
sdesk(_mx(2.50),_my(4.00),_mx(4.50),_my(6.00),_MD)                    # return
schair(_mx(3.50),_my(7.20),_MN)                                       # Maud, facing wall 3 (east)
schair(_mx(8.10),_my(5.60),_MG2); schair(_mx(8.10),_my(8.20),_MG2)    # two across the desk
# baby play pen — low open rail enclosure (soft mat + a toy), not a solid box
_pp0x,_pp0y=_mx(0.40),_my(11.20); _pp1x,_pp1y=_mx(4.40),_my(14.80); _PP="#f0e4e6"
box(_pp0x,_pp0y,_pp1x,_pp1y,FLR_Z,FLR_Z+0.12,shade(_PP,1.05))                   # soft mat
for _rr in ((_pp0x,_pp0y,_pp1x,_pp0y+0.20),(_pp0x,_pp1y-0.20,_pp1x,_pp1y),
            (_pp0x,_pp0y,_pp0x+0.20,_pp1y),(_pp1x-0.20,_pp0y,_pp1x,_pp1y)):
    box(_rr[0],_rr[1],_rr[2],_rr[3],FLR_Z,FLR_Z+1.10,_PP)                        # rails
box(_pp0x+0.8,_pp0y+0.9,_pp0x+1.5,_pp0y+1.6,FLR_Z+0.12,FLR_Z+0.95,"#f2c14e")     # a toy peeking over
schair(_mx(6.60),_my(13.00),"#8a6240",s=1.6,h=2.6,face='N')          # rocking chair, faces the room

# --- 5 · TWADDLE'S and 6 · MEGAN'S: the two east-column rooms. Both studio frames are
# rotated 90 deg from the building's — studio north (windows) is the plan's east wall, and
# studio east (Twaddle's Megan-side / Megan's reception side) is the plan's south. So map
# rather than eyeball: studio (sx,sy) -> plan (X1 - sy*13/10.67, Y0 + sx*11/10.67).
_EK,_EJ=13.0/10.67, 11.0/10.67
def _epx(sy): return 104.0-sy*_EK
def _epy(sx,Y0): return Y0+sx*_EJ
def ebox(sx0,sy0,sx1,sy1,Y0,z1,col,z0=0.0):
    box(_epx(sy1),_epy(sx0,Y0),_epx(sy0),_epy(sx1,Y0),FLR_Z+z0,FLR_Z+z1,col)
def echair(sx,sy,Y0,col,s=1.3,h=1.9):
    schair(_epx(sy),_epy(sx,Y0),col,s=s,h=h)

# 5 · TWADDLE'S (91,18,104,29): TV wall = plan north (conference side), windows = plan east
ebox(0.18,1.50,1.90,3.10,18,5.0,"#7d8894")                  # tablet cabinet by the TV wall
ebox(5.0,3.0,7.2,8.2,18,2.5,"#9a7048")                      # L-desk main
ebox(7.2,3.0,9.4,4.8,18,2.5,"#9a7048")                      # return
echair(8.2,5.9,18,"#6b4c35")                                # Twaddle, facing the TV wall
echair(3.5,4.8,18,"#9aa89a"); echair(3.5,7.0,18,"#9aa89a")  # two across the desk

# 6 · MEGAN'S (91,29,104,40): screen wall = plan north, windows = plan east, reception south
box(_epx(8.85),_epy(1.85,29),_epx(1.85),_epy(8.85,29),FLR_Z,FLR_Z+0.06,"#e8d5d8")   # floral rug
ebox(3.2,3.4,5.3,7.2,29,3.5,"#c8bfb0",z0=3.2)               # standing desk, top at 3.2'
ebox(3.5,3.75,5.0,4.05,29,3.2,"#6b7280"); ebox(3.5,6.55,5.0,6.85,29,3.2,"#6b7280")  # T-legs
ebox(5.4,4.2,7.4,6.6,29,0.4,"#3a4150")                      # walking pad
echair(2.9,9.05,29,"#9fae9f",s=1.8,h=3.3)                   # sage accent chair, room corner

# --- 10 · JD'S + 9 · BAS'S: south-row private offices. The studio draws each in a local
# frame (wall 1 = west) that is a TRANSPOSE of the building here — studio x (windows -> glass
# front) is the plan's south -> north depth; studio y (TV wall -> far wall) is the plan's
# west -> east width. So map the real studio coordinates across instead of eyeballing them:
# the owner then backs a party wall and faces the TV, not the windows / the open office.
def _south_office(X0,X1,sd,cred,desk,chair,g0,g1,book,bricks=()):
    def MX(sy): return X0+sy*(X1-X0)/sd
    def MY(sx): return 64.0-sx
    def RC(sx0,sy0,sx1,sy1):
        xs=sorted((MX(sy0),MX(sy1))); ys=sorted((MY(sx0),MY(sx1)))
        return xs[0],ys[0],xs[1],ys[1]
    scred(*RC(0.18,3.50,2.00,9.50),cred)                      # credenza under the windows (south)
    sdesk(*RC(3.60,5.40,9.60,7.60),desk); sdesk(*RC(7.60,7.60,9.60,9.60),desk)  # L-desk
    schair(MX(8.70),MY(6.40),chair)                           # owner, backs a party wall, faces the TV
    schair(MX(3.90),MY(5.00),g0); schair(MX(3.90),MY(7.80),g1)   # two guests across the desk
    box(*RC(1.30,0.18,3.90,1.18),FLR_Z,FLR_Z+5.0,book)        # bookcase by the TV wall
    for sx0,sy0,sx1,sy1,bc,bn in bricks:                      # Lego builds on the credenza (Bas)
        bx0,by0,bx1,by1=RC(sx0,sy0,sx1,sy1)
        box(bx0,by0,bx1,by1,FLR_Z+2.5,FLR_Z+3.2,bc)
        _cym=(by0+by1)/2
        for _st in range(bn):
            _sxm=bx0+(bx1-bx0)*(_st+0.5)/bn
            box(_sxm-0.10,_cym-0.10,_sxm+0.10,_cym+0.10,FLR_Z+3.2,FLR_Z+3.36,shade(bc,1.12))
_south_office(37.625,46.5,13.5,"#8a9099","#6f6a63","#2b3a52","#2b3a52","#2b3a52","#7d8894")   # 10 · JD (navy/grey)
_south_office(28.75,37.625,10.0,"#6f685c","#4e5766","#d21f26","#0a6cff","#00a94f","#d21f26",  # 9 · Bas (bright/Lego)
    bricks=((0.42,4.05,1.62,5.75,"#d21f26",2),(0.55,6.05,1.45,7.05,"#f6c018",2),(0.52,7.55,1.55,8.75,"#0a6cff",2)))

# --- 7 · 8 · 2 · INTERVIEW OFFICES: straight desk + iMac + 2 guest chairs + open shelf, no
# credenza; themed. 7/8 are south-row (same transpose as JD/Bas); 2 is west-column (identity).
def _south_interview(X0,X1,sd,desk,owner,g0,g1,shelf):
    def MX(sy): return X0+sy*(X1-X0)/sd
    def MY(sx): return 64.0-sx
    def RC(sx0,sy0,sx1,sy1):
        xs=sorted((MX(sy0),MX(sy1))); ys=sorted((MY(sx0),MY(sx1)))
        return xs[0],ys[0],xs[1],ys[1]
    sdesk(*RC(3.60,5.40,9.60,7.60),desk)                     # straight desk
    schair(MX(8.70),MY(6.40),owner)                          # owner, backs a party wall, faces the TV
    schair(MX(3.90),MY(5.00),g0); schair(MX(3.90),MY(7.80),g1)   # two guests across the desk
    box(*RC(1.30,0.18,3.90,1.18),FLR_Z,FLR_Z+5.0,shelf)      # open shelf by the TV wall
_south_interview(11.0,19.875,10.5,"#5f5560","#7b4f6a","#9a929a","#9a929a","#6a5a66")     # 7 · plum
_south_interview(19.875,28.75,10.5,"#5b564d","#c19a3e","#9a948a","#9a948a","#6e5f3e")    # 8 · gold

# 2 · WEST OFFICE (0,37,11,47): interior interview office. Maps identity (glass entry faces
# the open office to the east), so the owner faces the TV on the NORTH wall.
sdesk(2.2,41.6,8.6,43.4,"#6a5847")                          # straight desk (E-W)
schair(5.4,45.0,"#a97c53")                                 # owner, backs the south wall, faces north
schair(3.8,40.2,"#9c948a"); schair(6.6,40.2,"#9c948a")     # two guests
box(1.0,37.3,2.5,38.6,FLR_Z,FLR_Z+5.0,"#5c4a38")           # open shelf on the north (TV) wall

# ---- wall-mounted TV / screens (where each room's screen sits) ----
tv(37.0,5.5,'N')                      # 2 · office 2 (north wall)
tv(37.625,58.0,'W')                   # 10 · JD (west wall)
tv(28.75,58.0,'W')                    # 9 · Bas (west wall)
tv(11.0,58.0,'W')                     # 7 · interview (west wall)
tv(19.875,58.0,'W')                   # 8 · interview (west wall)
tv(47.0,5.7,'N')                      # 3 · Maud (TV on wall 2 -> north wall)
tv(18.0,97.0,'N',db=2.6)              # 5 · Twaddle (north wall; extra bias to clear the desk)
tv(50.0,11.5,'W')                      # 4 · Raf (TV on the west wall toward the sitting table)
for _mgx in (95.7,98.3):              # 6 · Megan — a 2x2 array of FOUR distinct screens (north wall y29)
    for _mgz in (1.55,2.75):
        box(_mgx-0.55,29.26,_mgx+0.55,29.42,FLR_Z+_mgz-0.36,FLR_Z+_mgz+0.36,"#454b54",db=4.7)   # bezel
        box(_mgx-0.48,29.28,_mgx+0.48,29.44,FLR_Z+_mgz-0.28,FLR_Z+_mgz+0.28,"#20252b",db=4.71) # screen
tv(0.0,87.0,'N',w=6.0)                # 13 · conference (north wall, y0)
tv(18.0,5.5,'N',w=3.0,z0=2.48,z1=3.12)  # 1 · training screen, above the credenza
tv(64.25,58.0,'E')                    # 11 · training screen (east wall; hidden behind the near wall)
tv(82.0,58.0,'E')                     # 12 · training screen (east wall; hidden behind the near wall)

# --- TRAINING ROOMS: classroom seating facing the screen wall + credenza under it.
# The screen wall comes from the studio, mapped to the building: room 1's entry faces the
# open office to its EAST, so it maps 1:1 (screen on the north wall). Rooms 11/12's entry
# faces the open office to the NORTH while their windows are the south exterior — a 180-deg
# rotation — so the studio's screen wall lands on the EAST party wall, not the west.
def classroom(x0,y0,x1,y1,col,cred,face):
    """12 seats facing `face` (the screen wall, building frame) + the credenza under it."""
    def chair(cx,cy,back):
        r=0.66                                                              # low, wide seat reads
        box(cx-r,cy-r,cx+r,cy+r,FLR_Z,FLR_Z+1.05,col)                       # as a chair, not a post
        d={'N':(cx-r,cy-r-0.16,cx+r,cy-r),'S':(cx-r,cy+r,cx+r,cy+r+0.16),
           'W':(cx-r-0.16,cy-r,cx-r,cy+r),'E':(cx+r,cy-r,cx+r+0.16,cy+r)}[back]
        box(d[0],d[1],d[2],d[3],FLR_Z,FLR_Z+1.80,shade(col,1.12))           # short back, opposite the screen
    if face=="N":                                          # screen on north wall; chairs face north
        scred(x0+2.2,y0+0.25,x1-2.2,y0+1.60,cred)
        xs=[x0+3.1,(x0+x1)/2,x1-3.1]                        # more margin off the side walls
        for cy in (y0+4.4+k*3.3 for k in range(4)):        # first row well off the credenza
            for cx in xs: chair(cx,cy,'S')
    elif face=="E":                                        # screen on east wall; chairs face east
        # The east wall is a NEAR wall to the fixed SE camera, so the room's east partition
        # would hide a credenza against it. A depth bias makes it draw in front of that
        # partition — same screen position, just no longer occluded.
        # East is a NEAR wall to the camera, so a credenza there is correctly hidden behind it.
        # No depth bias — better unseen than poking through the wall.
        box(x1-1.60,y0+2.6,x1-0.25,y1-4.0,FLR_Z,FLR_Z+2.4,cred)
        ys=[y0+3.2,(y0+3.2+y1-4.2)/2,y1-4.2]               # front row well clear of the south wall
        for cx in (x1-4.4-k*3.5 for k in range(4)):        # first column off the credenza
            for cy in ys: chair(cx,cy,'W')
classroom(0,18,11,37,"#c2572c","#6f6a63","N")              # 1 · burnt orange
classroom(46.5,52,64.25,64,"#2d7273","#5f7273","E")        # 11 · deep teal
classroom(64.25,52,82,64,"#4f7343","#6a7562","E")          # 12 · forest green

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
