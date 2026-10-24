"""Validate current Jenks classes, numeric summaries and rendered count labels."""
from pathlib import Path
import sys
WORKSPACE = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(WORKSPACE / 'project/code'), str(WORKSPACE / 'plot/shared'), str(Path(__file__).resolve().parent)]
import json
import sqlite3
from collections import Counter
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from paths import RESULT_ROOT, STATISTICS_ROOT, PLOT_OUTPUT_ROOT
from classification import CLASS_NAMES, classify
from current_results import SPECS, continuous_hash, current_breaks


def main():
    report = {'modules': {}, 'all_checks_passed': True}
    for module, relative, table, field, class_field, stem in SPECS:
        path = RESULT_ROOT / relative
        breaks = current_breaks(path, stem)
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            frame = pd.read_sql_query(f'SELECT "{field}", "{class_field}" FROM "{table}"', db)
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            current_fingerprint = continuous_hash(db, table)
        labels = classify(frame[field], breaks)
        assert np.array_equal(labels.to_numpy(), frame[class_field].to_numpy()), module
        counts = labels.value_counts().reindex(CLASS_NAMES, fill_value=0)
        folder = STATISTICS_ROOT / module / 'analysis'
        stats = pd.read_csv(folder / f'{stem}_class_statistics.csv')
        column = 'Building_Count' if module == 'Hazard' else 'building_count'
        assert np.array_equal(stats[column].to_numpy(), counts.to_numpy()), module
        for level in ['county', 'street']:
            name = f'pga_by_{level}_level_unit.csv' if module == 'Hazard' else f'{stem}_by_{level}.csv'
            admin = pd.read_csv(folder / name)
            columns = [name.replace(' ', '_') + '_Count' for name in CLASS_NAMES]
            assert np.array_equal(admin[columns].fillna(0).sum().to_numpy(int), counts.to_numpy()), (module, level)
            assert int(admin.Building_Count.sum()) == len(frame)
        report['modules'][module] = {'building_count': len(frame), 'class_counts': counts.to_dict(),
                                     'sqlite_integrity_passed': True, 'current_continuous_and_geometry_sha256': current_fingerprint,
                                     'classes_statistics_and_admin_totals_match': True, 'breaks': breaks}
    svg = PLOT_OUTPUT_ROOT / '09_class_composition/output/four_indicator_class_counts_2x2.svg'
    nodes = list(ET.parse(svg).getroot().iter('{http://www.w3.org/2000/svg}text'))
    rendered = Counter(''.join(node.itertext()) for node in nodes)
    for info in report['modules'].values():
        for count in info['class_counts'].values():
            assert rendered[f'{count:,}'] >= 1
            assert rendered[f'({count / info["building_count"] * 100:.2f}%)'] >= 1
    report['four_panel_labels_verified'] = True
    destination = STATISTICS_ROOT / 'jenks_validation.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
