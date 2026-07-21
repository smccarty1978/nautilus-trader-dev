"""Feature-reduction study on no-delay walk-forward ML.

Wrapper around `ml_va_walkforward_075atr_featselect.py` with paths
redirected to the no-delay collector output. Lets us compare
N=20 (the previous run's sweet spot) on no-delay vs delayed data.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import importlib.util
spec = importlib.util.spec_from_file_location(
    "fs_orig",
    "studies/v_a_excursion_regime/ml_va_walkforward_075atr_featselect.py")
orig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orig)

YEARS = [2024, 2025, 2026]
orig.SNAP_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_nodelay_{yr}/snapshots_with_vol_vwap.parquet"
    for yr in YEARS
}
orig.TRADE_PATHS = {
    yr: f"collectors/collector_v2/results/v_a_v0_nodelay_{yr}/trades.parquet"
    for yr in YEARS
}
orig.YEARS = YEARS


if __name__ == "__main__":
    print("Running feature-selection ML on NO-DELAY data...")
    orig.main()
