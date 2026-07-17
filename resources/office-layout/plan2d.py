#!/usr/bin/env python3
"""Flat top-down numbered floor plan (key map) matching the studio order."""
S=13.0                      # px per foot
MX,MY=40,90                 # plan margins (top margin leaves room for title)
PW,PD=104,64                # plan feet
LEG_W=430                   # legend panel width
Wpx=MX+PW*S+LEG_W+40
Hpx=MY+PD*S+50

C_OFFICE="#dbe4f1"; C_OPEN="#ece5d4"; C_CONF="#d3e7dd"; C_SERV="#e2e4e8"
C_RECEP="#f3dfe0"; C_ACCENT="#e8482b"; C_INK="#2a2f3a"; C_SUB="#8b91a0"
C_DESK="#b98a5e"; C_LINE="#b9c0cc"

def X(x): return MX+x*S
def Y(y): return MY+y*S

el=[]
def rect(x0,y0,x1,y1,fill,stroke=C_LINE,sw=1.4,dash=None,rx=0):
    d=f' stroke-dasharray="{dash}"' if dash else ''
    el.append(f'<rect x="{X(x0):.1f}" y="{Y(y0):.1f}" width="{(x1-x0)*S:.1f}" height="{(y1-y0)*S:.1f}" '
              f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d} rx="{rx}"/>')
def txt(x,y,s,size=11,color=C_INK,w="700",anchor="middle"):
    el.append(f'<text x="{X(x):.1f}" y="{Y(y):.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" '
              f'font-size="{size}" font-weight="{w}" fill="{color}" text-anchor="{anchor}">{s}</text>')
def rtext(px,py,s,size=11,color=C_INK,w="700",anchor="start"):
    el.append(f'<text x="{px}" y="{py}" font-family="Inter,Segoe UI,Arial,sans-serif" '
              f'font-size="{size}" font-weight="{w}" fill="{color}" text-anchor="{anchor}">{s}</text>')
def badge(x,y,n):
    cx,cy=X(x),Y(y)
    el.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="11" fill="{C_ACCENT}"/>')
    el.append(f'<text x="{cx:.1f}" y="{cy+4:.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" '
              f'font-size="13" font-weight="800" fill="#fff" text-anchor="middle">{n}</text>')

def room(x0,y0,x1,y1,fill,name,dim=None,num=None,combined=False):
    rect(x0,y0,x1,y1,fill)
    if combined:
        rect(x0+0.4,y0+0.4,x1-0.4,y1-0.4,"none",stroke=C_ACCENT,sw=1.6,dash="6 4")
    cx,cy=(x0+x1)/2,(y0+y1)/2
    if name:
        txt(cx,cy-(0.35 if dim else -0.15),name,size=min(11,10),color=C_INK,w="700")
        if dim: txt(cx,cy+1.15,dim,size=8.5,color=C_SUB,w="600")
    if num is not None:
        badge(x0+1.15,y0+1.15,num)

import math as _m
def door(hx,hy,w,q):
    """Door swing at hinge (hx,hy), width w, quadrant q in {'NE','SE','SW','NW'} (plan, y-down)."""
    quads={'NE':(270,360),'SE':(0,90),'SW':(90,180),'NW':(180,270)}
    a0,a1=quads[q]
    p0=(hx+w*_m.cos(_m.radians(a0)),hy+w*_m.sin(_m.radians(a0)))
    p1=(hx+w*_m.cos(_m.radians(a1)),hy+w*_m.sin(_m.radians(a1)))
    # door leaf (open) + swing arc
    el.append(f'<line x1="{X(hx):.1f}" y1="{Y(hy):.1f}" x2="{X(p1[0]):.1f}" y2="{Y(p1[1]):.1f}" stroke="#d06a34" stroke-width="2.4" stroke-linecap="round"/>')
    el.append(f'<path d="M {X(p1[0]):.1f} {Y(p1[1]):.1f} A {w*S:.1f} {w*S:.1f} 0 0 1 {X(p0[0]):.1f} {Y(p0[1]):.1f}" fill="none" stroke="#e6b596" stroke-width="1.2"/>')

