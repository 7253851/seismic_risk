"""Build the editable current Static-only-baseline project from local derivatives."""
from pathlib import Path
import argparse,json,os
from qgis.core import (QgsApplication,QgsProject,QgsVectorLayer,QgsFillSymbol,QgsMarkerSymbol,QgsSingleSymbolRenderer,QgsCategorizedSymbolRenderer,QgsRendererCategory,QgsPrintLayout,QgsLayoutItemMap,QgsLayoutItemLabel,QgsLayoutPoint,QgsLayoutSize,QgsLayoutExporter,QgsRectangle,QgsReadWriteContext,Qgis)
from qgis.PyQt.QtGui import QFont

def main():
    p=argparse.ArgumentParser();p.add_argument('output_dir',type=Path);args=p.parse_args();out=args.output_dir.resolve();root=Path(__file__).resolve().parents[3];qd=root/'plot/12_insar_contribution/output/support';qd.mkdir(parents=True,exist_ok=True);db=out/'QGIS/data/static_baseline_5_1.gpkg';project_path=root/'plot/12_insar_contribution/qgis/support/static_baseline.qgz';template_path=root/'plot/12_insar_contribution/qgis/layouts/12_insar_contribution/static_baseline.qpt'
    s=json.loads((out/'data/static_baseline_statistics.json').read_text())
    app=QgsApplication([],False);app.initQgis();project=QgsProject()
    layers={}
    for table,title in [('district_boundaries','Districts'),('all_40000_buildings','All 40,000 buildings (optional)'),('selected_building_footprints','Selected case footprints'),('primary_pair_footprints','Primary matched pair'),('upgraded_building_points',f'Upgraded buildings ({s["upgrade_n"]:,})')]:
        layer=QgsVectorLayer(str(db)+'|layername='+table+'|option:IMMUTABLE=YES',title,'ogr');assert layer.isValid(),table
        project.addMapLayer(layer);layers[table]=layer
    layers['district_boundaries'].setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'color':'250,250,250,255','outline_color':'165,175,181,255','outline_width':'.18'})))
    for table,color,size in [('all_40000_buildings','#B5BDC3',.5),('upgraded_building_points','#C5433C',.85)]:
        layers[table].setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({'name':'circle','color':color,'size':str(size),'outline_style':'no'})))
    layers['selected_building_footprints'].setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({'style':'no','outline_color':'#202A31','outline_width':'.35'})))
    categories=[]
    for role,color in [('Upgraded target','#C5433C'),('Unchanged-class control','#2875B5')]:
        symbol=QgsFillSymbol.createSimple({'color':color,'outline_color':color,'outline_width':'.3'})
        categories.append(QgsRendererCategory(role,symbol,role))
    layers['primary_pair_footprints'].setRenderer(QgsCategorizedSymbolRenderer('pair_role',categories))
    active=[layers['upgraded_building_points'],layers['district_boundaries']]
    for node in project.layerTreeRoot().findLayers():node.setItemVisibilityChecked(node.layerId() in {x.id() for x in active})
    extent=QgsRectangle(layers['upgraded_building_points'].extent());extent.scale(1.12)
    layout=QgsPrintLayout(project);layout.initializeDefaults();layout.setName('01_Frozen_Static_only_upgraded_buildings')
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(210,248))
    item=QgsLayoutItemMap(layout);layout.addLayoutItem(item);item.attemptMove(QgsLayoutPoint(12,30));item.attemptResize(QgsLayoutSize(186,193));item.setCrs(layers['upgraded_building_points'].crs());item.setLayers(active);item.setKeepLayerSet(True);item.zoomToExtent(extent)
    def label(text,y,size=10,bold=False,parent=None):
        parent=layout if parent is None else parent
        q=QgsLayoutItemLabel(parent);q.setText(text);q.setFont(QFont('Arial',size));f=q.font();f.setBold(bold);q.setFont(f);parent.addLayoutItem(q);q.attemptMove(QgsLayoutPoint(12,y));q.attemptResize(QgsLayoutSize(186,10));return q
    label('Add InSAR on the frozen Static-only baseline',8,12,True)
    label(f'N = 40,000 | Upgraded {s["upgrade_n"]:,} | Unchanged {s["unchanged_n"]:,} | Downgraded 0',19,9)
    label('Red: all upgraded centroids. Same static normalization and Jenks boundaries.',225,8)
    label('No sampling or displacement; case selection and full attributes remain editable.',234,8)
    project.layoutManager().addLayout(layout)
    detail=QgsPrintLayout(project);detail.initializeDefaults();detail.setName('02_Relaxed_matched_pair')
    detail.pageCollection().pages()[0].setPageSize(QgsLayoutSize(210,248))
    local=QgsLayoutItemMap(detail);detail.addLayoutItem(local);local.attemptMove(QgsLayoutPoint(12,35));local.attemptResize(QgsLayoutSize(186,164));local.setCrs(item.crs());local.setLayers([layers['primary_pair_footprints']]);local.setKeepLayerSet(True)
    pair_extent=QgsRectangle(layers['primary_pair_footprints'].extent());pair_extent.scale(1.6);local.zoomToExtent(pair_extent)
    label('Same-block matched pair on the fixed static baseline',8,11,True,detail)
    label(f'IDs {s["pair_ids"][0]} / {s["pair_ids"][1]} | centroid separation {s["primary_pair_distance_m"]:.1f} m',21,9,False,detail)
    for i,row in enumerate(s['pair_rows']):
        label(f'{row["Build_ID"]}: {row["static_class"]} -> {row["insar_class"]} | R {row["R_static_baseline"]:.5f} -> {row["R_insar_static_baseline"]:.5f}',204+i*12,9,False,detail)
    label('Red: upgraded target. Blue: unchanged-class control. Geometry in EPSG:32648.',231,8,False,detail)
    project.layoutManager().addLayout(detail);project.setCrs(item.crs());project.setTitle('5.1 Frozen Static-only baseline: InSAR increment')
    project.setFilePathStorage(Qgis.FilePathType.Relative);project.setFileName(str(project_path));assert project.write()
    assert layout.saveAsTemplate(str(template_path),QgsReadWriteContext())
    export=QgsLayoutExporter(layout);opt=QgsLayoutExporter.ImageExportSettings();opt.dpi=600;opt.exportMetadata=False
    assert export.exportToImage(str(qd/'static_baseline_map.png'),opt)==QgsLayoutExporter.Success
    assert QgsLayoutExporter(detail).exportToImage(str(qd/'matched_pair_map.png'),opt)==QgsLayoutExporter.Success
    check=QgsProject();assert check.read(str(project_path));assert all(x.isValid() for x in check.mapLayers().values())
    counts={name:int(layer.featureCount()) for name,layer in layers.items()};assert counts['upgraded_building_points']==s['upgrade_n'];assert counts['all_40000_buildings']==40000
    assert counts['primary_pair_footprints']==2 and len(check.layoutManager().layouts())==2
    (qd/'verification.json').write_text(json.dumps({'status':'passed','layer_feature_counts':counts,'project_uses_relative_paths':True,'layouts':2,'all_layers_valid_after_reopen':True},indent=2)+'\n')
    (qd/'README.md').write_text('# 当前5.1固定静态基准QGIS工程\n\n打开[static_baseline.qgz](../../qgis/support/static_baseline.qgz)。工程及布局使用本文件夹data内的独立GeoPackage，相对路径随整个Static-only基准目录移动。默认显示全部2,391栋升档建筑和行政边界；40,000栋完整样本、候选建筑轮廓和主配对建筑保留为可选原生图层。评分、等级和变化均使用Static-only固定归一化与Jenks分界。布局01为全区升档点，布局02为39899/39929的局部原生建筑轮廓。\n\n[当前统计与方法](../README.md) · [全区预览](static_baseline_map.png) · [配对预览](matched_pair_map.png)\n')
    print(json.dumps(counts),flush=True)
    # Qt/QGIS native objects can crash during interpreter teardown on this Mac;
    # all files are closed and reopened/asserted above before the clean process exit.
    os._exit(0)
if __name__=='__main__':main()
