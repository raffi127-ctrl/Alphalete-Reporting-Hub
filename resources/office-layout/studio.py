#!/usr/bin/env python3
"""Per-office isometric room studio -> single interactive HTML file."""
import math, json

COS = math.cos(math.radians(30)); SIN = math.sin(math.radians(30))
FLR_Z = 1.2

# ---- palette ---------------------------------------------------------------
C_FLOOR="#bec1c7"; C_TILE="#d3d7dd"   # gray carpet everywhere; gray tile in the break room
C_WALL="#eceef2"; C_DESK="#b98a5e"; C_DESK2="#c9bfb0"
C_TASK="#37506b"; C_GUEST="#8a94a3"; C_SOFA="#5b6b86"; C_WOOD="#a97c53"
C_PLANT="#4f7a52"; C_POT="#b06a3c"; C_SCREEN="#222833"; C_RUG="#d8c6b0"
C_TABLE="#8a5a3c"; C_ACCENT="#e8482b"; C_STEEL="#c2c7cf"; C_COUNTER="#b7bcc4"
C_PINK_W="#f4e2e4"                          # Megan's office — pink walls (floor stays gray carpet)

# Each office gets its own wall colour. Floors stay gray carpet throughout (gray tile in the
# break room) — only the walls change.
TRAINING_VIBE={   # a scheme per training room. No black and no navy: navy is already
                  # Maud's and JD's, and red is Raf's and the boardroom.
 "w-comb": dict(wall="#eae8e4", chair="#c2572c", cred="#6f6a63", accent="#c2572c"),  # stone + burnt orange
 "s-comb1":dict(wall="#e1eaea", chair="#2d7273", cred="#5f7273", accent="#2d7273"),  # pale stone + deep teal
 "s-comb2":dict(wall="#e7eae2", chair="#4f7343", cred="#6a7562", accent="#4f7343"),  # sage stone + forest green
}

OPEN_PILLARS_FT=(16.2,48.8,77.4)   # A2.01: on the centreline, feet from the west edge

WALL_COL={
 "w-comb":TRAINING_VIBE["w-comb"]["wall"],   # 1  West training     — sage
 "w-3"   :"#e8e7e2",   # 2  West office       — interview (neutral)
 "w-4"   :"#e4dadc",   # 3  Maud's            — soft mauve, blush accents, navy
 "n-large":"#dcd5d0",  # 4  Raf's             — warm grey, red accents
 "e-1"   :"#d5e3d6",   # 5  Twaddle's         — sage / brown scheme
 "e-2"   :C_PINK_W,    # 6  Megan's           — pink
 "s-1"   :"#e8e7e2",   # 7  South office 1    — interview (neutral)
 "s-2"   :"#e8e7e2",   # 8  South office 2    — interview (neutral)
 "s-3"   :"#e8e3db",   # 9  Bas's              — warm greige / ochre
 "s-4"   :"#dde3ea",   # 10 JD's              — navy / grey scheme
 "s-comb1":TRAINING_VIBE["s-comb1"]["wall"],  # 11 South training A  — soft green
 "s-comb2":TRAINING_VIBE["s-comb2"]["wall"],  # 12 South training B  — soft green
 "conf"  :"#e3ded4",   # 13 Large conference  — warm greige, red chairs
 "recep" :"#f3dfe0",   # 14 Reception         — blush
 "break" :"#e2edf1",   # 15 Break room        — light blue
 "open"  :"#e8e4da",   # 16 Open office       — warm neutral
}

def shade(hexc,f):
    h=hexc.lstrip('#'); r,g,b=int(h[0:2],16),int(h[2:4],16),int(h[4:6],16)
    r=max(0,min(255,int(r*f)));g=max(0,min(255,int(g*f)));b=max(0,min(255,int(b*f)))
    return f'#{r:02x}{g:02x}{b:02x}'

# ---- foliage ---------------------------------------------------------------
# Leaf blades drawn as rotated shapes in screen space. The box primitive is axis-aligned,
# so stacked boxes only ever read as blocks, never as leaves.
GRN=("#4f7a52","#5d8a5f","#456e48")
_LEAF=((-0.42,-0.26,0.44,0.17,-25,0),( 0.38,-0.34,0.44,0.17, 22,1),
       (-0.55,-0.64,0.38,0.15,-52,2),( 0.50,-0.74,0.38,0.15, 50,1),
       (-0.12,-0.98,0.34,0.14,-84,0),( 0.08,-0.54,0.48,0.18,  5,1),
       (-0.72,-0.10,0.34,0.14, -8,2),( 0.68,-0.14,0.34,0.14, 12,0),
       ( 0.22,-1.06,0.30,0.12, 68,2),(-0.30,-1.12,0.30,0.12,-70,1))
def leafy(R,cx,cy,zb,depth,sc=1.0):
    px,py=R.iso(cx,cy,zb); S=R.S
    for dx,dy,rx,ry,rot,ci in _LEAF:
        X=px+dx*S*sc; Y=py+dy*S*sc; c=GRN[ci]
        R.emit(depth,zb+1.0,
            f'<ellipse cx="{X:.1f}" cy="{Y:.1f}" rx="{rx*S*sc:.1f}" ry="{ry*S*sc:.1f}" '
            f'fill="{c}" stroke="{shade(c,0.72)}" stroke-width="0.6" '
            f'transform="rotate({rot} {X:.1f} {Y:.1f})"/>')

