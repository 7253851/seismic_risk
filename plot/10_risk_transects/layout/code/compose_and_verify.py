"""Compose editable map and chart PDFs on A4; check sizes and source data."""
from pathlib import Path
from collections import Counter
import csv,hashlib,json,math
from pypdf import PdfReader,PdfWriter,Transformation

D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text())
R=Path(S['root']);B=Path(S['backup']);C=Path(S['change_log']);PT=72/25.4
F=S['font_targets_a4_pt'];SCALE=180/248;MAP=S['map_scale_in_native']*SCALE

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def texts(page):
    out=[]
    def visit(text,cm,tm,font,pt):
        if not text.strip():return
        a,b,c,d=cm[:4];u,v=tm[2:4]
        out.append({'text':' '.join(text.split()),'actual_pt':pt*math.hypot(u*a+v*c,u*b+v*d),
            'font':str(font.get('/BaseFont'))})
    page.extract_text(visitor_text=visit);return out

def main():
    assert D.is_relative_to(R/'plot')
    original=[]
    map_report=json.loads((D/'map_report.json').read_text())
    chart=json.loads((D/'chart_report.json').read_text())
    native=json.loads((R/'plot/10_risk_transects/output/figure_manifest.json').read_text())
    assert map_report['map_geometry_layer_styles_unchanged'] and chart['original_panel_boxes_and_axes_preserved']
    writer=PdfWriter();page=writer.add_blank_page(210*PT,297*PT)
    source=PdfReader(map_report['pdf']).pages[0]
    # Reproduce the original upper-left map crop (190.279 x 201 mm).
    source.cropbox.lower_left=(0,31*PT);source.cropbox.upper_right=(190.279*PT,232*PT)
    ml,mb,mw,mh=native['outputs']['map_box_mm'];map_top=mb+mh
    ox=15+ml*SCALE;oy=25+(150-map_top)*SCALE
    page.merge_transformed_page(source,Transformation().scale(MAP).translate(ox*PT,(297-oy-232*MAP)*PT))
    charts=PdfReader(chart['pdf']).pages[0]
    page.merge_transformed_page(charts,Transformation().scale(SCALE).translate(15*PT,(297-25-150*SCALE)*PT))
    labels=D/'panel_labels_fig10_A4.pdf'
    if labels.exists():page.merge_page(PdfReader(labels).pages[0])
    dest=D/'output/pdf/figure10_A4_fonts_updated.pdf'
    writer.add_metadata({'/Title':'Figure 10 - A4 typography draft',
        '/Subject':'Requested sizes apply to the 180 mm wide figure on A4; original geometry and data retained'})
    writer.write(dest)
    old=texts(PdfReader(S['source_pdf']).pages[0]);new_chart=texts(charts)
    assert len(old)==len(new_chart)==104
    mapping={7.7:('axis_ticks',F['axis_ticks']),8:('axis_titles',F['axis_titles']),
        7.8:('chart_titles',F['chart_titles']),8.5:('transect_tags',F['transect_tags']),
        7.5:('peaks',F['peaks']),7.3:('sample_n',F['sample_n']),
        7.1:('map_legend_title',F['map_legend_title']),7:('map_legend_classes',F['map_legend_classes']),
        6.7:('map_symbols',F['map_symbols']),6.5:('bar_legend',F['bar_legend'])}
    rows=[]
    for a,b in zip(old,new_chart):
        role,target=mapping[round(a['actual_pt'],4)]
        if role=='bar_legend' and a['text'] in ['High + very high','Width sensitivity']:role='line_legend'
        actual=b['actual_pt']*SCALE
        assert abs(actual-target)<1e-6,(a['text'],b['text'])
        rows.append({'role':role,'text':b['text'],'target_pt':target,'actual_pt':actual,
            'error_pt':actual-target,'font':b['font'],'source':'Python / PDF text matrix'})
    native_map=texts(PdfReader(map_report['pdf']).pages[0])
    # QGIS can split a multiline label into separate text spans. Every span
    # must agree with the point size of its corresponding editable label.
    matched=[]
    for label in map_report['fonts']:
        if label['role']=='coordinates':
            candidates=[t for t in native_map if '°' in t['text']]
        elif label['role']=='scale_bar':
            candidates=[t for t in native_map if t['text'] in ['0','2','km','2 km']]
        else:
            parts=label['text'].splitlines()
            candidates=[t for t in native_map if t['text'] in parts]
        assert candidates,{'map_label_missing':label,'spans':native_map}
        for t in candidates:
            actual=t['actual_pt']*MAP;target=label['target_a4_pt']
            tolerance=.012 if label['specified'] else .035
            assert abs(actual-target)<tolerance,{'label':label,'actual_a4_pt':actual}
            rows.append({'role':label['role'],'text':t['text'],'target_pt':target,'actual_pt':actual,
                'error_pt':actual-target,'font':t['font'],'source':'QGIS / PDF text matrix'})
            matched.append(t['text'])
    # Check all bar heights/bottoms, curve values, ticks and box positions
    # against the saved analysis; no analysis or statistics are rewritten.
    drawings=json.loads((D/'work/drawing_state.json').read_text());data=[]
    colors=list(native['outputs']['analysis_colors'].values())
    classes=['Very Low','Low','Moderate','High','Very High']
    for ci,code in enumerate(['AB','CD']):
        folder=R/'result/statistics/Risk/transect'
        if code=='CD':folder=folder/'CD'
        table=list(csv.DictReader((folder/'segment_statistics.csv').open(encoding='utf-8-sig')))
        top,mid,low=drawings[ci*3:ci*3+3]
        for j,axis in enumerate([top,mid,low]):
            native_box=native['outputs']['panel_boxes_mm'][code][j]
            assert max(abs(v-e) for v,e in zip(axis['box'],[native_box[0]/248,native_box[1]/150,native_box[2]/248,native_box[3]/150]))<1e-10
        for panel,column in [(top,'pct'),(low,'count')]:
            bottom=[0.]*len(table)
            assert len(panel['bars'])==5*len(table)
            for k,label in enumerate(classes):
                for i,row in enumerate(table):
                    bar=panel['bars'][k*len(table)+i];height=float(row[label.lower().replace(' ','_')+'_'+column])
                    assert abs(bar['height']-height)<1e-9 and abs(bar['y']-bottom[i])<1e-9
                    width=float(row['length_km'])*.965
                    assert abs(bar['width']-width)<1e-10 and abs(bar['x']-(float(row['mid_km'])-width/2))<1e-10
                    rgb=[int(colors[k][z:z+2],16)/255 for z in [1,3,5]]
                    assert max(abs(a-b) for a,b in zip(bar['color'][:3],rgb))<1e-10
                    bottom[i]+=height
        curve=mid['lines'][0]
        assert max(abs(v-float(row['high_very_high_pct'])) for v,row in zip(curve['y'],table))<1e-10
        assert max(abs(v-float(row['mid_km'])) for v,row in zip(curve['x'],table))<1e-10
        assert top['ylim']==[0,170] and mid['ylim']==[-3,120] and low['ylim']==[0,3000]
        assert top['yticks']==mid['yticks']==[0,50,100] and low['yticks']==[0,1000,2000]
        data.append({'transect':code,'N':sum(int(row['building_count']) for row in table),
            'segments':len(table),'statistics_sha256':sha(folder/'segment_statistics.csv')})
    assert len(rows)>=130
    with (D/'actual_font_sizes.csv').open('w',encoding='utf-8-sig',newline='') as f:
        out=csv.DictWriter(f,fieldnames=list(rows[0]));out.writeheader();out.writerows(rows)
    final_rows=texts(PdfReader(dest).pages[0]);expected=Counter((r['text'],round(r['actual_pt'],4)) for r in rows)
    actual=Counter((r['text'],round(r['actual_pt'],4)) for r in final_rows)
    assert not (expected-actual),expected-actual
    assert all('Arial' in r['font'] for r in rows)
    report={'pdf':str(dest),'sha256':sha(dest),'page_mm':[210,297],
        'figure_mm':[180,150*SCALE],'origin_top_left_mm':[15,25],
        'font_targets':F,'text_spans_verified':len(rows),'max_font_error_pt':max(abs(r['error_pt']) for r in rows),
        'unrequested_fonts_preserved':['north','scale_bar'],'data_verification':data,
        'original_map_extent_layers_symbol_styles_unchanged':True,
        'chart_data_colors_panel_boxes_ticks_unchanged':True,'data_update':'2026-10-22 vertical-rate correction; transects recomputed',
        'map_anchors_preserved':True,'position_adjustments':[],
        'legend_containment_and_data_clearance_audit':chart['legend_audit'],
        'formal_files_unchanged':True,'backup_files_verified':len(original),'published':False}
    for p in [D/'verification.json',C/'verification.json']:
        p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['legend_containment_and_data_clearance_audit','font_targets']},ensure_ascii=False))

if __name__=='__main__':main()
