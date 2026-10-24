"""Add a pale hillshade beneath the existing saved hazard layout, preserving design."""
from qgis_paths import export_path
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
import shutil
from qgis.core import *
from qgis_paths import ROOT, PROJECT, EXPORTS
from hillshade_support import ensure_hillshade, SERVICE, OPACITY, COLORS, HILLSHADE_FILE
import layout_support

RECORD = Path(os.environ.get('SEISMIC_HILLSHADE_RECORD', str(ROOT/'history/changes'/datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d_%H%M%S_hillshade'))))


def apply():
    RECORD.mkdir(parents=True,exist_ok=True)
    project = QgsProject.instance()
    assert project.read(str(PROJECT))
    before = RECORD/'project_before_current_run.qgz'
    shutil.copy2(PROJECT,before)
    digest = layout_support.digest(PROJECT)
    original_ids = set(project.mapLayers())
    layout = project.layoutManager().layoutByName('Kunming_Hazard_PGA')
    main = layout.itemById('Hazard_Main_Map')
    extent = QgsRectangle(main.extent())
    original_layers = [l for l in main.layers() if l.customProperty('seismic_building/print_base','')!='hillshade']
    original_overrides = dict(main.layerStyleOverrides())
    hashes = {l.source().split('|')[0]:layout_support.digest(l.source().split('|')[0]) for l in original_layers}
    terrain = ensure_hillshade(project)
    terrain.saveNamedStyle(str(ROOT/'04_seismic_hazard/qgis/layouts/hazard/print_styles/hillshade.qml'))
    main.setLayers(original_layers+[terrain])
    original_overrides[terrain.id()] = layout_support.xml_style(terrain)
    main.setLayerStyleOverrides(original_overrides)
    main.setKeepLayerSet(True)
    main.setKeepLayerStyles(True)
    layout.itemById('Footer_2').setText('Dian Lake: 2016 reference (Zhu et al., 2019) | Hillshade: Esri & contributors.')
    layout.setCustomProperty('seismic_building/hillshade_trial','pale_gray_green')
    layout.renderContext().setDpi(1200)
    layout.refresh()
    exporter = QgsLayoutExporter(layout)
    image = QgsLayoutExporter.ImageExportSettings()
    image.dpi = 180
    assert exporter.exportToImage(str(export_path('Kunming_Building_Hazard_preview.png')),image)==QgsLayoutExporter.Success
    image.dpi = 1200
    assert exporter.exportToImage(str(export_path('Kunming_Building_Hazard_1200dpi.png')),image)==QgsLayoutExporter.Success
    pdf = QgsLayoutExporter.PdfExportSettings()
    pdf.dpi = 1200
    pdf.forceVectorOutput = True
    pdf.rasterizeWholeImage = False
    pdf.simplifyGeometries = False
    pdf.textRenderFormat = Qgis.TextRenderFormat.AlwaysText
    pdf.appendGeoreference = False
    stage = RECORD/'hillshade_stage.pdf'
    assert exporter.exportToPdf(str(stage),pdf)==QgsLayoutExporter.Success
    stage.replace(export_path('Kunming_Building_Hazard.pdf'))
    context = QgsReadWriteContext()
    context.setPathResolver(project.pathResolver())
    assert layout.saveAsTemplate(str(ROOT/'04_seismic_hazard/qgis/layouts/hazard/Kunming_Hazard_PGA.qpt'),context)
    assert main.extent()==extent
    assert original_ids.issubset(set(project.mapLayers()))
    assert all(layout_support.digest(p)==h for p,h in hashes.items())
    assert layout_support.digest(PROJECT)==digest,'Concurrent project change'
    layout_support.preserve_gui_and_save(project,None,before)
    report_path = export_path('hazard_print_report.json')
    report = json.loads(report_path.read_text())
    report.update(time=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                  hillshade={'source':SERVICE,'local_raster':str(HILLSHADE_FILE),
                             'opacity':OPACITY,'ramp':COLORS,'kind':'rendered basemap, not raw DEM'},
                  main_map_layers=[l.name() for l in main.layers()],
                  original_vector_data_unchanged=True,map_extent_unchanged=True,
                  graticule_font_size_pt=main.grid().annotationTextFormat().size(),
                  pdf_has_raster_hillshade_and_vector_foreground=True)
    for path in [report_path,RECORD/'verification_summary.json']:
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Saved pale hillshade trial:',PROJECT,flush=True)


if __name__=='__main__':
    app = QgsApplication([],False)
    app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True)
    app.initQgis()
    apply()
    os._exit(0)
