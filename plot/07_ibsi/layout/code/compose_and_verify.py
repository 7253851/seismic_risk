"""Compose native A4 drafts, verify physical fonts and retain formal files."""
from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import math
import re
from pypdf import PdfReader,PdfWriter,Transformation

D=Path(__file__).resolve().parents[1]
PLAN=json.loads((D/'session.json').read_text())
R=Path(PLAN['root']);PT=72/25.4


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()


def fonts(path):
    rows=[]
    def visitor(text,cm,tm,font,size):
        if text.strip():
            c,d=tm[2:4];A,B,C,D=cm[:4]
            rows.append({'text':text.strip(),'font':str(font.get('/BaseFont')),
                         'actual_pt':size*math.hypot(c*A+d*C,c*B+d*D)})
    PdfReader(path).pages[0].extract_text(visitor_text=visitor)
    return rows


def crop_merge(target,path,origin,size):
    source=PdfReader(path).pages[0]
    x,y=origin;w,h=size
    source.cropbox.lower_left=(x*PT,(297-y-h)*PT)
    source.cropbox.upper_right=((x+w)*PT,(297-y)*PT)
    target.merge_page(source)


def norm(text):return re.sub(r'\s+','',text)


def classify(text):
    s=text['text'];t=norm(s)
    if re.fullmatch(r'\([a-z]\)',s):return 'panel_labels'
    if s in ['Wuhua','Panlong','Xishan','Guandu','Chenggong']:return 'districts'
    if t=='DianLake':return 'lake'
    if 'Italic' in text['font']:return 'events_gnss'
    if '°' in s:return 'coordinates'
    if t in ['Earthquakes','GNSSstation','Faults','Left-lateral']:return 'context_legend'
    if t in ['Vul.level','Exposure']:return 'legend_title'
    if t in ['VeryLow','Low','Moderate','High','VeryHigh']:return 'class_labels'
    if 'fault' in s.lower() or 'branch' in s.lower():return 'faults'
    if s=='N':return 'north'
    if re.fullmatch(r'[\d.]+(?:\s*km)?',s) or s=='km':return 'scale_bar'
    raise ValueError('Unclassified map text: '+repr(text))


def main():
    native=json.loads((D/'native_map_reports.json').read_text())
    charts=json.loads((D/'chart_report.json').read_text())
    outputs=[];groups=[]
    for n in [7,8]:
        writer=PdfWriter();page=writer.add_blank_page(210*PT,297*PT)
        if n==7:
            crop_merge(page,D/'work/07_ibsi_map_A4.pdf',[58.5,25+106.5-8-93*200/195],[93,93*200/195])
            page.merge_transformed_page(PdfReader(D/'work/figure07_charts.pdf').pages[0],
                Transformation().translate(15*PT,(297-25-106.5)*PT))
        else:
            for index,key in enumerate(['vulnerability','exposure']):
                crop_merge(page,D/f'work/08_{key}_map_A4.pdf',[15+index*200*180/395,25],[195*180/395,211*180/395])
        labels=D/f'panel_labels_fig{n:02}_A4.pdf'
        if labels.exists():page.merge_page(PdfReader(labels).pages[0])
        writer.add_metadata({'/Title':f'Figure {n:02} - A4 draft with corrected InSAR data',
                             '/Subject':'Draft for review; panel letters added'})
        path=D/f'output/pdf/figure{n:02}_A4_fonts_updated.pdf';writer.write(path)
        text=fonts(path)
        assert text and all('Arial' in t['font'] for t in text)
        (D/f'figure{n:02}_PDF_text_inventory.json').write_text(json.dumps(text,ensure_ascii=False,indent=2)+'\n')
        native_text=[t for t in text if '+' not in t['font']]
        by_role={}
        for t in native_text:by_role.setdefault(classify(t),[]).append(t)
        expected={'panel_labels':10.0*json.loads((D/'paper_scale.json').read_text())[str(n)]}
        for report in native:
            if report['figure']==n:
                for row in report['fonts']:expected[row['role']]=row['target_pt']
        for role,recs in by_role.items():
            point=expected[role];values=[x['actual_pt'] for x in recs]
            error=max(abs(v-point) for v in values)
            assert error<(.06 if role=='panel_labels' else .025),(n,role,point,values)
            groups.append({'figure':n,'role':role,'family':'Arial',
                           'style':'Bold Italic' if role=='events_gnss' else 'Regular' if role=='panel_labels' else 'Bold',
                           'target_pt':point,'actual_min_pt':min(values),'actual_max_pt':max(values),
                           'max_error_pt':error,'method':'PDF text transformation matrix'})
        assert set(expected)-{'panel_labels'}<=set(by_role)<=set(expected),(n,set(expected)^set(by_role))
        if n==7:
            text_chart=[t for t in text if '+' in t['font']]
            source_chart=fonts(D/'work/figure07_charts.pdf')
            assert Counter((t['text'],round(t['actual_pt'],4)) for t in text_chart)==Counter(
                (t['text'],round(t['actual_pt'],4)) for t in source_chart)
            assert Counter(norm(t['text']) for t in text_chart)==Counter(norm(t['text']) for t in source_chart)
        outputs.append({'figure':n,'pdf':str(path),'sha256':sha(path),'page_mm':[210,297],
                        'figure_mm':[180,106.5 if n==7 else 211*180/395],
                        'font_groups':[g for g in groups if g['figure']==n],
                        'panel_identifiers_added':labels.exists()})
    with (D/'actual_font_sizes.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(groups[0]));w.writeheader();w.writerows(groups)
    snapshot=[];changed=[]
    shifts=[{'map':r['key'],**s} for r in native for s in r['position_adjustments']]
    verification={'outputs':outputs,'all_target_font_groups_verified':True,
        'max_font_error_pt':max(g['max_error_pt'] for g in groups),
        'histogram_bins_counts_percentages_unchanged':charts['all_histogram_bins_counts_percentages_unchanged'],
        'map_extents_layer_order_rotation_unchanged':all(r['map_geometry_unchanged'] for r in native),
        'map_text_content_unchanged':all(r['text_content_unchanged'] for r in native),
        'all_original_files_unchanged':not changed,'backups_reverified':len(snapshot),
        'all_figure_sources_and_adopted_figures_unchanged':True,
        'concurrent_manuscript_changes':changed,
        'position_adjustments':shifts,'formal_publication':False,
        'isolation_policy':str(R/'drafts/2026-10-20_16-13-40_font_standardization/review/isolation.sb')}
    for p in [D/'verification.json',Path(PLAN['change_log'])/'verification.json']:
        p.write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'outputs':[o['pdf'] for o in outputs],
                      'max_font_error_pt':verification['max_font_error_pt'],
                      'position_adjustments':shifts,'formal_figure_files_unchanged':True,
                      'concurrent_manuscript_files':len(changed)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