# ---- plumbing fixtures -----------------------------------------------------
def sink(x,y): el.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="2.5" fill="#ffffff" stroke="#7d848f" stroke-width="1.1"/>')
def toilet(x,y): el.append(f'<ellipse cx="{X(x):.1f}" cy="{Y(y):.1f}" rx="1.9" ry="2.5" fill="#ffffff" stroke="#7d848f" stroke-width="1.1"/>')
def urinal(x,y): el.append(f'<rect x="{X(x)-3.0:.1f}" y="{Y(y)-4.5:.1f}" width="6" height="7" rx="3" fill="#ffffff" stroke="#7d848f" stroke-width="1.1"/>')
def wc_stall(x0,y0,x1,y1): rect(x0,y0,x1,y1,"none",stroke="#b3b8c1",sw=1.0)

# ---- footprint -------------------------------------------------------------
rect(0,0,PW,PD,"#ffffff",stroke="#7d848f",sw=2.4)
# exterior glass / window walls (south + east perimeter)
GLASS="#4ea6cf"
el.append(f'<line x1="{X(0):.1f}" y1="{Y(PD):.1f}" x2="{X(PW):.1f}" y2="{Y(PD):.1f}" stroke="{GLASS}" stroke-width="5"/>')
el.append(f'<line x1="{X(PW):.1f}" y1="{Y(0):.1f}" x2="{X(PW):.1f}" y2="{Y(PD):.1f}" stroke="{GLASS}" stroke-width="5"/>')
for gx in range(3,int(PW),5):
    el.append(f'<line x1="{X(gx):.1f}" y1="{Y(PD)-4:.1f}" x2="{X(gx):.1f}" y2="{Y(PD)+4:.1f}" stroke="{GLASS}" stroke-width="1.4"/>')
for gy in range(3,int(PD),5):
    el.append(f'<line x1="{X(PW)-4:.1f}" y1="{Y(gy):.1f}" x2="{X(PW)+4:.1f}" y2="{Y(gy):.1f}" stroke="{GLASS}" stroke-width="1.4"/>')
txt(PW*0.42,PD+3.1,"exterior glass / windows",size=9.5,color="#2f7fa3",w="800")

