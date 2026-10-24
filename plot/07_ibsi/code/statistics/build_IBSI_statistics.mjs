import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../output/07_ibsi/statistics');
const fig = path.dirname(out);
const data = JSON.parse(await fs.readFile(path.join(out, 'IBSI_statistics_data.json'), 'utf8'));
const workbook = Workbook.create();
const primary = workbook.worksheets.add('建筑指标统计');
const ps = workbook.worksheets.add('原始PS统计');
const params = workbook.worksheets.add('处理参数');
const defs = workbook.worksheets.add('字段定义');
const navy = '#28465F', ink = '#202A33', muted = '#566879', rule = '#CBD5DE';

function base(sheet, lastCell, widths, tabColor) {
  sheet.showGridLines = false;
  sheet.tabColor = tabColor;
  const range = sheet.getRange(`A1:${lastCell}`);
  range.format.font = { name: 'Arial', size: 11, color: ink };
  range.format.verticalAlignment = 'center';
  range.format.rowHeight = 26;
  for (const [col, px] of Object.entries(widths)) {
    sheet.getRange(`${col}1:${col}${lastCell.match(/\d+/)[0]}`).format.columnWidthPx = px;
  }
  sheet.getRange('A1').format.rowHeight = 12;
}
function title(sheet, text, context, lastCol) {
  sheet.getRange('A2').values = [[text]];
  sheet.getRange('A2').format.font = { name: 'Arial', size: 15, bold: true, color: navy };
  sheet.getRange(`A3:${lastCol}3`).format.borders = { bottom: { style: 'thin', color: rule } };
  sheet.getRange('A3').values = [[context]];
  sheet.getRange('A3').format.font = { name: 'Arial', size: 10, italic: true, color: muted };
  sheet.getRange('A3').format.rowHeight = 30;
}
function header(sheet, row, lastCol, labels) {
  sheet.getRange(`A${row}:${lastCol}${row}`).values = [labels];
  const range = sheet.getRange(`A${row}:${lastCol}${row}`);
  range.format = { fill: navy, font: { name: 'Arial', size: 11, bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center', verticalAlignment: 'center', rowHeight: 32,
    borders: { insideVertical: { style: 'thin', color: '#FFFFFF' } } };
}
function statisticalFormat(sheet, start, end) {
  sheet.getRange(`D${start}:N${end}`).format.horizontalAlignment = 'right';
  sheet.getRange(`D${start}:D${end}`).setNumberFormat('#,##0');
  sheet.getRange(`E${start}:L${end}`).setNumberFormat('#,##0.000');
  sheet.getRange(`M${start}:N${end}`).setNumberFormat('#,##0');
  sheet.getRange(`A${end}:N${end}`).format.borders = { bottom: { style: 'thin', color: rule } };
}
function statsValues(s, labels) {
  return [...labels, s.N, s.mean, s.sd, s.min, s.P25, s.median, s.P75, s.P90, s.max, s.missing, s.zero];
}
const statsHeaders = ['类别','指标','保存字段','N','均值','样本标准差','最小值','P25','中位数','P75','P90','最大值','缺失数','零值数'];
const statsWidths = { A:145, B:225, C:155, D:100, E:120, F:125, G:135, H:120, I:120, J:120, K:120, L:135, M:90, N:90 };
const end = 6 + data.statistics.length;
base(primary, `N${end}`, statsWidths, navy);
title(primary, 'IBSI及中间指标描述统计', `共同有效样本 ${data.valid_N.toLocaleString('en-US')} 栋；标准差采用 n−1 分母；与五面板图一致`, 'N');
primary.getRange('A4').values = [['RMS、Tilt、DGI为入模归一化前字段；实际尺度与处理定义见“字段定义”。']];
primary.getRange('A4').format.font = { name:'Arial', size:10, color:muted };
header(primary, 6, 'N', statsHeaders);
primary.getRange(`A7:N${end}`).values = data.statistics.map(s => statsValues(s,[s.group,s.indicator,s.field]));
statisticalFormat(primary,7,end);
let lastGroup = null;
for (let i=0;i<data.statistics.length;i++) {
  const s=data.statistics[i], row=i+7;
  if (s.group!==lastGroup) primary.getRange(`A${row}:N${row}`).format.borders = { top:{style:'thin',color:rule} };
  if (s.field==='IBSI') primary.getRange(`A${row}:N${row}`).format = { fill:'#EAF1F7', font:{name:'Arial',size:11,bold:true,color:ink} };
  if (s.field==='Tilt_Angle') primary.getRange(`E${row}:L${row}`).setNumberFormat('0.000000');
  if (s.min>0 && s.min<.001) primary.getRange(`G${row}`).setNumberFormat('0.000E+00');
  if (['PS_Count','N_Pt_Deform','N_Edg_Tot','N_Pt_DGI','N_Pt_Abn','PS_Q_OK','Tilt_OK','Vul_Valid'].includes(s.field)) {
    primary.getRange(`G${row}`).setNumberFormat('#,##0');
    primary.getRange(`L${row}`).setNumberFormat('#,##0');
  }
  lastGroup=s.group;
}
primary.freezePanes.freezeRows(6);
primary.freezePanes.freezeColumns(3);

base(ps,'N10',{...statsWidths,A:225,B:155,C:430},'#6B859A');
title(ps,'已归档PS输入观测统计',`${data.PS_association_N.toLocaleString('en-US')} 条建筑–PS关联记录；按保存的输入字段尺度统计`, 'N');
ps.getRange('A4').values = [[`同一源PS可能关联多栋建筑；源PS标识 ${data.PS_unique_source_point_N.toLocaleString('en-US')} 个，其中 ${data.PS_multi_building_source_point_N.toLocaleString('en-US')} 个存在多建筑关联。`]];
ps.getRange('A4').format.font={name:'Arial',size:10,color:muted};
ps.getRange('A5').values = [['速率输入单位为mm/年（用户确认）；Tilt已统一毫米与米并转为°/年；入射角原始约定仍待核实。']];
ps.getRange('A5').format.font={name:'Arial',size:10,color:muted};
header(ps,6,'N',['参数','保存字段','输入尺度说明',...statsHeaders.slice(3)]);
ps.getRange('A7:N10').values = data.raw_PS_statistics.map(s=>statsValues(s,[s.indicator,s.field,s.scale]));
statisticalFormat(ps,7,10);
ps.getRange('C7:C10').format.wrapText=true;
ps.getRange('A7:N10').format.rowHeight=48;
for (let i=0;i<data.raw_PS_statistics.length;i++) {
  const s=data.raw_PS_statistics[i];
  if (s.min!==0 && Math.abs(s.min)<.001) ps.getRange(`G${i+7}`).setNumberFormat('0.000E+00');
}

const paramLast=6+data.fixed_parameters.length;
const normHeader=paramLast+4, normEnd=normHeader+data.normalization_thresholds.length;
const sourceStart=normEnd+4, sourceEnd=sourceStart+9;
base(params,`G${sourceEnd}`,{A:160,B:330,C:240,D:150,E:410,F:140,G:140},'#8DA1B3');
title(params,'处理参数与保存阈值','固定系数单独列值；不对常量计算均值与标准差。归一化阈值直接读取保存结果。','G');
header(params,6,'E',['环节','参数','固定值','尺度','作用或边界规则']);
params.getRange(`A7:E${paramLast}`).values=data.fixed_parameters;
params.getRange(`C7:C${paramLast}`).setNumberFormat('0.000');
params.getRange(`C7:C${paramLast}`).format.horizontalAlignment='right';
params.getRange(`A7:E${paramLast}`).format.rowHeight=32;
params.getRange(`A${normHeader-1}`).values=[['入模归一化与异常增强阈值']];
params.getRange(`A${normHeader-1}`).format.font={name:'Arial',size:12,bold:true,color:navy};
header(params,normHeader,'G',['原值字段','入模字段','处理规则','样本数','P1','P75','P99']);
const methods = {
  'V_RMS':'P1–P99截尾后min–max归一化',
  'Tilt_Angle':'≤P75为0；P75–P99线性；≥P99为1',
  'DGI_Str':'≤P75为0；P75–P99线性；≥P99为1',
};
params.getRange(`A${normHeader+1}:G${normEnd}`).values=data.normalization_thresholds.map(r=>[r.field,r.normalized_field,methods[r.field]??methods.V_RMS,r.N,r.P01,r.P75,r.P99]);
params.getRange(`A${normHeader+1}:G${normEnd}`).format.rowHeight=50;
params.getRange(`C${normHeader+1}:C${normEnd}`).format.wrapText=true;
params.getRange(`D${normHeader+1}:D${normEnd}`).setNumberFormat('#,##0');
params.getRange(`E${normHeader+1}:G${normEnd}`).setNumberFormat('0.000000');
params.getRange(`D${normHeader+1}:G${normEnd}`).format.horizontalAlignment='right';
params.getRange(`A${sourceStart-1}`).values=[['数据来源与样本说明']];
params.getRange(`A${sourceStart-1}`).format.font={name:'Arial',size:12,bold:true,color:navy};
const sourceRows = [
 ['建筑保存结果','01_building_vulnerability_metrics.gpkg；图层 building_vulnerability_metrics'],
 ['PS保存输入','building_ps_points.gpkg；图层 building_ps_points'],
 ['方法及参数','Vulnerability/pipeline.py、config.json、run_manifest.json、normalization_parameters.csv'],
 ['计算版本',data.metadata.version],
 ['样本',data.metadata.cohort],
 ['标准差与分位数',data.metadata.SD],
 ['源输入尺度','速率输入单位为mm/年（用户确认）；保留已归档v_vertical；入射角原始约定待核实。'],
 ['有效样本',data.metadata.eligibility_note],
 ['原始PS粒度',data.metadata.PS_note],
 ['解释范围',data.metadata.interpretation],
];
params.getRange(`A${sourceStart}:B${sourceEnd}`).values=sourceRows;
params.getRange(`B${sourceStart}:B${sourceEnd}`).format.wrapText=true;
params.getRange(`A${sourceStart}:B${sourceEnd}`).format.autofitRows();

const defEnd=6+data.definitions.length;
base(defs,`H${defEnd}`,{A:145,B:225,C:155,D:320,E:600,F:330,G:145,H:145},'#A6B7C5');
title(defs,'字段定义、计算尺度与数值完整性',`全库存 ${data.inventory_N.toLocaleString('en-US')} 栋；主表共同有效样本 ${data.valid_N.toLocaleString('en-US')} 栋。`, 'H');
defs.getRange('A4').values=[['“原值”指当前建筑级归一化前计算字段；不保证进入程序前的PS数值未经处理。']];
defs.getRange('A4').format.font={name:'Arial',size:10,color:muted};
defs.getRange('A5').values=[['有限值N仅表示保存了数值；质量未通过时部分计数中间量为0，不等同于模型有效样本数。']];
defs.getRange('A5').format.font={name:'Arial',size:10,color:muted};
header(defs,6,'H',['类别','指标','保存字段','计算尺度','定义或处理方式','在计算链中的用途','全库存有限值N','非有限或缺失N']);
defs.getRange(`A7:H${defEnd}`).values=data.definitions.map(d=>[d.group,d.indicator,d.field,d.scale,d.definition,d.role,d.inventory_available_N,d.inventory_missing_N]);
defs.getRange(`D7:F${defEnd}`).format.wrapText=true;
defs.getRange(`A7:H${defEnd}`).format.autofitRows();
defs.getRange(`G7:H${defEnd}`).setNumberFormat('#,##0');
defs.getRange(`G7:H${defEnd}`).format.horizontalAlignment='right';
defs.freezePanes.freezeRows(6);
defs.freezePanes.freezeColumns(3);

workbook.recalculate();
const inspected = await workbook.inspect({kind:'table',range:'建筑指标统计!A6:N14',include:'values,formulas',tableMaxRows:9,tableMaxCols:14,maxChars:5000});
await fs.writeFile(path.join(out,'workbook_inspection.ndjson'),inspected.ndjson);
const errors = await workbook.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:40},maxChars:1500});
await fs.writeFile(path.join(out,'workbook_error_scan.ndjson'),errors.ndjson);
const rendered = [];
for (const [sheetName,range,file] of [
  ['建筑指标统计',`A1:N${end}`,'statistics_preview.png'],
  ['原始PS统计','A1:N10','PS_statistics_preview.png'],
  ['处理参数',`A1:G${normEnd}`,'parameters_preview.png'],
  ['处理参数',`A${sourceStart-1}:B${sourceEnd}`,'source_notes_preview.png'],
  ['字段定义',`A1:H${defEnd}`,'definitions_preview.png'],
]) {
  const preview = await workbook.render({sheetName,range,scale:1,format:'png'});
  await fs.writeFile(path.join(out,file),new Uint8Array(await preview.arrayBuffer()));
  rendered.push({sheetName,range,file});
}
const output=await SpreadsheetFile.exportXlsx(workbook);
const filename=path.join(fig,'IBSI_intermediate_indicators_statistics.xlsx');
await output.save(filename);
// Inspect the exported values, since this is a frozen statistical report.
const exported=await SpreadsheetFile.importXlsx(await fs.readFile(filename));
const checkRows=exported.worksheets.getItem('建筑指标统计').getRange(`A7:N${end}`).values;
for (let i=0;i<data.statistics.length;i++) {
  const s=data.statistics[i],r=checkRows[i];
  if(r[2]!==s.field || r[3]!==s.N || Math.abs(r[4]-s.mean)>1e-10 || Math.abs(r[5]-s.sd)>1e-10) throw new Error(`Export mismatch: ${s.field}`);
}
await fs.writeFile(path.join(out,'workbook_quality_check.json'),JSON.stringify({output:filename,building_fields:data.statistics.length,common_N:data.valid_N,raw_PS_fields:data.raw_PS_statistics.length,fixed_parameters:data.fixed_parameters.length,normalization_rows:data.normalization_thresholds.length,exported_values_verified:true,rendered},null,2)+'\n');
console.log(JSON.stringify({output:filename,building_fields:data.statistics.length,common_N:data.valid_N,raw_PS_fields:data.raw_PS_statistics.length,exported_values_verified:true}));
