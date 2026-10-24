"""Synchronize saved H/E/V/R building maps with shared Jenks class attributes.

Keeps page design, extent, line styles, annotations and existing map palettes.
Run with run_pyqgis.sh after refreshing current model and paper statistical tables.
"""
from qgis_paths import export_path, layout_directory, project_path
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
import csv
import json
import os
import sqlite3

from qgis.core import *
from qgis_paths import ROOT, EXPORTS
from draw_hazard_streets import save_project
from revise_hazard_layout import map_polygon
from map_series_support import export_layout, save_template

NAMES = ["Very Low", "Low", "Moderate", "High", "Very High"]
SOURCES = {
    "hazard": ("hazard/scs_pipeline/06_building_hazard.gpkg", "building_hazard", "PGA_Class", "PGA_Final_g"),
    "exposure": ("exposure/scs_paper_method/building_exposure.gpkg", "building_exposure_scs", "Exposure_Class", "Exp_Final"),
    "vulnerability": ("vulnerability/scs_paper_method/02_building_comprehensive_vulnerability.gpkg", "building_comprehensive_vulnerability", "Vul_Class", "Vul_Index"),
    "risk": ("risk/scs_paper_method/building_risk.gpkg", "building_risk_scs", "Risk_Class", "Risk_Final"),
}
CONFIGS = [
    ("04_seismic_hazard.qgz", "Kunming_Hazard_PGA", "hazard", "", "Kunming_Building_Hazard", "hazard", "hazard.qml"),
    ("04_seismic_hazard_streets.qgz", "Kunming_Hazard_PGA_Streets", "hazard", "hazard_streets", "Kunming_Building_Hazard_Streets", "hazard_streets", "hazard.qml"),
    ("08b_exposure.qgz", "Kunming_Exposure", "exposure", "exposure", "Kunming_Building_Exposure", "exposure", "building_exposure.qml"),
    ("08a_vulnerability.qgz", "Kunming_Vulnerability", "vulnerability", "vulnerability", "Kunming_Building_Vulnerability", "vulnerability", "building_vulnerability.qml"),
    ("10_risk_base.qgz", "Kunming_Final_Risk", "risk", "final_risk", "Kunming_Final_Building_Risk", "final_risk", "building_final_risk.qml"),
]


