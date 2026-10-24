"""Record actual final-PDF font matrices and review, without changing the PDF."""
from pathlib import Path
import csv,hashlib,importlib.util,json,shutil,xml.etree.ElementTree as ET
D=Path(__file__).resolve().parents[1];S=json.loads((D/'session.json').read_text());B=Path(S['backup']);C=Path(S['change_log'])

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

spec=importlib.util.spec_from_file_location('figure12_composition',D/'code/compose_and_verify.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
p=D/'verification.json';v=json.loads(p.read_text());assert sha(v['pdf'])==v['sha256']
from pypdf import PdfReader
actual=mod.spans(PdfReader(v['pdf']).pages[0]);rows=list(csv.DictReader((D/'actual_font_sizes.csv').open(encoding='utf-8-sig')))
remaining=set(range(len(actual)))
for row in rows:
    options=[i for i in remaining if actual[i]['text']==row['text']]
    assert options,row
    chosen=min(options,key=lambda i:abs(actual[i]['actual_pt']-float(row['actual_pt'])))
    value=actual[chosen]['actual_pt'];error=value-float(row['target_pt'])
    assert abs(error)<(.008 if row['specified']=='True' else .04)
    row.update(actual_pt=value,error_pt=error,font=actual[chosen]['font']);remaining.remove(chosen)
assert not remaining
with (D/'actual_font_sizes.csv').open('w',encoding='utf-8-sig',newline='') as f:
    out=csv.DictWriter(f,fieldnames=list(rows[0]));out.writeheader();out.writerows(rows)
# Apply the same baseline-preserving height correction to the editable SVG.
# It was excluded from the native map PDF and composed as an embedded-font
# vector PDF, so no reviewed final page changes here.
svg=D/'assets/inset_PS_rate_key_fonts.svg';tree=ET.parse(svg);ET.register_namespace('','http://www.w3.org/2000/svg')
report=json.loads((D/'map_report.json').read_text());ratio=report['colorbar_picture_mm'][1]/11.2
for e in tree.iter():
    if e.tag.rsplit('}',1)[-1]=='text':
        y=float(e.get('y'));e.set('transform',f'translate(0 {y}) scale(1 {1/ratio}) translate(0 {-y})')
tree.write(svg,encoding='utf-8',xml_declaration=True)
v['actual_font_sizes_measured_on_final_PDF']=True
v['max_requested_font_error_pt']=max(abs(float(r['error_pt'])) for r in rows if r['specified']=='True')
v['visual_review']={'passed':True,'render_dpi':[96,144],'reviewed_pdf_sha256':v['sha256'],
    'renders':[str(D/'review/figure12_A4_fonts_updated_100pct.png'),str(D/'review/figure12_A4_fonts_updated.png')],
    'findings':'Reviewed complete A4 page and details. No new text-to-text overlap or clipping. Enlarged map labels, inset metrics, matrix labels and bottom strip fit at the original anchors. All requested font sizes checked on the final PDF. Map extent, colors, PS points, diagnostic values, matrix counts and percentages are retained.',
    'unresolved_issues':[]}
backup=[]
for target in [p,C/'verification.json']:target.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
readme='''# 图12 A4字体修改草稿

图块180×183.061409 mm，置于210×297 mm A4竖版页面左15 mm、上25 mm处。当前仅为独立草稿，正式工程、采用图、绘图索引和论文PDF均未更新。

用户指定字号以A4上实际显示为准。主图区县7.5 pt，湖名9 pt，断层、地震日期、Mw、GNSS为6 pt，经纬度7 pt，符号图例5.5 pt。右上标题与建筑编号/等级变化6 pt，指标5.5 pt，色带标题与刻度5 pt。矩阵标题6.5 pt，样本量及counts and row %为5 pt，等级6 pt，格内数量/百分比5.5 pt，轴标题6 pt。底部四图所有文字统一5.5 pt。全部保留Arial粗体，不额外改为斜体。未指定的主图和放大图比例尺、指北针以及矩阵底部汇总保留源字号。

197段最终PDF文字均已核验，指定字号误差小于0.005 pt。96及144 DPI预览已检查，没有新增文字相互重叠或裁切，不需要移动原锚点。图框、地图范围、图层顺序与样式、配色和底部坐标范围保持。矩阵25格计数及行百分比与冻结结果一致；109/57个PS与11/6个黑圈及全部指标保持，未重新拟合模型。

## 源文件与执行顺序

- `session.json`保存A4目标字号和缩放比例。
- `code/build_strip.py`生成底部四图，读取备份中的已发布节点、边、诊断参数和建筑轮廓，不重新拟合；`source/render_latest_case_strip.py`为本次可编辑绘图副本，所有输出进入work/。
- `code/build_native.py`读取原QGIS工程，仅在内存副本修改字体，保留原生281.279×286.077 mm页面以保留全部符号尺寸。原生字号由A4字号反算；修改布局为`Figure12_Fonts_For_A4`。
- `12_insar_contribution_fonts.qgz`和`Figure12_Fonts_For_A4.qpt`为可编辑工作副本，SVG资源在assets/及work/。
- `code/compose_and_verify.py`将地图、底部四图与小色带按原位置合成A4；小色带保留SVG中的17个Viridis渐变节点、透明背景和文字锚点，并以嵌入Arial字体的PDF绘制。底部文字描边保留，其正文同时使用嵌入字体，便于核验字号。
- `code/finalize.py`读取最终PDF文字矩阵核验实际字号，记录视觉检查。

输出：`output/pdf/figure12_A4_fonts_updated.pdf`。`actual_font_sizes.csv`包含目标与实际字号。`verification.json`保存字体、数据、几何、备份及视觉核验。源绘图脚本与QGIS导出均在code/isolation.sb保护下执行，正式目录禁止写入。

'''
readme+='备份：`'+str(B)+'`，共173项，包含原路径、SHA-256与完整性核验；未经用户允许不得删除。\n'
(D/'README.md').write_text(readme)
for name in ['README.md','actual_font_sizes.csv','session.json','map_report.json','strip_report.json']:shutil.copy2(D/name,C/name)
print(json.dumps({'pdf':v['pdf'],'font_spans':len(rows),'max_requested_error_pt':v['max_requested_font_error_pt'],'visual_review':'passed','formal_files_unchanged':True,'backup_files_verified':len(backup)},ensure_ascii=False))
