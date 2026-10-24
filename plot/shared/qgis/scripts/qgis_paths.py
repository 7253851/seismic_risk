"""Canonical paths for QGIS assets in plot/<figure>/qgis and plot/<figure>/output/qgis."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[3]
WORKSPACE=ROOT.parent
_index=json.loads((WORKSPACE/'plot/figure_index.json').read_text())
FIGURES={int(f['figure']):next(p for p in Path(f['code_directory']).parts if p[:2].isdigit()) for f in _index['figures']}
_KINDS={'study_area':1,'hazard':4,'hazard_streets':4,'tsx_deformation':6,
        'vulnerability':8,'exposure':8,'final_risk':10,'risk':10,'risk_transect':10,
        '12_insar_contribution':12,'13_event_validation':13}

def project_path(filename):
    """Locate a primary or supporting project, without legacy path aliases."""
    aliases={'seismic_building_vulnerability.qgz':'08a_vulnerability.qgz',
             'seismic_building_exposure.qgz':'08b_exposure.qgz',
             'seismic_building_risk.qgz':'10_risk_base.qgz',
             'seismic_building_hazard.qgz':'04_seismic_hazard.qgz'}
    filename=aliases.get(str(filename),str(filename))
    existing=[p for p in ROOT.glob('[0-9][0-9]_*/qgis/**/*.qgz') if p.name==filename]
    if existing:return existing[0]
    return ROOT/FIGURES[int(filename[:2])]/'qgis/projects'/filename

def layout_directory(kind):
    kind=str(kind)
    if kind=='risk':kind='final_risk'
    return ROOT/FIGURES[_KINDS[kind]]/'qgis/layouts'/kind

def export_path(relative=''):
    """Route map exports and shared checks to their figure-specific folders."""
    relative=str(relative)
    first=relative.split('/')[0]
    if first in _KINDS:
        if first=='risk':first='final_risk';relative=first+relative[len('risk'):]
        return ROOT/FIGURES[_KINDS[first]]/'output/qgis'/relative
    if not relative or first=='current_layout_record' or first.startswith(('hazard_','Kunming_Building_Hazard')) or first=='export_quality_checks.json':
        return ROOT/FIGURES[4]/'output/qgis'/relative
    return ROOT/'shared/output/qgis'/relative

PROJECT=project_path('04_seismic_hazard.qgz')
BASIC=WORKSPACE/'data'
INTERMEDIATE=WORKSPACE/'result/intermediate'
RESULTS=WORKSPACE/'result'
VALIDATION=WORKSPACE/'data/validation'
EXPORTS=export_path()
HISTORY=ROOT/'shared/qgis/records'

_MAP_SOURCES={'Kunming_Building_Hazard_Streets':4,'Kunming_Building_Vulnerability':8,'Kunming_Building_Exposure':8,
              'Kunming_Final_Building_Risk':10,'Kunming_Risk_Transects_AB_CD_Map':10}

def map_source_path(filename):
    """Delivery copy of a native map export, kept in that figure's output/qgis/map_sources."""
    name=Path(filename).name
    figure=next(n for stem,n in _MAP_SOURCES.items() if name.startswith(stem+'_'))
    return ROOT/FIGURES[figure]/'output/qgis/map_sources'/name
