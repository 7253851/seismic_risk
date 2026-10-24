"""Read the saved A4 project without modifying it; check links and map state."""
import json,os
from pathlib import Path
from qgis.core import QgsApplication,QgsProject,QgsLayoutItemMap,QgsLayoutItemPicture

out=Path(__file__).resolve().parents[1]
app=QgsApplication([],False);app.initQgis()
project=QgsProject();assert project.read(str(out/'06_insar_deformation_A4.qgz'))
layout=project.layoutManager().layoutByName('Figure06_A4');assert layout
page=layout.pageCollection().pages()[0]
assert abs(page.sizeWithUnits().width()-210)<1e-6 and abs(page.sizeWithUnits().height()-297)<1e-6
expected=json.loads((out/'map_report.json').read_text())['map_state_after']
for item in layout.items():
    if isinstance(item,QgsLayoutItemMap):
        e=item.extent()
        actual={'extent':[e.xMinimum(),e.yMinimum(),e.xMaximum(),e.yMaximum()],
                'rotation':item.mapRotation(),'layers':[l.id() for l in item.layers()]}
        assert actual==expected[item.id()]
        assert all(l.isValid() for l in item.layers())
    if isinstance(item,QgsLayoutItemPicture) and item.id()=='Python_chart_overlay':
        assert Path(item.picturePath()).is_file()
v={'saved_project_reopened':True,'A4_page_verified':True,'map_state_preserved':True,
   'map_layers_valid':True,'chart_overlay_svg_link_valid':True}
(out/'saved_layout_verification.json').write_text(json.dumps(v,indent=2)+'\n')
print(json.dumps(v),flush=True)
os._exit(0)
