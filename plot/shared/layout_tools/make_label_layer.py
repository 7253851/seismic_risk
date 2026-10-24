"""Build a standalone A4 QGIS layout holding only the panel letters and export it.

Usage (QGIS Python): run_pyqgis.sh make_label_layer.py <figure work folder> [name]
Writes panel_labels_A4.pdf and panel_labels_A4.qpt next to panel_labels.json.
"""
import json
import os
import sys
from pathlib import Path

from qgis.core import QgsApplication, QgsPrintLayout, QgsProject, QgsReadWriteContext, QgsLayoutSize

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panel_labels


def main():
    folder = Path(sys.argv[1]).resolve()
    name = sys.argv[2] if len(sys.argv) > 2 else ''
    app = QgsApplication([], False); app.initQgis()
    project = QgsProject()
    specs = json.loads((folder/f'panel_labels{name}.json').read_text())
    layout = QgsPrintLayout(project); layout.initializeDefaults()
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(210, 297))
    layout.setName('Panel_labels_A4' + name)
    scale = folder/'paper_scale.json'
    k = 1.0
    if scale.exists():
        data = json.loads(scale.read_text())
        k = data.get(name.replace('_fig', '').lstrip('0'), data.get('K', 1.0))
    added = panel_labels.add(layout, specs, font_pt=panel_labels.FONT_PT*k)
    panel_labels.export_top_layer(layout, folder/f'panel_labels{name}_A4.pdf')
    assert layout.saveAsTemplate(str(folder/f'panel_labels{name}_A4.qpt'), QgsReadWriteContext())
    print(json.dumps({'labels': added, 'pdf': str(folder/f'panel_labels{name}_A4.pdf')}))
    os._exit(0)


if __name__ == '__main__':
    main()
