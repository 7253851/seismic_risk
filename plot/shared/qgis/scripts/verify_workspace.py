"""Read-only checks of current QGIS projects, local layers and map resources."""
from pathlib import Path
import argparse,json,os
from qgis.core import QgsApplication,QgsProject,QgsLayoutItemMap,QgsLayoutItemPicture,QgsLayoutExporter
from qgis_paths import ROOT


def verify(render_preview=False):
    projects=sorted(list(ROOT.glob('[0-9][0-9]_*/qgis/projects/*.qgz'))+
                    list(ROOT.glob('[0-9][0-9]_*/qgis/support/*.qgz'))+
                    list((ROOT.parent/'plot/diagnostics').rglob('*.qgz')))
    assert projects, 'No organized QGIS projects found'
    report={'projects':[],'all_local_layers_valid':True,'online_basemaps_not_network_checked':True}
    for path in projects:
        project=QgsProject();assert project.read(str(path)),path
        invalid=[{'name':l.name(),'source':l.source()} for l in project.mapLayers().values() if not l.isValid() and 'type=xyz' not in l.source()]
        assert not invalid,(path,invalid)
        layouts=[]
        for layout in project.layoutManager().layouts():
            for item in layout.items():
                if isinstance(item,QgsLayoutItemMap):assert all(l.isValid() for l in item.layers()),item.id()
                if isinstance(item,QgsLayoutItemPicture):
                    picture=item.picturePath()
                    if picture and not picture.startswith(':/'):assert Path(picture).is_file(),picture
            layouts.append(layout.name())
            if render_preview and (layout.name()=='Kunming_Study_Area' or path.name=='04_seismic_hazard.qgz'):
                output=ROOT/'shared/output/qgis/verification';output.mkdir(parents=True,exist_ok=True)
                settings=QgsLayoutExporter.ImageExportSettings();settings.dpi=100;settings.exportMetadata=False
                assert QgsLayoutExporter(layout).exportToImage(str(output/(layout.name()+'_preview.png')),settings)==QgsLayoutExporter.Success
        report['projects'].append({'project':str(path),'layer_count':len(project.mapLayers()),'layouts':layouts,'local_layers_valid':True})
        print('Verified:',path.name,flush=True)
    target=ROOT/'shared/qgis/manifests/current_workspace_verification.json'
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--render-preview',action='store_true');args=parser.parse_args()
    app=QgsApplication([],False);app.setPrefixPath('/Applications/QGIS.app/Contents/Resources/qgis',True);app.initQgis()
    verify(args.render_preview)
    os._exit(0)
