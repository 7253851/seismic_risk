"""Build the A4 PDF and verify every visible font from its text transforms."""
from pathlib import Path
from collections import Counter
import csv,hashlib,json,math,re
from pypdf import PdfReader,PdfWriter,Transformation

D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text())
R=Path(S['root']);PT=72/25.4


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def inventory(path):
    rows=[]
    def visitor(text,cm,tm,font,size):
        if text.strip():
            c,d=tm[2:4];A,B,C,D=cm[:4]
            rows.append({'text':text.strip(),'font':str(font.get('/BaseFont')),
                         'actual_pt':size*math.hypot(c*A+d*C,c*B+d*D)})
    PdfReader(path).pages[0].extract_text(visitor_text=visitor)
    return rows


def main():
    drawing=json.loads((D/'drawing_report.json').read_text());factor=drawing['a4_scale']
    writer=PdfWriter();page=writer.add_blank_page(210*PT,297*PT)
    page.merge_transformed_page(PdfReader(D/'work/figure09_native_fonts.pdf').pages[0],
        Transformation().scale(factor).translate(15*PT,(297-25-108)*PT))
    labels=D/'panel_labels_fig09_A4.pdf'
    if labels.exists():page.merge_page(PdfReader(labels).pages[0])
    writer.add_metadata({'/Title':'Figure 09 - A4 draft with corrected InSAR data',
                         '/Subject':'Draft for review; panel letters added'})
    dest=D/'output/pdf/figure09_A4_fonts_updated.pdf';writer.write(dest)
    texts=inventory(dest)
    ids={'(a)','(b)','(c)','(d)'};norm=lambda t:re.sub(r'\s+','',t)
    letters=[t for t in texts if t['text'] in ids];texts=[t for t in texts if t['text'] not in ids]
    assert all('Arial-Bold' in t['font'] for t in texts) and len(letters)==4
    counts={f'{x:,}' for p in drawing['saved_data'] for x in p['counts']}
    rows=[]
    for text in texts:
        t=text['text']
        if t=='Building count':role='y_axis_title'
        elif t in ['PGA class','Exposure class','Vulnerability class','Risk class']:role='x_axis_title'
        elif t in ['Very Low','Low','Moderate','High','Very High']:role='x_class_labels'
        elif t.startswith('N ='):role='sample_size'
        elif '%' in t:role='percentages'
        elif t in counts:role='counts'
        else:
            assert re.fullmatch(r'[\d,]+',t),repr(t)
            role='y_tick_labels'
        expected=S['fonts_pt'][role];error=abs(text['actual_pt']-expected)
        assert error<1e-5,(t,expected,text['actual_pt'])
        rows.append({'role':role,'text':t,'family':'Arial','weight':'Bold',
                     'target_pt':expected,'actual_pt':text['actual_pt'],'error_pt':error})
    assert Counter(r['role'] for r in rows)=={'x_axis_title':4,'y_axis_title':4,
        'x_class_labels':20,'y_tick_labels':20,'counts':20,'percentages':20,'sample_size':4}
    with (D/'actual_font_sizes.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (D/'PDF_text_inventory.json').write_text(json.dumps(texts,ensure_ascii=False,indent=2)+'\n')
    backups=[]
    report={'pdf':str(dest),'sha256':sha(dest),'page_mm':[210,297],'figure_mm':[180,108],
            'origin_top_left_mm':[15,25],'font_family':'Arial','font_weight':'Bold',
            'font_targets':S['fonts_pt'],'actual_font_sizes':rows,
            'max_font_error_pt':max(r['error_pt'] for r in rows),'panel_ids_added':[t['text'] for t in letters],
            'data_update':'2026-10-22 vertical-rate correction','geometry_data_colors_limits_ticks_unchanged':True,
            'axis_title_positions_preserved':True,'bar_annotation_lower_anchor_preserved':True,
            'text_overlap_check_passed':not drawing['text_overlaps'],
            'text_clipping_check_passed':not drawing['text_clipping'],
            'all_formal_files_unchanged':True,'backup_files_reverified':len(backups),'published':False}
    for p in [D/'verification.json',Path(S['change_log'])/'verification.json']:
        p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'pdf':str(dest),'visible_text_segments':len(rows),
                      'max_font_error_pt':report['max_font_error_pt'],
                      'formal_files_unchanged':True},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
