"""Canonical workspace paths shared by the model and plotting code."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parent
DATA_ROOT = WORKSPACE_ROOT / "data"
RESULT_ROOT = WORKSPACE_ROOT / "result"
STATISTICS_ROOT = RESULT_ROOT / "statistics"
PLOT_CODE_ROOT = WORKSPACE_ROOT / "plot/shared"
PLOT_OUTPUT_ROOT = WORKSPACE_ROOT / "plot"


def resolve_path(value):
    """Resolve workspace-relative configuration entries."""
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (WORKSPACE_ROOT / path).resolve()
