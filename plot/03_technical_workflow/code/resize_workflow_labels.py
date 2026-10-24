from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import Color
import argparse

parser=argparse.ArgumentParser(description='Preserve the author workflow and enlarge its four smallest labels for manuscript text width.')
parser.add_argument('--base-image',type=Path,default=Path(__file__).resolve().parents[1]/'source/figure03_author_base.png')
parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'output/figure03_textwidth.pdf')
args=parser.parse_args()
original=args.base_image
args.output.parent.mkdir(parents=True,exist_ok=True)
# Clip only the transparent outer margin. Keep all original frames and flow arrows.
left,top,right,bottom=3,19,4174,2016
source_w,source_h=4345,2016
page_w=164.6*72/25.4
scale=page_w/(right-left)
page_h=(bottom-top)*scale
pdfmetrics.registerFont(TTFont('WorkflowTimes','/System/Library/Fonts/Supplemental/Times New Roman.ttf'))
c=canvas.Canvas(str(args.output),pagesize=(page_w,page_h),pageCompression=1)
c.setTitle('Building-level seismic-risk workflow')
c.saveState()
clip=c.beginPath();clip.rect(0,0,page_w,page_h);c.clipPath(clip,stroke=0,fill=0)
c.drawImage(ImageReader(str(original)),-left*scale,(bottom-source_h)*scale,source_w*scale,source_h*scale,mask='auto')
c.restoreState()
background=Color(234/255,247/255,241/255)
def blank(x0,y0,x1,y1):
 c.setFillColor(background)
 c.rect((x0-left)*scale,(bottom-y1)*scale,(x1-x0)*scale,(y1-y0)*scale,stroke=0,fill=1)
def text(x,y,s):
 c.setFillColor(Color(17/255,17/255,17/255))
 c.setFont('WorkflowTimes',5.70)
 c.drawString((x-left)*scale,(bottom-y)*scale,s)
blank(610,1335,1303,1610)
for y in (1390,1466,1595):text(630,y,'•')
text(662,1390,'Shape Complexity Index, SCI')
text(662,1466,'Building–Fault Orientation')
text(662,1522,'Consistency Index, BFOCI')
text(662,1595,'Building Density Index, BDI')
blank(1330,1495,2115,1575)
text(1345,1552,'•')
text(1390,1552,'InSAR Building State Index, IBSI')
c.showPage();c.save()
print('Created diagram PDF:',args.output,'; width =',page_w,'pt; smallest replacement text = 5.7 pt')
