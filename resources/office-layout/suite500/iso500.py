import sys
#!/usr/bin/env python3
"""Isometric 'dollhouse' render of the Alphalete new office floor plan -> SVG."""
import math

COS = math.cos(math.radians(30))
SIN = math.sin(math.radians(30))
SCALE = 9.0
WALL_H = 8.5
FLR_Z = 1.6
W, D = 76, 40

# ---- compute canvas offset up front ---------------------------------------
def _iso_raw(x, y, z):
    return ((x - y) * COS * SCALE, (x + y) * SIN * SCALE - z * SCALE)

_corners = [_iso_raw(x, y, z) for x in (14, W + 1) for y in (-1, D + 1)
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


# ======================= SUITE 500 (from IMG_2709 walk-through) ==============
# plan units ~ feet-ish, NOT to scale. North (y=0) = outside wall with windows.
C_CARPET="#ddd3c0"; C_VINYL="#c8ccc9"; C_HALL="#ece8df"; C_WET="#dfe3ea"; C_LOBBY="#efdcd9"
C_WALL="#e9ebef"; C_GLASS="#bfe0ea"; C_ACC="#e8482b"
box(15,0,W,D,0,FLR_Z,"#c7ccd6",db=-3e6)

ANCHOR={"O":(61,4.6),"O2":(45,4.6),"E":(21.6,2.6),"A":(33,7),"L":(67,25.6),"K":(53.5,31),"O4":(44.5,25.6),"W":(27,28.2),"M":(37,28.2),"MS":(20.2,31)}
LINES={"MS":["MOP SINK /","STORAGE"]}
# room names as signs on each room's hall-side wall (that face looks at the camera, so a name never covers furniture)
SIGN={"E":(["OFFICE 3"],15,24,17),"A":(["ATMO"],24,42,17),"O2":(["OFFICE 2"],42,58,17),"O":(["AL'S OFFICE"],58,76,17),
      "MS":(["MOP SINK /","STORAGE"],15,24,23),"W":(["WOMEN'S"],24,30,23),"M":(["MEN'S"],34,40,23),"K":(["BREAK ROOM"],40,58,23),
      "F":(["FOUNTAINS"],30,34,30)}
def wall_sign(lines,x0,x1,yw):
    H=3.4; n=len(lines); ml=max(len(l) for l in lines)
    fs=min(13.0, 0.86*(x1-x0)*SCALE/(0.64*ml), H*SCALE*0.78/(n*1.12))
    px,py=iso((x0+x1)/2,yw+0.26,FLR_Z+H*0.55)
    out=""
    for k,l in enumerate(lines):
        dy=(k-(n-1)/2)*fs*1.12
        out+=(f'<text transform="matrix({COS:.4f},{SIN:.4f},0,1,{px:.1f},{py:.1f})" y="{dy:.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" '
              f'font-size="{fs:.1f}" font-weight="800" fill="#1d222b" stroke="#ffffff" stroke-width="3" stroke-linejoin="round" paint-order="stroke" '
              f'text-anchor="middle" dominant-baseline="central" style="letter-spacing:0.5px">{l}</text>')
    emit(9e9,9e9,out)
def floorlabel(rid,nm,x0,y0,x1,y1):
    # name painted flat on the room's own floor, along its long side, sized to fit inside the walls
    w,h=x1-x0,y1-y0; along_y=h>w*1.15
    L,S=(h,w) if along_y else (w,h)
    fs=min(16.0, 0.82*L*SCALE/(0.62*len(nm)), 0.5*S*SCALE)
    cx,cy=ANCHOR.get(rid,((x0+x1)/2,(y0+y1)/2))
    px,py=iso(cx,cy,FLR_Z+0.05)
    m=(f"{COS:.4f},{-SIN:.4f},{COS:.4f},{SIN:.4f}" if along_y else f"{COS:.4f},{SIN:.4f},{-COS:.4f},{SIN:.4f}")
    emit(9e9,9e9,f'<text transform="matrix({m},{px:.1f},{py:.1f})" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{fs:.1f}" '
         f'font-weight="800" fill="#1d222b" stroke="#ffffff" stroke-width="3.4" stroke-linejoin="round" paint-order="stroke" '
         f'text-anchor="middle" dominant-baseline="central" style="letter-spacing:0.5px">{nm}</text>')
def note(x,y,z,text):
    # small dark tag for a fixture (not a room)
    px,py=iso(x,y,z); fs=8.5; tw=len(text)*fs*0.62+10; th=fs+7
    emit(9e9,9e9,f'<rect x="{px-tw/2:.1f}" y="{py-th/2:.1f}" width="{tw:.1f}" height="{th:.1f}" rx="{th/2:.1f}" fill="#3a404c" fill-opacity="0.92"/>'
         f'<text x="{px:.1f}" y="{py+fs*0.36:.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{fs}" font-weight="700" fill="#ffffff" text-anchor="middle" style="letter-spacing:0.3px">{text}</text>')
def pill(cx,cy,nm,w,rid=None):
    lines=LINES.get(rid,[nm]); fs=9.5 if w<10 else 11.5
    px,py=iso(cx,cy,FLR_Z+0.05)
    tw=max(len(l) for l in lines)*fs*0.64+12; th=len(lines)*fs*1.15+8
    o=f'<rect x="{px-tw/2:.1f}" y="{py-th/2:.1f}" width="{tw:.1f}" height="{th:.1f}" rx="4" fill="#ffffff" fill-opacity="0.94" stroke="#b9c0ca" stroke-width="1"/>'
    for k,l in enumerate(lines):
        ty=py-th/2+4+fs*0.95+k*fs*1.15
        o+=(f'<text x="{px:.1f}" y="{ty:.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{fs}" font-weight="800" '
            f'fill="#1d222b" text-anchor="middle" style="letter-spacing:0.4px">{l}</text>')
    emit(9e9,9e9,o)
ROOMS=[("L","LOBBY",(58,17,76,40),C_LOBBY),("O","AL'S OFFICE",(58,0,76,17),C_CARPET),
 ("A","ATMO",(24,0,42,17),C_CARPET),("O2","OFFICE 2",(42,0,58,17),C_VINYL),
 ("O4","OFFICE 4",(40,23,49,40),C_CARPET),("K","BREAK ROOM",(49,23,58,40),C_VINYL),("MS","MOP SINK / STORAGE",(15,23,24,40),C_CARPET),
 ("W","WOMEN'S",(24,23,30,40),C_WET),("F","FOUNTAINS",(30,23,34,30),"#e6eef5"),("M","MEN'S",(34,23,40,40),C_WET),
 ("E","OFFICE 3",(15,0,24,17),C_VINYL)]
floor(15,17,58,23,FLR_Z,C_HALL)
label(34,20.6,FLR_Z+0.05,"MAIN HALL",size=7.5,color="#8a8478",weight="700")
for rid,nm,(x0,y0,x1,y1),col in ROOMS:
    floor(x0,y0,x1,y1,FLR_Z,col)
    cx,cy=ANCHOR.get(rid,((x0+x1)/2,(y0+y1)/2))
    if rid=="F": note(32,26.6,FLR_Z+5.8,"fountains")
    elif nm: pill(*ANCHOR.get(rid,((x0+x1)/2,(y0+y1)/2)),nm,x1-x0,rid)

H=3.4; T=0.45; DW=3.0
def hwall(y,x0,x1,doors=(),dw=DW):
    a=x0
    for d in sorted(doors):
        if d-dw/2>a: box(a,y-T/2,d-dw/2,y+T/2,FLR_Z,FLR_Z+H,C_WALL)
        a=d+dw/2
    if x1>a: box(a,y-T/2,x1,y+T/2,FLR_Z,FLR_Z+H,C_WALL)
def vwall(x,y0,y1,doors=(),dw=DW):
    a=y0
    for d in sorted(doors):
        if d-dw/2>a: box(x-T/2,a,x+T/2,d-dw/2,FLR_Z,FLR_Z+H,C_WALL)
        a=d+dw/2
    if y1>a: box(x-T/2,a,x+T/2,y1,FLR_Z,FLR_Z+H,C_WALL)

hwall(17,15,76,doors=(19.5,33,50,60))
box(63,17-0.2,73,17+0.2,FLR_Z+H,FLR_Z+5.6,C_GLASS,op=0.5)      # office pass-through window -> lobby
hwall(23,15,30,doors=(19.5,)); hwall(23,34,58,doors=(44.5,53.5))
for x in (42,58): vwall(x,0,17)
box(42-0.2,4,42+0.2,13,FLR_Z+H,FLR_Z+5.6,C_GLASS,op=0.5)       # large training <-> plank room window
vwall(24,0,17)

def imac(x0,y,face_n=True):
    # silver iMac: thin screen on a small stand, screen facing the chair
    box(x0+1.15,y+0.2,x0+1.55,y+0.75,FLR_Z+2.5,FLR_Z+3.1,"#b9bec5",db=6)
    box(x0,y,x0+2.7,y+0.22,FLR_Z+3.0,FLR_Z+5.0,"#d9dce1",db=6)
    box(x0,y,x0+2.7,y+0.22,FLR_Z+3.0,FLR_Z+3.35,"#c3c7cd",db=6.1)
# ATMO: dry-erase boards - a big one on the outside wall, a second on the Office 3 side wall
box(24.8,0.05,32.8,0.3,FLR_Z+2.0,FLR_Z+6.4,"#8a9099",db=60); box(25.0,0.3,32.6,0.4,FLR_Z+2.2,FLR_Z+6.2,"#fbfcfd",db=61)
box(24.22,3,24.32,14,FLR_Z+1.0,FLR_Z+3.35,"#8a9099"); box(24.32,3.2,24.42,13.8,FLR_Z+1.15,FLR_Z+3.2,"#fbfcfd")
# interview rooms (Office 3 + Office 2): desk, interviewer chair behind it, two chairs across
def chair(cx,cy,face,col="#2c313b"):
    box(cx-0.8,cy-0.8,cx+0.8,cy+0.8,FLR_Z,FLR_Z+0.8,col)
    if face=="S": box(cx-0.8,cy-0.8,cx+0.8,cy-0.55,FLR_Z,FLR_Z+2.4,shade(col,1.18))
    elif face=="E": box(cx-0.8,cy-0.8,cx-0.55,cy+0.8,FLR_Z,FLR_Z+2.4,shade(col,1.18))
    elif face=="W": box(cx+0.55,cy-0.8,cx+0.8,cy+0.8,FLR_Z,FLR_Z+2.4,shade(col,1.18))
    else:         box(cx-0.8,cy+0.55,cx+0.8,cy+0.8,FLR_Z,FLR_Z+2.4,shade(col,1.18))
def interview(x0,x1,L=False):
    mid=(x0+x1)/2; w=min(4.0,(x1-x0)/2-1.2)
    box(mid-w,6,mid+w,8.4,FLR_Z,FLR_Z+2.5,"#3b3632")
    if L: box(mid+w-2.4,1.2,mid+w,6,FLR_Z,FLR_Z+2.5,"#3b3632")     # L return toward the back wall
    chair(mid-(1.0 if L else 0),3.6,"S")
    chair(mid-w*0.55,11.2,"N"); chair(mid+w*0.55,11.2,"N")
interview(15,24)
# Office 4 (south side, mirrors Office 3): desk, chair behind it by the outside wall, two chairs across facing it
box(41.2,32,47.8,34.4,FLR_Z,FLR_Z+2.5,"#3b3632"); chair(44.5,36.4,"N"); chair(42.7,28.8,"S"); chair(46.3,28.8,"S")
# Office 2: same layout as Al's - L-desk, chair behind facing the hall, two guest chairs across
box(46,9,55,11.4,FLR_Z,FLR_Z+2.5,"#3b3632"); box(52.6,4,55,9,FLR_Z,FLR_Z+2.5,"#3b3632")
box(49.2,6.4,50.8,8.0,FLR_Z,FLR_Z+0.8,"#2c313b"); box(49.2,6.2,50.8,6.5,FLR_Z,FLR_Z+3.6,"#3d4452")
chair(48.4,13.3,"N"); chair(51.6,13.3,"N")
# lobby: small reception desk by Al's window facing the entry; lounge seating on the open back + side walls
box(64,20,70,22.2,FLR_Z,FLR_Z+2.6,"#a98a63"); chair(67,18.7,"S"); imac(65.65,20.35)
C_SOFA="#4f6b7a"
# couch along the back glass wall, facing the room
box(63,37.4,71,39.6,FLR_Z,FLR_Z+1.0,C_SOFA); box(63,39.0,71,39.6,FLR_Z,FLR_Z+2.3,shade(C_SOFA,1.15),db=0.02)
box(63,37.4,63.6,39.6,FLR_Z,FLR_Z+1.6,shade(C_SOFA,1.08)); box(70.4,37.4,71,39.6,FLR_Z,FLR_Z+1.6,shade(C_SOFA,1.08))
# couch along the side wall, facing the entry
box(58.4,27.6,60.6,35.6,FLR_Z,FLR_Z+1.0,C_SOFA); box(58.4,27.6,59.0,35.6,FLR_Z,FLR_Z+2.3,shade(C_SOFA,1.15))
box(58.4,27.6,60.6,28.2,FLR_Z,FLR_Z+1.6,shade(C_SOFA,1.08)); box(58.4,35.0,60.6,35.6,FLR_Z,FLR_Z+1.6,shade(C_SOFA,1.08))
box(65.3,30,68.7,33.2,FLR_Z,FLR_Z+1.2,"#8b7a63")
for _y in (23.6,34.6,36.9): chair(74.8,_y,"W",col="#4f6b7a")       # chairs on the entry wall
# tablet station on the end wall of the mop sink / storage room: counter with tablets standing in charging slots
box(15.2,25,17.2,33.5,FLR_Z,FLR_Z+2.8,"#c9ced6"); box(15.2,25,17.4,33.5,FLR_Z+2.8,FLR_Z+2.95,"#e4e7ec")
for _k in range(8):
    _y=25.6+_k*1.0
    box(15.6,_y,16.9,_y+0.2,FLR_Z+2.95,FLR_Z+4.2,"#1c2026")
note(16.3,29.3,FLR_Z+5.6,"tablet station")
# mop sink in O3's back corner: deep floor basin, wall faucet, mop standing in the basin
box(15.3,36.6,18.4,39.7,FLR_Z,FLR_Z+1.3,"#eef0f2"); box(15.8,37.1,17.9,39.2,FLR_Z+1.3,FLR_Z+1.34,"#7d8790")
box(15.05,38.0,15.45,38.5,FLR_Z+1.3,FLR_Z+3.4,"#9aa3ab"); box(15.05,38.0,16.6,38.5,FLR_Z+3.1,FLR_Z+3.4,"#9aa3ab")
box(15.9,37.3,17.0,38.2,FLR_Z+1.34,FLR_Z+1.7,"#cfcabc")                    # mop head in the basin
box(16.3,37.6,16.55,37.85,FLR_Z+1.7,FLR_Z+6.2,"#b07a45")                  # mop handle
vwall(24,23,40); vwall(30,23,40,doors=(27,)); vwall(34,23,40,doors=(27,)); hwall(30,30,34)
floor(30,30,34,40,FLR_Z,"#b9bec7")                          # plumbing wall behind the fountains
box(30.4,28.4,33.6,29.7,FLR_Z,FLR_Z+2.6,"#cfe0ea")          # water fountains

vwall(40,23,40); vwall(49,23,40); vwall(58,23,40)

# office: dark L-desk under the outside window + chair
# Al's Office: L-desk facing the lobby window; chair behind it with its back to the outside wall
box(66,9,75,11.4,FLR_Z,FLR_Z+2.5,"#3b3632"); box(72.6,4,75,9,FLR_Z,FLR_Z+2.5,"#3b3632")
imac(68.9,9.35)
box(69.2,6.4,70.8,8.0,FLR_Z,FLR_Z+0.8,"#2c313b"); box(69.2,6.2,70.8,6.5,FLR_Z,FLR_Z+3.6,"#3d4452")
chair(68.4,13.3,"N"); chair(71.6,13.3,"N")                 # two guest chairs across Al's desk
# break room: cabinets + counter down BOTH side walls, uppers both sides, sink, fridge, whiteboard
for cx0,cx1,ux0,ux1 in ((49.3,51.7,49.3,50.3),(55.6,57.8,56.8,57.8)):
    box(cx0,25,cx1,37,FLR_Z,FLR_Z+2.8,"#7a3b2a"); box(cx0,25,cx1+0.15,37,FLR_Z+2.8,FLR_Z+3.05,"#d8cdb0")
    if ux0>52: box(ux0,25,ux1,37,FLR_Z+4.6,FLR_Z+6.6,"#8a4431",op=0.9)   # uppers on the east wall only
box(50,29,51.2,31,FLR_Z+3.05,FLR_Z+3.1,"#9aa3ab")
box(55.0,37.3,57.8,39.8,FLR_Z,FLR_Z+6.0,"#a9adb2")
box(52,37.6,55,37.8,FLR_Z+1.6,FLR_Z+4.4,"#f4f6f8"); box(52,37.2,55,38.2,FLR_Z,FLR_Z+0.3,"#c4c9cf")
# training room: wall screen on the hall-side wall

# end of the hall: EXIT door on the back wall, extinguisher on the electrical room wall
box(15,18.5,15.35,21.5,FLR_Z,FLR_Z+6.6,"#5a4f45")
label(15.3,20,FLR_Z+8.4,"EXIT",size=9.0,color=C_ACC,weight="800")
box(21,17.25,22,17.75,FLR_Z+2.0,FLR_Z+3.4,"#c0392b")
# storage: panel + bracket on the outside wall
box(16,0.05,18,0.45,FLR_Z+2.2,FLR_Z+5.8,"#a7adb4",db=60)
box(19.5,0.05,22,0.3,FLR_Z+2.6,FLR_Z+5.4,"#23272d",op=0.8,db=60)
# men's restroom: toilet + wall sink
box(25.5,35.5,27.1,37.9,FLR_Z,FLR_Z+1.4,"#f8f9fa"); box(25.5,37.3,27.1,37.9,FLR_Z,FLR_Z+2.6,"#f1f3f5")
box(27,24.3,29,25.3,FLR_Z+2.2,FLR_Z+2.9,"#f8f9fa")
box(36,35.5,37.6,37.9,FLR_Z,FLR_Z+1.4,"#f8f9fa"); box(36,37.3,37.6,37.9,FLR_Z,FLR_Z+2.6,"#f1f3f5")
box(37,24.3,39,25.3,FLR_Z+2.2,FLR_Z+2.9,"#f8f9fa")

box(15,-1.0,W,0,FLR_Z,FLR_Z+WALL_H,C_WALL)
for a,b in ((60,74),(44,56),(33.5,41)):
    box(a,0.05,b,0.3,FLR_Z+2.4,FLR_Z+7.4,"#8fb9cf",op=0.9,db=60)
box(14,0,15,D,FLR_Z,FLR_Z+WALL_H,C_WALL)
box(15,D,W,D+0.5,FLR_Z,FLR_Z+1.3,C_GLASS,op=0.55)
box(W,0,W+0.5,D,FLR_Z,FLR_Z+1.3,C_GLASS,op=0.55)
box(W-0.1,26,W+0.6,32,FLR_Z,FLR_Z+5.0,"#5d8fb0",op=0.75)    # glass double doors "500" at the front end
label(W+0.4,29,FLR_Z+6.4,"500",size=10.0,color="#2a2f3a",weight="800")
label(W+3.5,32,FLR_Z,"ENTRY",size=9.0,color="#5b6270",weight="800")

_svg.sort(key=lambda t:(t[0],t[1]))
body="\n".join(s for _,_,s in _svg)
svg_doc=(f'<svg viewBox="0 0 {Wpx:.0f} {Hpx:.0f}" xmlns="http://www.w3.org/2000/svg" role="img" class="iso">'
         f'<title>Suite 500, 3D view</title><rect width="{Wpx:.0f}" height="{Hpx:.0f}" fill="#f5f6f8"/>{body}</svg>')
open(sys.argv[1],"w").write(svg_doc); print("px",int(Wpx),int(Hpx),"polys",len(_svg))
