"""Read-only definitions for current saved model results."""
from pathlib import Path
import hashlib, pickle, sqlite3
import pandas as pd

SPECS = [
    ("Hazard", "hazard/scs_pipeline/06_building_hazard.gpkg", "building_hazard", "PGA_Final_g", "PGA_Class", "pga"),
    ("Exposure", "exposure/scs_paper_method/building_exposure.gpkg", "building_exposure_scs", "Exp_Final", "Exposure_Class", "exposure"),
    ("Vulnerability", "vulnerability/scs_paper_method/02_building_comprehensive_vulnerability.gpkg", "building_comprehensive_vulnerability", "Vul_Index", "Vul_Class", "vulnerability"),
    ("Risk", "risk/scs_paper_method/building_risk.gpkg", "building_risk_scs", "Risk_Final", "Risk_Class", "risk"),
]

def continuous_hash(connection, table):
    fields = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
              if row[1] not in {"PGA_Class", "Exposure_Class", "Vul_Class", "Risk_Class"}]
    columns = ",".join(f'"{name}"' for name in fields)
    digest = hashlib.sha256()
    for row in connection.execute(f'SELECT {columns} FROM "{table}" ORDER BY Build_ID'):
        digest.update(pickle.dumps(row, protocol=4))
    return digest.hexdigest()


def current_breaks(result_path, stem):
    table = pd.read_csv(result_path.parent / f"{stem}_class_breaks.csv", float_precision="round_trip")
    return [float(table.lower_break.iloc[0]), *table.upper_break.astype(float).tolist()]
