#!/bin/zsh
# Run a figure script with write protection (plot/shared/protected_writes.sb):
#   plot/shared/run_protected.sh plot/09_class_composition/code/draw_charts.py [args]
#   plot/shared/run_protected.sh /path/to/python -B script.py [args]
# A .py first argument runs with $PYTHON (default: the seismic conda env).
# SEISMIC_ALLOW_PROTECTED_WRITES=1 disables the protection for an intentional rebuild/publish.
set -eu
POLICY="${0:A:h}/protected_writes.sb"
export PYTHONDONTWRITEBYTECODE=1
if [[ "${1:-}" == *.py ]]; then
  set -- "${PYTHON:-/Users/bin/miniforge3/envs/seismic/bin/python}" "$@"
fi
if [[ "${SEISMIC_ALLOW_PROTECTED_WRITES:-0}" == 1 ]]; then
  print -u2 "run_protected: protection DISABLED (SEISMIC_ALLOW_PROTECTED_WRITES=1)"
  exec "$@"
fi
if [[ -n "${SEISMIC_PROTECTED:-}" ]]; then
  exec "$@"  # already inside the protected sandbox; children inherit it
fi
command -v sandbox-exec >/dev/null || { print -u2 "run_protected: sandbox-exec unavailable; refusing to run unprotected"; exit 1; }
export SEISMIC_PROTECTED=1
exec sandbox-exec -f "$POLICY" "$@"