# NORTH BAND
# NORTH-WEST service zone: STOR (narrow tall) · break room+island · hall · IT · restrooms
room(0,0,6,18,C_SERV,"STOR","5'×17'")                           # far-left narrow storage
room(6,0,24,18,C_SERV,"BREAK ROOM","15'6×20'",num=15)
# freestanding island (near the sink counter)
rect(18,4,20,12.5,"#b7bcc4",stroke="#7d848f",sw=1.2)
txt(19,8.5,"island",size=6,color="#3a4150",w="700")
# built-in sink counter along the east wall (GFI outlets)
rect(22,2,24,16,"#c4cdd8",stroke="#7d848f",sw=1.3)
el.append(f'<circle cx="{X(23):.1f}" cy="{Y(7):.1f}" r="2.9" fill="none" stroke="#5b6270" stroke-width="1.2"/>')  # sink
txt(19.4,15.4,"sink counter",size=4.8,color="#5b6270",w="700")
# HALL (narrow) + IT — the fountain VESTIBULE sits BETWEEN the two restrooms
room(24,0,27,18,"#eef1f4",None)                                 # narrow hall
txt(25.5,16.2,"HALL",size=5.5,color="#5b6270",w="800")
room(24,0,27,5,C_SERV,"IT")                                     # IT (narrow)
# ================= RESTROOMS (fixtures counted from A2.01) =================
# ---- MEN 119 (NORTH of the vestibule) ----
room(27,0,50,7,C_SERV,None)
txt(30,2.0,"MEN",size=7,color=C_INK,w="800"); txt(30,3.3,"119",size=4.5,color=C_SUB,w="600")
rect(33,4.55,39.2,6.85,"#eaeef3",stroke="#7d848f",sw=1.3)        # sink vanity (hug center wall)
sink(34.5,5.7); sink(37.6,5.7)
txt(36,4.0,"sinks",size=3.6,color="#5b6270",w="700")
urinal(41.6,6.0)                                                 # 1 urinal
txt(41.6,4.3,"urinal",size=3.6,color="#5b6270",w="700")
rect(45.5,3.3,50,6.85,"#f7f8fa",stroke="#5b6270",sw=1.7); toilet(47.75,5.85)   # ADA stall (toilet backs to center)
txt(47.75,3.9,"toilet",size=3.6,color="#5b6270",w="700"); txt(47.75,4.7,"ADA",size=3.2,color="#8a90a0",w="700")
# ---- VESTIBULE — little room you walk into; doors N→men, S→women; fountains on east wall ----
room(27,7,33,11,"#e6eef5",None)
txt(29.8,8.3,"vestibule",size=3.7,color="#5b6270",w="700")
rect(30.7,7.7,32.5,8.8,"#cfe0ea",stroke="#7fb8d4",sw=1)          # water fountains (east wall, aligned to sinks)
rect(30.7,9.2,32.5,10.3,"#cfe0ea",stroke="#7fb8d4",sw=1)
txt(28.9,9.6,"fountains",size=3,color="#3f88a8",w="600")
# ---- plumbing wall east of the vestibule (toilets back-to-back through the chase) ----
rect(33,7,50,11,C_SERV,stroke="#c7ccd4",sw=1.1)
rect(33,7.7,50,10.3,"#4a505c",stroke="none",sw=0)
# ---- WOMEN 121 (SOUTH of the vestibule) ----
room(27,11,50,18,C_SERV,None)
txt(30,16.0,"WOMEN",size=7,color=C_INK,w="800"); txt(30,17.3,"121",size=4.5,color=C_SUB,w="600")
rect(33,11.15,39.2,13.45,"#eaeef3",stroke="#7d848f",sw=1.3)      # sink vanity (hug center wall)
sink(34.5,12.3); sink(37.6,12.3)
txt(36,14.2,"sinks",size=3.6,color="#5b6270",w="700")
rect(40.3,11.15,44.7,14.7,"#f7f8fa",stroke="#5b6270",sw=1.7); toilet(42.5,12.25)   # toilet stall (backs to center)
txt(42.5,13.8,"toilet",size=3.6,color="#5b6270",w="700")
rect(45.5,11.15,50,14.7,"#f7f8fa",stroke="#5b6270",sw=1.7); toilet(47.75,12.25)    # ADA toilet stall
txt(47.75,13.8,"toilet",size=3.6,color="#5b6270",w="700"); txt(47.75,14.5,"ADA",size=3.2,color="#8a90a0",w="700")
room(50,0,70,18,C_OFFICE,"RAF'S OFFICE","20' × 20'",num=4)
# NE CONFERENCE — drawn AFTER the open office (below) so it stays a full rectangle
# WEST COLUMN — offices 114+113 = training room, 112 = office, 111 = Maud's tall corner
room(0,18,11,37,C_OFFICE,"TRAINING ROOM","10'6 × 20'",num=1)   # tallest (20')
room(0,37,11,47,C_OFFICE,"OFFICE","10'6×10'5",num=2)
room(0,47,11,64,C_OFFICE,"MAUD'S OFFICE","10'5 × 17'5",num=3)   # tall narrow corner (office 111)
# EAST COLUMN
room(91,18,104,29,C_OFFICE,"TWADDLE'S OFFICE","10'8×10'8",num=5)
room(91,29,104,40,C_OFFICE,"CLAUDE / MEGAN'S","10'8×10'8",num=6)
# RECEPTION / LOBBY (bottom-right). Enclosed back room + built-in desk; entry at SE.
room(82,40,104,64,C_RECEP,None,num=14)
# fully enclosed back room — WALL TO WALL, entered by its own door on the west
rect(82,40.4,104,44.4,"#f6e9ea",stroke="#7d848f",sw=1.8)
txt(94,41.9,"ENCLOSED ROOM",size=6.5,color="#8a6a6f",w="800")
txt(94,43.3,"back office · door on west",size=5.0,color="#b08a8f",w="600")
# glass-upper partition above the desk (wall to wall)
rect(82,44.4,104,44.75,"#bfe0ea",stroke="#7fb8d4",sw=1.0)
txt(95,44.15,"glass upper",size=4.3,color="#3f88a8",w="700")
# built-in desk — WALL TO WALL
rect(82,44.9,104,46.8,C_DESK,stroke="#7a5f3c",sw=1.2)
txt(93,46.0,"BUILT-IN DESK",size=8,color="#fff",w="800")
# lobby / waiting (below the desk — extra walkway room now)
txt(94,55,"LOBBY",size=13,color=C_INK,w="800")
txt(94,57.1,"13'6 × 21'10",size=8.5,color=C_SUB,w="600")
# open walkway from the open office (west) — bigger now
txt(83.4,49,"walkway · door ▸",size=7.5,color="#2f7d8c",w="800",anchor="start")
rect(82,47,82.4,58,C_RECEP,stroke="#2f7d8c",sw=2.0,dash="4 3")
# curved building entry at SE corner
el.append(f'<path d="M {X(98):.1f} {Y(64):.1f} A {6*S:.1f} {6*S:.1f} 0 0 0 {X(104):.1f} {Y(58):.1f}" fill="none" stroke="#7d848f" stroke-width="2.2"/>')
txt(100.3,62,"entry",size=7,color=C_SUB,w="700")
# BOTTOM ROW (south offices) start at the west-column edge
sx0,sx1=11,82; ow=(sx1-sx0)/8
south=[(0,1,"OFFICE","12×10'6",7,False),(1,2,"OFFICE","12×10'6",8,False),
       (2,3,"OFFICE","12×10'",9,False),(3,4,"JD'S OFFICE","12×13'6",10,False),
       (4,6,"TRAINING ROOM","24' × 9'",11,False),(6,8,"TRAINING ROOM","24' × 10'6",12,False)]