def draw(config):
    project_name, layout_name, key, output_folder, stem, template_folder, style_name = config
    source, table, class_field, value_field = SOURCES[key]
    source = ROOT / "../result" / source
    module = {"hazard": "Hazard", "exposure": "Exposure", "vulnerability": "Vulnerability", "risk": "Risk"}[key]
    provenance = json.loads((ROOT.parent / "change_logs/2026-10-15_jenks_unification/classification_update.json").read_text())["modules"][module]
    project_file = project_path(project_name)
    project = QgsProject()
    assert project.read(str(project_file))
    layout = project.layoutManager().layoutByName(layout_name)
    assert layout
    main = next(item for item in layout.items() if isinstance(item, QgsLayoutItemMap) and
                any(layer.customProperty("seismic_building/result_key", "") == key for layer in item.layers()))
    extent_before = main.extent().toString(12)
    layer = next(layer for layer in main.layers() if layer.customProperty("seismic_building/result_key", "") == key)
    overrides = main.layerStyleOverrides()
    styled = layer.clone()
    if layer.id() in overrides:
        QgsMapLayerStyle(overrides[layer.id()]).writeToLayer(styled)
    renderer = styled.renderer().clone()
    assert isinstance(renderer, QgsRuleBasedRenderer)
    rules = renderer.rootRule().children()
    assert len(rules) == 5
    layer.setDataSource(str(source) + "|layername=" + table, layer.name(), "ogr")
    assert layer.isValid() and layer.featureCount() == provenance["building_count"]
    assert layer.fields().indexFromName(class_field) >= 0 and not layer.subsetString()
    for rule, name in zip(rules, NAMES):
        rule.setFilterExpression('"' + class_field + '" = ' + repr(name))
        rule.setLabel(name)
    layer.setRenderer(renderer)
    layer.setCustomProperty("seismic_building/classification_method", provenance["method"])
    layer.setCustomProperty("seismic_building/class_breaks", json.dumps(provenance["breaks"]))
    updated_style = QgsMapLayerStyle()
    updated_style.readFromLayer(layer)
    overrides[layer.id()] = updated_style.xmlData()
    main.setLayerStyleOverrides(overrides)
    for index, name in enumerate(NAMES):
        item = layout.itemById("Legend_range_" + str(index))
        if item:
            item.setText(name)
    if key == "hazard" and layout.itemById("Legend_title"):
        layout.itemById("Legend_title").setText("PGA level")

    clip = map_polygon(main.extent(), main.crs(), layer.crs(), project)
    engine = QgsGeometry.createGeometryEngine(clip.constGet())
    engine.prepareGeometry()
    full, visible = Counter(), Counter()
    for feature in layer.getFeatures(QgsFeatureRequest().setSubsetOfAttributes([class_field], layer.fields())):
        name = str(feature[class_field])
        assert name in NAMES
        full[name] += 1
        if engine.intersects(feature.geometry().constGet()):
            visible[name] += 1
    assert dict(full) == provenance["class_counts"]
    assert main.extent().toString(12) == extent_before

    output = export_path(output_folder)
    export_layout(layout, output, stem)
    template = layout_directory(template_folder) / (layout_name + ".qpt")
    save_template(layout, template)
    message, ok = layer.saveNamedStyle(str(template.parent / style_name))
    assert ok, message
    if key == "hazard" and template_folder == "hazard":
        message, ok = layer.saveNamedStyle(str(template.parent / "print_styles/hazard.qml"))
        assert ok, message
    global_style = {"hazard": "hazard_pga_five_classes.qml", "exposure": "exposure_classes.qml",
                    "vulnerability": "vulnerability_classes.qml", "risk": "risk_classes.qml"}[key]
    message, ok = layer.saveNamedStyle(str(ROOT / "shared/styles/layer_defaults" / global_style))
    assert ok, message
    save_project(project, target=project_file, source=project_file)
    checked = QgsProject()
    assert checked.read(str(project_file))
    restored = checked.layoutManager().layoutByName(layout_name)
    restored_main = restored.itemById(main.id())
    assert restored_main and all(item.isValid() for item in restored_main.layers())
    restored_layer = next(item for item in restored_main.layers() if item.customProperty("seismic_building/result_key", "") == key)
    clone = restored_layer.clone()
    QgsMapLayerStyle(restored_main.layerStyleOverrides()[restored_layer.id()]).writeToLayer(clone)
    assert [rule.filterExpression() for rule in clone.renderer().rootRule().children()] == [
        '"' + class_field + '" = ' + repr(name) for name in NAMES]
    report = {"updated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "project": str(project_file),
              "layout": layout_name, "source": str(source), "field": value_field, "class_field": class_field,
              "method": provenance["method"], "breaks": provenance["breaks"],
              "source_count": sum(full.values()), "mapped_count": sum(visible.values()),
              "source_class_counts": dict(full), "visible_class_counts": dict(visible),
              "extent_unchanged": True, "project_reload_validated": True, "exports": stem}
    (output / (key + "_jenks_update.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with (output / (key + "_map_class_breaks.csv")).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["class", "lower", "upper", "source_count", "mapped_count"])
        for i, name in enumerate(NAMES):
            writer.writerow([name, provenance["breaks"][i], provenance["breaks"][i + 1], full[name], visible[name]])
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main():
    app = QgsApplication.instance()
    if app is None:
        app = QgsApplication([], False)
        app.setPrefixPath("/Applications/QGIS.app/Contents/Resources/qgis", True)
        app.initQgis()
    reports = [draw(config) for config in CONFIGS]
    target = ROOT.parent / "change_logs/2026-10-15_jenks_unification/qgis_map_update.json"
    target.write_text(json.dumps(reports, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
    os._exit(0)
