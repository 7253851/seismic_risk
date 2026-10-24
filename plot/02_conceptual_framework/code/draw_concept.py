from pathlib import Path
from html import escape
import math

OUT = Path(__file__).resolve().parents[3] / "plot/02_conceptual_framework/output"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1350, 1230
INK = '#252525'
HAZ = '#AA6046'
VUL = '#2F6484'
EXP = '#AB8A34'
OBS = '#AC3C69'
POP = '#77746C'
parts = []

def add(s): parts.append(s)
def line(x1,y1,x2,y2,c=INK,w=2,dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="{w}"{d}/>')
def rect(x,y,w,h,fill='none',stroke=INK,sw=2,rx=0):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" rx="{rx}"/>')
def circle(x,y,r,fill='none',stroke=INK,sw=2):
    add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
def ellipse(x,y,rx,ry,fill='none',stroke=INK,sw=2):
    add(f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
def path(d,fill='none',stroke=INK,sw=2,dash=None):
    ds=f' stroke-dasharray="{dash}"' if dash else ''
    add(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round" stroke-linecap="round"{ds}/>')
def poly(points,fill='none',stroke=INK,sw=2):
    add(f'<polygon points="{" ".join(f"{x},{y}" for x,y in points)}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"/>')
def text(x,y,t,size=28,c=INK,bold=False,anchor='middle',italic=False):
    weight='700' if bold else '400'
    style='italic' if italic else 'normal'
    add(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" font-style="{style}" fill="{c}">{escape(t)}</text>')
def equation(x,y,t,size=30):
    add(f'<text x="{x}" y="{y}" text-anchor="middle" font-size="{size}" fill="{INK}">{t}</text>')
def arrow(x1,y1,x2,y2,c=INK,sw=2):
    line(x1,y1,x2,y2,c,sw)
    a=math.atan2(y2-y1,x2-x1)
    n=8
    poly([(x2,y2),(x2-n*math.cos(a-.42),y2-n*math.sin(a-.42)),(x2-n*math.cos(a+.42),y2-n*math.sin(a+.42))],c,c,1)
def building(x,base,w,h,fill='#F9F9F9',windows=True,stroke=INK):
    rect(x,base-h,w,h,fill,stroke,2)
    rect(x+w*.35,base-15,w*.22,15,'#D2D2D2',stroke,1.5)
    if windows:
        for yy in range(int(base-h+13),int(base-22),20):
            for xx in range(int(x+10),int(x+w-7),18):
                rect(xx,yy,6,9,'#92999C','none',0)

add(f'<svg xmlns="http://www.w3.org/2000/svg" width="180mm" height="164mm" viewBox="0 0 {W} {H}">')
add('<title>InSAR-informed building-level seismic risk: conceptual relationships</title>')
add('<desc>Hazard, exposure and InSAR-informed vulnerability jointly contribute to relative building-level seismic risk. The vulnerability region depicts a static baseline multiplied by an InSAR condition modifier. The overlapping circles express conceptual contributions, not mapped regions or probabilities.</desc>')
add('<g font-family="Arial, Helvetica, sans-serif">')
rect(0,0,W,H,'white','none',0)

# A conceptual overlap, with no chronological or processing arrows.
for cx,cy,rx,ry,fill in [(375,325,355,300,'#F7EAE3'),(975,325,355,300,'#F7F1DB'),(675,835,570,370,'#E9F1F7')]:
    add(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" fill-opacity="0.70" stroke="none"/>')
for cx,cy,rx,ry,c in [(375,325,355,300,HAZ),(975,325,355,300,EXP),(675,835,570,370,VUL)]:
    ellipse(cx,cy,rx,ry,'none',c,3)

# H: physical shaking at the building location, rather than an algorithm chain.
text(375,118,'Seismic hazard (H)',43,HAZ,True)
add('<g transform="translate(340 260) scale(1.45) translate(-560 -379)">')
path('M 411 407 L 709 407 L 709 452 L 411 452 Z','#E7DDD5','#77716A',1.7)
line(411,422,709,422,'#A99C90',1.4)
line(411,437,709,437,'#A99C90',1.4)
building(440,407,49,75,'#FAFAFA')
building(501,407,62,115,'#FAFAFA')
building(575,407,48,59,'#FAFAFA')
path('M 531 452 L 546 437 L 538 428 L 555 416 L 550 407','none',HAZ,3.5)
for rr in [24,46,68]:
    path(f'M {553-rr} 401 A {rr} {rr} 0 0 1 {553+rr} 401','none',HAZ,1.8)
add('</g>')
text(340,400,'Scenario PGA',31,INK,True)
equation(340,440,'PGA<tspan baseline-shift="super" font-size="19">final</tspan> = max<tspan baseline-shift="sub" font-size="19" font-style="italic">j</tspan>(PGA<tspan baseline-shift="sub" font-size="19" font-style="italic">j</tspan>)',29)
text(340,478,'Faults · site response',26,INK)

# E: exposed people and assets, represented by austere flat pictograms.
text(1030,118,'Exposure (E)',43,EXP,True)
add('<g transform="translate(1030 260) scale(1.65) translate(-1245 -371)">')
add('<g transform="translate(1180 412) scale(0.72) translate(-1180 -412)">')
for xx,yy,scale in [(1135,320,1),(1180,306,1.16),(1227,322,.97)]:
    circle(xx,yy,10*scale,POP,'none',0)
    rect(xx-11*scale,yy+17*scale,22*scale,34*scale,POP,'none',0,6)
    line(xx-5*scale,yy+45*scale,xx-5*scale,yy+75*scale,POP,4.5*scale)
    line(xx+5*scale,yy+45*scale,xx+5*scale,yy+75*scale,POP,4.5*scale)
    line(xx-10*scale,yy+23*scale,xx-20*scale,yy+48*scale,POP,3.8*scale)
    line(xx+10*scale,yy+23*scale,xx+20*scale,yy+48*scale,POP,3.8*scale)
add('</g>')
poly([(1270,356),(1315,317),(1360,356)],'#EEE4C7',INK,2.1)
rect(1280,356,70,61,'#FAFAFA',INK,2.1)
rect(1306,383,19,34,'#E4D7AC',INK,1.6)
rect(1289,369,11,12,'none',INK,1.5)
circle(1360,411,25,'#F7EAC0',EXP,2)
text(1360,421,'$',29,EXP,True)
add('</g>')
text(1030,400,'People and assets',31,INK,True)
equation(1030,440,'<tspan font-style="italic">E*</tspan> = 0.6 <tspan font-style="italic">I</tspan><tspan baseline-shift="super" font-size="19" font-style="italic">P</tspan> + 0.4 <tspan font-style="italic">I</tspan><tspan baseline-shift="super" font-size="19" font-style="italic">E</tspan>',29)
text(1030,478,'Population · economic proxy',26,INK)

# The common assessment unit is the individual building.
circle(675,480,175,'white',INK,3)
add('<g transform="translate(675 386) scale(1.17) translate(-900 -540)">')
building(829,588,43,61,'#F4F4F4')
building(882,588,47,99,'#E3E7E8')
building(939,588,36,47,'#F4F4F4')
line(818,590,986,590,INK,2)
add('</g>')
text(675,487,'Building-level',35,INK,True)
text(675,531,'seismic risk',38,INK,True)
equation(675,568,'<tspan font-style="italic">R = H × V × E</tspan>',32)

# V: geometric baseline and pre-earthquake condition coexist inside vulnerability.
text(675,701,'InSAR-informed vulnerability (V)',41,VUL,True)
text(440,756,'Static baseline',32,INK,True)
text(950,756,'InSAR state modifier',31,INK,True)

# Observable geospatial proxies. All are geometry, not structural capacity tests.
add('<g transform="translate(440 890) scale(1.45) translate(-723 -1028)">')
path('M 585 991 L 635 991 L 635 1013 L 659 1013 L 659 1046 L 616 1046 L 616 1060 L 585 1060 Z','#C4D6E3',VUL,2)
add('<g transform="rotate(-20 717 1026)">')
rect(685,1007,64,40,'#C4D6E3',VUL,2)
line(673,1027,761,1027,VUL,1.8,'6 4')
add('</g>')
line(685,1061,748,984,HAZ,2.2)
circle(815,1026,46,'none',VUL,1.6)
for xx,yy,ww,hh in [(789,1000,16,13),(815,994,13,17),(836,1010,13,12),(800,1022,13,16),(820,1024,17,13),(789,1044,15,13),(820,1047,14,12)]:
    rect(xx,yy,ww,hh,'#C4D6E3',VUL,1.1)
add('</g>')
for x,t in [(293.5,'SCI'),(432.7,'BFOCI'),(573.4,'BD')]: text(x,994,t,29,VUL,True)
text(440,1033,'Shape · orientation · density',26,INK)

# The multiplication expresses a modifier, not additive equivalent indicators.
text(690,916,'×',46,INK)

# IBSI is hierarchical: evidence support, baseline magnitude, anomaly amplification.
for x,upper,lower in [(770,'Observation','reliability'),(950,'Baseline','deformation'),(1130,'Local anomaly','amplification')]:
    text(x,803,upper,24,INK,True)
    text(x,833,lower,24,INK,True)

# 1. Observation support: PS count, density, coherence and footprint coverage.
rect(721,859,98,88,'#F8FBFD',VUL,2)
for xx,yy,c in [(731,870,VUL),(753,870,VUL),(775,870,VUL),(797,870,'#B8C4CB'),
                (731,891,VUL),(753,891,VUL),(775,891,OBS),(797,891,VUL),
                (731,912,'#B8C4CB'),(753,912,VUL),(775,912,VUL),(797,912,VUL),
                (731,933,VUL),(753,933,VUL),(775,933,VUL),(797,933,VUL)]:
    circle(xx,yy,4.7,c,'none',0)
path('M 802 882 L 812 892 L 829 869','none',VUL,3)
equation(770,985,'<tspan font-style="italic">Q</tspan><tspan baseline-shift="sub" font-size="20">InSAR</tspan>',28)
text(860,920,'×',30,INK)

# 2. PS deformation magnitudes on a building, including both rate signs.
ellipse(950,948,55,14,'none',VUL,1.5)
building(917,942,66,73,'#F9F9F9',True,VUL)
for xx,yy in [(925,879),(944,885),(967,877),(934,904),(962,912)]:
    circle(xx,yy,4.7,OBS,'white',1)
arrow(902,925,902,878,OBS,2)
arrow(998,878,998,925,OBS,2)
# A compact satellite retains the observation cue without shrinking the building.
rect(965,850,13,13,'#D8D8D8',INK,1.2)
rect(941,850,20,10,'#CFDCE7',VUL,1.1)
rect(982,850,20,10,'#CFDCE7',VUL,1.1)
line(961,855,965,855,INK,1.1)
line(978,855,982,855,INK,1.1)
line(970,863,954,869,'#777777',1,'3 3')
equation(950,985,'<tspan font-style="italic">V</tspan><tspan baseline-shift="sub" font-size="20">rms,n</tspan>',28)
text(1040,920,'×',30,INK)

# 3. A sloped velocity plane and unequal neighboring PS rates: Tilt and DGI.
poly([(1079,884),(1157,862),(1194,915),(1114,939)],'#D9E6EF',VUL,2)
line(1091,901,1170,879,'#9CAFBF',1.2)
line(1102,920,1182,898,'#9CAFBF',1.2)
line(1104,877,1140,932,'#9CAFBF',1.2)
line(1130,870,1167,924,'#9CAFBF',1.2)
for (x1,y1),(x2,y2) in [((1093,887),(1132,876)),((1132,876),(1168,901)),((1093,887),(1128,926)),((1128,926),(1168,901)),((1132,876),(1128,926))]:
    line(x1,y1,x2,y2,VUL,1.5)
for xx,yy,c in [(1093,887,VUL),(1132,876,OBS),(1168,901,OBS),(1128,926,VUL)]:
    circle(xx,yy,5,c,'white',1)
arrow(1093,877,1093,863,VUL,1.8)
arrow(1132,865,1132,841,OBS,1.8)
arrow(1168,891,1168,857,OBS,1.8)
text(1130,985,'Tilt + DGI',26,VUL,True)

# The brace groups simultaneous roles; there is no chronological sequence.
path('M 732 1004 L 732 1014 L 1168 1014 L 1168 1004','none',OBS,1.9)
text(950,1048,'InSAR Building State',30,OBS,True)
text(950,1083,'Index (IBSI)',30,OBS,True)
equation(675,1113,'<tspan font-style="italic">IBSI</tspan> = min[<tspan font-style="italic">Q</tspan><tspan baseline-shift="sub" font-size="20">InSAR</tspan> × <tspan font-style="italic">V</tspan><tspan baseline-shift="sub" font-size="20">rms,n</tspan> × (1 + <tspan font-style="italic">βT</tspan><tspan baseline-shift="sub" font-size="20">n</tspan> + <tspan font-style="italic">γDGI</tspan><tspan baseline-shift="sub" font-size="20">n</tspan>), 1]',27)
equation(675,1168,'<tspan font-style="italic">V*</tspan> = <tspan font-style="italic">V</tspan><tspan baseline-shift="sub" font-size="25">static</tspan> × (1 + 0.3 <tspan font-style="italic">IBSI</tspan>)',35)
add('</g></svg>')
(OUT/'concept_v07.svg').write_text('\n'.join(parts),encoding='utf-8')
print(OUT/'concept_v07.svg')