for a,b,nm,lab,n,comb in south:
    room(sx0+a*ow,52,sx0+b*ow,64,C_OFFICE,nm,lab,num=n,combined=comb)
# OPEN OFFICE — empty open floor with fixed structural pillars
room(11,18,82,52,C_OPEN,None,num=16)
txt(47.5,23.5,"OPEN OFFICE",size=13,color="#8a7c56",w="800")
txt(47.5,26.2,"34'9 × 96'  ·  open floor",size=9,color="#a2946f",w="600")
for px in (23,47,68):
    rect(px-0.8,35-0.8,px+0.8,35+0.8,"#8b919c",stroke="#5b6270",sw=1.2)
txt(47.5,41.5,"■ 3 structural pillars — can't move",size=9,color="#5b6270",w="700")
# walkway/circulation west of the east offices — same color as the open area
room(82,18,91,40,C_OPEN,None)
# NE CONFERENCE (drawn here so it renders as a full rectangle over the open-office corner)
room(70,0,104,18,C_CONF,"LARGE CONFERENCE","20' × 49'",num=13)
# interior glass window in the conference's west wall — looks into Raf's office
el.append(f'<line x1="{X(70):.1f}" y1="{Y(3.5):.1f}" x2="{X(70):.1f}" y2="{Y(14.5):.1f}" stroke="{GLASS}" stroke-width="4.5"/>')
txt(72.7,9.6,"glass",size=4.2,color="#3f88a8",w="700")
# (built-in desk now drawn inside the reception/lobby block above)

