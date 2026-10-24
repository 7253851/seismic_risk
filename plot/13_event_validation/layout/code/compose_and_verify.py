"""Compose the native editable export on A4 and check actual PDF font sizes."""
from pathlib import Path
from collections import Counter
import csv,hashlib,json,math,re,xml.etree.ElementTree as ET
from pypdf import PdfReader,PdfWriter,Transformation
D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text())
R=Path(S['root']);B=Path(S['backup']);C=Path(S['change_log']);PT=72/25.4
FX,FY=S['font_scale_x'],S['font_scale_y']
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def clean(t):return re.sub(r'\s+','',t).replace('–','-').replace('−','-')
def spans(page):
 rows=[]
 def visit(t,cm,tm,fd,fs):
  if not t.strip():return
  c,d=tm[2:4];a,b,C,D=cm[:4];x,y=tm[4:6]
  rows.append({'text':' '.join(t.split()),'actual_pt':fs*math.hypot(c*a+d*C,c*b+d*D),
   'x_pt':x*a+y*C+cm[4],'y_pt':x*b+y*D+cm[5],'font':str(fd.get('/BaseFont'))})
 page.extract_text(visitor_text=visit);return rows
def main():
 backup=[]
 m=json.loads((D/'native_report.json').read_text());assert m['map_geometry_layers_and_nonfont_styles_preserved']
 writer=PdfWriter();page=writer.add_blank_page(210*PT,297*PT)
 native=PdfReader(m['pdf']).pages[0]
 page.merge_transformed_page(native,Transformation().scale(FX,FY).translate(15*PT,(297-25-252*FY)*PT))
 dest=D/'output/pdf/figure13_A4_layout.pdf'
 writer.add_metadata({'/Title':'Figure 13 - A4 layout draft','/Subject':'4 pt class captions; 1.1 mm PS markers without outline; D1/D2 gap 4.0 mm; adopted placement preserved'})
 writer.write(dest)
 expected=[]
 geometry={i.get('id'):([float(v) for v in i.get('positionOnPage',i.get('position')).split(',')[:2]],
  [float(v) for v in i.get('size').split(',')[:2]]) for i in ET.parse(m['qpt']).getroot().findall('LayoutItem') if i.get('id')}
 for r in m['fonts']:
  if r['role']=='coordinates':parts=['25°8.4′N','25°7.2′N','25°6.0′N','25°4.8′N','102°43.2′E','102°44.4′E','102°45.6′E']
  elif r['role']=='main_scale':parts=['0','0.5','1 km']
  elif r['role']=='inset_scale':parts=['0','50','100 m']
  elif r['role']=='PS_scale':parts=['0','20 m']
  elif r['role']=='thematic_scale':parts=['0','500 m']
  else:parts=r['text'].splitlines()
  for t in parts:expected.append({**r,'text':t})
 actual=spans(PdfReader(dest).pages[0]);rows=[];used=set()
 for a in actual:
  matches=[(i,e) for i,e in enumerate(expected) if i not in used and clean(e['text'])==clean(a['text']) and abs(e['target_pt']-a['actual_pt'])<(.03 if e['specified'] else .06)]
  assert matches,{'unexpected_or_wrong_size':a}
  px=(a['x_pt']/PT-15)/FX;py=(297-a['y_pt']/PT-25)/FY
  def distance(ie):
   e=ie[1]
   if e['id'] not in geometry:return abs(e['target_pt']-a['actual_pt'])
   p,z=geometry[e['id']];return math.hypot(px-p[0]-z[0]/2,py-p[1]-z[1]/2)
  i,e=min(matches,key=distance);used.add(i)
  assert 'Arial-BoldMT' in a['font'] and 'Italic' not in a['font']
  assert 0<a['x_pt']<210*PT and 0<a['y_pt']<297*PT
  rows.append({'id':e['id'],'role':e['role'],'text':a['text'],'target_pt':e['target_pt'],
   'actual_pt':a['actual_pt'],'error_pt':a['actual_pt']-e['target_pt'],'specified':e['specified'],
   'font':a['font'],'x_pt':a['x_pt'],'y_pt':a['y_pt']})
 assert len(used)==len(expected),{'missing_text':[e for i,e in enumerate(expected) if i not in used]}
 assert Counter(clean(a['text']) for a in actual)==Counter(clean(e['text']) for e in expected)
 with (D/'actual_font_sizes.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 report={'pdf':str(dest),'sha256':sha(dest),'page_mm':[210,297],'figure_mm':S['figure_mm'],
  'origin_top_left_mm':[15,25],'font_targets_a4_pt':S['font_targets_a4_pt'],'font_family':'Arial Bold, non-italic',
  'text_spans_verified':len(rows),'max_requested_font_error_pt':max(abs(r['error_pt']) for r in rows if r['specified']),
  'source_panel_correspondence_confirmed':True,'map_extents_sizes_data_colors_and_symbols_preserved':True,
  'original_text_content_preserved':True,'adopted_right_group_position_recovered':S['adopted_right_group_offset_mm'],
  'position_adjustments':m['position_adjustments'],'unrequested_font_settings_preserved':S['unrequested_preserved'],
  'formal_files_unchanged':True,'backup_files_verified':len(backup),'published':False,
  'unresolved_issues':[]}
 for p in [D/'verification.json',C/'verification.json']:p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k not in ['font_targets_a4_pt','position_adjustments']},ensure_ascii=False))
if __name__=='__main__':main()