class Room:
    def __init__(self, w, d):
        self.w=w; self.d=d; self.items=[]
        # scale so room fits ~ target
        span=(w+d)
        self.S=max(9.0,min(20.0, 620/(span*COS)))
        self.OX=0; self.OY=0
        self._fit()
    def iso_raw(self,x,y,z):
        return ((x-y)*COS*self.S,(x+y)*SIN*self.S - z*self.S)
    def _fit(self):
        pts=[self.iso_raw(x,y,z) for x in(-1,self.w+1) for y in(-1,self.d+1) for z in(0,10)]
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        pad=54
        self.OX=-min(xs)+pad; self.OY=-min(ys)+pad
        self.Wpx=(max(xs)-min(xs))+2*pad; self.Hpx=(max(ys)-min(ys))+2*pad
    def iso(self,x,y,z):
        px,py=self.iso_raw(x,y,z); return(px+self.OX,py+self.OY)
    def emit(self,depth,z,s): self.items.append((depth,z,s))
    def poly(self,coords,fill,stroke,sw,depth,z,op=1.0,dash=None):
        p=" ".join(f'{a:.1f},{b:.1f}' for a,b in coords)
        d=f' stroke-dasharray="{dash}"' if dash else ''
        self.emit(depth,z,f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"{d} opacity="{op}"/>')
    def floor(self,x0,y0,x1,y1,color,z=FLR_Z,stroke="#ffffff",sw=1.0,op=1.0,bias=-2e6):
        # the ground plane must paint before any vertical object, or it erases furniture
        c=[self.iso(x0,y0,z),self.iso(x1,y0,z),self.iso(x1,y1,z),self.iso(x0,y1,z)]
        self.poly(c,color,stroke,sw,bias+(x0+y0+x1+y1)/2,z,op)
    def box(self,x0,y0,x1,y1,z0,z1,color,op=1.0,edge=None,db=0.0):
        st=edge or shade(color,0.5); depth=db+(x0+y0+x1+y1)/2
        ef=[self.iso(x1,y0,z0),self.iso(x1,y1,z0),self.iso(x1,y1,z1),self.iso(x1,y0,z1)]
        self.poly(ef,shade(color,0.62),st,0.5,depth,z1,op)
        sf=[self.iso(x0,y1,z0),self.iso(x1,y1,z0),self.iso(x1,y1,z1),self.iso(x0,y1,z1)]
        self.poly(sf,shade(color,0.80),st,0.5,depth,z1,op)
        tf=[self.iso(x0,y0,z1),self.iso(x1,y0,z1),self.iso(x1,y1,z1),self.iso(x0,y1,z1)]
        self.poly(tf,color,st,0.5,depth+0.02,z1+0.001,op)
    def rbox(self,cx,cy,w,dp,z0,z1,ang,color,op=1.0,edge=None,db=0.0):
        """Box rotated `ang` degrees about the vertical axis through (cx,cy).
        box() is axis-aligned, so anything set at an angle to the room needs this."""
        import math as m
        a=m.radians(ang); ca,sa=m.cos(a),m.sin(a)
        hw,hd=w/2.0,dp/2.0
        W=[(cx+u*ca-v*sa, cy+u*sa+v*ca) for u,v in ((-hw,-hd),(hw,-hd),(hw,hd),(-hw,hd))]
        st=edge or shade(color,0.5); depth=db+cx+cy
        faces=[]
        for i in range(4):
            x0,y0=W[i]; x1,y1=W[(i+1)%4]
            nx,ny=(y1-y0),-(x1-x0)                  # outward normal of this edge
            if nx+ny<=0: continue                   # faces away from the camera
            sh=0.62 if abs(nx)>=abs(ny) else 0.80   # match box(): x-facing reads darker
            faces.append(((x0+x1+y0+y1)/2.0,
                          [self.iso(x0,y0,z0),self.iso(x1,y1,z0),self.iso(x1,y1,z1),self.iso(x0,y0,z1)],sh))
        faces.sort(key=lambda f:f[0])
        for k,(_fd,_pts,_sh) in enumerate(faces):
            self.poly(_pts,shade(color,_sh),st,0.5,depth-0.01+k*0.001,z1,op)
        self.poly([self.iso(x,y,z1) for x,y in W],color,st,0.5,depth+0.02,z1+0.001,op)

    def text(self,x,y,z,s,size=6,color="#3a4150",w="700",anchor="middle",op=1.0):
        px,py=self.iso(x,y,z)
        self.emit(9e9,9e9,f'<text x="{px:.1f}" y="{py:.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{w}" fill="{color}" text-anchor="{anchor}" opacity="{op}" style="letter-spacing:.2px">{s}</text>')
    def screen_text(self,px,py,s,size=13,color="#2a2f3a",w="800",anchor="start"):
        self.emit(9e9,9e9,f'<text x="{px}" y="{py}" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{w}" fill="{color}" text-anchor="{anchor}">{s}</text>')

    # ---- structure ----
    def shell(self, door="S", floor_col=C_FLOOR, wall_col=C_WALL):
        w,d=self.w,self.d
        self.box(0,0,w,d,0,FLR_Z,shade(floor_col,0.94),db=-3e6)  # slab (under everything)
        self.floor(0,0,w,d,floor_col)                        # floor face
        WH=9.0
        # Back (north) & left (west) walls tall; front/right low curb.
        # The tall walls paint before all room contents — they sort by centroid, so anything
        # in a far corner would otherwise be painted over by the wall behind it.
        self.box(0,-0.5,w,0,FLR_Z,FLR_Z+WH,wall_col,db=-1e6)
        self.box(-0.5,0,0,d,FLR_Z,FLR_Z+WH,wall_col,db=-1e6)
        self.box(0,d,w,d+0.5,FLR_Z,FLR_Z+0.6,shade(wall_col,0.9))
        self.box(w,0,w+0.5,d,FLR_Z,FLR_Z+0.6,shade(wall_col,0.9))
        self.door(door)
    def door(self, side):
        if side is None: return          # room draws its own entry (glass fronts)
        w,d=self.w,self.d; r=3.0
        if side=="S": cx,cy,a0=w-1.0, d-0.3, (180,270)   # swing into room from front-right
        elif side=="E": cx,cy,a0=w-0.3, d-1.0,(90,180)
        else: cx,cy,a0=1.0,d-0.3,(270,360)
        pts=[]
        import math as m
        for i in range(0,13):
            ang=m.radians(a0[0]+(a0[1]-a0[0])*i/12)
            pts.append(self.iso(cx+r*m.cos(ang), cy+r*m.sin(ang), FLR_Z+0.02))
        p=" ".join(f'{a:.1f},{b:.1f}' for a,b in pts)
        self.emit(9e8,9e8,f'<polyline points="{p}" fill="none" stroke="#b9bcc4" stroke-width="1" stroke-dasharray="3 2"/>')
    def swing_at(self, cx, cy, r, a0, a1):   # arbitrary door swing arc
        import math as m
        pts=[self.iso(cx+r*m.cos(m.radians(a0+(a1-a0)*i/12)), cy+r*m.sin(m.radians(a0+(a1-a0)*i/12)), FLR_Z+0.02) for i in range(13)]
        p=" ".join(f'{a:.1f},{b:.1f}' for a,b in pts)
        self.emit(9e8,9e8,f'<polyline points="{p}" fill="none" stroke="#b9bcc4" stroke-width="1.2" stroke-dasharray="3 2"/>')

    # ---- furniture primitives ----
    def desk(self,x,y,w=4.8,d=2.2,h=2.5): self.box(x,y,x+w,y+d,FLR_Z,FLR_Z+h,C_DESK)
    def ldesk(self,x,y):  # L-shaped exec desk, main along back
        self.box(x,y,x+5.0,y+2.2,FLR_Z,FLR_Z+2.5,C_DESK)
        self.box(x,y+2.2,x+2.2,y+4.6,FLR_Z,FLR_Z+2.5,C_DESK)
    def taskchair(self,x,y):
        self.box(x-0.8,y-0.8,x+0.8,y+0.8,FLR_Z,FLR_Z+1.6,C_TASK)
        self.box(x-0.8,y+0.5,x+0.8,y+0.9,FLR_Z,FLR_Z+2.8,shade(C_TASK,1.15))
    def guest(self,x,y):
        self.box(x-0.7,y-0.7,x+0.7,y+0.7,FLR_Z,FLR_Z+1.5,C_GUEST)
        self.box(x-0.7,y-0.7,x+0.7,y-0.4,FLR_Z,FLR_Z+2.4,shade(C_GUEST,0.9))
    def credenza(self,x,y,w=4.0,d=1.4): self.box(x,y,x+w,y+d,FLR_Z,FLR_Z+2.2,C_WOOD)
    def bookshelf(self,x,y,w=1.2,d=3.2): self.box(x,y,x+w,y+d,FLR_Z,FLR_Z+5.5,shade(C_WOOD,0.92))
    def sofa(self,x,y,w=5.5,d=2.2):
        self.box(x,y,x+w,y+d,FLR_Z,FLR_Z+1.4,C_SOFA)
        self.box(x,y,x+w,y+0.5,FLR_Z,FLR_Z+2.6,shade(C_SOFA,1.12))
        self.box(x,y,x+0.5,y+d,FLR_Z,FLR_Z+2.2,shade(C_SOFA,1.05))
        self.box(x+w-0.5,y,x+w,y+d,FLR_Z,FLR_Z+2.2,shade(C_SOFA,1.05))
    def coffee(self,x,y,w=3.2,d=1.8): self.box(x,y,x+w,y+d,FLR_Z,FLR_Z+1.1,C_TABLE)
    def rtable(self,cx,cy,r=2.2):  # round-ish meeting table (octagon)
        pts=[];
        import math as m
        for i in range(8):
            a=m.radians(45*i+22.5); pts.append((cx+r*m.cos(a),cy+r*m.sin(a)))
        top=[self.iso(px,py,FLR_Z+2.4) for px,py in pts]
        # simple: draw as box footprint
        self.box(cx-r,cy-r,cx+r,cy+r,FLR_Z,FLR_Z+2.4,C_TABLE)
    def conftable(self,x0,y0,x1,y1): self.box(x0,y0,x1,y1,FLR_Z,FLR_Z+2.4,C_TABLE)
    def plant(self,x,y):
        self.box(x-0.5,y-0.5,x+0.5,y+0.5,FLR_Z,FLR_Z+1.0,C_POT)
        self.box(x-0.9,y-0.9,x+0.9,y+0.9,FLR_Z+1.0,FLR_Z+1.1,C_PLANT)
        self.box(x-0.7,y-0.7,x+0.7,y+0.7,FLR_Z+1.1,FLR_Z+2.6,C_PLANT)
        self.box(x-0.4,y-0.4,x+0.4,y+0.4,FLR_Z+2.6,FLR_Z+3.3,shade(C_PLANT,1.1))
    def screen(self,x,w=4.0):  # wall TV on back wall
        self.box(x,0.05,x+w,0.2,FLR_Z+3.0,FLR_Z+6.0,C_SCREEN)
    def rug(self,x0,y0,x1,y1,color=C_RUG): self.floor(x0,y0,x1,y1,color,z=FLR_Z+0.01,stroke=shade(color,0.85),sw=0.8,bias=-1.9e6)  # above floor, below furniture
    def counter(self,x0,y0,x1,y1,h=3.0): self.box(x0,y0,x1,y1,FLR_Z,FLR_Z+h,C_COUNTER)
    def upper_cab(self,x0,y0,x1,y1): self.box(x0,y0,x1,y1,FLR_Z+5.0,FLR_Z+7.5,shade(C_WOOD,0.95))
    def glass(self,x0,y0,x1,y1,z0,z1):  # translucent glass-upper panel
        self.box(x0,y0,x1,y1,z0,z1,"#bfe0ea",op=0.32)
    def builtin_desk(self,x0,y0,x1,y1,h=3.2): self.box(x0,y0,x1,y1,FLR_Z,FLR_Z+h,C_DESK)

    # ---- dimension caption on floor ----
    def dims(self, wlabel, dlabel):
        w,d=self.w,self.d
        self.text(w/2, d+2.2, FLR_Z, wlabel, size=6.5, color="#9a8f78", w="700")
        self.text(w+2.4, d/2, FLR_Z, dlabel, size=6.5, color="#9a8f78", w="700")

    def render(self):
        self.items.sort(key=lambda t:(t[0],t[1]))
        body="\n".join(s for _,_,s in self.items)
        return (f'<svg viewBox="0 0 {self.Wpx:.0f} {self.Hpx:.0f}" xmlns="http://www.w3.org/2000/svg" '
                f'preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%">\n{body}\n</svg>')

# ===========================================================================
#  FURNITURE LAYOUTS PER OFFICE KIND
# ===========================================================================
def furnish(kind, R, key=None):
    """LAYOUT ONLY — fixed built-ins & architecture, no loose furniture."""
    w,d=R.w,R.d
    if kind=="reception":   # LOBBY: long built-in desk across upper third + walkway + curved entry
        R.builtin_desk(2.3, d*0.30, w-2.3, d*0.30+2.0, 3.2)      # full-width built-in desk
        R.text(w*0.5, d*0.30+1.0, FLR_Z+3.4, "BUILT-IN DESK", size=4.4, color="#7a5f3c", w="800")
        R.text(w*0.5, d*0.15, FLR_Z+0.05, "(behind desk)", size=4.0, color="#9a6a6f", w="600")
        R.text(w*0.55, d*0.82, FLR_Z+0.05, "LOBBY", size=5.4, color="#9a6a6f", w="800")
        R.text(1.9,d*0.70,FLR_Z+0.05,"open walkway ▸",size=5.0,color="#2f7d8c",w="700",anchor="start")
        R.text(w-7.0,d-1.8,FLR_Z+0.05,"◄ curved entry",size=4.6,color="#5b6270",w="700",anchor="start")
    elif kind=="break":     # kitchenette counter + island + storage behind wall
        R.counter(0.6,0.8,11.0,3.0,3.0)                          # built-in counter along back wall
        R.upper_cab(1.0,0.5,10.0,0.9)
        R.box(w*0.5-1.2,d*0.30,w*0.5+1.2,d*0.30+6.0,FLR_Z,FLR_Z+3.0,C_COUNTER)   # island
        R.box(w*0.5-0.9,d*0.30+2.2,w*0.5+0.9,d*0.30+3.6,FLR_Z+3.0,FLR_Z+3.2,"#8f96a0")  # sink inset
        R.text(w*0.5,d*0.30-0.8,FLR_Z+3.3,"ISLAND",size=4.8,color="#5b6270",w="800")
        R.text(1.7,d*0.55,FLR_Z+0.05,"storage behind wall ◂",size=4.4,color="#8f95a0",w="700",anchor="start")
    elif kind=="conference":   # long 18-person boardroom table (8 per side + 1 each end) + TV wall
        tx0,ty0,tx1,ty1 = 10.0, 7.6, 39.0, 12.4    # a touch wider
        # The table is one long box, so it sorts by its centroid depth. Chairs past that
        # midpoint would flip to the wrong side, so pin each row's depth either side of it.
        _CH="#9e3b32"                                         # red chairs
        TBL=(tx0+ty0+tx1+ty1)/2
        BEHIND, INFRONT = TBL-0.5, TBL+0.5
        def _cchair(cx,cy,back,target):
            db=target-(cx+cy)      # force sort order relative to the table
            # seat + a back TALLER than the table top so far-side chairs stay visible
            R.box(cx-0.75,cy-0.75,cx+0.75,cy+0.75,FLR_Z,FLR_Z+1.5,_CH,db=db)
            if   back=="N": R.box(cx-0.75,cy-0.75,cx+0.75,cy-0.40,FLR_Z,FLR_Z+3.6,shade(_CH,1.15),db=db)
            elif back=="S": R.box(cx-0.75,cy+0.40,cx+0.75,cy+0.75,FLR_Z,FLR_Z+3.6,shade(_CH,1.15),db=db)
            elif back=="W": R.box(cx-0.75,cy-0.75,cx-0.40,cy+0.75,FLR_Z,FLR_Z+3.6,shade(_CH,1.15),db=db)
            else:           R.box(cx+0.40,cy-0.75,cx+0.75,cy+0.75,FLR_Z,FLR_Z+3.6,shade(_CH,1.15),db=db)
        for k in range(6):                                       # 6 a side + 1 each end = 14
            cx=12.5+k*(36.5-12.5)/5
            _cchair(cx, ty0-1.35, "N", BEHIND)                   # far row: behind the table
            _cchair(cx, ty1+1.35, "S", INFRONT)                  # near row: in front of it
        _cchair(tx0-1.5,(ty0+ty1)/2,"W",BEHIND)                  # far end
        _cchair(tx1+1.5,(ty0+ty1)/2,"E",INFRONT)                 # near end
        R.box(tx0,ty0,tx1,ty1,FLR_Z,FLR_Z+2.4,"#5c4033")   # walnut table
        R.box(45.9,2.5,48.6,17.5,FLR_Z,FLR_Z+3.0,"#c9c2b6")                        # built-in counter, right (east) wall
        # ---- back wall: large TV, shelving either side, whiteboards outboard ----
        # every wall item shares one depth just in front of the wall; nudge to stack them
        NW=(0-0.5+w+0)/2
        def _wall(x0,x1,y1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(x0,0.05,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(NW+0.6+nudge)-((x0+0.05+x1+y1)/2))
        _wall(20.5,28.5,0.24,2.7,7.3,C_SCREEN)                   # TV — 8' wide × 4'6" tall
        SHELF_Z=(2.6,4.0,5.4,6.8)
        for _z in SHELF_Z:                                       # shelving flanking the TV
            _wall(13.0,18.8,0.85,_z,_z+0.18,"#7a5333")
            _wall(30.2,36.0,0.85,_z,_z+0.18,"#7a5333")
        for _bx0,_bx1 in ((4.0,11.6),(37.4,45.0)):               # whiteboards on the far side of each shelf unit
            _wall(_bx0,_bx1,0.16,2.4,7.4,"#7f8792")                            # frame
            _wall(_bx0+0.20,_bx1-0.20,0.22,2.58,7.22,"#fbfcfd",nudge=0.06)     # writing surface
        # decor on the shelves — kept sparse; a few small pieces, not a full display
        C_BOOK1="#7a5c48"; C_BOOK2="#4f6b7a"; C_TRINK="#c2a05a"
        def _thing(x0,x1,z0,h,col):
            R.box(x0,0.24,x1,0.68,FLR_Z+z0,FLR_Z+z0+h,col,db=(NW+0.9)-((x0+0.24+x1+0.68)/2))
        _DECOR_L=[[(0.5,1.2,0.80,C_BOOK1),(3.6,0.7,0.85,C_PLANT)],
                  [(2.4,0.8,0.50,C_TRINK)],
                  [(0.6,1.4,0.70,C_BOOK2)],
                  [(3.3,0.7,0.80,C_PLANT)]]
        _DECOR_R=[[(3.5,1.3,0.75,C_BOOK2)],
                  [(0.6,0.7,0.85,C_PLANT),(2.7,0.8,0.48,C_TRINK)],
                  [(3.6,0.8,0.52,C_TRINK)],
                  [(0.7,1.5,0.70,C_BOOK1)]]
        for _sx0,_dec in ((13.0,_DECOR_L),(30.2,_DECOR_R)):
            for _zi,_z in enumerate(SHELF_Z):
                for _off,_wd,_ht,_col in _dec[_zi]:
                    _thing(_sx0+_off,_sx0+_off+_wd,_z+0.18,_ht,_col)
        def _award(ax,z0):                                       # dark base + gold figure
            _thing(ax,ax+0.60,z0,0.14,"#3f444d")
            _thing(ax+0.16,ax+0.44,z0+0.14,0.62,"#c9a227")
        for _ax,_az in ((13.6,4.0),(13.8,6.8),(30.8,2.6),(30.8,5.4)):
            _award(_ax,_az+0.18)
        # on top of the built-in counter: books between bookends + a plant
        CTR=(45.9+2.5+48.6+17.5)/2      # counter depth; items on it must sort in front
        def _onctr(x0,y0,x1,y1,z0,z1,col):
            R.box(x0,y0,x1,y1,FLR_Z+z0,FLR_Z+z1,col,
                  db=(CTR+0.6+((y0+y1)/2)*0.02)-((x0+y0+x1+y1)/2))
        _onctr(46.5,4.90,48.1,5.08,3.0,3.95,"#6b7280")           # bookend
        for _i,(_h,_c) in enumerate(((0.85,C_BOOK1),(0.78,C_BOOK2),(0.88,"#8a5a4a"),
                                     (0.74,C_BOOK1),(0.82,C_BOOK2),(0.80,"#6e7f5c"))):
            _by=5.16+_i*0.33
            _onctr(46.6,_by,48.0,_by+0.27,3.0,3.0+_h,_c)         # books
        _onctr(46.5,7.20,48.1,7.38,3.0,3.95,"#6b7280")           # bookend
        _onctr(46.8,12.00,47.8,13.00,3.0,3.65,C_POT)             # plant — pot
        _onctr(46.55,11.75,48.05,13.25,3.65,4.15,C_PLANT)        # foliage
        _onctr(46.7,11.95,47.9,13.05,4.15,4.90,C_PLANT)
        # ---- left (west) wall: interior glass window into Raf's office next door ----
        # framed + mullioned + sill so it reads as a window, not a tint on the wall
        WW=(-0.5+0+0+d)/2         # west-wall depth; window parts sort in front of it
        def _wwin(y0,y1,x1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(-0.04,y0,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(WW+0.6+nudge)-((-0.04+y0+x1+y1)/2))
        _wwin(2.6,17.4,0.22,2.2,7.7,"#59616e")                      # frame
        _wwin(2.95,17.05,0.30,2.5,7.4,"#9fdcf0",op=0.85,nudge=0.06) # glazing
        for _my in (7.35,12.65):                                    # mullions
            _wwin(_my-0.10,_my+0.10,0.36,2.5,7.4,"#59616e",nudge=0.12)
        _wwin(2.6,17.4,0.62,1.95,2.2,"#aeb4bd",nudge=0.12)          # sill
        # caption on the open floor beside it — the window is near full-height, no clear wall above
    elif kind=="megan":     # Megan's office — window wall, 4 screens, standing desk + walking pad
        import math as _m
        NWD=(0-0.5+w+0)/2                    # north-wall depth
        WWD=(-0.5+0+0+d)/2                   # west-wall depth
        def _onN(x0,x1,y1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(x0,0.05,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(NWD+0.6+nudge)-((x0+0.05+x1+y1)/2))
        def _onW(y0,y1,x1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(-0.04,y0,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(WWD+0.6+nudge)-((-0.04+y0+x1+y1)/2))
        # RIGHT (north) wall = windows to outside. Banded like the real wall: solid below the
        # sill, grid of panes behind blinds, solid above the head — not floor-to-ceiling glass.
        _WB0,_WB1=2.7,7.3
        _onN(0.4,10.27,0.16,_WB0-0.16,_WB0,"#9aa2ad",nudge=0.04)            # sill
        _onN(0.4,10.27,0.16,_WB1,_WB1+0.16,"#9aa2ad",nudge=0.04)            # head
        _onN(0.4,10.27,0.22,_WB0,_WB1,"#e3ebf0",nudge=0.06)                 # panes, blinds down
        for _k in range(1,23):
            _bz=_WB0+0.2*_k
            if _bz<_WB1-0.06: _onN(0.55,10.12,0.24,_bz,_bz+0.06,"#ccd8df",nudge=0.08)   # blind slats
        for _mx in (0.4,3.69,6.98,10.27):
            _onN(_mx-0.07,_mx+0.07,0.30,_WB0,_WB1,"#9aa2ad",nudge=0.14)     # vertical mullions
        for _mz in (_WB0+1.53,_WB0+3.07):
            _onN(0.4,10.27,0.30,_mz-0.05,_mz+0.05,"#9aa2ad",nudge=0.14)     # horizontal mullions
        # LEFT (west) wall = solid: 2 × 2 screen array, generously spaced
        for _sy in (2.35,6.10):
            for _sz in (2.80,4.75):
                _onW(_sy,_sy+2.25,0.16,_sz,_sz+1.35,"#59616e",nudge=0.06)             # bezel
                _onW(_sy+0.09,_sy+2.16,0.22,_sz+0.09,_sz+1.26,"#222833",nudge=0.12)   # panel
        # wall planters — kept outboard of the screen array; they sit proud of the screens
        # so anything between the columns overlaps them
        def _wplant(cy,z0):
            _onW(cy-0.30,cy+0.30,0.44,z0,z0+0.46,C_POT,nudge=0.18)                    # pot
            _onW(cy-0.36,cy+0.36,0.48,z0+0.46,z0+0.56,shade(C_POT,0.82),nudge=0.19)   # rim
            leafy(R,0.22,cy,FLR_Z+z0+0.56,WWD+0.9,sc=0.85)
        _wplant(1.15,4.2); _wplant(9.5,3.6)
        # FRONT-RIGHT (east) wall = shared with reception: half glass over a solid knee wall.
        # Drawn as a framed partition (posts + rails, no filled pane) — a filled sheet on the
        # near side hazes over the whole room and you lose the interior.
        R.box(w,0,w+0.45,d,FLR_Z,FLR_Z+3.2,shade(C_PINK_W,0.90))        # solid knee wall
        R.box(w,0,w+0.45,d,FLR_Z+3.2,FLR_Z+3.45,"#8f96a0")              # sill rail
        R.box(w,0,w+0.45,d,FLR_Z+7.15,FLR_Z+7.4,"#8f96a0")              # head rail
        for _py in (0.0,d/2-0.11,d-0.22):                                # glazing posts
            R.box(w,_py,w+0.45,_py+0.22,FLR_Z+3.45,FLR_Z+7.15,"#8f96a0")
        # standing desk, centred in the room; walking pad in front of it
        R.box(3.2,3.4,5.3,7.2,FLR_Z+3.2,FLR_Z+3.5,C_DESK)                   # desk top
        R.box(3.5,3.75,5.0,4.05,FLR_Z,FLR_Z+3.2,"#6b7280")                  # T-legs at each end
        R.box(3.5,6.55,5.0,6.85,FLR_Z,FLR_Z+3.2,"#6b7280")
        R.box(5.4,4.2,7.4,6.6,FLR_Z,FLR_Z+0.32,"#3a4150")                   # walking pad deck
        R.box(5.6,4.3,7.2,6.5,FLR_Z+0.32,FLR_Z+0.40,"#22262e")              # belt
        # Laptop on the standing desk. db must clear the desk: the desk is one big box sorting
        # by its centroid, and at db=0.7 it painted straight over the vase.
        _LD=1.4
        R.box(3.70,4.95,4.48,6.05,FLR_Z+3.50,FLR_Z+3.56,"#cfd3d8",db=_LD)      # base 9" x 13"
        R.box(3.84,5.10,4.36,5.78,FLR_Z+3.56,FLR_Z+3.585,"#3a4048",db=_LD+0.1) # keyboard
        R.box(4.02,5.84,4.22,5.98,FLR_Z+3.56,FLR_Z+3.585,"#9aa2ad",db=_LD+0.1) # trackpad
        R.box(3.62,4.95,3.72,6.05,FLR_Z+3.56,FLR_Z+4.30,"#cfd3d8",db=_LD)      # lid
        R.box(3.70,5.03,3.78,5.97,FLR_Z+3.62,FLR_Z+4.24,"#20252c",db=_LD+0.2)  # screen
        # flowers in a vase — blush blooms on sage stems
        _vx,_vy=4.98,3.66                                                   # top-right corner of the desk
        R.box(_vx-0.20,_vy-0.20,_vx+0.20,_vy+0.20,FLR_Z+3.50,FLR_Z+4.02,"#cfd6da",db=_LD)
        for _fdx,_fdy,_fdz,_fc in ((-0.15,-0.10,0.60,"#d4788f"),(0.13,0.08,0.72,"#e3a9b8"),
                                   (-0.02,0.15,0.52,"#d4788f"),(0.17,-0.13,0.46,"#e3a9b8"),
                                   (-0.17,0.06,0.40,"#c9607a")):
            R.box(_vx+_fdx-0.04,_vy+_fdy-0.04,_vx+_fdx+0.04,_vy+_fdy+0.04,
                  FLR_Z+4.02,FLR_Z+4.02+_fdz,"#7f9478",db=_LD+0.1)             # stems
            R.box(_vx+_fdx-0.12,_vy+_fdy-0.12,_vx+_fdx+0.12,_vy+_fdy+0.12,
                  FLR_Z+4.02+_fdz,FLR_Z+4.02+_fdz+0.17,_fc,db=_LD+0.2)         # blooms
        # floral rug under the lounge end. Blooms ride just above the rug bias so the rug
        # doesn't paint over them, but furniture still lands on top.
        R.rug(1.85,1.85,8.85,8.85,"#e8d5d8")
        for _fx,_fy,_fc in ((2.60,2.60,"#d4788f"),(4.60,2.30,"#9fae9f"),(6.90,2.70,"#e3a9b8"),
                            (8.20,3.90,"#d4788f"),(2.35,4.40,"#e3a9b8"),(2.80,6.60,"#9fae9f"),
                            (8.40,6.30,"#c9607a"),(7.90,8.10,"#e3a9b8"),(4.10,8.30,"#d4788f"),
                            (6.20,8.40,"#9fae9f"),(2.45,8.20,"#e3a9b8"),(5.30,6.90,"#c9607a")):
            _RX,_RY=R.iso(_fx,_fy,FLR_Z+0.02)
            for _pk in range(5):
                _pa=_pk*72+18
                _ppx=_RX+0.15*R.S*_m.cos(_m.radians(_pa)); _ppy=_RY+0.15*R.S*_m.sin(_m.radians(_pa))
                R.emit(-1.85e6+_fx+_fy, FLR_Z+0.03,
                    f'<ellipse cx="{_ppx:.1f}" cy="{_ppy:.1f}" rx="{0.13*R.S:.1f}" ry="{0.075*R.S:.1f}" '
                    f'fill="{_fc}" transform="rotate({_pa} {_ppx:.1f} {_ppy:.1f})"/>')
            R.emit(-1.84e6+_fx+_fy, FLR_Z+0.04,
                f'<circle cx="{_RX:.1f}" cy="{_RY:.1f}" r="{0.06*R.S:.1f}" fill="#f4e2b0"/>')
        # accent chair, set at an angle to the room
        # Faces +u, turned in toward the room. Past about -25 deg the chair goes edge-on to
        # the fixed SE camera and flattens into an unreadable slab, so this is the limit.
        CHX,CHY,CHA=2.9,9.05,-18.0
        _cca,_csa=_m.cos(_m.radians(CHA)),_m.sin(_m.radians(CHA))
        def _L(u,v): return (CHX+u*_cca-v*_csa, CHY+u*_csa+v*_cca)
        C_UPH="#9fae9f"                                                     # sage
        _qx,_qy=_L(0,0);      R.rbox(_qx,_qy,1.75,1.85,FLR_Z+0.85,FLR_Z+1.45,CHA,C_UPH)   # seat
        _qx,_qy=_L(-0.87,0);  R.rbox(_qx,_qy,0.38,1.85,FLR_Z+1.45,FLR_Z+3.30,CHA,C_UPH)   # back
        for _av in (-0.92,0.92):                                                          # arms
            _qx,_qy=_L(0,_av); R.rbox(_qx,_qy,1.75,0.34,FLR_Z+1.45,FLR_Z+2.15,CHA,shade(C_UPH,0.95))
        for _lu,_lv in ((-0.72,-0.78),(0.72,-0.78),(-0.72,0.78),(0.72,0.78)):             # legs
            _qx,_qy=_L(_lu,_lv); R.rbox(_qx,_qy,0.18,0.18,FLR_Z,FLR_Z+0.85,CHA,"#7a5f3c")
    elif kind=="twaddle":   # Twaddle's — back-left solid wall carries the TV
        # Wall map, as you read the view:
        #   upper-left (BACK)  = conference side, SOLID -> TV
        #   upper-right        = windows to outside
        #   lower-left (near)  = the entry wall, all glass + door
        #   lower-right        = Megan's side, solid
        import math as _m
        NWD=(0-0.5+w+0)/2; WWD=(-0.5+0+0+d)/2
        def _onN(x0,x1,y1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(x0,0.05,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(NWD+0.6+nudge)-((x0+0.05+x1+y1)/2))
        def _onW(y0,y1,x1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(-0.04,y0,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(WWD+0.6+nudge)-((-0.04+y0+x1+y1)/2))
        # BACK (upper-left / west) = conference-side SOLID wall: TV over a shelf
        _onW(3.6,7.4,0.22,3.3,5.8,"#59616e",nudge=0.06)                     # TV bezel
        _onW(3.8,7.2,0.28,3.45,5.65,"#222833",nudge=0.12)                   # TV panel
        # tall skinny cabinet to the right of the TV — open shelves holding TABLETS on charge
        _WD="#8a6240"                                                      # brown millwork
        R.box(0.18,1.50,1.90,3.10,FLR_Z,FLR_Z+6.40,_WD)                    # carcass
        R.box(0.34,1.66,1.94,2.94,FLR_Z+0.34,FLR_Z+6.02,"#241d16")         # dark cavity
        for _sz in (1.42,2.54,3.66,4.78):
            R.box(0.34,1.66,1.98,2.94,FLR_Z+_sz,FLR_Z+_sz+0.10,shade(_WD,0.78))   # shelf boards
        # tablets stood on edge in a row, screens out
        for _si,_sz in enumerate((0.44,1.52,2.64,3.76,4.88)):
            _ty=1.78; _k=_si*3
            while _ty<2.84:
                R.box(0.50,_ty,1.30,_ty+0.09,FLR_Z+_sz,FLR_Z+_sz+0.78,"#2b3038",db=0.7)   # body
                R.box(0.56,_ty,1.24,_ty+0.10,FLR_Z+_sz+0.06,FLR_Z+_sz+0.72,"#59636f",db=0.8)  # screen
                _ty+=0.09+0.10; _k+=1
        R.box(1.66,2.18,1.78,2.42,FLR_Z+3.05,FLR_Z+3.45,"#c9ccd2")              # pull
        # small decor on the cabinet top
        R.box(0.50,1.70,1.35,2.20,FLR_Z+6.40,FLR_Z+6.64,"#7a5c48")              # notepads
        R.box(0.53,1.74,1.31,2.16,FLR_Z+6.64,FLR_Z+6.83,"#4f6b7a")
        R.box(0.60,2.38,0.75,2.92,FLR_Z+6.40,FLR_Z+7.12,"#5b6270")              # small framed photo
        R.box(0.72,2.44,0.80,2.86,FLR_Z+6.48,FLR_Z+7.04,"#c2a05a")
        R.box(1.00,2.42,1.38,2.80,FLR_Z+6.40,FLR_Z+6.80,"#9aa2ad")              # trinket
        # two canvases stacked one above the other, left of the TV
        for _az0,_az1,_col in ((5.30,6.70,"#7f9478"),(2.80,4.20,"#8a6a4a")):
            _onW(8.50,9.90,0.17,_az0,_az1,shade(_col,0.68),nudge=0.06)      # wrapped edge
            _onW(8.56,9.84,0.21,_az0+0.06,_az1-0.06,_col,nudge=0.12)        # canvas face
        # UPPER-RIGHT (north) = windows to outside, banded like the real wall
        _WB0,_WB1=2.7,7.3
        _onN(0.4,10.27,0.16,_WB0-0.16,_WB0,"#9aa2ad",nudge=0.04)            # sill
        _onN(0.4,10.27,0.16,_WB1,_WB1+0.16,"#9aa2ad",nudge=0.04)            # head
        _onN(0.4,10.27,0.22,_WB0,_WB1,"#e3ebf0",nudge=0.06)                 # panes, blinds down
        for _k in range(1,23):
            _bz=_WB0+0.2*_k
            if _bz<_WB1-0.06: _onN(0.55,10.12,0.24,_bz,_bz+0.06,"#ccd8df",nudge=0.08)   # slats
        for _mx in (0.4,3.69,6.98,10.27):
            _onN(_mx-0.07,_mx+0.07,0.30,_WB0,_WB1,"#9aa2ad",nudge=0.14)     # vertical mullions
        for _mz in (_WB0+1.53,_WB0+3.07):
            _onN(0.4,10.27,0.30,_mz-0.05,_mz+0.05,"#9aa2ad",nudge=0.14)     # horizontal mullions
        # NEAR-LEFT (south) = the entry wall, all glass + door. Translucent because it sits
        # between the camera and the room.
        R.box(0,d,w,d+0.38,FLR_Z+0.5,FLR_Z+8.0,"#9fdcf0",op=0.22)           # glazing
        R.box(0,d,w,d+0.42,FLR_Z,FLR_Z+0.5,"#59616e",op=0.8)                # base rail
        R.box(0,d,w,d+0.42,FLR_Z+8.0,FLR_Z+8.2,"#59616e",op=0.8)            # head rail
        for _mx2 in (0.0,3.5,6.9,10.5):
            R.box(_mx2,d,_mx2+0.15,d+0.42,FLR_Z+0.5,FLR_Z+8.0,"#59616e",op=0.8)   # mullions/stiles
        R.box(2.55,d,2.70,d+0.46,FLR_Z+0.5,FLR_Z+7.3,"#59616e",op=0.9)      # door stiles
        R.box(0.20,d,0.35,d+0.46,FLR_Z+0.5,FLR_Z+7.3,"#59616e",op=0.9)
        R.box(2.15,d,2.35,d+0.5,FLR_Z+3.05,FLR_Z+3.55,"#c9ccd2",op=0.95)    # pull
        R.swing_at(2.6,d-0.3,2.5,262,332)
        # L-desk — main run in front of the desk owner, return wrapping round to his side
        R.box(5.0,3.0,7.2,8.2,FLR_Z+2.2,FLR_Z+2.5,"#9a7048")                   # main
        R.box(7.2,3.0,9.4,4.8,FLR_Z+2.2,FLR_Z+2.5,"#9a7048")                   # return
        for _ex,_ey in ((5.3,3.3),(6.9,3.3),(5.3,7.9),(6.9,7.9),(9.1,3.3),(9.1,4.5)):
            R.box(_ex-0.18,_ey-0.18,_ex+0.18,_ey+0.18,FLR_Z,FLR_Z+2.2,"#6b7280")   # legs
        # seating: Twaddle backing the TV wall, two chairs across for interviews / meetings
        def _seat(cx,cy,ang,col,bh=2.4):
            R.rbox(cx,cy,1.45,1.45,FLR_Z,FLR_Z+1.5,ang,col)
            _bx=cx-0.58*_m.cos(_m.radians(ang)); _by=cy-0.58*_m.sin(_m.radians(ang))
            R.rbox(_bx,_by,0.30,1.45,FLR_Z,FLR_Z+bh,ang,shade(col,1.12))
        _seat(8.2,5.9,180,"#6b4c35",2.7)                                       # owner: back to the far wall, facing the TV
        _seat(3.5,4.8,0,"#9aa89a"); _seat(3.5,7.0,0,"#9aa89a")                  # across the desk
        # iMac on the desk, screen turned toward the owner
        _ix,_iy=6.0,5.9
        R.box(_ix-0.28,_iy-0.42,_ix+0.28,_iy+0.42,FLR_Z+2.5,FLR_Z+2.58,"#c9ccd2")   # foot
        R.box(_ix-0.05,_iy-0.10,_ix+0.05,_iy+0.10,FLR_Z+2.58,FLR_Z+3.05,"#c9ccd2")  # stand
        R.box(_ix-0.06,_iy-0.95,_ix+0.06,_iy+0.95,FLR_Z+3.05,FLR_Z+4.35,"#d8dbe0")  # bezel
        R.box(_ix+0.02,_iy-0.86,_ix+0.09,_iy+0.86,FLR_Z+3.14,FLR_Z+4.24,"#222833")  # screen
        R.box(_ix+0.65,_iy-0.55,_ix+1.15,_iy+0.55,FLR_Z+2.5,FLR_Z+2.58,"#e6e8ec")   # keyboard
    elif kind=="jd":        # JD's office. Walls per Megan: 1 = exterior windows, 2 = solid
                            # (TV wall), 3 = all-glass front w/ door to the open space, 4 = solid
        import math as _m
        NWD=(0-0.5+w+0)/2; WWD=(-0.5+0+0+d)/2
        def _onN(x0,x1,y1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(x0,0.05,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(NWD+0.6+nudge)-((x0+0.05+x1+y1)/2))
        def _onW(y0,y1,x1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(-0.04,y0,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(WWD+0.6+nudge)-((-0.04+y0+x1+y1)/2))
        # WALL 1 (back-left) = windows to outside. Banded: solid below the sill, grid of panes
        # behind blinds, solid above the head — not floor-to-ceiling glass.
        _WB0,_WB1=2.7,7.3
        _onW(0.4,13.10,0.16,_WB0-0.16,_WB0,"#9aa2ad",nudge=0.04)            # sill
        _onW(0.4,13.10,0.16,_WB1,_WB1+0.16,"#9aa2ad",nudge=0.04)            # head
        _onW(0.4,13.10,0.22,_WB0,_WB1,"#e3ebf0",nudge=0.06)                 # panes, blinds down
        for _k in range(1,23):
            _bz=_WB0+0.2*_k
            if _bz<_WB1-0.06: _onW(0.55,12.95,0.24,_bz,_bz+0.06,"#ccd8df",nudge=0.08)
        for _my in (0.4,4.63,8.87,13.10):
            _onW(_my-0.07,_my+0.07,0.30,_WB0,_WB1,"#9aa2ad",nudge=0.14)     # vertical mullions
        for _mz in (_WB0+1.53,_WB0+3.07):
            _onW(0.4,13.10,0.30,_mz-0.05,_mz+0.05,"#9aa2ad",nudge=0.14)     # horizontal mullions
        # WALL 2 (back-right) = SOLID: TV, canvases, tall cabinet
        _onN(4.20,8.60,0.22,3.30,5.80,"#59616e",nudge=0.06)                 # TV bezel
        _onN(4.40,8.40,0.28,3.45,5.65,"#222833",nudge=0.12)                 # TV panel
        for _az0,_az1,_col in ((5.30,6.70,"#33486b"),(2.80,4.20,"#8b95a3")):
            _onN(9.40,11.00,0.17,_az0,_az1,shade(_col,0.68),nudge=0.06)     # wrapped edge
            _onN(9.46,10.94,0.21,_az0+0.06,_az1-0.06,_col,nudge=0.12)       # canvas face
        # OPEN shelving left of the TV on wall 2 — executive walnut, no back panel, a
        # restrained mix of books, an award, a framed photo and a plant. Same open build as
        # Bas's but in JD's navy/grey palette (no Lego, no bright primaries).
        _SHW="#6b5540"
        R.box(1.30,0.34,1.55,1.16,FLR_Z,FLR_Z+6.30,_SHW)                   # left post
        R.box(3.65,0.34,3.90,1.16,FLR_Z,FLR_Z+6.30,_SHW)                   # right post
        for _sz in (0.10,1.35,2.55,3.75,4.95,6.15):
            R.box(1.30,0.34,3.90,1.20,FLR_Z+_sz,FLR_Z+_sz+0.12,shade(_SHW,0.92))  # shelf boards
        def _books(x0,z,n,seed=0):
            _pal=("#2f4260","#7d8894","#c5ccd4","#3a4a5e","#dde3ea","#4a6b96","#8a95a3","#5c6b7d")
            _bx=x0
            for _i in range(n):
                _bw=0.13+0.03*((_i+seed)%3); _bh=0.60+0.05*(((_i+seed)*2)%4)
                R.box(_bx,0.55,_bx+_bw,1.08,FLR_Z+z,FLR_Z+z+_bh,_pal[(_i+seed)%len(_pal)],db=0.8)
                _bx+=_bw+0.03
        def _stack(x0,z):
            R.box(x0,0.52,x0+0.80,1.10,FLR_Z+z,FLR_Z+z+0.13,"#3a4a5e",db=0.8)
            R.box(x0+0.05,0.55,x0+0.72,1.06,FLR_Z+z+0.13,FLR_Z+z+0.25,"#8a95a3",db=0.8)
        def _trinket(x0,z,col,w=0.34,h=0.42):
            R.box(x0,0.62,x0+w,1.00,FLR_Z+z,FLR_Z+z+h,col,db=0.8)
        def _photo(x0,z):
            R.box(x0,0.92,x0+0.54,1.02,FLR_Z+z,FLR_Z+z+0.62,"#c5ccd4",db=0.8)        # frame
            R.box(x0+0.06,0.94,x0+0.48,1.00,FLR_Z+z+0.08,FLR_Z+z+0.54,"#46586e",db=0.85)  # photo
        def _award(cx,z):
            R.box(cx-0.14,0.74,cx+0.14,1.00,FLR_Z+z,FLR_Z+z+0.09,"#3a3a3a",db=0.8)   # base
            R.box(cx-0.10,0.78,cx+0.10,0.96,FLR_Z+z+0.09,FLR_Z+z+0.28,"#c9a53e",db=0.82)  # stem
            R.box(cx-0.16,0.72,cx+0.16,1.02,FLR_Z+z+0.28,FLR_Z+z+0.46,"#d9b84e",db=0.84)  # cup bowl
        def _pot(cx,z,sc=0.6):
            R.box(cx-0.17,0.66,cx+0.17,1.00,FLR_Z+z,FLR_Z+z+0.28,"#7d8894",db=0.8)   # pot (grey, not terracotta)
            leafy(R,cx,0.83,FLR_Z+z+0.28,4.6,sc)                                      # foliage
        _books(1.66,0.22,6,0)                                                        # bottom: a full run of books
        _stack(1.70,1.47); _award(3.10,1.47)                                         # book stack + award
        _photo(1.70,2.67); _pot(3.15,2.67)                                           # framed photo + plant
        _books(1.66,3.87,4,3); _trinket(3.10,3.87,"#46586e",0.32,0.46)              # books + a muted box
        _pot(1.90,5.07,0.5); _books(2.55,5.07,3,1)                                   # small plant + a few books
        # credenza sitting under the windows on wall 1 (tucks below the 2'8" sill)
        _CRD="#2f4260"                                                             # navy
        R.box(0.18,3.50,2.00,9.50,FLR_Z,FLR_Z+2.50,_CRD)
        for _rz in (0.85,1.70):
            R.box(2.00,3.50,2.04,9.50,FLR_Z+_rz,FLR_Z+_rz+0.10,shade(_CRD,0.72))   # door rails
        for _py in (5.00,6.50,8.00):
            R.box(2.00,_py-0.10,2.06,_py+0.10,FLR_Z+1.20,FLR_Z+1.45,"#c9ccd2")     # pulls
        R.box(0.55,4.10,1.45,4.80,FLR_Z+2.50,FLR_Z+2.76,"#3d5175")                 # books on top
        R.box(0.58,4.14,1.42,4.76,FLR_Z+2.76,FLR_Z+2.96,"#8b95a3")
        R.box(0.60,6.10,0.75,6.80,FLR_Z+2.50,FLR_Z+3.18,"#5b6270")                 # framed photo
        R.box(0.72,6.16,0.80,6.74,FLR_Z+2.58,FLR_Z+3.10,"#c2a05a")
        R.box(0.75,8.10,1.20,8.60,FLR_Z+2.50,FLR_Z+2.92,"#9aa2ad")                 # trinket
        # WALL 3 (front-right) = all-glass office front with the door onto the open space.
        # Translucent: it sits between the camera and the room.
        R.box(w,0,w+0.38,d,FLR_Z+0.5,FLR_Z+8.0,"#9fdcf0",op=0.22)           # glazing
        R.box(w,0,w+0.42,d,FLR_Z,FLR_Z+0.5,"#59616e",op=0.8)                # base rail
        R.box(w,0,w+0.42,d,FLR_Z+8.0,FLR_Z+8.2,"#59616e",op=0.8)            # head rail
        for _py in (0.0,4.40,8.80,13.34):
            R.box(w,_py,w+0.42,_py+0.16,FLR_Z+0.5,FLR_Z+8.0,"#59616e",op=0.8)      # mullions
        for _py in (9.60,12.34):
            R.box(w,_py,w+0.46,_py+0.16,FLR_Z+0.5,FLR_Z+7.3,"#59616e",op=0.9)      # door stiles
        R.box(w,11.86,w+0.50,12.06,FLR_Z+3.05,FLR_Z+3.55,"#c9ccd2",op=0.95)        # pull
        R.swing_at(11.90,9.80,2.70,92,168)
        # L-desk — main run in front of the owner, return wrapping round to his side
        _DSK="#4e5766"                                                      # graphite, to suit navy/grey
        R.box(3.60,5.40,9.60,7.60,FLR_Z+2.2,FLR_Z+2.5,_DSK)                 # main
        R.box(7.60,7.60,9.60,9.60,FLR_Z+2.2,FLR_Z+2.5,_DSK)                 # return
        for _ex,_ey in ((3.9,5.7),(3.9,7.3),(9.3,5.7),(9.3,7.3),(9.3,9.3),(7.9,9.3)):
            R.box(_ex-0.18,_ey-0.18,_ex+0.18,_ey+0.18,FLR_Z,FLR_Z+2.2,"#8b95a3")   # brushed-metal legs
        # seating: JD backing wall 4, facing the TV on wall 2; two chairs across for interviews
        def _seat(cx,cy,ang,col,bh=2.4):
            R.rbox(cx,cy,1.45,1.45,FLR_Z,FLR_Z+1.5,ang,col)
            _bx=cx-0.58*_m.cos(_m.radians(ang)); _by=cy-0.58*_m.sin(_m.radians(ang))
            R.rbox(_bx,_by,0.30,1.45,FLR_Z,FLR_Z+bh,ang,shade(col,1.12))
        _seat(6.40,8.70,-90,C_TASK,2.7)                                     # JD
        _seat(5.00,3.90,90,C_GUEST); _seat(7.80,3.90,90,C_GUEST)            # across the desk
        # iMac on the desk, screen turned toward the owner. db pushes it past the desk:
        # the desk is one big box sorting by its centroid, which lands behind things on it.
        _ix,_iy=6.40,6.50; _MD=0.7
        R.box(_ix-0.42,_iy-0.28,_ix+0.42,_iy+0.28,FLR_Z+2.5,FLR_Z+2.58,"#c9ccd2",db=_MD)  # foot
        R.box(_ix-0.10,_iy-0.05,_ix+0.10,_iy+0.05,FLR_Z+2.58,FLR_Z+3.05,"#c9ccd2",db=_MD) # stand
        R.box(_ix-0.95,_iy-0.06,_ix+0.95,_iy+0.06,FLR_Z+3.05,FLR_Z+4.35,"#d8dbe0",db=_MD) # bezel
        R.box(_ix-0.86,_iy+0.02,_ix+0.86,_iy+0.09,FLR_Z+3.14,FLR_Z+4.24,"#222833",db=_MD) # screen
        R.box(_ix-0.55,_iy+0.60,_ix+0.55,_iy+1.05,FLR_Z+2.5,FLR_Z+2.58,"#e6e8ec",db=_MD)  # keyboard
    elif kind=="bas":       # Bas's office. Same kit + wall layout as JD (Megan): 1 = exterior
                            # windows, 2 = solid TV wall, 3 = all-glass front + door, 4 = solid.
                            # Room is 3.5' shallower than JD's, so the depth-run walls are shorter.
        import math as _m
        NWD=(0-0.5+w+0)/2; WWD=(-0.5+0+0+d)/2
        def _onN(x0,x1,y1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(x0,0.05,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(NWD+0.6+nudge)-((x0+0.05+x1+y1)/2))
        def _onW(y0,y1,x1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(-0.04,y0,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(WWD+0.6+nudge)-((-0.04+y0+x1+y1)/2))
        def _brick(x0,y0,x1,y1,z0,ztop,col,nx,ny,db=0.0):
            """A flat Lego brick: body + nx x ny round studs. db pushes the whole brick in
            front of whatever it sits on — the credenza sorts by its centroid and would
            otherwise paint over the brick's base and leave the studs floating."""
            R.box(x0,y0,x1,y1,FLR_Z+z0,FLR_Z+ztop,col,db=db)
            _hs=0.09; _spx=(x1-x0)/nx; _spy=(y1-y0)/ny; _r=min(_spx,_spy)*0.30
            for _si in range(nx):
                _cx=x0+_spx*(_si+0.5)
                for _sj in range(ny):
                    _cy=y0+_spy*(_sj+0.5)
                    R.box(_cx-_r,_cy-_r,_cx+_r,_cy+_r,FLR_Z+ztop,FLR_Z+ztop+_hs,shade(col,1.06),db=db+0.3)
                    _px,_py=R.iso(_cx,_cy,FLR_Z+ztop+_hs)
                    R.emit(db+_cx+_cy+0.7, ztop+_hs+0.02,
                        f'<ellipse cx="{_px:.1f}" cy="{_py:.1f}" rx="{_r*R.S:.1f}" ry="{_r*R.S*0.5:.1f}" '
                        f'fill="{shade(col,1.13)}" stroke="{shade(col,0.72)}" stroke-width="0.5"/>')
        # WALL 1 (back-left) = windows to outside. Banded: solid below the sill, grid of panes
        # behind blinds, solid above the head — not floor-to-ceiling glass.
        _WB0,_WB1=2.7,7.3
        _onW(0.4,9.6,0.16,_WB0-0.16,_WB0,"#9aa2ad",nudge=0.04)            # sill
        _onW(0.4,9.6,0.16,_WB1,_WB1+0.16,"#9aa2ad",nudge=0.04)            # head
        _onW(0.4,9.6,0.22,_WB0,_WB1,"#e3ebf0",nudge=0.06)                 # panes, blinds down
        for _k in range(1,23):
            _bz=_WB0+0.2*_k
            if _bz<_WB1-0.06: _onW(0.55,9.45,0.24,_bz,_bz+0.06,"#ccd8df",nudge=0.08)
        for _my in (0.4,3.47,6.53,9.6):
            _onW(_my-0.07,_my+0.07,0.30,_WB0,_WB1,"#9aa2ad",nudge=0.14)     # vertical mullions
        for _mz in (_WB0+1.53,_WB0+3.07):
            _onW(0.4,9.6,0.30,_mz-0.05,_mz+0.05,"#9aa2ad",nudge=0.14)     # horizontal mullions
        # WALL 2 (back-right) = SOLID: TV, canvases, tall cabinet
        _onN(4.20,8.60,0.22,3.30,5.80,"#59616e",nudge=0.06)                 # TV bezel
        _onN(4.40,8.40,0.28,3.45,5.65,"#222833",nudge=0.12)                 # TV panel
        # framed Lego mosaic instead of canvases — bright primaries, Bas's thing
        _onN(9.28,11.02,0.16,2.66,6.44,"#2b3038",nudge=0.06)               # frame
        _onN(9.40,10.90,0.20,2.78,6.32,"#11151b",nudge=0.10)               # backing
        _LM=("#d21f26","#f6c018","#0a6cff","#00a94f","#ff7a1c","#e83a8c","#2ab7c4","#7b4fa3")
        _mi=0
        for _mr in range(4):
            for _mc in range(3):
                _mtx=9.46+_mc*0.50; _mtz=2.86+_mr*0.85
                _onN(_mtx,_mtx+0.42,0.24,_mtz,_mtz+0.72,_LM[_mi%len(_LM)],nudge=0.14)
                _mi+=1
        # OPEN shelving left of the TV on wall 2 — light wood, no back panel (the wall shows
        # through), an eclectic mix of books, trinkets, plants and one small build. Deliberately
        # unlike JD's enclosed grey bookcase.
        _SHW="#b98a5e"
        R.box(1.30,0.34,1.55,1.16,FLR_Z,FLR_Z+6.30,_SHW)                   # left post
        R.box(3.65,0.34,3.90,1.16,FLR_Z,FLR_Z+6.30,_SHW)                   # right post
        for _sz in (0.10,1.35,2.55,3.75,4.95,6.15):
            R.box(1.30,0.34,3.90,1.20,FLR_Z+_sz,FLR_Z+_sz+0.12,shade(_SHW,0.9))   # shelf boards
        def _books(x0,z,n,seed=0):
            _pal=("#d21f26","#f6c018","#0a6cff","#00a94f","#ff7a1c","#e83a8c","#2ab7c4","#7b4fa3")
            _bx=x0
            for _i in range(n):
                _bw=0.13+0.03*((_i+seed)%3); _bh=0.58+0.05*(((_i+seed)*2)%4)
                R.box(_bx,0.55,_bx+_bw,1.08,FLR_Z+z,FLR_Z+z+_bh,_pal[(_i+seed)%len(_pal)],db=0.8)
                _bx+=_bw+0.03
        def _stack(x0,z):
            R.box(x0,0.52,x0+0.78,1.10,FLR_Z+z,FLR_Z+z+0.13,"#c98a3a",db=0.8)
            R.box(x0+0.05,0.55,x0+0.70,1.06,FLR_Z+z+0.13,FLR_Z+z+0.25,"#3a6ea5",db=0.8)
        def _trinket(x0,z,col,w=0.32,h=0.40):
            R.box(x0,0.62,x0+w,1.00,FLR_Z+z,FLR_Z+z+h,col,db=0.8)
        def _photo(x0,z):
            R.box(x0,0.92,x0+0.52,1.02,FLR_Z+z,FLR_Z+z+0.60,"#5b6270",db=0.8)         # frame
            R.box(x0+0.06,0.94,x0+0.46,1.00,FLR_Z+z+0.07,FLR_Z+z+0.53,"#dbe3ea",db=0.85)  # photo
        def _pot(cx,z,sc=0.6):
            R.box(cx-0.17,0.66,cx+0.17,1.00,FLR_Z+z,FLR_Z+z+0.28,"#c96a3c",db=0.8)    # pot
            leafy(R,cx,0.83,FLR_Z+z+0.28,4.6,sc)                                       # foliage
        _books(1.68,0.22,4,0);  _trinket(2.95,0.22,"#00a94f"); _trinket(3.34,0.22,"#f6c018",0.26,0.34)
        _brick(1.66,0.50,2.42,1.05,1.47,1.85,"#d21f26",2,3,db=0.9); _stack(2.78,1.47)   # small Lego build + books
        _photo(1.70,2.67); _pot(3.10,2.67)                                              # photo + plant
        _books(1.68,3.87,3,2); _trinket(2.82,3.87,"#0a6cff"); _trinket(3.24,3.87,"#e83a8c",0.30,0.50)
        _trinket(1.78,5.07,"#7b4fa3",0.36,0.42); _trinket(2.44,5.07,"#2ab7c4",0.28,0.52); _pot(3.22,5.07,0.5)
        # credenza sitting under the windows on wall 1 (tucks below the 2'8" sill)
        _CRD="#6f685c"                                                             # warm taupe
        R.box(0.18,3.50,2.00,9.50,FLR_Z,FLR_Z+2.50,_CRD)
        for _rz in (0.85,1.70):
            R.box(2.00,3.50,2.04,9.50,FLR_Z+_rz,FLR_Z+_rz+0.10,shade(_CRD,0.72))   # door rails
        for _py in (5.00,6.50,8.00):
            R.box(2.00,_py-0.10,2.06,_py+0.10,FLR_Z+1.20,FLR_Z+1.45,"#c9ccd2")     # pulls
        _brick(0.62,3.95,1.80,5.60,2.50,2.92,"#d21f26",2,4,db=2.5)                 # red 2x4, flat
        _brick(0.74,6.00,1.66,6.96,2.50,2.85,"#f6c018",2,2,db=2.5)                 # yellow 2x2
        _brick(0.66,7.35,1.78,8.75,2.50,2.95,"#0a6cff",2,3,db=2.5)                 # blue 2x3
        # WALL 3 (front-right) = all-glass office front with the door onto the open space.
        # Translucent: it sits between the camera and the room.
        R.box(w,0,w+0.38,d,FLR_Z+0.5,FLR_Z+8.0,"#9fdcf0",op=0.22)           # glazing
        R.box(w,0,w+0.42,d,FLR_Z,FLR_Z+0.5,"#59616e",op=0.8)                # base rail
        R.box(w,0,w+0.42,d,FLR_Z+8.0,FLR_Z+8.2,"#59616e",op=0.8)            # head rail
        for _py in (0.0,3.28,6.56,9.84):
            R.box(w,_py,w+0.42,_py+0.16,FLR_Z+0.5,FLR_Z+8.0,"#59616e",op=0.8)      # mullions
        for _py in (6.86,9.60):
            R.box(w,_py,w+0.46,_py+0.16,FLR_Z+0.5,FLR_Z+7.3,"#59616e",op=0.9)      # door stiles
        R.box(w,9.12,w+0.50,9.32,FLR_Z+3.05,FLR_Z+3.55,"#c9ccd2",op=0.95)          # pull
        R.swing_at(11.90,7.06,2.70,92,168)
        # L-desk — main run in front of the owner, return wrapping round to his side
        _DSK="#4e5766"                                                      # graphite, to suit navy/grey
        R.box(3.60,5.40,9.60,7.60,FLR_Z+2.2,FLR_Z+2.5,_DSK)                 # main
        R.box(7.60,7.60,9.60,9.60,FLR_Z+2.2,FLR_Z+2.5,_DSK)                 # return
        for _ex,_ey in ((3.9,5.7),(3.9,7.3),(9.3,5.7),(9.3,7.3),(9.3,9.3),(7.9,9.3)):
            R.box(_ex-0.18,_ey-0.18,_ex+0.18,_ey+0.18,FLR_Z,FLR_Z+2.2,"#8b95a3")   # brushed-metal legs
        # seating: JD backing wall 4, facing the TV on wall 2; two chairs across for interviews
        def _seat(cx,cy,ang,col,bh=2.4):
            R.rbox(cx,cy,1.45,1.45,FLR_Z,FLR_Z+1.5,ang,col)
            _bx=cx-0.58*_m.cos(_m.radians(ang)); _by=cy-0.58*_m.sin(_m.radians(ang))
            R.rbox(_bx,_by,0.30,1.45,FLR_Z,FLR_Z+bh,ang,shade(col,1.12))
        _seat(6.40,8.70,-90,"#d21f26",2.7)                                   # Bas, bright red
        _seat(5.00,3.90,90,"#0a6cff"); _seat(7.80,3.90,90,"#00a94f")         # blue + green guests
        # iMac on the desk, screen turned toward the owner. db pushes it past the desk:
        # the desk is one big box sorting by its centroid, which lands behind things on it.
        _ix,_iy=6.40,6.50; _MD=0.7
        R.box(_ix-0.42,_iy-0.28,_ix+0.42,_iy+0.28,FLR_Z+2.5,FLR_Z+2.58,"#c9ccd2",db=_MD)  # foot
        R.box(_ix-0.10,_iy-0.05,_ix+0.10,_iy+0.05,FLR_Z+2.58,FLR_Z+3.05,"#c9ccd2",db=_MD) # stand
        R.box(_ix-0.95,_iy-0.06,_ix+0.95,_iy+0.06,FLR_Z+3.05,FLR_Z+4.35,"#d8dbe0",db=_MD) # bezel
        R.box(_ix-0.86,_iy+0.02,_ix+0.86,_iy+0.09,FLR_Z+3.14,FLR_Z+4.24,"#222833",db=_MD) # screen
        R.box(_ix-0.55,_iy+0.60,_ix+0.55,_iy+1.05,FLR_Z+2.5,FLR_Z+2.58,"#e6e8ec",db=_MD)  # keyboard
    elif kind=="maud":      # Maud's corner office. Walls per Megan: 1 & 2 solid, 3 = glass entry,
                            # 4 = window / exterior. Brown / grey / navy scheme.
        import math as _m
        NWD=(0-0.5+w+0)/2; WWD=(-0.5+0+0+d)/2
        _WD="#8a6240"; _GY="#a8b2bc"                       # brown millwork, LIGHT grey shelving
        _DK="#4a5260"                                      # desk: darker, or it blends with the shelf
        def _onN(x0,x1,y1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(x0,0.05,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(NWD+0.6+nudge)-((x0+0.05+x1+y1)/2))
        def _onW(y0,y1,x1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(-0.04,y0,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(WWD+0.6+nudge)-((-0.04+y0+x1+y1)/2))
        # WALL 2 (back-right) = solid: TV
        _onN(3.20,7.60,0.22,3.30,5.80,"#59616e",nudge=0.06)                 # TV bezel
        _onN(3.40,7.40,0.28,3.45,5.65,"#222833",nudge=0.12)                 # TV panel
        # WALL 1 (back-left) = solid: navy credenza + two canvases
        # skinny corner shelf in the wall 1 / wall 2 corner — keeps the floor clear
        R.box(0.18,0.30,1.05,3.60,FLR_Z,FLR_Z+3.10,_GY)                     # carcass
        R.box(0.30,0.42,1.09,3.48,FLR_Z+0.24,FLR_Z+2.86,shade(_GY,0.55))    # open cavity
        for _sz in (1.02,1.94):
            R.box(0.30,0.42,1.11,3.48,FLR_Z+_sz,FLR_Z+_sz+0.09,_GY)         # shelf boards
        R.box(0.42,0.70,0.95,1.55,FLR_Z+0.32,FLR_Z+0.94,"#7a5c48",db=0.5)   # books
        R.box(0.42,2.10,0.95,2.90,FLR_Z+1.24,FLR_Z+1.82,"#3d5175",db=0.5)
        R.box(0.46,0.60,0.61,1.24,FLR_Z+3.10,FLR_Z+3.72,"#5b6270",db=0.5)   # framed photo
        R.box(0.56,0.66,0.64,1.18,FLR_Z+3.18,FLR_Z+3.64,"#c2a05a",db=0.6)
        for _fi,_fc in enumerate(("#2f4260","#f2f2f2","#c0392b")):          # tricolore
            R.box(0.50,3.02+_fi*0.13,0.90,3.02+_fi*0.13+0.12,FLR_Z+3.10,FLR_Z+3.74,_fc,db=0.6)
        _vx,_vy=0.68,1.90                                                   # flowers on the shelf
        R.box(_vx-0.18,_vy-0.18,_vx+0.18,_vy+0.18,FLR_Z+3.10,FLR_Z+3.58,"#e8dfe0",db=0.5)
        for _fdx,_fdy,_fdz,_fc in ((-0.12,-0.08,0.50,"#d4788f"),(0.11,0.07,0.60,"#e3a9b8"),
                                   (-0.02,0.12,0.44,"#c9607a")):
            R.box(_vx+_fdx-0.04,_vy+_fdy-0.04,_vx+_fdx+0.04,_vy+_fdy+0.04,
                  FLR_Z+3.58,FLR_Z+3.58+_fdz,"#7f9478",db=0.6)              # stems
            R.box(_vx+_fdx-0.10,_vy+_fdy-0.10,_vx+_fdx+0.10,_vy+_fdy+0.10,
                  FLR_Z+3.58+_fdz,FLR_Z+3.58+_fdz+0.15,_fc,db=0.7)          # blooms
        # Wall 1 is a long blank run, so the art is a collage: one large canvas with smaller
        # ones scattered round it. The large one carries an Eiffel Tower — Maud is French.
        _onW(7.10,10.50,0.15,3.40,7.00,"#8f8378",nudge=0.06)                # large canvas — frame
        _onW(7.18,10.42,0.20,3.48,6.92,"#ece4d8",nudge=0.12)                # canvas ground
        # The tower is drawn as a flat silhouette on the canvas face. Stacked boxes read as a
        # blocky ziggurat — the flare is a curve, so it needs a polygon.
        def _onface(pts,col,dep):
            _pp=" ".join('%.1f,%.1f'%R.iso(0.21,_fy,FLR_Z+_fz) for _fy,_fz in pts)
            R.emit(dep,7.0,f'<polygon points="{_pp}" fill="{col}"/>')
        _TC,_TZ0,_TH=8.80,3.86,2.84                                         # centre, base, height
        def _hw(t): return 0.58*(1.0-t)**2.6+0.020                          # half-width up the flare
        _tow=[(_TC-_hw(_i/16.0),_TZ0+(_i/16.0)*_TH) for _i in range(17)]
        _tow+=[(_TC+_hw(_i/16.0),_TZ0+(_i/16.0)*_TH) for _i in range(16,-1,-1)]
        _onface(_tow,"#5b5348",WWD+0.78)                                    # silhouette
        for _pz,_phw in ((4.34,0.42),(5.26,0.21)):                          # platforms
            _onface([(_TC-_phw,_pz),(_TC+_phw,_pz),(_TC+_phw,_pz+0.10),(_TC-_phw,_pz+0.10)],
                    "#5b5348",WWD+0.79)
        _arch=[(_TC-0.33,_TZ0)]+[(_TC-0.33*_m.cos(_m.pi*_i/14.0),_TZ0+0.40*_m.sin(_m.pi*_i/14.0))
                                 for _i in range(15)]+[(_TC+0.33,_TZ0)]
        _onface(_arch,"#ece4d8",WWD+0.80)                                   # arch cut at the base
        for _sy0,_sy1,_sz0,_sz1,_sc in ((5.20,6.35,5.55,6.70,"#c98d96"),(5.20,6.25,3.85,4.85,"#3d5175"),
                                        (5.45,6.35,2.45,3.30,"#9fae9f"),(11.25,12.40,5.40,6.55,"#3d5175"),
                                        (11.25,12.15,3.75,4.70,"#c98d96"),(11.40,12.45,2.40,3.30,"#e8dfd6")):
            _onW(_sy0,_sy1,0.15,_sz0,_sz1,shade(_sc,0.62),nudge=0.06)       # small canvases
            _onW(_sy0+0.07,_sy1-0.07,0.20,_sz0+0.06,_sz1-0.06,_sc,nudge=0.12)
        # WALL 3 (front-right) = all-glass front with the entry door. Translucent — it sits
        # between the camera and the room.
        # Only the first bay is glass — it is the only stretch that meets the open office.
        # The rest of this wall is SHARED with the neighbouring office, so it is solid.
        _G3=5.70
        R.box(w,_G3,w+0.42,d,FLR_Z,FLR_Z+8.60,shade(WALL_COL.get(key,C_WALL),0.92),op=0.40)  # solid
        R.box(w,0,w+0.38,_G3,FLR_Z+0.5,FLR_Z+8.0,"#9fdcf0",op=0.20)         # glazing
        R.box(w,0,w+0.42,_G3,FLR_Z,FLR_Z+0.5,"#59616e",op=0.8)              # base rail
        R.box(w,0,w+0.42,_G3,FLR_Z+8.0,FLR_Z+8.2,"#59616e",op=0.8)          # head rail
        for _py in (0.0,_G3-0.16):
            R.box(w,_py,w+0.42,_py+0.16,FLR_Z+0.5,FLR_Z+8.0,"#59616e",op=0.8)      # jambs
        for _py in (2.20,4.94):
            R.box(w,_py,w+0.46,_py+0.16,FLR_Z+0.5,FLR_Z+7.3,"#59616e",op=0.9)      # door stiles
        R.box(w,4.50,w+0.50,4.70,FLR_Z+3.05,FLR_Z+3.55,"#c9ccd2",op=0.95)          # pull
        R.swing_at(w-0.10,2.40,2.70,95,168)
        # WALL 4 (front-left) = window / exterior. Banded, translucent for the same reason.
        _WB0,_WB1=2.7,7.3
        R.box(0,d,w,d+0.42,FLR_Z,FLR_Z+_WB0,shade(WALL_COL.get(key,C_WALL),0.92),op=0.42)  # below sill
        R.box(0,d,w,d+0.42,FLR_Z+_WB0,FLR_Z+_WB0+0.16,"#9aa2ad",op=0.85)    # sill
        R.box(0,d,w,d+0.38,FLR_Z+_WB0+0.16,FLR_Z+_WB1,"#e3ebf0",op=0.34)    # panes, blinds down
        for _k in range(1,21):
            _bz=_WB0+0.16+0.2*_k
            if _bz<_WB1-0.06: R.box(0.14,d,w-0.14,d+0.40,FLR_Z+_bz,FLR_Z+_bz+0.06,"#ccd8df",op=0.34)
        for _mx in (0.0,3.42,6.86,10.28):
            R.box(_mx,d,_mx+0.14,d+0.42,FLR_Z+_WB0+0.16,FLR_Z+_WB1,"#9aa2ad",op=0.85)   # mullions
        R.box(0,d,w,d+0.42,FLR_Z+_WB1,FLR_Z+_WB1+0.16,"#9aa2ad",op=0.85)    # head
        # L-desk in the working half, brown wood on bronze legs
        R.box(4.50,4.00,6.70,9.20,FLR_Z+2.2,FLR_Z+2.5,_DK)            # main
        R.box(2.50,4.00,4.50,6.00,FLR_Z+2.2,FLR_Z+2.5,_DK)            # return
        for _ex,_ey in ((4.8,4.3),(6.4,4.3),(4.8,8.9),(6.4,8.9),(2.8,4.3),(2.8,5.7)):
            R.box(_ex-0.18,_ey-0.18,_ex+0.18,_ey+0.18,FLR_Z,FLR_Z+2.2,"#8b95a3")   # legs
        def _seat(cx,cy,ang,col,bh=2.4):
            R.rbox(cx,cy,1.45,1.45,FLR_Z,FLR_Z+1.5,ang,col)
            _bx=cx-0.58*_m.cos(_m.radians(ang)); _by=cy-0.58*_m.sin(_m.radians(ang))
            R.rbox(_bx,_by,0.30,1.45,FLR_Z,FLR_Z+bh,ang,shade(col,1.12))
        _seat(3.50,7.20,0,"#2f4260",2.7)                                    # Maud, facing wall 3
        _seat(8.10,5.60,180,"#3d5175"); _seat(8.10,8.20,180,"#3d5175")      # two across the desk
        # iMac — db pushes it past the desk, which sorts by its centroid and would cover it
        _ix,_iy=5.60,7.20; _MD=0.7
        R.box(_ix-0.28,_iy-0.42,_ix+0.28,_iy+0.42,FLR_Z+2.5,FLR_Z+2.58,"#c9ccd2",db=_MD)  # foot
        R.box(_ix-0.05,_iy-0.10,_ix+0.05,_iy+0.10,FLR_Z+2.58,FLR_Z+3.05,"#c9ccd2",db=_MD) # stand
        R.box(_ix-0.07,_iy-0.95,_ix+0.07,_iy+0.95,FLR_Z+3.05,FLR_Z+4.35,"#d8dbe0",db=_MD) # monitor back
        R.box(_ix-0.10,_iy-0.88,_ix-0.06,_iy+0.88,FLR_Z+3.12,FLR_Z+4.28,"#20252c",db=_MD+0.1) # screen, facing her
        R.box(_ix-0.95,_iy-0.55,_ix-0.45,_iy+0.55,FLR_Z+2.5,FLR_Z+2.58,"#e6e8ec",db=_MD)  # keyboard
        # baby play pen down by the window
        _PEN="#f0e4e6"; _px0,_py0,_px1,_py1=0.40,11.20,4.40,14.80    # soft white pen, toward wall 1
        R.rug(_px0+0.14,_py0+0.14,_px1-0.14,_py1-0.14,"#f2dfe3")            # blush mat
        for _cx,_cy in ((_px0,_py0),(_px1-0.16,_py0),(_px0,_py1-0.16),(_px1-0.16,_py1-0.16)):
            R.box(_cx,_cy,_cx+0.16,_cy+0.16,FLR_Z,FLR_Z+2.20,_PEN)          # corner posts
        for _s in ((_px0,_py0,_px1,_py0+0.10),(_px0,_py1-0.10,_px1,_py1),
                   (_px0,_py0,_px0+0.10,_py1),(_px1-0.10,_py0,_px1,_py1)):
            R.box(_s[0],_s[1],_s[2],_s[3],FLR_Z+0.18,FLR_Z+2.02,"#e2e7ea",op=0.32)  # mesh
            R.box(_s[0],_s[1],_s[2],_s[3],FLR_Z+2.02,FLR_Z+2.20,_PEN)               # top rail
            R.box(_s[0],_s[1],_s[2],_s[3],FLR_Z,FLR_Z+0.18,_PEN)                    # bottom rail
        # rocking chair angled toward the window
        _rx,_ry,_ra=6.60,13.00,-105                                         # facing the room; we see its back
        R.rbox(_rx,_ry,1.55,1.50,FLR_Z+0.62,FLR_Z+1.42,_ra,"#8a6240")       # seat
        R.rbox(_rx,_ry,1.38,1.32,FLR_Z+1.42,FLR_Z+1.60,_ra,"#e3a9b8")       # blush cushion
        _bx=_rx-0.60*_m.cos(_m.radians(_ra)); _by=_ry-0.60*_m.sin(_m.radians(_ra))
        R.rbox(_bx,_by,0.26,1.50,FLR_Z+0.62,FLR_Z+3.30,_ra,shade("#8a6240",1.12))   # tall back
        for _off in (-0.60,0.60):
            _sx=_rx-_off*_m.sin(_m.radians(_ra)); _sy=_ry+_off*_m.cos(_m.radians(_ra))
            R.rbox(_sx,_sy,1.80,0.14,FLR_Z,FLR_Z+0.24,_ra,"#6b4c35")        # rockers
            R.rbox(_sx,_sy,0.14,0.14,FLR_Z+0.24,FLR_Z+0.66,_ra,"#6b4c35")   # legs
    elif kind=="raf":       # Raf's office. Walls per Megan: 1 & 2 solid, 3 = glass shared with
                            # the conference room, 4 = glass with the entry door. Red is his colour.
        import math as _m
        NWD=(0-0.5+w+0)/2; WWD=(-0.5+0+0+d)/2
        _RD="#9e3b32"; _WN="#5c4033"; _WD2="#7a5333"        # red, walnut, mid walnut
        def _onN(x0,x1,y1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(x0,0.05,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(NWD+0.6+nudge)-((x0+0.05+x1+y1)/2))
        def _onW(y0,y1,x1,z0,z1,col,op=1.0,nudge=0.0):
            R.box(-0.04,y0,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(WWD+0.6+nudge)-((-0.04+y0+x1+y1)/2))
        # WALL 2 (back-right) = solid: corner bookcase, mini fridge, decor collage
        _BC="#9aa2ac"
        def _case(x0,y0,x1,y1,seed,inset=0.40,cav=0.94):
            """A run of bookcase, open face SOUTH at y1 (the camera can't see a west face).
            `inset` is the carcass frame, `cav` how deep the shelves cut in — a leg running
            along wall 3 is narrow and deep, so both differ from a leg along wall 2."""
            R.box(x0,y0,x1,y1,FLR_Z,FLR_Z+6.40,_BC)                         # carcass
            _cy0=y1-cav
            R.box(x0+inset,_cy0,x1-inset,y1+0.02,FLR_Z+0.36,FLR_Z+5.96,"#20272f")    # cavity
            for _sz in (1.42,2.54,3.66,4.78):
                R.box(x0+inset,_cy0,x1-inset,y1+0.06,FLR_Z+_sz,FLR_Z+_sz+0.10,"#6b7580")
            _BK=("#c5ccd4","#9e3b32","#a9b2bd","#7a5333","#dde3ea","#c0533f","#93a0ae","#5c4033")
            for _si,_sz in enumerate((0.46,1.52,2.64,3.76,4.88)):
                _bx=x0+inset+0.08; _k=_si*4+seed; _run=x1-inset-0.06
                while _bx<_run:
                    _bw=0.14+0.04*(_k%3); _bh=0.72+0.055*((_k*3)%5)
                    if _bx+_bw>_run: break
                    R.box(_bx,y1-0.80,_bx+_bw,y1+0.08,FLR_Z+_sz,FLR_Z+_sz+_bh,_BK[_k%len(_BK)],db=0.7)
                    _bx+=_bw+0.03; _k+=1
        _case(16.60,0.18,18.86,1.24,0)                                      # leg along wall 2
        # The wall-3 return is kept shallow on purpose: it sits nearer the camera than the
        # wall-2 leg, so a deep one would legitimately occlude most of the books beside it.
        _case(18.86,0.18,19.84,1.70,3,inset=0.11,cav=0.95)                  # leg along wall 3
        R.box(0.22,0.20,1.92,1.90,FLR_Z,FLR_Z+3.40,_RD)                     # mini fridge, walls 1/2 corner
        R.box(1.92,0.32,1.96,1.80,FLR_Z+1.55,FLR_Z+1.65,shade(_RD,0.7))     # fridge door split
        R.box(1.84,1.82,1.98,1.94,FLR_Z+2.40,FLR_Z+2.90,"#c9ccd2")          # handle
        # decor collage behind the desk — one anchor piece with smaller ones clustered round it
        for _x0,_x1,_z0,_z1,_c in ((8.60,11.00,3.30,6.30,_RD),(11.30,12.70,4.95,6.30,"#7a5333"),
                                   (11.30,12.70,3.30,4.75,"#c0533f"),(13.00,14.60,5.20,6.30,"#a9b2bd"),
                                   (13.00,13.95,3.30,4.95,"#7a5333"),(14.10,14.60,3.30,4.95,"#c5ccd4")):
            _onN(_x0,_x1,0.15,_z0,_z1,shade(_c,0.62),nudge=0.06)
            _onN(_x0+0.07,_x1-0.07,0.20,_z0+0.07,_z1-0.07,_c,nudge=0.12)
        # WALL 1 (back-left) = solid: a large collage of art filling the run
        for _y0,_y1,_z0,_z1,_c in ((7.60,12.40,3.70,7.20,_RD),                     # anchor
                                   (4.80,7.00,5.45,7.20,"#7a5333"),(4.80,7.00,3.70,5.05,"#a9b2bd"),
                                   (2.40,4.20,4.60,6.40,"#c0533f"),(2.40,4.20,3.15,4.45,"#7a5333"),
                                   (8.60,10.60,2.20,3.20,"#a9b2bd"),(11.00,13.00,2.20,3.20,"#c5ccd4")):
            _onW(_y0,_y1,0.17,_z0,_z1,shade(_c,0.68),nudge=0.06)
            _onW(_y0+0.07,_y1-0.07,0.21,_z0+0.07,_z1-0.07,_c,nudge=0.12)
        # TV on the wall 1 end nearest the sitting table
        _onW(13.70,18.00,0.16,3.25,5.95,"#2b3038",nudge=0.06)               # bezel
        _onW(13.86,17.84,0.21,3.38,5.82,"#0f1319",nudge=0.12)               # screen
        # WALL 3 (front-right) = glass shared with the conference room. Translucent — it is
        # between the camera and the room.
        # Same band and mullions as the window drawn on the conference side of this wall
        # (y2.6-17.4, z2.2-7.7, mullions at 7.35 / 12.65) so the two rooms agree.
        R.box(w,0,w+0.42,d,FLR_Z,FLR_Z+8.60,shade(WALL_COL.get(key,C_WALL),0.92),op=0.34)  # wall
        R.box(w,2.60,w+0.46,17.40,FLR_Z+1.95,FLR_Z+2.20,"#aeb4bd",op=0.85)  # sill
        R.box(w,2.60,w+0.44,17.40,FLR_Z+7.70,FLR_Z+7.95,"#aeb4bd",op=0.85)  # head
        R.box(w,2.95,w+0.40,17.05,FLR_Z+2.50,FLR_Z+7.40,"#9fdcf0",op=0.24)  # glazing
        for _py in (2.60,7.35,12.65,17.20):
            R.box(w,_py,w+0.44,_py+0.20,FLR_Z+2.20,FLR_Z+7.70,"#59616e",op=0.8)    # mullions
        # WALL 4 (front-left) = glass with the entry door
        R.box(0,d,w,d+0.36,FLR_Z+0.5,FLR_Z+8.0,"#9fdcf0",op=0.18)           # glazing
        R.box(0,d,w,d+0.40,FLR_Z,FLR_Z+0.5,"#59616e",op=0.75)               # base rail
        R.box(0,d,w,d+0.40,FLR_Z+8.0,FLR_Z+8.2,"#59616e",op=0.75)           # head rail
        for _mx in (0.0,6.55,13.10,19.84):
            R.box(_mx,d,_mx+0.16,d+0.40,FLR_Z+0.5,FLR_Z+8.0,"#59616e",op=0.75)     # mullions
        for _mx in (14.20,16.94):
            R.box(_mx,d,_mx+0.16,d+0.44,FLR_Z+0.5,FLR_Z+7.3,"#59616e",op=0.9)      # door stiles
        R.box(16.50,d,16.70,d+0.48,FLR_Z+3.05,FLR_Z+3.55,"#c9ccd2",op=0.95)        # pull
        R.swing_at(14.40,d-0.10,2.70,188,258)
        # L-desk in walnut — main run in front of Raf, return wrapping his side
        R.box(7.20,5.20,14.20,7.60,FLR_Z+2.2,FLR_Z+2.5,_WN)                 # main
        R.box(12.00,2.80,14.20,5.20,FLR_Z+2.2,FLR_Z+2.5,_WN)                # return
        for _ex,_ey in ((7.6,5.6),(7.6,7.2),(13.8,5.6),(13.8,7.2),(12.4,3.2),(13.8,3.2)):
            R.box(_ex-0.18,_ey-0.18,_ex+0.18,_ey+0.18,FLR_Z,FLR_Z+2.2,"#6b5a49")   # legs
        def _seat(cx,cy,ang,col,bh=2.4,db=0.0):
            R.rbox(cx,cy,1.45,1.45,FLR_Z,FLR_Z+1.5,ang,col,db=db)
            _bx=cx-0.58*_m.cos(_m.radians(ang)); _by=cy-0.58*_m.sin(_m.radians(ang))
            R.rbox(_bx,_by,0.30,1.45,FLR_Z,FLR_Z+bh,ang,shade(col,1.12),db=db)
        _seat(10.20,3.90,90,_RD,2.7)                                        # Raf, back to wall 2
        _seat(8.80,9.20,-90,_RD); _seat(12.20,9.20,-90,_RD)                 # two across the desk
        # iMac — db clears the desk, which sorts by its centroid and would paint over it
        _ix,_iy=10.60,6.40; _MD=1.4
        R.box(_ix-0.28,_iy-0.42,_ix+0.28,_iy+0.42,FLR_Z+2.5,FLR_Z+2.58,"#c9ccd2",db=_MD)  # foot
        R.box(_ix-0.05,_iy-0.10,_ix+0.05,_iy+0.10,FLR_Z+2.58,FLR_Z+3.05,"#c9ccd2",db=_MD) # stand
        R.box(_ix-0.95,_iy-0.07,_ix+0.95,_iy+0.07,FLR_Z+3.05,FLR_Z+4.35,"#d8dbe0",db=_MD) # back
        R.box(_ix-0.86,_iy-0.10,_ix+0.86,_iy-0.06,FLR_Z+3.14,FLR_Z+4.24,"#222833",db=_MD+0.1) # screen
        R.box(_ix-0.55,_iy+0.60,_ix+0.55,_iy+1.05,FLR_Z+2.5,FLR_Z+2.58,"#e6e8ec",db=_MD)  # keyboard
        # walking pad — right-hand end of wall 2, behind the desk
        R.box(14.60,1.30,16.40,3.70,FLR_Z,FLR_Z+0.32,"#3a4150")             # deck
        R.box(14.75,1.42,16.25,3.58,FLR_Z+0.32,FLR_Z+0.40,"#22262e")        # belt
        # small couch on wall 1, toward the wall 2 end
        _SOF="#5a5f68"
        R.box(0.25,2.80,2.95,8.20,FLR_Z,FLR_Z+0.55,shade(_SOF,0.75))        # plinth
        R.box(0.25,2.80,1.05,8.20,FLR_Z,FLR_Z+2.90,_SOF)                    # back panel
        R.box(0.25,2.80,2.95,3.48,FLR_Z,FLR_Z+1.95,shade(_SOF,0.92))        # arm, wall-2 end
        R.box(0.25,7.52,2.95,8.20,FLR_Z,FLR_Z+1.95,shade(_SOF,0.92))        # arm, far end
        for _cy0,_cy1 in ((3.54,5.46),(5.54,7.46)):
            R.box(1.08,_cy0,2.88,_cy1,FLR_Z+0.55,FLR_Z+1.42,shade(_SOF,1.16),db=0.5)  # seat
            R.box(1.00,_cy0,1.62,_cy1,FLR_Z+1.42,FLR_Z+2.78,shade(_SOF,1.06),db=0.4)  # back
        for _py in (4.10,6.20):
            R.box(1.58,_py,2.16,_py+0.92,FLR_Z+1.42,FLR_Z+2.28,_RD,db=1.1)  # red throw pillows
        # Oval meeting table, seats 6. Drawn as a pair of stacked ellipse polygons — the box
        # primitive can't do a curve; the lower one peeking out reads as the table edge.
        _tcx,_tcy,_tra,_trb=6.20,15.20,2.60,1.70
        _oval=[(_tcx+_tra*_m.cos(2*_m.pi*_i/48.0),_tcy+_trb*_m.sin(2*_m.pi*_i/48.0)) for _i in range(48)]
        _od=_tcx+_tcy
        for _zz,_cc,_dd in ((2.22,shade(_WD2,0.62),_od+0.30),(2.42,_WD2,_od+0.32)):
            _pp=" ".join('%.1f,%.1f'%R.iso(_ox,_oy,FLR_Z+_zz) for _ox,_oy in _oval)
            R.emit(_dd,_zz,f'<polygon points="{_pp}" fill="{_cc}" stroke="{shade(_WD2,0.5)}" stroke-width="0.6"/>')
        R.box(_tcx-0.34,_tcy-0.34,_tcx+0.34,_tcy+0.34,FLR_Z,FLR_Z+2.22,"#6b5a49")   # pedestal
        R.box(_tcx-0.90,_tcy-0.90,_tcx+0.90,_tcy+0.90,FLR_Z,FLR_Z+0.16,"#6b5a49")   # base plate
        _TBL=_od+0.32                                                       # pin chairs either side
        for _cx,_cy,_ca,_front in ((2.70,15.20,0,False),(9.70,15.20,180,True),
                                   (4.80,12.80,90,False),(7.60,12.80,90,False),
                                   (4.80,17.50,-90,True),(7.60,17.50,-90,True)):
            _tgt=_TBL+(0.5 if _front else -0.5)
            _seat(_cx,_cy,_ca,_RD,db=_tgt-(_cx+_cy))
    elif kind=="open":      # Open office. Per O'Brien sheet A2.01 the 3 structural pillars sit
                            # on the centreline; everything else is open floor awaiting design.
        for _px in OPEN_PILLARS_FT:
            R.box(_px-0.8,R.d/2-0.8,_px+0.8,R.d/2+0.8,FLR_Z,FLR_Z+9.0,"#aab0b9")
    elif kind=="long":      # room 1: walls 1/2/4 solid, wall 3 all glass with the entry
        classroom(R,TRAINING_VIBE["w-comb"],screen_wall=2)
        glass_front(R,3)
    elif kind=="wide":      # rooms 11/12: wall 2 is exterior glass, so the screen moves
                            # to wall 1; walls 1/3 solid, wall 4 the glass entry
        classroom(R,TRAINING_VIBE.get(key,TRAINING_VIBE["s-comb1"]),screen_wall=1)
        ext_windows_n(R)
        glass_front(R,4)
    elif kind=="interview":   # offices 2/7/8 — JD-style interview kit, no credenza
        interview_office(R, windows=(key!="w-3"))   # office 2 is interior: no windows, wall 1 solid
    # every other room = empty architectural shell (walls + door + dimensions only)
    elif kind=="break":
        R.counter(0.6,0.8,0.6+10.0,0.8+2.2,3.0)  # counter along back
        R.upper_cab(1.0,0.5,9.0,0.9)
        R.counter(0.8,0.8,3.0,0.8,3.0)
        # tables
        for tx in (w*0.35, w*0.72):
            for ty in (d*0.55,):
                R.box(tx-1.6,ty-1.6,tx+1.6,ty+1.6,FLR_Z,FLR_Z+2.4,C_TABLE)
                R.guest(tx-2.6,ty); R.guest(tx+2.6,ty); R.guest(tx,ty-2.6); R.guest(tx,ty+2.6)
        R.plant(w-1.3,d-1.3)

# ===========================================================================
#  CATALOG
# ===========================================================================
CATALOG=[
  ("w-comb","West · Training Room","10'6\" × 20'","long",10.5,20.0,"Training room — classroom setup","Screen · 12 chairs · posters",False),
  ("w-3","West · Office","10'6\" × 10'5\"","interview",10.5,10.42,"Interview office","L-desk · iMac · 2 guest · TV · open shelf · glass front",False),
  ("w-4","Maud's Office (corner)","10'5\" × 17'5\"","maud",10.42,17.42,"Maud's corner office","L-desk · 2 guest · play pen · rocking chair · TV",False),
  ("n-large","Raf's Office","20' × 20'","raf",20.0,20.0,"Raf's office","L-desk · iMac · walking pad · 2 guest · bookcase · mini fridge · oval table",False),
  ("e-1","Twaddle's Office","10'8\" × 10'8\"","twaddle",10.67,10.67,"Twaddle's office","L-desk · 2 guest chairs · TV · glass entrance",False),
  ("e-2","Claude Room / Megan's","10'8\" × 10'8\"","megan",10.67,10.67,"Megan's office / Claude room","4 screens · standing desk · walking pad · window wall",False),
  ("s-1","South · Office 1","12' × 10'6\"","interview",12.0,10.5,"Interview office","L-desk · iMac · 2 guest · TV · open shelf · glass front",False),
  ("s-2","South · Office 2","12' × 10'6\"","interview",12.0,10.5,"Interview office","L-desk · iMac · 2 guest · TV · open shelf · glass front",False),
  ("s-3","Bas's office","12' × 10'","bas",12.0,10.0,"Bas's office","L-desk · iMac · 2 guest · TV · bookcase · credenza · glass front",False),
  ("s-4","JD's Office","12' × 13'6\"","jd",12.0,13.5,"JD's office","L-desk · 2 guest chairs · TV · credenza · window wall",False),
  ("s-comb1","South · Training Room A","24' × 9'","wide","24.0","9.0","Training room — classroom setup","Screen · 12 chairs · posters",False),
  ("s-comb2","South · Training Room B","24' × 10'6\"","wide",24.0,10.5,"Training room — classroom setup","Screen · 12 chairs · posters",False),
  ("conf","Large Conference","20' × 49'","conference",49.0,20.0,"Main boardroom","Boardroom table · 14 seats · TV wall",False),
  ("recep","Reception / Lobby","21'10\" × 13'6\"","reception",21.83,13.5,"Front-of-house lobby — built-in desk, glass upper, open walkway entry","Built-in desk · glass upper · lounge · open walkway",False),
  ("break","Break Room","15'6\" × 20'","break",20.0,15.5,"Staff kitchen + seating","Kitchenette · 2 tables · 8 seats",False),
  ("open","Open Office","34'9\" × 96'","open",96.0,34.75,"Open floor — 3 fixed structural pillars; A2.01 calls for (28) 6' × 6' workstations","3 structural pillars · open floor",False),
]


def interview_office(R, windows=True, desk_col="#59616e", shelf_col="#7a6144", owner_col="#3f5170", guest_col=C_GUEST):
    """Generic interview office: L-desk facing the TV wall, iMac, TWO guest chairs across for
    interviews, a TV and a compact open shelf. Windows on wall 1, glass front + door on wall 3,
    solid walls 2 & 4. NO credenza. Local frame, so it fits every room that shares this layout."""
    import math as _m
    w,d=R.w,R.d
    NWD=(0-0.5+w+0)/2; WWD=(-0.5+0+0+d)/2
    def _onN(x0,x1,y1,z0,z1,col,op=1.0,nudge=0.0):
        R.box(x0,0.05,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(NWD+0.6+nudge)-((x0+0.05+x1+y1)/2))
    def _onW(y0,y1,x1,z0,z1,col,op=1.0,nudge=0.0):
        R.box(-0.04,y0,x1,y1,FLR_Z+z0,FLR_Z+z1,col,op=op,db=(WWD+0.6+nudge)-((-0.04+y0+x1+y1)/2))
    if windows:
        # WALL 1 (west) banded windows, scaled to the room depth
        _b0,_b1=2.7,7.3; _m0,_m1=0.4,d-0.4
        _onW(_m0,_m1,0.16,_b0-0.16,_b0,"#9aa2ad",nudge=0.04)               # sill
        _onW(_m0,_m1,0.16,_b1,_b1+0.16,"#9aa2ad",nudge=0.04)              # head
        _onW(_m0,_m1,0.22,_b0,_b1,"#e3ebf0",nudge=0.06)                   # panes
        _kk=1
        while _b0+0.2*_kk<_b1-0.06:
            _onW(_m0+0.15,_m1-0.15,0.24,_b0+0.2*_kk,_b0+0.2*_kk+0.06,"#ccd8df",nudge=0.08)
            _kk+=1
        _nb=max(2,int(round((_m1-_m0)/4.3)))
        for _i in range(_nb+1):
            _my=_m0+(_m1-_m0)*_i/_nb
            _onW(_my-0.07,_my+0.07,0.30,_b0,_b1,"#9aa2ad",nudge=0.14)     # vertical mullions
        for _mz in (_b0+1.53,_b0+3.07):
            _onW(_m0,_m1,0.30,_mz-0.05,_mz+0.05,"#9aa2ad",nudge=0.14)     # horizontal mullions
    else:
        # WALL 1 solid (no exterior windows) — a pair of framed prints instead
        for _ay0,_ay1,_c in ((d*0.28,d*0.28+2.3,"#46586e"),(d*0.28+2.7,d*0.28+4.4,"#7d8894")):
            _onW(_ay0,_ay1,0.17,3.30,5.70,shade(_c,0.66),nudge=0.06)     # frame
            _onW(_ay0+0.08,_ay1-0.08,0.21,3.42,5.58,_c,nudge=0.12)       # print
    # WALL 2 (north): TV + a compact open shelf to its left
    _onN(4.20,8.60,0.22,3.30,5.80,"#59616e",nudge=0.06)              # TV bezel
    _onN(4.40,8.40,0.28,3.45,5.65,"#222833",nudge=0.12)             # TV panel
    R.box(1.30,0.34,1.52,1.14,FLR_Z,FLR_Z+5.40,shelf_col)           # shelf: left post
    R.box(3.58,0.34,3.80,1.14,FLR_Z,FLR_Z+5.40,shelf_col)          # right post
    for _sz in (0.10,1.30,2.55,3.80,5.25):
        R.box(1.30,0.34,3.80,1.18,FLR_Z+_sz,FLR_Z+_sz+0.11,shade(shelf_col,0.92))   # boards
    _pal=("#3f5170","#7d8894","#c5ccd4","#4a6b96","#8a95a3","#dde3ea")
    def _brow(x0,z,n,seed=0):
        _bx=x0
        for _i in range(n):
            _bw=0.13+0.03*((_i+seed)%3); _bh=0.55+0.05*(((_i+seed)*2)%4)
            R.box(_bx,0.55,_bx+_bw,1.06,FLR_Z+z,FLR_Z+z+_bh,_pal[(_i+seed)%len(_pal)],db=0.8)
            _bx+=_bw+0.03
    _brow(1.62,0.21,5,0); _brow(1.62,1.41,4,2)                       # books on two shelves
    R.box(2.95,0.60,3.60,1.02,FLR_Z+2.66,FLR_Z+2.66+0.46,"#4a6b96",db=0.8)   # a box file
    R.box(1.70,0.66,2.04,1.02,FLR_Z+3.91,FLR_Z+3.91+0.26,"#7d8894",db=0.8)   # pot
    leafy(R,1.87,0.84,FLR_Z+3.91+0.26,4.4,0.55)                     # plant on top
    # WALL 3 (east) glass front + door
    glass_front(R,3)
    # L-desk (graphite), owner backs wall 4 facing the TV. Slide the whole cluster west so
    # it clears the glass wall (wall 3) by ~3.3'; guard keeps it off wall 1 in the small room.
    _gx=w-12.9
    if 3.60+_gx<1.10: _gx=1.10-3.60
    R.box(3.60+_gx,5.40,9.60+_gx,7.60,FLR_Z+2.2,FLR_Z+2.5,desk_col)  # main
    R.box(7.60+_gx,7.60,9.60+_gx,9.60,FLR_Z+2.2,FLR_Z+2.5,desk_col)  # return
    for _ex,_ey in ((3.9,5.7),(3.9,7.3),(9.3,5.7),(9.3,7.3),(9.3,9.3),(7.9,9.3)):
        R.box(_ex+_gx-0.18,_ey-0.18,_ex+_gx+0.18,_ey+0.18,FLR_Z,FLR_Z+2.2,"#8b95a3")   # legs
    def _seat(cx,cy,ang,col,bh=2.4):
        R.rbox(cx,cy,1.45,1.45,FLR_Z,FLR_Z+1.5,ang,col)
        _bx=cx-0.58*_m.cos(_m.radians(ang)); _by=cy-0.58*_m.sin(_m.radians(ang))
        R.rbox(_bx,_by,0.30,1.45,FLR_Z,FLR_Z+bh,ang,shade(col,1.12))
    _seat(6.40+_gx,8.70,-90,owner_col,2.7)                          # owner
    _seat(5.00+_gx,3.90,90,guest_col); _seat(7.80+_gx,3.90,90,guest_col)   # TWO across for interviews
    # iMac
    _ix,_iy=6.40+_gx,6.50; _MD=0.7
    R.box(_ix-0.42,_iy-0.28,_ix+0.42,_iy+0.28,FLR_Z+2.5,FLR_Z+2.58,"#c9ccd2",db=_MD)  # foot
    R.box(_ix-0.10,_iy-0.05,_ix+0.10,_iy+0.05,FLR_Z+2.58,FLR_Z+3.05,"#c9ccd2",db=_MD) # stand
    R.box(_ix-0.95,_iy-0.06,_ix+0.95,_iy+0.06,FLR_Z+3.05,FLR_Z+4.35,"#d8dbe0",db=_MD) # bezel
    R.box(_ix-0.86,_iy+0.02,_ix+0.86,_iy+0.09,FLR_Z+3.14,FLR_Z+4.24,"#222833",db=_MD) # screen
    R.box(_ix-0.55,_iy+0.60,_ix+0.55,_iy+1.05,FLR_Z+2.5,FLR_Z+2.58,"#e6e8ec",db=_MD)  # keyboard


def classroom(R,vibe,screen_wall=2,seats=12):
    """Training rooms are classroom setups: a screen on a solid wall, rows of chairs
    facing it, 3'x2' posters on whatever solid wall is left. `screen_wall` is 2 (north)
    or 1 (west) — it has to be solid AND a far wall, or the camera only sees its back.
    Chairs face it, so we see their backs; that is how a classroom reads anyway."""
    w,d=R.w,R.d
    NWD=(0-0.5+w+0)/2; WWD=(-0.5+0+0+d)/2
    def _onN(a0,a1,t,z0,z1,col,nudge=0.0):
        R.box(a0,0.05,a1,t,FLR_Z+z0,FLR_Z+z1,col,db=(NWD+0.6+nudge)-((a0+0.05+a1+t)/2))
    def _onW(a0,a1,t,z0,z1,col,nudge=0.0):
        R.box(-0.04,a0,t,a1,FLR_Z+z0,FLR_Z+z1,col,db=(WWD+0.6+nudge)-((-0.04+a0+t+a1)/2))
    _on=_onN if screen_wall==2 else _onW
    span=w if screen_wall==2 else d
    sw=min(span*0.60,9.0); sh=sw*0.5625; a0=(span-sw)/2.0; z0=2.80    # 16:9, centred
    _on(a0,a0+sw,0.16,z0,z0+sh,"#2b3038",nudge=0.06)                       # bezel
    _on(a0+0.14,a0+sw-0.14,0.21,z0+0.14,z0+sh-0.14,"#0f1319",nudge=0.12)   # screen

    def _plate(a0,a1,t,z0,z1,col,nudge=0.0):
        """A thin plate on wall 1. Depth stays at 0.04: a plate that reaches back into
        the wall shows a shaded side face and reads as a raised block, not as print."""
        lo=t-0.04
        R.box(lo,a0,t,a1,FLR_Z+z0,FLR_Z+z1,col,db=(WWD+0.6+nudge)-((lo+a0+t+a1)/2))
    def poster(p0,pz,i):
        """3' x 2' framed print — paper stock with a bold graphic, no text. The motif
        rotates so a run of them doesn't read as wallpaper."""
        W,H=3.0,2.0; A=vibe["accent"]; A2=shade(A,0.66)
        _plate(p0,p0+W,0.13,pz,pz+H,"#43403c",0.04)                        # slim frame
        _plate(p0+0.05,p0+W-0.05,0.16,pz+0.05,pz+H-0.05,"#f3f1ed",0.08)    # paper
        m=i%3
        if m==0:                                                           # bar over rule
            _plate(p0+0.30,p0+W-0.30,0.18,pz+0.30,pz+0.94,A,0.12)
            _plate(p0+0.30,p0+1.40,0.18,pz+1.12,pz+1.44,A2,0.12)
        elif m==1:                                                         # tall block + tab
            _plate(p0+0.30,p0+1.34,0.18,pz+0.30,pz+H-0.30,A,0.12)
            _plate(p0+1.54,p0+W-0.30,0.18,pz+0.30,pz+0.88,A2,0.12)
        else:                                                              # stacked bands
            _plate(p0+0.30,p0+W-0.30,0.18,pz+0.98,pz+H-0.30,A,0.12)
            _plate(p0+0.30,p0+W-0.30,0.18,pz+0.60,pz+0.86,A2,0.12)

    # Posters only where there is a solid wall the camera can actually see. In rooms
    # 11/12 that is nowhere: wall 3 faces away and wall 1 carries the screen.
    if screen_wall==2:
        for i,py in enumerate((4.0,8.5,13.0)): poster(py,3.60,i)

    # credenza under the screen, running a touch wider than it
    c0,c1=a0-0.20,a0+sw+0.20
    body=vibe["cred"]; top=shade(body,0.78); split=shade(body,0.72)
    n=3
    if screen_wall==2:                                   # against wall 2, front faces south
        R.box(c0,0.15,c1,1.75,FLR_Z,FLR_Z+2.30,body)                          # body
        R.box(c0-0.06,0.10,c1+0.06,1.82,FLR_Z+2.30,FLR_Z+2.42,top)            # top slab
        for i in range(1,n):
            dx=c0+(c1-c0)*i/n
            R.box(dx-0.02,1.75,dx+0.02,1.80,FLR_Z+0.16,FLR_Z+2.20,split)      # door splits
        for i in range(n):
            hx=c0+(c1-c0)*(i+0.5)/n
            R.box(hx-0.38,1.75,hx+0.38,1.82,FLR_Z+1.52,FLR_Z+1.61,vibe["accent"])   # pulls
    else:                                                # against wall 1, front faces east
        R.box(0.15,c0,1.75,c1,FLR_Z,FLR_Z+2.30,body)
        R.box(0.10,c0-0.06,1.82,c1+0.06,FLR_Z+2.30,FLR_Z+2.42,top)
        for i in range(1,n):
            dy=c0+(c1-c0)*i/n
            R.box(1.75,dy-0.02,1.80,dy+0.02,FLR_Z+0.16,FLR_Z+2.20,split)
        for i in range(n):
            hy=c0+(c1-c0)*(i+0.5)/n
            R.box(1.75,hy-0.38,1.82,hy+0.38,FLR_Z+1.52,FLR_Z+1.61,vibe["accent"])

    ang=-90 if screen_wall==2 else 180
    bx,by=(0.0,0.58) if screen_wall==2 else (0.58,0.0)
    def _seat(cx,cy):
        R.rbox(cx,cy,1.35,1.35,FLR_Z,FLR_Z+1.45,ang,vibe["chair"])
        R.rbox(cx+bx,cy+by,0.28,1.35,FLR_Z,FLR_Z+2.30,ang,shade(vibe["chair"],1.22))
    across=w if screen_wall==2 else d
    back  =d if screen_wall==2 else w
    cols=max(1,min(int((across-3.2)/2.9)+1,seats)); rows=max(1,round(seats/cols))
    c0=(across-(cols-1)*2.9)/2.0
    ry0,ry1=5.0,back-2.2
    ys=[ry0+(ry1-ry0)*r/(rows-1) for r in range(rows)] if rows>1 else [ry0]
    for t in ys:
        for c in range(cols):
            _seat(c0+c*2.9,t) if screen_wall==2 else _seat(t,c0+c*2.9)
    return rows*cols

def glass_front(R,wall):
    """Full-height glass wall with an entry door, on wall 3 (east) or wall 4 (south).
    Translucent — both sit between the camera and the room."""
    w,d=R.w,R.d; GL="#9fdcf0"; FR="#59616e"
    span=d if wall==3 else w
    def slab(a0,a1,z0,z1,col,op,t=0.40):
        if wall==3: R.box(w,a0,w+t,a1,FLR_Z+z0,FLR_Z+z1,col,op=op)
        else:       R.box(a0,d,a1,d+t,FLR_Z+z0,FLR_Z+z1,col,op=op)
    slab(0,span,0.5,8.0,GL,0.18,0.36)                                # glazing
    slab(0,span,0.0,0.5,FR,0.75); slab(0,span,8.0,8.2,FR,0.75)       # base + head rail
    n=max(2,int(round(span/6.6)))
    for i in range(n+1):
        a=min(span*i/n,span-0.16); slab(a,a+0.16,0.5,8.0,FR,0.75)    # mullions
    dw=min(3.0,span*0.34); d0=min(max(span*0.62,0.4),span-dw-0.4); d1=d0+dw
    for a in (d0,d1): slab(a,a+0.16,0.5,7.3,FR,0.9,0.44)             # door stiles
    slab(d1-0.40,d1-0.20,3.05,3.55,"#c9ccd2",0.95,0.48)              # pull
    if wall==3: R.swing_at(w-0.10,d0+0.20,2.70,98,168)
    else:       R.swing_at(d0+0.20,d-0.10,2.70,188,258)

def ext_windows_n(R):
    """Banded exterior window run along wall 2 — solid below the sill, blinds between,
    mullions on a regular bay. Matches the window Megan photographed."""
    w=R.w; NWD=(0-0.5+w+0)/2
    def _onN(x0,x1,y1,z0,z1,col,nudge=0.0):
        R.box(x0,0.05,x1,y1,FLR_Z+z0,FLR_Z+z1,col,db=(NWD+0.6+nudge)-((x0+0.05+x1+y1)/2))
    b0,b1=2.7,7.3; m0=0.4; m1=w-0.4
    _onN(m0,m1,0.16,b0-0.16,b0,"#9aa2ad",nudge=0.04)                 # sill
    _onN(m0,m1,0.16,b1,b1+0.16,"#9aa2ad",nudge=0.04)                 # head
    _onN(m0,m1,0.22,b0,b1,"#e3ebf0",nudge=0.06)                      # panes, blinds down
    k=b0+0.2
    while k<b1-0.06:
        _onN(m0+0.15,m1-0.15,0.24,k,k+0.06,"#ccd8df",nudge=0.08)     # slats
        k+=0.2
    n=max(2,int(round((m1-m0)/5.5)))
    for i in range(n+1):
        mx=m0+(m1-m0)*i/n
        _onN(mx-0.07,mx+0.07,0.30,b0,b1,"#9aa2ad",nudge=0.14)        # vertical mullions
    for mz in (b0+1.53,b0+3.07):
        _onN(m0,m1,0.30,mz-0.05,mz+0.05,"#9aa2ad",nudge=0.14)        # horizontal mullions

def wall_numbers(R):
    """Number the four walls so they can be named without ambiguity.
    1 = back-left, 2 = back-right, 3 = front-right, 4 = front-left (clockwise)."""
    w,d=R.w,R.d
    for n,(x,y,z) in ((1,(-0.80,d*0.50,FLR_Z+7.4)),(2,(w*0.50,-0.80,FLR_Z+7.4)),
                      (3,(w+0.80,d*0.50,FLR_Z+1.7)),(4,(w*0.50,d+0.80,FLR_Z+1.7))):
        px,py=R.iso(x,y,z)
        R.emit(9e9,9e9,   f'<circle cx="{px:.1f}" cy="{py:.1f}" r="10" fill="{C_ACCENT}" stroke="#ffffff" stroke-width="1.6"/>')
        R.emit(9e9,9e9+1, f'<text x="{px:.1f}" y="{py+3.8:.1f}" font-family="Inter,Segoe UI,Arial,sans-serif" '
                          f'font-size="12" font-weight="800" fill="#ffffff" text-anchor="middle">{n}</text>')

def _ft(s):
    """'10\\'6"' -> 10.5 feet."""
    s=s.replace('"','').strip()
    if "'" in s:
        a,_,b=s.partition("'")
        return float(a)+(float(b)/12.0 if b.strip() else 0.0)
    return float(s)

def build_office(entry):
    key,title,dim,kind,w,d,note,furn,comb=entry
    R=Room(float(w),float(d))
    door={"reception":"W","conference":"E","break":"E","large":"E",
          "long":None,"wide":None,"interview":None}.get(kind,"S")   # None = the room draws its own entry
    wcol=WALL_COL.get(key,C_WALL)                    # each office its own wall colour
    if kind=="break":
        R.shell(door=door, floor_col=C_TILE, wall_col=wcol)   # break room is the only tile floor
    else:
        R.shell(door=door, wall_col=wcol)
    furnish(kind,R,key)
    if comb:  # accent outline marking merged room
        o=[R.iso(0.3,0.3,FLR_Z+0.03),R.iso(R.w-0.3,0.3,FLR_Z+0.03),R.iso(R.w-0.3,R.d-0.3,FLR_Z+0.03),R.iso(0.3,R.d-0.3,FLR_Z+0.03)]
        p=" ".join(f'{a:.1f},{b:.1f}' for a,b in o)
        R.emit(9e8,9e8,f'<polygon points="{p}" fill="none" stroke="{C_ACCENT}" stroke-width="1.6" stroke-dasharray="5 3"/>')
    # put each dim caption on the axis it actually measures (some catalog dims read d × w)
    parts=dim.split(" × ")
    if len(parts)==2:
        wl,dl=parts
        if abs(_ft(wl)-float(w)) > abs(_ft(dl)-float(w)): wl,dl=dl,wl
    else:
        wl=dl=parts[0]
    R.dims(f'{wl} wide', f'{dl} deep')
    wall_numbers(R)
    return R.render()

FURN_BY_KIND={
 'small':'Private office · shell + door','med':'Private office · shell + door',
 'interview':'L-desk · iMac · 2 guest chairs · TV · open shelf · glass front (no credenza)',
 'long':'Classroom · screen · credenza · 12 chairs · posters · glass front','wide':'Classroom · screen · credenza · 12 chairs · window wall · glass front',
 'large':'Large office · shell + door','conference':'Boardroom · 14 seats · TV wall · whiteboards · built-in counter',
 'megan':'4 screens · standing desk · laptop · walking pad · florals · window wall',
 'twaddle':'L-desk · 2 guest · TV · tablet cabinet · window wall · glass entrance',
 'jd':'L-desk · 2 guest · TV · open shelving · credenza under the windows · glass front',
 'bas':'L-desk · iMac · 2 bright guest chairs · TV · Lego mosaic · brick builds · open shelving · glass front',
 'maud':'L-desk · 2 guest · iMac · TV · play pen · rocking chair · window wall',
 'raf':'L-desk · iMac · walking pad · 2 guest · bookcase · mini fridge · 6-seat oval table',
 'reception':'Built-in desk · dog area · glass upper · open walkway',
 'break':'Kitchenette · island · storage wall'}
offices=[]
for n,e in enumerate(CATALOG,start=1):
    key,title,dim,kind,w,d,note,furn,comb=e
    svg=build_office(e)
    offices.append(dict(key=key,num=n,title=f"{n} · {title}",dim=dim,note=note,
                        furn=FURN_BY_KIND.get(kind,furn),comb=comb,svg=svg))

# overview + key map
overview_svg=open("/private/tmp/claude-501/-Users-megan-1st-Claude-Folder/de840332-a406-47e2-ab31-cb468bebf93c/scratchpad/office.svg").read()
overview_svg=overview_svg.replace('<svg ','<svg preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%" ',1)
keymap_svg=open("/private/tmp/claude-501/-Users-megan-1st-Claude-Folder/de840332-a406-47e2-ab31-cb468bebf93c/scratchpad/keymap.svg").read()

data=[
 dict(key="keymap",title="Key Map (numbered)",dim="Reference",note="Numbers match the walk-through order — use this to point at a room",furn="Numbered plan",comb=False,svg=keymap_svg),
 dict(key="overview",title="Floor Overview (3D)",dim="Full plate",note="Whole office in one isometric view",furn="Master isometric",comb=False,svg=overview_svg),
]+offices

# ---- group nav ------------------------------------------------------------
def group_of(k):
    if k in ("overview","keymap"): return "Overview"
    if k.startswith("w-"): return "West wing"
    if k.startswith("n-"): return "North"
    if k.startswith("e-"): return "East wing"
    if k.startswith("s-"): return "South row"
    return "Common areas"

HTML_TMPL = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alphalete — Office Studio</title>
<style>
 *{box-sizing:border-box;margin:0;padding:0}
 :root{--bg:#f4f5f7;--panel:#fff;--ink:#242832;--sub:#8b91a0;--line:#e7e9ee;--accent:#e8482b;--accent2:#2f6df0}
 html,body{height:100%}
 body{font-family:Inter,-apple-system,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink);display:flex;height:100vh;overflow:hidden}
 .side{width:250px;flex:0 0 250px;background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column}
 .brand{padding:16px 18px;border-bottom:1px solid var(--line)}
 .brand h1{font-size:16px;letter-spacing:.5px;font-weight:800}
 .brand p{font-size:10.5px;letter-spacing:2px;color:var(--sub);font-weight:600;margin-top:2px}
 .nav{overflow-y:auto;padding:8px 0;flex:1}
 .grp{font-size:10px;letter-spacing:1.2px;color:var(--sub);font-weight:700;padding:12px 18px 4px;text-transform:uppercase}
 .item{display:flex;align-items:center;gap:8px;padding:8px 18px;cursor:pointer;border-left:3px solid transparent}
 .item:hover{background:#f7f8fa}
 .item.active{background:#f0f4ff;border-left-color:var(--accent2)}
 .item .t{font-size:12.5px;font-weight:600;line-height:1.2}
 .item .d{font-size:10.5px;color:var(--sub)}
 .dot{width:7px;height:7px;border-radius:50%;background:var(--accent);flex:0 0 7px}
 .main{flex:1;display:flex;flex-direction:column;min-width:0}
 .top{padding:16px 24px;border-bottom:1px solid var(--line);background:var(--panel);display:flex;align-items:flex-end;gap:16px}
 .top h2{font-size:20px;font-weight:800}
 .top .dim{font-size:13px;color:var(--accent2);font-weight:700;margin-top:3px}
 .top .note{font-size:12px;color:var(--sub);margin-top:2px}
 .chips{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;max-width:320px;justify-content:flex-end}
 .chip{font-size:11px;background:#f0f1f4;border:1px solid var(--line);border-radius:20px;padding:4px 10px;color:#4a505c}
 .stage{flex:1;position:relative;min-height:0;overflow:hidden}
 #zoomwrap{position:absolute;inset:0;overflow:hidden;cursor:grab}
 #zoomwrap.drag{cursor:grabbing}
 #stage{width:100%;height:100%;transform-origin:0 0;display:flex;align-items:center;justify-content:center;padding:18px;will-change:transform}
 #stage svg{max-width:100%;max-height:100%}
 .zoomctl{position:absolute;right:16px;bottom:16px;display:flex;gap:6px;z-index:5}
 .zoomctl button{width:36px;height:36px;border:1px solid var(--line);background:#fff;border-radius:9px;font-size:17px;font-weight:700;cursor:pointer;color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.06)}
 .zoomctl button:hover{background:#f5f6f8}
 .zoomctl button.fit{width:auto;padding:0 12px;font-size:12px}
 .zlvl{position:absolute;right:16px;top:16px;font-size:11px;font-weight:700;color:var(--sub);background:#fff;border:1px solid var(--line);border-radius:20px;padding:3px 10px;z-index:5}
 .zhint{position:absolute;left:20px;bottom:18px;font-size:11px;color:var(--sub);z-index:5}
 .badge{position:absolute;top:16px;left:20px;font-size:11px;font-weight:700;color:var(--accent);background:#fff;border:1px solid #f3c8bf;border-radius:20px;padding:4px 11px;z-index:5}
 .foot{display:flex;align-items:center;gap:12px;padding:12px 24px;border-top:1px solid var(--line);background:var(--panel)}
 .btn{border:1px solid var(--line);background:#fff;border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600;cursor:pointer;color:var(--ink)}
 .btn:hover{background:#f5f6f8}
 .btn:disabled{opacity:.4;cursor:default}
 .count{font-size:12px;color:var(--sub);margin-left:auto}
 .hint{font-size:11px;color:var(--sub)}
</style></head><body>
 <aside class="side"><div class="brand"><h1>ALPHALETE</h1><p>OFFICE STUDIO</p></div><nav class="nav" id="nav"></nav></aside>
 <section class="main">
   <div class="top"><div><h2 id="ttl"></h2><div class="dim" id="dim"></div><div class="note" id="note"></div></div><div class="chips" id="chips"></div></div>
   <div class="stage">
     <div class="badge" id="badge" style="display:none">◧ walls removed · combined</div>
     <div class="zlvl" id="zlvl">100%</div>
     <div id="zoomwrap"><div id="stage"></div></div>
     <div class="zhint">scroll to zoom · drag to pan · double-click to zoom in</div>
     <div class="zoomctl"><button id="zout">−</button><button class="fit" id="zfit">Fit</button><button id="zin">+</button></div>
   </div>
   <div class="foot"><button class="btn" id="prev">← Prev</button><button class="btn" id="next">Next →</button><span class="hint">Use ← / → keys</span><span class="count" id="count"></span></div>
 </section>
<script>
const DATA=__DATA__;
let i=0;
const nav=document.getElementById('nav');
let groups={};DATA.forEach((o,idx)=>{const g=o.group||'Other';(groups[g]=groups[g]||[]).push(idx)});
for(const g in groups){const h=document.createElement('div');h.className='grp';h.textContent=g;nav.appendChild(h);
 groups[g].forEach(idx=>{const o=DATA[idx];const el=document.createElement('div');el.className='item';el.dataset.i=idx;
  el.innerHTML=(o.comb?'<span class="dot"></span>':'')+'<div><div class="t">'+o.title+'</div><div class="d">'+o.dim+'</div></div>';
  el.onclick=()=>go(idx);nav.appendChild(el);});}
// ---- zoom / pan ----
let sc=1,tx=0,ty=0;
const wrap=document.getElementById('zoomwrap'),stg=document.getElementById('stage'),zlvl=document.getElementById('zlvl');
function applyT(){stg.style.transform='translate('+tx+'px,'+ty+'px) scale('+sc+')';zlvl.textContent=Math.round(sc*100)+'%';}
function resetT(){sc=1;tx=0;ty=0;applyT();}
function zoomAt(mx,my,f){let ns=Math.min(9,Math.max(1,sc*f));const k=ns/sc;tx=mx-(mx-tx)*k;ty=my-(my-ty)*k;sc=ns;if(sc<=1.001){sc=1;tx=0;ty=0;}applyT();}
wrap.addEventListener('wheel',e=>{e.preventDefault();const r=wrap.getBoundingClientRect();zoomAt(e.clientX-r.left,e.clientY-r.top,e.deltaY<0?1.15:1/1.15);},{passive:false});
wrap.addEventListener('dblclick',e=>{const r=wrap.getBoundingClientRect();zoomAt(e.clientX-r.left,e.clientY-r.top,1.6);});
let dg=false,lx=0,ly=0;
wrap.addEventListener('mousedown',e=>{dg=true;lx=e.clientX;ly=e.clientY;wrap.classList.add('drag');});
window.addEventListener('mousemove',e=>{if(!dg)return;tx+=e.clientX-lx;ty+=e.clientY-ly;lx=e.clientX;ly=e.clientY;applyT();});
window.addEventListener('mouseup',()=>{dg=false;wrap.classList.remove('drag');});
function ctr(f){const r=wrap.getBoundingClientRect();zoomAt(r.width/2,r.height/2,f);}
document.getElementById('zin').onclick=()=>ctr(1.3);
document.getElementById('zout').onclick=()=>ctr(1/1.3);
document.getElementById('zfit').onclick=resetT;

function go(n){i=(n+DATA.length)%DATA.length;const o=DATA[i];
 document.getElementById('stage').innerHTML=o.svg;resetT();
 document.getElementById('ttl').textContent=o.title;
 document.getElementById('dim').textContent=o.dim;
 document.getElementById('note').textContent=o.note;
 document.getElementById('badge').style.display=o.comb?'block':'none';
 const ch=document.getElementById('chips');ch.innerHTML='';
 (o.furn||'').split(' · ').forEach(f=>{const c=document.createElement('span');c.className='chip';c.textContent=f;ch.appendChild(c);});
 document.getElementById('count').textContent=(i+1)+' / '+DATA.length;
 document.querySelectorAll('.item').forEach(e=>e.classList.toggle('active',+e.dataset.i===i));
 const act=document.querySelector('.item.active');if(act)act.scrollIntoView({block:'nearest'});
}
document.getElementById('prev').onclick=()=>go(i-1);
document.getElementById('next').onclick=()=>go(i+1);
window.addEventListener('keydown',e=>{if(e.key==='ArrowLeft')go(i-1);if(e.key==='ArrowRight')go(i+1);});
go(0);
</script></body></html>"""

if __name__=="__main__":
    import sys
    if "--one" in sys.argv:
        open("/private/tmp/claude-501/-Users-megan-1st-Claude-Folder/de840332-a406-47e2-ab31-cb468bebf93c/scratchpad/one.svg","w").write(build_office(CATALOG[0]))
        print("wrote one.svg")
    else:
        for o in data: o["group"]=group_of(o["key"])
        html=HTML_TMPL.replace("__DATA__", json.dumps(data))
        out="/private/tmp/claude-501/-Users-megan-1st-Claude-Folder/de840332-a406-47e2-ab31-cb468bebf93c/scratchpad/studio.html"
        open(out,"w").write(html)
        print("offices:",len(data),"-> studio.html", len(html),"bytes")