# ---- doors (swing per room) ------------------------------------------------
DOORS=[
 (11,22,2.4,'SW'),(11,41,2.4,'SW'),(11,50,2.4,'SW'),            # west: training, office, maud
 (16,52,2.4,'SE'),(24.6,52,2.4,'SE'),(33.1,52,2.4,'SE'),(41.7,52,2.4,'SE'),  # south 7-10
 (52,52,2.4,'SE'),(69,52,2.4,'SE'),                             # south training A/B
 (91,20,2.4,'SE'),(91,31,2.4,'SE'),                             # east: twaddle, claude/megan
 (16,18,2.4,'NW'),(57,18,2.4,'NW'),                            # break room, raf
 (70,8,2.4,'SE'),                                               # conference
 (31,7,2.3,'NW'),(31,11,2.3,'SE'),(27,9,2.2,'SE'),(25.5,5,1.1,'SE'),  # men(N)/women(S) entries off vestibule + hall→vestibule + IT
                                                               # (stall doors removed — labeled instead)
 (82,42.2,2.0,'SE'),                                            # reception enclosed back room (door on west)
 (82,52,2.4,'SE'),                                              # reception entry door in the open walkway
 (6,9,2.0,'SE'),                                                # stor
]
# door markers removed per request
# for hx,hy,w,q in DOORS: door(hx,hy,w,q)

# ---- title -----------------------------------------------------------------
el.append(f'<text x="{MX}" y="34" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="22" '
          f'font-weight="800" fill="{C_INK}">ALPHALETE — Office Key Map</text>')
el.append(f'<text x="{MX}" y="54" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12" '
          f'font-weight="600" fill="{C_SUB}" letter-spacing="1.5">NUMBERS MATCH THE WALK-THROUGH ORDER · '
          f'<tspan fill="{C_ACCENT}">◧ dashed = combined (walls removed)</tspan></text>')
# compass
el.append(f'<text x="{X(PW)-6}" y="{MY-8}" font-size="11" font-weight="700" fill="{C_SUB}" text-anchor="end">N ↑ · W ← left</text>')

# ---- legend panel ----------------------------------------------------------
LX=MX+PW*S+30
legend=[(1,"West · Training Room","10'6×20'"),(2,"West · Office","10'6×10'5"),
        (3,"Maud's Office (tall corner)","10'5×17'5"),(4,"Raf's Office","20×20"),
        (5,"Twaddle's Office","10'8×10'8"),(6,"Claude Room / Megan's","10'8×10'8"),
        (7,"South · Office 1","12×10'6"),(8,"South · Office 2","12×10'6"),
        (9,"Bas's Office","12×10'"),(10,"JD's Office","12×13'6"),
        (11,"South · Training Room A","24×9'"),(12,"South · Training Room B","24×10'6"),
        (13,"Large Conference","20×49'"),(14,"Reception / Lobby","13'6×21'10"),
        (15,"Break Room","15'6×20'"),(16,"Open Office","34'9×96'")]
rtext(LX,MY-4,"WALK-THROUGH ORDER",size=12,color=C_SUB,w="800")
ly=MY+22
for n,name,dim in legend:
    el.append(f'<circle cx="{LX+11}" cy="{ly-4}" r="11" fill="{C_ACCENT}"/>')
    el.append(f'<text x="{LX+11}" y="{ly}" font-size="13" font-weight="800" fill="#fff" text-anchor="middle" font-family="Inter,Arial">{n}</text>')
    rtext(LX+30,ly-6,name,size=13,color=C_INK,w="700")
    rtext(LX+30,ly+8,dim,size=11,color=C_SUB,w="600")
    ly+=38

svg=(f'<svg viewBox="0 0 {Wpx:.0f} {Hpx:.0f}" xmlns="http://www.w3.org/2000/svg" '
     f'preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%">'
     f'<rect x="0" y="0" width="{Wpx:.0f}" height="{Hpx:.0f}" fill="#f7f8fa"/>'
     + "\n".join(el) + '</svg>')
open("/private/tmp/claude-501/-Users-megan-1st-Claude-Folder/de840332-a406-47e2-ab31-cb468bebf93c/scratchpad/keymap.svg","w").write(svg)
print("keymap",int(Wpx),int(Hpx))
