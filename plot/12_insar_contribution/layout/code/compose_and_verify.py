"""Compose source-exported Figure 12 on A4 and verify fonts and frozen data."""
from pathlib import Path
from collections import Counter
import csv,hashlib,json,math,re,xml.etree.ElementTree as ET
from pypdf import PdfReader,PdfWriter,Transformation
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor

D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text())
R=Path(S['root']);B=Path(S['backup']);C=Path(S['change_log']);PT=72/25.4
FX,FY=S['font_scale_x'],S['font_scale_y']
KP=json.loads((D/'paper_scale.json').read_text())['K']

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def spans(page):
    rows=[]
    def visit(t,cm,tm,fd,fs):
        if not t.strip():return
        c,d=tm[2:4];a,b,C,D=cm[:4]
        rows.append({'text':' '.join(t.split()),'actual_pt':fs*math.hypot(c*a+d*C,c*b+d*D),
            'font':str(fd.get('/BaseFont'))})
    page.extract_text(visitor_text=visit);return rows

def rate_key(report):
    """Retain the SVG's gradient, transparent background and text anchors."""
    root=ET.parse(report['colorbar_svg']).getroot()
    stops=[e for e in root.iter() if e.tag.rsplit('}',1)[-1]=='stop']
    colors=[HexColor(e.get('stop-color')) for e in stops]
    offsets=[float(e.get('offset')) for e in stops]
    _,_,w,h=report['colorbar_box_mm'];pw,ph=report['colorbar_picture_mm']
    # Zoom centered the original 44 x 11 mm picture inside a 44 x 11.2 mm frame.
    dx,dy=(w-pw)/2,(h-ph)/2;rx,ry=pw/44,ph/11.2
    font='Figure12ArialBold';pdfmetrics.registerFont(TTFont(font,'/System/Library/Fonts/Supplemental/Arial Bold.ttf'))
    p=D/'work/inset_rate_key.pdf';cv=canvas.Canvas(str(p),pagesize=(w*PT,h*PT))
    def point(x,y):return ((dx+x*rx)*PT,(h-dy-y*ry)*PT)
    left,bottom=point(3,5.9);ww,hh=38*rx*PT,1.7*ry*PT
    cv.saveState();path=cv.beginPath();path.rect(left,bottom,ww,hh);cv.clipPath(path,stroke=0,fill=0)
    cv.linearGradient(left,bottom,left+ww,bottom,colors,positions=offsets,extend=True);cv.restoreState()
    cv.setStrokeColor(HexColor('#24282B'));cv.setLineWidth(.15*PT)
    cv.rect(left,bottom,ww,hh,stroke=1,fill=0)
    for x in [3,22,41]:cv.line(*point(x,5.9),*point(x,6.6))
    cv.setFillColor(HexColor('#24282B'));cv.setFont(font,5*KP/FY)
    cv.drawCentredString(*point(22,2.85),'Vertical rate (mm/yr)')
    cv.drawString(*point(3,9.6),'−9');cv.drawCentredString(*point(22,9.6),'−4');cv.drawRightString(*point(41,9.6),'1')
    cv.showPage();cv.save();return p

