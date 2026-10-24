"""Refresh paper tables and adopted statistical figures from saved model results."""
from pathlib import Path
import argparse, os, subprocess, sys
ROOT = Path(__file__).resolve().parents[3]
CODE = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-building-maps", action="store_true")
    args = parser.parse_args()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", MPLCONFIGDIR="/private/tmp/seismic-paper-mpl")
    scripts = [CODE / module / "run_analysis.py" for module in ["Hazard", "Vulnerability", "Exposure", "Risk"]]
    scripts += [ROOT / rel for rel in ["plot/04_seismic_hazard/code/draw_histogram.py", "plot/09_class_composition/code/draw_charts.py", "plot/11_street_patterns/code/compose_street_p90_maps.py"]]
    for script in scripts:
        subprocess.run([sys.executable, "-B", str(script)], cwd=ROOT, env=env, check=True)
    if args.with_building_maps:
        runner = ROOT / "plot/shared/qgis/scripts/run_pyqgis.sh"
        subprocess.run([str(runner), str(runner.with_name("sync_jenks_maps.py"))], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, "-B", str(CODE / "verify_jenks_outputs.py")], cwd=ROOT, env=env, check=True)

if __name__ == "__main__":
    main()
