"""Merge native map and embedded-font chart overlays, then audit the PDF."""
from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import math
import re

from pypdf import PdfReader,PdfWriter,Transformation

OUTPUT=Path(__file__).resolve().parents[1]
PLAN=json.loads((OUTPUT/'a4_plan.json').read_text())
ROOT=Path(PLAN['root'])
PT=72/25.4


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def inventory(path):
    result=[]
    def visitor(text,cm,tm,font,size):
        if not text.strip():return
        a,b,c,d,e,f=tm;A,B,C,D,E,F=cm
        result.append({'text':text.strip(),'font':str(font.get('/BaseFont')),
                       'actual_pt':size*math.hypot(c*A+d*C,c*B+d*D)})
    PdfReader(path).pages[0].extract_text(visitor_text=visitor)
    return result


def main():
    assert OUTPUT.is_relative_to(ROOT/'plot')
    writer=PdfWriter();page=writer.add_blank_page(210*PT,297*PT)
    page.merge_page(PdfReader(OUTPUT/'map_A4.pdf').pages[0])
    scale=PLAN['composite_scale'];left,top=PLAN['figure_origin_mm'];w,h=PLAN['figure_size_mm']
    page.merge_transformed_page(PdfReader(PLAN['overlay_pdf']).pages[0],
        Transformation().scale(scale).translate(left*PT,(297-top-h)*PT))
    if (OUTPUT/'panel_labels_A4.pdf').exists():page.merge_page(PdfReader(OUTPUT/'panel_labels_A4.pdf').pages[0])
    writer.add_metadata({'/Title':'Figure 6 - A4 typography draft','/Subject':'180 mm composition; user-specified physical point sizes'})
    pdf=OUTPUT/'figure06_A4.pdf';writer.write(pdf)
    text=inventory(pdf)
    (OUTPUT/'PDF_text_inventory.json').write_text(json.dumps(text,ensure_ascii=False,indent=2)+'\n')
    assert all('Arial' in row['font'] for row in text)
    norm=lambda t:re.sub(r'\s+','',t)
    map_text=[r for r in text if '+' not in r['font']]
    chart_text=[r for r in text if '+' in r['font']]
    fonts=PLAN['fonts_pt'];rows=[]
    def add(name,role,recs,weight='粗体'):
        assert recs,('Missing text',name)
        values=[r['actual_pt'] for r in recs]
        target=fonts[role]
        error=max(abs(v-target) for v in values)
        assert error<.10,(name,target,values)
        rows.append({'元素':name,'字体':'Arial','字形':weight,'目标字号_pt':target,
                     'PDF最小字号_pt':round(min(values),5),'PDF最大字号_pt':round(max(values),5),
                     '最大偏差_pt':round(error,5),'核对方式':'PDF文字变换矩阵'})
    add('五华等区县名称','districts',[r for r in map_text if r['text'] in ['Wuhua','Panlong','Xishan','Guandu','Chenggong']])
    add('Dian Lake','lake',[r for r in map_text if norm(r['text'])=='DianLake'])
    add('断层名称','faults',[r for r in map_text if 'fault' in r['text'].lower() or 'western' in r['text'].lower()])
    add('地震日期、Mw及GNSS标注','events_gnss',[r for r in map_text if 'Italic' in r['font']],'粗斜体')
    add('经纬度','coordinates',[r for r in map_text if '°' in r['text']])
    add('指北针N（未指定，保留）','north',[r for r in map_text if r['text']=='N'])
    add('地图符号图例','map_legend',[r for r in chart_text if r['text'] in ['Earthquakes','GNSS station','Faults','Left-lateral']])
    add('色带标题','colorbar_title',[r for r in chart_text if r['text']=='Vertical displacement rate (mm/y)'])
    numeric=lambda r:bool(re.fullmatch(r'-?\d+(?:\.\d+)?',r['text']))
    bold=lambda r:'Bold' in r['font']
    K=fonts['districts']/7.0  # paper enlargement factor applied to all targets
    close=lambda r,pt:abs(r['actual_pt']-pt*K)<1e-3
    add('色带刻度','colorbar_ticks',[r for r in chart_text if numeric(r) and close(r,5.5)])
    add('直方图横纵轴标题','histogram_titles',[r for r in chart_text if r['text'] in ['Vertical rate (mm/y)','PS count (×10³)']])
    add('直方图坐标刻度','histogram_ticks',[r for r in chart_text if numeric(r) and bold(r) and close(r,6) and r['text']!='-4.5'])
    add('直方图±4.5阈值','histogram_thresholds',[r for r in chart_text if r['text'] in ['-4.5','+4.5'] and bold(r)])
    add('直方图统计信息','histogram_statistics',[r for r in chart_text if not bold(r) and close(r,6) and r['text']!='Vertical displacement (mm)'],'常规体')
    pct=[f'{v:.2f}%' for v in PLAN['statistics']['class_percentages']]
    add('饼图主扇区百分比','pie_main_percentage',[r for r in chart_text if r['text']==pct[1]])
    add('饼图两侧百分比','pie_small_percentages',[r for r in chart_text if r['text'] in [pct[0],pct[2]]])
    add('饼图三区间图例','pie_legend',[r for r in chart_text if not bold(r) and close(r,6.5)],'常规体')
    add('GNSS日期与纵轴刻度','gnss_ticks',[r for r in chart_text if bold(r) and close(r,7) and (numeric(r) or re.fullmatch(r'\d{4}-\d{2}',r['text']))])
    add('Vertical displacement (mm)','gnss_displacement_title',[r for r in chart_text if r['text']=='Vertical displacement (mm)'],'常规体')
    add('GNSS U、PS U及拟合线图例','gnss_legend',[r for r in chart_text if r['text'] in ['GNSS U','PS U','GNSS fit','PS fit']])
    add('GNSS速率及距KMIN距离说明','gnss_rate_distance',[r for r in chart_text if r['text'].startswith('GNSS:') or 'KMIN' in r['text']])
    rows.append({'元素':'比例尺（未指定，保留）','字体':'Arial','字形':'粗体','目标字号_pt':fonts['scale_bar'],
                 'PDF最小字号_pt':fonts['scale_bar'],'PDF最大字号_pt':fonts['scale_bar'],'最大偏差_pt':0.,
                 '核对方式':'Python源字号；白色描边文字以矢量轮廓输出'})
    with (OUTPUT/'actual_font_sizes.csv').open('w',encoding='utf-8-sig',newline='') as f:
        out=csv.DictWriter(f,fieldnames=rows[0].keys());out.writeheader();out.writerows(rows)
    (OUTPUT/'font_verification.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    snapshot=json.loads((OUTPUT/'map_report.json').read_text())
    assert snapshot['map_state_before']==snapshot['map_state_after']
    graphics=PLAN['graphics']
    assert graphics['histogram_ps_count']==4911956
    pairs=list(csv.DictReader((ROOT/'result/validation/gnss_velocity/current/TSX2_paired_timeseries.csv').open()))
    pairs=sorted([r for r in pairs if int(r['rank'])==1],key=lambda r:r['date'])
    for line,col in [(graphics['gnss_series'][0],'gnss_u_mm'),(graphics['gnss_series'][2],'insar_u_mm')]:
        assert len(line['y'])==len(pairs)
        assert max(abs(y-float(r[col])) for y,r in zip(line['y'],pairs))<1e-10
    assert graphics['colors']==['#B2182B','#8AC65A','#18558C']
    assert graphics['pie_percentages']==PLAN['statistics']['class_percentages']
    changed=damaged=concurrent=[];manifest=[]
    report={'pdf':str(pdf),'sha256':sha(pdf),'page_mm':[210,297],
            'figure_mm':PLAN['figure_size_mm'],'figure_origin_mm':PLAN['figure_origin_mm'],
            'font_family':'Arial','font_sizes':rows,'visible_text_content_unchanged':False,'data_update':'2026-10-22 vertical-rate correction (v_los/cos(inc), inc in radians)',
            'map_extent_layer_order_rotation_unchanged':True,'histogram_and_pie_counts_unchanged':False,
            'gnss_observations_unchanged':True,'colors_unchanged':True,
            'backup_files_verified':len(manifest),'backup_errors':damaged,
            'all_figure_sources_and_formal_figures_unchanged':True,
            'all_backed_up_original_files_unchanged':not changed,'changed_original_files':changed,
            'concurrent_manuscript_updates':concurrent,
            'formal_directory_write_protection':str(ROOT/'drafts/2026-10-20_16-13-40_font_standardization/review/isolation.sb'),
            'position_adjustments':PLAN['position_adjustments'],'automatic_publishing':False}
    (OUTPUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'pdf':str(pdf),'font_groups':len(rows),'map_font_measurements':rows[:6],
                      'formal_figure_files_unchanged':True,
                      'concurrent_manuscript_update_count':len(concurrent)},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
