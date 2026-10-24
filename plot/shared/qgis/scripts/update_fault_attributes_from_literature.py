#!/usr/bin/env python3
"""Build an auditable literature enrichment without changing model inputs.

Run with the seismic environment, then use sync_fault_literature_qgis.py in
native PyQGIS. Reviewed observations are inputs, not automatically inferred
from PDF text. Re-running creates a new history directory and an atomic GPKG.
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse
import hashlib
import json
import os
import shutil
import sqlite3

import pandas as pd
import pyogrio

QGIS_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = QGIS_ROOT.parent
INPUT = QGIS_ROOT / '../data/faults/02_Kunming_Fault_Processed.shp'
OUTPUT = QGIS_ROOT / '../data/faults/kunming_faults_literature.gpkg'
REVIEW_DIR = QGIS_ROOT / '../result/intermediate/fault_literature'
REVIEW = REVIEW_DIR / 'reviewed_fault_evidence.json'
PROJECT = QGIS_ROOT / '04_seismic_hazard/qgis/projects/04_seismic_hazard.qgz'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def protected_paths():
    paths = list(INPUT.parent.glob(INPUT.stem + '.*'))
    paths += [INPUT.parent / 'China_faults.gpkg']
    paths += [p for p in (QGIS_ROOT / '../result').rglob('*') if p.is_file()]
    return sorted(p for p in paths if p.suffix not in {'.shm', '.wal'} and not p.name.endswith(('-wal', '-shm')))


def fingerprint(paths):
    return {str(p.relative_to(WORKSPACE)): sha(p) for p in paths}


def register_table(con, name, rows, pk):
    frame = pd.DataFrame(rows)
    frame.insert(0, 'fid', range(1, len(frame) + 1))
    columns = []
    numeric = {'source_row', 'value', 'value_min', 'value_max', 'uncertainty_pm', 'year', 'pages'}
    for col in frame.columns:
        typ = 'INTEGER PRIMARY KEY' if col == 'fid' else ('REAL' if col in numeric else 'TEXT')
        columns.append(f'"{col}" {typ}')
    con.execute(f'CREATE TABLE "{name}" ({", ".join(columns)})')
    values = frame.astype(object).where(pd.notna(frame), None)
    con.executemany(f'INSERT INTO "{name}" VALUES ({",".join("?" for _ in frame.columns)})', values.itertuples(index=False, name=None))
    con.execute(f'CREATE UNIQUE INDEX "{name}_{pk}" ON "{name}" ("{pk}")')
    con.execute('INSERT INTO gpkg_contents (table_name,data_type,identifier,description) VALUES (?,?,?,?)', (name, 'attributes', name, 'Reviewed literature evidence; PDF pages are 1-based'))
    if con.execute("SELECT name FROM sqlite_master WHERE name='gpkg_ogr_contents'").fetchone():
        con.execute('INSERT INTO gpkg_ogr_contents(table_name,feature_count) VALUES (?,?)', (name, len(frame)))
    frame.drop(columns='fid').to_csv(REVIEW_DIR / f'{name}.csv', index=False, encoding='utf-8-sig')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path, help='New, empty history directory')
    parser.add_argument('--resume-incomplete', action='store_true', help='Reuse an incomplete run with identical reviewed input')
    args = parser.parse_args()
    stamp = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d_%H%M%S')
    history = args.history or QGIS_ROOT / 'history/changes' / (stamp + '_fault_literature_enrichment')
    if args.resume_incomplete:
        assert history.is_dir() and not (history / 'data_validation.json').exists()
        assert sha(history / REVIEW.name) == sha(REVIEW)
    else:
        history.mkdir(parents=True, exist_ok=False)
    reviewed = json.loads(REVIEW.read_text())
    expected_input = json.loads((REVIEW_DIR / 'original_faults_manifest.json').read_text())
    assert fingerprint(sorted(INPUT.parent.glob(INPUT.stem + '.*'))) == expected_input, 'Original fault dataset changed; review row/name correspondence again'
    before = fingerprint(protected_paths())
    for s in reviewed['sources']:
        path = WORKSPACE / s['path']
        assert sha(path) == s['sha256'], f'PDF changed: {path}'
    for s in reviewed['evidence']:
        source = next(x for x in reviewed['sources'] if x['source_id'] == s['source_id'])
        assert all(1 <= int(p) <= source['pages'] for p in s['pdf_pages'].split(','))
        assert not (s['value_min'] is not None and s['value_max'] is not None and s['value_min'] > s['value_max'])
        if source['source_id'] == 'COMMENT2026':
            assert s['decision'].startswith('excluded_')
        if source['source_id'] == 'CHANG2026' and s['topic'] == 'slip_rate':
            assert s['evidence_grade'] == 'secondary_review' and s['underlying_reference']
    backup = history / 'original_faults'
    backup.mkdir(exist_ok=args.resume_incomplete)
    for path in INPUT.parent.glob(INPUT.stem + '.*'):
        if (backup / path.name).exists():
            assert sha(backup / path.name) == sha(path)
        shutil.copy2(path, backup / path.name)
    shutil.copy2(REVIEW, history / REVIEW.name)
    if OUTPUT.exists():
        shutil.copy2(OUTPUT, history / 'enriched_before.gpkg')
    source = pyogrio.read_dataframe(INPUT)
    assert len(source) == 59 and source.crs.to_epsg() == 4547
    original_columns = [c for c in source if c != 'geometry']
    assert 'Mw_Max' not in source
    enriched = source.copy()
    enriched['fault_uid'] = [f'KMF_{i:04}' for i in range(len(source))]
    enriched['source_row'] = list(range(len(source)))
    text_fields = ['name_cn', 'name_en', 'age', 'age_status', 'motion', 'strike', 'dip', 'slip', 'paleo', 'segment', 'notes']
    for field in text_fields:
        enriched['lit_' + field] = ''
    enriched['lit_sources'] = ''
    enriched['lit_evidence_n'] = 0
    enriched['lit_confidence'] = 'unreviewed'
    # "not_covered" means no directly adopted attribute for this source feature,
    # not absence of a lexical mention in a paper (see coverage_audit.csv).
    enriched['lit_status'] = ['unresolved_unnamed' if pd.isna(x) or not str(x).strip() else 'not_covered_by_supplied_papers' for x in source['FaultName']]
    enriched['lit_review_date'] = reviewed['review_date']
    for entry in reviewed['summaries']:
        i = entry['source_row']
        match = next(m for m in reviewed['scope_matches'] if m['fault_uid'] == entry['fault_uid'])
        assert pd.notna(source.loc[i, 'FN_Ch']) and (entry['name_cn'].split('（')[0].split('系统')[0].split('带')[0][:2] in source.loc[i, 'FN_Ch'] or entry['scope_id'] == 'luoci')
        records = [e for e in reviewed['evidence'] if e['fault_uid'] == entry['fault_uid']]
        for field in text_fields:
            enriched.loc[i, 'lit_' + field] = entry[field]
        enriched.loc[i, 'lit_notes'] += '；' + match['scope_note']
        enriched.loc[i, 'lit_sources'] = ';'.join(sorted(set(e['source_id'] for e in records)))
        enriched.loc[i, 'lit_evidence_n'] = len(records)
        enriched.loc[i, 'lit_confidence'] = match['confidence']
        enriched.loc[i, 'lit_status'] = 'reviewed_scope_limited'
    stage = OUTPUT.with_name('.kunming_faults_literature_stage.gpkg')
    if stage.exists():
        stage.unlink()
    # The Shapefile mixes 30 LineStrings and 29 MultiLineStrings. Declaring the
    # GPKG geometry column GEOMETRY avoids silent promotion of single parts.
    # OGR/QGIS discovers the line family; every per-feature WKB stays exact.
    pyogrio.write_dataframe(enriched, stage, layer='faults_enriched', driver='GPKG', geometry_type='Unknown', promote_to_multi=False)
    with sqlite3.connect(stage) as con:
        register_table(con, 'fault_evidence', reviewed['evidence'], 'evidence_id')
        register_table(con, 'source_catalog', reviewed['sources'], 'source_id')
        register_table(con, 'scope_matches', reviewed['scope_matches'], 'scope_id')
        con.execute('CREATE INDEX evidence_fault_idx ON fault_evidence(fault_uid)')
        con.execute('CREATE INDEX evidence_source_idx ON fault_evidence(source_id)')
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    roundtrip = pyogrio.read_dataframe(stage, layer='faults_enriched')
    pd.testing.assert_frame_equal(source[original_columns].reset_index(drop=True), roundtrip[original_columns].reset_index(drop=True), check_dtype=False, check_exact=True)
    assert source.crs == roundtrip.crs
    assert all(a.wkb == b.wkb for a, b in zip(source.geometry, roundtrip.geometry)), 'Geometry bytes changed'
    assert len(roundtrip) == 59 and roundtrip['fault_uid'].is_unique
    assert 'Mw_Max' not in roundtrip
    os.replace(stage, OUTPUT)
    changes = []
    for entry in reviewed['summaries']:
        i = entry['source_row']
        for field in [c for c in enriched if c.startswith('lit_')]:
            changes.append(dict(fault_uid=entry['fault_uid'],source_row=i,original_FaultName=source.loc[i,'FaultName'],field=field,original_value=None,new_value=enriched.loc[i,field],source_ids=enriched.loc[i,'lit_sources'],decision='new_context_field_original_attributes_unchanged'))
    pd.DataFrame(changes).to_csv(REVIEW_DIR / 'fault_attribute_changes.csv', index=False, encoding='utf-8-sig')
    after = fingerprint(protected_paths())
    assert before == after, 'Protected files changed during build'
    checks = dict(created_at=stamp,review_date=reviewed['review_date'],history=str(history),output=str(OUTPUT),output_sha256=sha(OUTPUT),reviewed_input_sha256=sha(REVIEW),features=59,matched_features=len(reviewed['summaries']),unnamed_features=int(source['FaultName'].isna().sum()),evidence_records=len(reviewed['evidence']),sources=len(reviewed['sources']),unmatched_literature_objects=sum(m['match_status']=='unmatched' for m in reviewed['scope_matches']),original_attributes_exact=True,geometry_wkb_exact=True,crs='EPSG:4547',model_Mw_and_Length_km_unchanged=True,no_Mw_Max_field=True,protected_files_unchanged=True,protected_file_count=len(before),source_pdfs_hash_verified=True)
    write_json(history / 'protected_sha256.json', before)
    write_json(history / 'data_validation.json', checks)
    write_json(REVIEW_DIR / 'latest_build.json', checks)
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
