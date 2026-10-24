#!/bin/zsh
# Use QGIS's own Python, Qt, GDAL and PROJ; no user installation is modified.
set -eu
SCRIPT_DIR="${0:A:h}"
export PROJ_DATA=/Applications/QGIS.app/Contents/Resources/qgis/proj
export GDAL_DATA=/Applications/QGIS.app/Contents/Resources/qgis/gdal
export QT_QPA_PLATFORM=offscreen
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$SCRIPT_DIR:/Applications/QGIS.app/Contents/Resources/python3.11:/Applications/QGIS.app/Contents/Resources/python3.11/lib-dynload:/Applications/QGIS.app/Contents/Resources/python3.11/site-packages"
# Write protection of adopted figures and QGIS master assets: see plot/shared/run_protected.sh.
exec "$SCRIPT_DIR/../../run_protected.sh" /Applications/QGIS.app/Contents/MacOS/python3.12 -u "$@"
