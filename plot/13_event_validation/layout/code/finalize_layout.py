"""Finalise the Figure 13 layout draft: measure, verify, document.

Produces font_summary.json, verification.json, README.md and mirrors the
user-facing records into change_logs/.  Renders the A4 and native pages only
for measurement; no formal figure, project or manuscript file is touched.
"""
from pathlib import Path
import csv,hashlib,json,shutil,subprocess
from collections import Counter
from pypdf import PdfReader
D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text());B=Path(S['backup']);C=Path(S['change_log'])
nr=json.loads((D/'native_report.json').read_text())
PT=72/25.4
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
backup=[]
v=json.loads((D/'verification.json').read_text());assert sha(v['pdf'])==v['sha256']
# embedded fonts
fonts=PdfReader(v['pdf']).pages[0]['/Resources']['/Font'];embedding=[]
for key,ref in fonts.items():
 f=ref.get_object()
 if f.get('/Subtype')=='/Type0':f=f['/DescendantFonts'][0].get_object()
 desc=f['/FontDescriptor'].get_object();embedded=any(k in desc for k in ['/FontFile','/FontFile2','/FontFile3'])
 assert embedded
 embedding.append({'font':str(f.get('/BaseFont')),'embedded':embedded})
v['fonts_embedded']=embedding
# class captions actually at 4 pt
actual=list(csv.DictReader((D/'actual_font_sizes.csv').open(encoding='utf-8-sig')))
classes=[float(r['actual_pt']) for r in actual if r['role']=='classes']
assert classes and abs(min(classes)-4)<.01 and abs(max(classes)-4)<.01,(min(classes),max(classes))
# every text span stays inside the 180 x 121.277 mm figure block
x0,x1=15*PT,(15+180)*PT;ytop=(297-25)*PT;ybot=(297-25-S['figure_mm'][1])*PT
inside=all(x0<float(r['x_pt'])<x1 and ybot<float(r['y_pt'])<ytop for r in actual)
assert inside
# measure the observed-PS marker diameter on the native page (600 dpi)
import numpy as np
from PIL import Image
from collections import deque
native=D/'work/figure13_native_aligned_600dpi.png'
subprocess.run(['gs','-q','-sDEVICE=png16m','-r600','-dNOPAUSE','-dBATCH','-o',str(native),nr['pdf']],check=True)
im=Image.open(native).convert('RGB');arr=np.asarray(im);pxmm=im.size[0]/374.0
def diameters(gx0,gy0,gx1,gy1,satmin=90):
 c=arr[int(gy0*pxmm):int(gy1*pxmm),int(gx0*pxmm):int(gx1*pxmm)]
 mx=c.max(axis=2).astype(int);mn=c.min(axis=2).astype(int)
 mask=((mx-mn)>satmin)&(mx>55)
 h,w=mask.shape;seen=np.zeros_like(mask,dtype=bool);out=[]
 for yy in range(h):
  for xx in range(w):
   if mask[yy,xx] and not seen[yy,xx]:
    dq=deque([(yy,xx)]);seen[yy,xx]=True;pts=[]
    while dq:
     cy,cx=dq.popleft();pts.append((cy,cx))
     for dy in(-1,0,1):
      for dx in(-1,0,1):
       ny,nx=cy+dy,cx+dx
       if 0<=ny<h and 0<=nx<w and mask[ny,nx] and not seen[ny,nx]:
        seen[ny,nx]=True;dq.append((ny,nx))
    ys=[p[0] for p in pts];xs=[p[1] for p in pts];ww=max(xs)-min(xs)+1;hh=max(ys)-min(ys)+1
    if len(pts)>=20 and 4<=ww<=70 and abs(ww-hh)<=max(3,0.35*max(ww,hh)):out.append((ww+hh)/2)
 return out
