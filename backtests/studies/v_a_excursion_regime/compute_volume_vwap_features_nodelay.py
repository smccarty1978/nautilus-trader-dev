"""Volume + VWAP feature extension for no-delay V_A snapshots.

Thin wrapper that imports the augmentation logic from
`compute_volume_vwap_features.py` and points it at the no-delay
collector output directories.

Causality structure unchanged from the audited original; only
SNAP_PATHS and OUT_PATHS differ.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Import everything from the original (audited) script so the
# augmentation logic is shared. Then override the paths.
import importlib.util
spec = importlib.util.spec_from_file_location(
    "compute_vol_vwap_orig",
    "studies/v_a_excursion_regime/compute_volume_vwap_features.py")
orig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orig)

YEARS = [2024, 2025, 2026]
orig.SNAP_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_nodelay_{yr}/snapshots.parquet"
    for yr in YEARS
}
orig.OUT_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_nodelay_{yr}/snapshots_with_vol_vwap.parquet"
    for yr in YEARS
}
orig.YEARS = YEARS


if __name__ == "__main__":
    print("Running volume+VWAP augmentation on NO-DELAY snapshots...")
    orig.main()