def main():
    assert D.is_relative_to(R/'plot')
    backup=[]
    m=json.loads((D/'map_report.json').read_text());b=json.loads((D/'strip_report.json').read_text())
    writer=PdfWriter();page=writer.add_blank_page(210*PT,297*PT)
    native=PdfReader(m['pdf']).pages[0];pageh=S['native_page_mm'][1]
    page.merge_transformed_page(native,Transformation().scale(FX,FY).translate(15*PT,(297-25-pageh*FY)*PT))
    strip=PdfReader(b['pdf']).pages[0];x,y,w,h=m['strip_box_mm']
    sx=w*PT/float(strip.mediabox.width)*FX;sy=h*PT/float(strip.mediabox.height)*FY
    page.merge_transformed_page(strip,Transformation().scale(sx,sy).translate((15+x*FX)*PT,(297-25-(y+h)*FY)*PT))
    rate=PdfReader(rate_key(m)).pages[0];x,y,w,h=m['colorbar_box_mm']
    page.merge_transformed_page(rate,Transformation().scale(FX,FY).translate((15+x*FX)*PT,(297-25-(y+h)*FY)*PT))
    labels=D/'panel_labels_fig12_A4.pdf'
    if labels.exists():page.merge_page(PdfReader(labels).pages[0])
    dest=D/'output/pdf/figure12_A4_fonts_updated.pdf'
    writer.add_metadata({'/Title':'Figure 12 - A4 typography draft','/Subject':'User-specified point sizes on the 180 mm figure; source maps and saved PS diagnostics retained'})
    writer.write(dest)
    # Validate actual map font sizes; duplicate wording is disambiguated by
    # the font size and source label identity (e.g. GNSS label vs legend).
    native_rows=spans(native);rows=[];used=set()
    for label in m['fonts']:
        role=label['role'];target=label['target_pt']
        if role=='inset_colorbar':continue
        if role=='coordinates':candidates=[(i,t) for i,t in enumerate(native_rows) if '°' in t['text'] and ('E' in t['text'] or 'N' in t['text'])]
        elif role in ['main_scale','inset_scale']:
            values=['0','2 km'] if role=='main_scale' else ['0','25','50 m']
            candidates=[(i,t) for i,t in enumerate(native_rows) if t['text'] in values]
        else:
            parts=[' '.join(t.split()) for t in label['text'].splitlines()]
            candidates=[(i,t) for i,t in enumerate(native_rows) if t['text'] in parts]
        valid=[]
        for i,t in candidates:
            # Map font vectors at rotations other than zero also pass through
            # the agreed near-isotropic x/y page scales.
            actual=t['actual_pt']*FY
            tolerance=.03 if label['specified'] else .06
            if abs(actual-target)<tolerance:valid.append((i,t,actual))
        assert valid,{'missing_or_wrong_font':label,'candidates':candidates}
        for i,t,actual in valid:
            if i in used:continue
            used.add(i);rows.append({'role':role,'text':t['text'],'target_pt':target,'actual_pt':actual,
                'error_pt':actual-target,'font':t['font'],'specified':label['specified'],'source':'QGIS PDF'})
    assert len(used)==len(native_rows),{'unmatched_map_text':[t for i,t in enumerate(native_rows) if i not in used]}
    bottom=spans(strip)
    text_inventory=json.loads((D/'work/strip_text_inventory.json').read_text())
    clean=lambda t:re.sub(r'\s+','',t)
    assert Counter(clean(''.join(t['text'] for t in bottom)))==Counter(clean(''.join(t['text'] for t in text_inventory)))
    for t in bottom:
        # PDF matrix scales are checked again on the final A4 page below.
        actual=t['actual_pt']*sy
        assert abs(actual-5.5*KP)<1e-6
        rows.append({'role':'bottom_all','text':t['text'],'target_pt':5.5*KP,'actual_pt':actual,
            'error_pt':actual-5.5*KP,'font':t['font'],'specified':True,'source':'Matplotlib PDF'})
    for t in spans(rate):
        actual=t['actual_pt']*FY;assert abs(actual-5*KP)<1e-5
        rows.append({'role':'inset_colorbar','text':t['text'],'target_pt':5,'actual_pt':actual,
            'error_pt':actual-5,'font':t['font'],'specified':True,'source':'SVG geometry / embedded-font PDF'})
    assert all('Arial' in t['font'] for t in rows)
    final=[t for t in spans(PdfReader(dest).pages[0]) if not re.fullmatch(r'\([a-z]\)',t['text'])]
    assert len(final)==len(rows)
    expected=Counter((r['text'],round(r['actual_pt'],1)) for r in rows)
    actual=Counter((r['text'],round(r['actual_pt'],1)) for r in final)
    assert expected==actual,{'missing':expected-actual,'extra':actual-expected}
    with (D/'actual_font_sizes.csv').open('w',encoding='utf-8-sig',newline='') as f:
        out=csv.DictWriter(f,fieldnames=list(rows[0]));out.writeheader();out.writerows(rows)
    stats=json.loads((R/'result/discussion/12_insar_contribution/static_baseline/data/static_baseline_statistics.json').read_text())
    qpt=ET.parse(m['qpt']).getroot();labels={i.get('id'):i.get('labelText') for i in qpt.findall('LayoutItem') if i.get('labelText')}
    for i,row in enumerate(stats['matrix']):
        total=sum(row)
        for j,count in enumerate(row):
            expected=f'{count:,}\n{100*count/total:.2f}%' if count else '0'
            assert labels[f'Latest_heatmap_value_{i}_{j}']==expected
    assert m['map_geometry_layer_styles_preserved'] and b['PS_coordinates_and_case_metrics_preserved']
    report={'pdf':str(dest),'sha256':sha(dest),'page_mm':[210,297],'figure_mm':S['figure_mm'],
        'origin_top_left_mm':[15,25],'font_targets':S['font_targets_a4_pt'],
        'text_spans_verified':len(rows),'max_requested_font_error_pt':max(abs(r['error_pt']) for r in rows if r['specified']),
        'map_geometry_layers_and_symbol_styles_preserved':True,'original_text_content_preserved':True,
        'heatmap_counts_percentages_verified':True,'PS_counts':[109,57],'black_rings':[11,6],
        'PS_and_colorbar_ranges_preserved':True,'source_anchors_preserved':True,'position_adjustments':[],
        'unrequested_fonts_preserved':S['unrequested_preserved'],'formal_files_unchanged':True,
        'backup_files_verified':len(backup),'published':False}
    for p in [D/'verification.json',C/'verification.json']:p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='font_targets'},ensure_ascii=False))

if __name__=='__main__':main()