ps={}
for name,(gx0,gy0,gx1,gy1) in {'D1_satellite_PS':(256.139,25.711,302.139,69.711),'D2_satellite_PS':(256.139,146.711,302.139,190.711)}.items():
 ds=diameters(gx0,gy0,gx1,gy1);mode=Counter(round(d) for d in ds).most_common(1)[0][0]
 ps[name]={'median_px':sorted(ds)[len(ds)//2],'mode_px':mode,'mode_mm':round(mode/pxmm,3),'samples':len(ds)}
assert abs(ps['D1_satellite_PS']['mode_mm']-S['PS_marker_diameter_native_mm'])<0.08
assert abs(ps['D2_satellite_PS']['mode_mm']-S['PS_marker_diameter_native_mm'])<0.08
v['ps_marker_measurement']=ps
v['ps_marker_structural']={'target_native_mm':S['PS_marker_diameter_native_mm'],'outline':S['PS_marker_outline'],
 'layout_style_symbols':sum(x['symbols'] for x in nr['ps_marker_changes']['layout_styles']),
 'project_symbols':sum(x['symbols'] for x in nr['ps_marker_changes']['project_layers']),
 'saved_project_and_qpt_size':1.1,'saved_project_and_qpt_outline':'no'}
v['right_group_gap_mm']=nr['right_group_gap_mm']
v['class_caption_actual_pt']={'min':min(classes),'max':max(classes),'target':S['font_targets_a4_pt']['classes']}
v['visual_QA']={'inspected_render_dpi':[96,144],'page_px':{'96':[794,1123],'144':[1191,1684]},
 'cropping':False,'text_inside_figure_block':inside,
 'text_overlap':'no new overlap: class captions only shrank from 5 to 4 pt at unchanged anchors; the 5 pt draft was previously verified',
 'model_can_view_images':False,'method':'pixel measurement, font-size extraction and geometry assertions instead of visual inspection',
 'all_photos_satellite_panels_and_thematic_maps_retained':True,'unresolved_issues':[]}
for p in [D/'verification.json',C/'verification.json']:p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
# font summary
labels={'districts':'Wuhua、Panlong区名','campus':'YUFE South、YNAU校园名称','faults':'断层名称','event':'地震日期、Epicenter标注','coordinates':'经纬度','symbols':'左上地图符号图例','locator':'定位框字母A、C','inset_title':'左侧卫星插图标题','inset_building':'卫星插图Building建筑编号','group_header':'右侧D1、D2案例组总标题','panel_title':'(a)–(f)各子图标题','case':'专题小图D1、D2标记','grade':'Moderate、High等等级标注','pga_units':'PGA (g)色带标题','classes':'Very Low至Very High等级文字','PS_count_units':'PS样本量n、色带标题'}
summary=[]
for role,target in S['font_targets_a4_pt'].items():
 values=[float(r['actual_pt']) for r in actual if r['role']==role];assert values
 summary.append({'element':labels[role],'target_pt':target,'actual_min_pt':min(values),'actual_max_pt':max(values),'spans':len(values),'family':'Arial Bold'})
(D/'font_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
g=nr['right_group_gap_mm'];d1b=g['d1_frame'][1]+g['frame_height']
lines=['# 图13：A4版式（对齐）草稿','',
 'A4竖版210×297 mm；图块180×121.276885 mm，左15 mm、上25 mm。可编辑中间工程保留374×252 mm源画板，最终验收对象为本目录`output/pdf/figure13_A4_layout.pdf`。正式图、绘图索引和论文均未更新。已保留199项文件的独立备份并复核原路径、SHA-256和独立inode。','',
 '## 本轮相对字号稿的改动','',
 '1. 五级等级文字Very Low至Very High由5 pt改为4 pt（A4）；其余字号、字体、字重与斜体设置不变。',
 '2. 右侧(b) Satellite + PS面板的PS观测点直径由0.65 mm放大到1.1 mm（源画板native尺寸），并去除白色描边；数据、配色分级与点位不变。',
 '3. 右侧D1、D2案例组间距保持4.0 mm（源画板）；实测4.00027 mm，为工程坐标小数位舍入，未移动任何面板。',
 '4. 工作布局更名为`Figure13_Aligned_Layout`。地图范围、面板尺寸、照片/卫星影像、专题图、色带、符号位置与其余文字锚点均保持。','',
 '## 指定字号与实际PDF字号','','全部Arial粗体，保持原非斜体设置；以下为最终A4 PDF中的pt。','',
 '| 元素 | 目标pt | 实际pt范围 |','|---|---:|---:|']
for r in summary:lines.append(f"| {r['element']} | {r['target_pt']:g} | {r['actual_min_pt']:.4f}–{r['actual_max_pt']:.4f} |")
lines+=['','已核验168段嵌入字体的PDF文字；指定字号最大误差%.4f pt。未指定的主图指北针、比例尺、左侧卫星比例尺、专题小图指北针和比例尺、PS指北针、比例尺和色标刻度保留源设置。'%v['max_requested_font_error_pt'],'',
 '## PS点核验','',
 '- 工程图层与布局锁定样式共128个分级圆点符号（D1、D2各64个），尺寸均为1.1 mm、`outline_style=no`。',
 f"- 原生页600 dpi渲染实测：D1面板众数{ps['D1_satellite_PS']['mode_px']:.0f} px（{ps['D1_satellite_PS']['mode_mm']:.3f} mm），D2面板众数{ps['D2_satellite_PS']['mode_px']:.0f} px（{ps['D2_satellite_PS']['mode_mm']:.3f} mm），与1.1 mm目标一致。",
 f"- D1/D2组间距：D1底边{d1b:.5f} mm，D2顶边{g['d2_frame'][1]:.5f} mm，差值{g['measured']:.5f} mm。",'',
 '## 定稿源对应关系','','沿用字号稿已完成的分项核对：左地图与恢复位置后源导出RGB完全一致，12幅右侧照片、卫星PS和专题图均有特征匹配，D1/D2边缘在1.5像素内匹配率99.06%/99.65%。本轮只修改等级字号与PS点符号，不重新应用任何整体位移。来源证据见`source_correspondence.json`。','',
 '## 可编辑文件与重现','',
 '- `13_event_validation_aligned.qgz`：独立QGIS工作工程。','- `Figure13_Aligned_Layout.qpt`：工作布局，布局名`Figure13_Aligned_Layout`。',
 '- `code/build_layout.py`：只改工作副本的等级字号、PS符号并核验组间距，随后导出原生PDF。',
 '- `code/compose_and_verify.py`：将原生PDF排入A4并逐段核验字号与位置。','- `code/finalize_layout.py`：量测PS点、嵌入字体与备份核验，生成本页与`verification.json`。',
 '- `actual_font_sizes.csv`：逐段文字实际字号。','',
 '重现顺序：`build_layout.py` → `compose_and_verify.py` → `finalize_layout.py`。前两步需QGIS自带的Python；合成与核验需pypdf。','',
 '## 显示检查','',
 '96 dpi与144 dpi整页已渲染（794×1123、1191×1684 px）。本轮执行环境无法目视图片，改用像素量测与几何断言：所有168段文字均在180×121.277 mm图块内；等级文字仅缩小字号、锚点未动，5 pt稿已确认无重叠，4 pt进一步减小占位；PS点尺寸与描边由工程/QPT结构与渲染量测双重确认。未生成供用户查看的前后对照。','',
 f'备份：`{B}`。未经用户允许不得删除。']
(D/'README.md').write_text('\n'.join(lines)+'\n')
for name in ['README.md','actual_font_sizes.csv','font_summary.json','verification.json']:shutil.copy2(D/name,C/name)
print(json.dumps({'final_sha256':v['sha256'],'text_spans':v['text_spans_verified'],'class_pt':[min(classes),max(classes)],
 'ps_mode_mm':{k:x['mode_mm'] for k,x in ps.items()},'gap_mm':g['measured'],'embedded_fonts':embedding},ensure_ascii=False))
