#!/usr/bin/env python3
"""Connect reviewed fault attributes to the canonical QGIS project.

Run with ./run_pyqgis.sh sync_fault_literature_qgis.py. Only the existing fault
layer XML, three evidence table layers, their tree group and relations change.
Other layers, layouts, map themes, GUI state and archive attachments are copied
from the latest project. A digest guard rejects concurrent project writes.
"""
from pathlib import Path
import copy
import hashlib
import json
import os
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

from qgis.core import (QgsApplication, QgsProject, QgsVectorLayer,
    QgsMapLayerStyle, QgsRelation, QgsRelationContext, QgsLayoutExporter, QgsAction, Qgis)
from qgis_paths import ROOT, PROJECT

DATA = ROOT / '../data/faults/kunming_faults_literature.gpkg'
MATERIAL = ROOT / '../result/intermediate/fault_literature'
BUILD = json.loads((MATERIAL / 'latest_build.json').read_text())
HISTORY = Path(BUILD['history'])
if not HISTORY.is_absolute():
    HISTORY = ROOT.parent / HISTORY
GROUP = '断层文献证据 · 2026-10-14'
ALIAS = {
    'fault_uid': '稳定记录ID', 'source_row': '原数据行号（从0起）',
    'lit_name_cn': '文献规范名称', 'lit_name_en': '文献规范英文名',
    'lit_age': '文献活动时代（非重分类）', 'lit_age_status': '活动时代审查说明',
    'lit_motion': '文献运动性质及范围', 'lit_strike': '文献走向及范围',
    'lit_dip': '文献倾角（局部结构面）', 'lit_slip': '文献速率（地点与时间尺度）',
    'lit_paleo': '文献古地震及复发信息', 'lit_segment': '文献分段与覆盖范围',
    'lit_sources': '关联来源ID', 'lit_evidence_n': '关联记录数（含冲突/未采用）',
    'lit_confidence': '名称对应置信说明', 'lit_status': '文献审查状态',
    'lit_review_date': '文献审查日期', 'lit_notes': '适用限制与备注',
    'evidence_id': '证据ID', 'source_id': '文献ID', 'pdf_pages': 'PDF页码（从1起）',
    'topic': '观测类别', 'spatial_scope': '适用地点/断裂段', 'observation': '观测摘要',
    'value': '报告中心值', 'value_min': '报告下限', 'value_max': '报告上限',
    'uncertainty_pm': '报告正负误差', 'unit': '原报告单位', 'time_scale': '时间尺度',
    'component': '位移/运动分量', 'method': '观测方法', 'evidence_grade': '证据类型',
    'decision': '采用状态', 'limitations': '适用限制', 'underlying_reference': '转引原文',
    'source_location': '原文节/表', 'related_evidence': '重复/关联证据',
    'scope_id': '文献对象ID', 'title': '文献标题', 'authors': '作者', 'year': '年份',
    'journal': '刊物/平台', 'volume_pages': '卷期页', 'pages': 'PDF总页数',
    'path': '相对工作区PDF路径', 'sha256': '来源SHA256', 'use_role': '使用角色',
    'literature_object': '文献断裂对象', 'match_status': '匹配状态',
    'confidence': '对应置信说明', 'scope_note': '分段和范围限制',
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def xml(p):
    with zipfile.ZipFile(p) as z:
        name = next(n for n in z.namelist() if n.endswith('.qgs'))
        return name, ET.fromstring(z.read(name))


def node_bytes(n):
    if n is None:
        return b''
    n = copy.deepcopy(n)
    for e in n.iter():
        e.tail = None
        if e.text is not None and not e.text.strip():
            e.text = None
    return ET.tostring(n, encoding='utf-8')


def load(p):
    project = QgsProject()
    assert project.read(str(p)), p
    return project


def preview(project, dest):
    layout = project.layoutManager().layoutByName('Kunming_Hazard_PGA')
    assert layout
    settings = QgsLayoutExporter.ImageExportSettings()
    settings.dpi = 120
    if dest.exists():
        dest.unlink()
    result = QgsLayoutExporter(layout).exportToImage(str(dest), settings)
    assert result == QgsLayoutExporter.Success, result


def main():
    assert sha(DATA) == BUILD['output_sha256'], 'Rebuild metadata differs from GPKG'
    baseline = sha(PROJECT)
    backup = HISTORY / 'project_before.qgz'
    if backup.exists():
        assert not (HISTORY / 'qgis_validation.json').exists() and sha(backup) == baseline, 'Completed or changed project; use a new build history'
    else:
        shutil.copy2(PROJECT, backup)
    name, original = xml(PROJECT)
    project = load(PROJECT)
    target = next(l for l in project.mapLayers().values() if l.customProperty('seismic_building/base_key', '') == 'faults')
    target_id = target.id()
    old_style = QgsMapLayerStyle()
    old_style.readFromLayer(target)
    old_source = target.source()
    preview(project, HISTORY / 'hazard_before.png')
    target.setDataSource(str(DATA) + '|layername=faults_enriched', target.name(), 'ogr', False)
    assert target.isValid() and target.featureCount() == 59
    old_style.writeToLayer(target)
    for field, label in ALIAS.items():
        idx = target.fields().indexFromName(field)
        if idx >= 0:
            target.setFieldAlias(idx, label)
    config = target.attributeTableConfig()
    config.update(target.fields())
    target.setAttributeTableConfig(config)
    target.setDisplayExpression('coalesce(nullif("lit_name_cn",\'\'),"FN_Ch","fault_uid")')
    target.setCustomProperty('fault_literature/review_date', '2026-10-14')
    target.setCustomProperty('fault_literature/original_source', target.customProperty('fault_literature/original_source', old_source))
    target.setCustomProperty('fault_literature/reviewed_input_sha256', BUILD['reviewed_input_sha256'])
    metadata = target.metadata()
    metadata.setTitle('昆明断层：原几何及模型参数保留的文献属性增强版')
    metadata.setAbstract('59条原始断层；几何、14个原始属性、Mw、Length_km、AGE均保留。9条有名称的记录新增文献上下文字段。局部观测不代表整条合并线；综述转引、冲突、重复引用、未采用判断均在fault_evidence。原始SHP继续作为模型输入。无Mw_Max字段，无PGA或H/V/E/R重算。PDF页码从1起。')
    target.setMetadata(metadata)
    group = project.layerTreeRoot().findGroup(GROUP) or project.layerTreeRoot().addGroup(GROUP)
    group.setExpanded(False)
    tables = {}
    for table, label in [('fault_evidence','断层文献证据（含冲突与未采用）'), ('source_catalog','断层文献来源目录'), ('scope_matches','断裂名称与空间范围对应')]:
        layer = next((l for l in project.mapLayers().values() if l.customProperty('fault_literature/table','') == table), None)
        is_new = layer is None
        if is_new:
            layer = QgsVectorLayer(str(DATA) + '|layername=' + table, label, 'ogr')
        else:
            layer.setDataSource(str(DATA) + '|layername=' + table, layer.name(), 'ogr', False)
        assert layer.isValid(), table
        for field, alias in ALIAS.items():
            idx = layer.fields().indexFromName(field)
            if idx >= 0:
                layer.setFieldAlias(idx, alias)
        layer.setCustomProperty('fault_literature/table', table)
        if table == 'source_catalog':
            layer.setDisplayExpression('"source_id" || \': \' || "title"')
            if not layer.actions().actions():
                layer.actions().addAction(QgsAction(Qgis.AttributeActionType.OpenUrl, '打开本地文献PDF', '[% concat(\'file://\', @project_folder, \'/../../../\', "path") %]', False))
        if is_new:
            project.addMapLayer(layer, False)
            group.addLayer(layer)
        tables[table] = layer
    for id_, title, parent, child, field in [
        ('fault_literature_evidence','断层关联文献证据',target,tables['fault_evidence'],'fault_uid'),
        ('fault_literature_scope','断层对应文献对象',target,tables['scope_matches'],'fault_uid'),
        ('fault_literature_sources','文献关联观测记录',tables['source_catalog'],tables['fault_evidence'],'source_id')]:
        relation = QgsRelation(QgsRelationContext(project))
        relation.setId(id_)
        relation.setName(title)
        relation.setReferencedLayer(parent.id())
        relation.setReferencingLayer(child.id())
        relation.addFieldPair(field, field)
        project.relationManager().addRelation(relation)
        assert relation.isValid()
    stage = PROJECT.parent / '.fault_literature_stage.qgz'
    assert project.write(str(stage))
    _, new = xml(stage)
    # Apply only the relevant nodes to the latest saved XML. Native QGIS's
    # offscreen writer omits GUI-only nodes and can rewrite other layout styles.
    merged = copy.deepcopy(original)
    layers = merged.find('projectlayers')
    replacement = next(l for l in new.findall('./projectlayers/maplayer') if l.findtext('id') == target_id)
    old_target = next(l for l in layers if l.findtext('id') == target_id)
    pos = list(layers).index(old_target)
    layers.remove(old_target)
    layers.insert(pos, copy.deepcopy(replacement))
    for table in tables.values():
        layer_xml = next(l for l in new.findall('./projectlayers/maplayer') if l.findtext('id') == table.id())
        existing = next((l for l in layers if l.findtext('id') == table.id()), None)
        if existing is not None:
            pos = list(layers).index(existing)
            layers.remove(existing)
            layers.insert(pos, copy.deepcopy(layer_xml))
        else:
            layers.append(copy.deepcopy(layer_xml))
    tree = merged.find('layer-tree-group')
    for node in tree.iter('layer-tree-layer'):
        if node.get('id') == target_id:
            node.set('source', replacement.findtext('datasource'))
    for existing in list(tree.findall('layer-tree-group')):
        if existing.get('name') == GROUP:
            tree.remove(existing)
    tree.append(copy.deepcopy(next(g for g in new.find('layer-tree-group').findall('layer-tree-group') if g.get('name') == GROUP)))
    for node in merged.findall('relations'):
        merged.remove(node)
    merged.append(copy.deepcopy(new.find('relations')))
    # Legacy GUI legend is retained; append only the new table group.
    if merged.find('legend') is not None and new.find('legend') is not None:
        node = next((g for g in new.find('legend') if g.get('name') == GROUP), None)
        if node is not None:
            for existing in list(merged.find('legend')):
                if existing.get('name') == GROUP:
                    merged.find('legend').remove(existing)
            merged.find('legend').append(copy.deepcopy(node))
    for tag in ['Layouts','mapcanvas','mapViewDocks','mapViewDocks3D','mapViewSettings','visibility-presets','ProjectViewSettings']:
        assert node_bytes(original.find(tag)) == node_bytes(merged.find(tag)), tag
    updated_ids = {target_id} | {t.id() for t in tables.values()}
    original_layers = {l.findtext('id'): node_bytes(l) for l in original.findall('./projectlayers/maplayer') if l.findtext('id') not in updated_ids}
    for layer in merged.findall('./projectlayers/maplayer'):
        if layer.findtext('id') in original_layers:
            assert node_bytes(layer) == original_layers[layer.findtext('id')]
    atomic = PROJECT.parent / '.fault_literature_atomic.qgz'
    with zipfile.ZipFile(backup) as old, zipfile.ZipFile(atomic,'w',zipfile.ZIP_DEFLATED) as out:
        out.writestr(name, b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(merged, encoding='utf-8'))
        for info in old.infolist():
            if not info.filename.endswith('.qgs'):
                out.writestr(info, old.read(info.filename))
    assert sha(PROJECT) == baseline, 'Concurrent project write detected; staged output retained, canonical file untouched'
    os.replace(atomic, PROJECT)
    stage.unlink()
    reloaded = load(PROJECT)
    updated = reloaded.mapLayer(target_id)
    assert updated and updated.isValid() and updated.featureCount() == 59
    assert updated.fields().indexFromName('lit_slip') >= 0 and updated.fields().indexFromName('Mw_Max') < 0
    actual_style = QgsMapLayerStyle()
    actual_style.readFromLayer(updated)
    # Compare renderer/label subtrees because new field aliases are intentional.
    a, b = ET.fromstring(old_style.xmlData()), ET.fromstring(actual_style.xmlData())
    for tag in ['renderer-v2','labeling']:
        assert node_bytes(a.find(tag)) == node_bytes(b.find(tag)), tag
    for relation in reloaded.relationManager().relations().values():
        if relation.id().startswith('fault_literature_'):
            assert relation.isValid()
    preview(reloaded, HISTORY / 'hazard_after.png')
    result = dict(project=str(PROJECT),project_before_sha256=baseline,project_after_sha256=sha(PROJECT),fault_layer_id_preserved=target_id,source=str(DATA),new_tables={k:{'id':v.id(),'rows':v.featureCount()} for k,v in tables.items()},fault_renderer_and_labels_preserved=True,other_layer_nodes_unchanged=True,layout_nodes_exact=True,map_themes_exact=True,gui_state_preserved=True,concurrent_write_guard_passed=True)
    (HISTORY / 'qgis_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    app = QgsApplication([], False)
    app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis', True)
    app.initQgis()
    main()
    sys.stdout.flush()
    os._exit(0)
