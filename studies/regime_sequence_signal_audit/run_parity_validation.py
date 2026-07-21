import os
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
OUT_DIR = PROJECT_ROOT / "studies/regime_sequence_signal_audit/results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def check_parity(year: int, policy: str):
    print(f"Checking feature and score parity for {year} {policy}...")
    
    parity_file = PROJECT_ROOT / f"backtests/results/w4_parity_{year}_{policy}.parquet"
    if not parity_file.exists():
        print(f"Error: Parity log file not found at {parity_file}")
        return
        
    df = pd.read_parquet(parity_file)
    if len(df) == 0:
        print("Parity log is empty!")
        return
        
    print(f"Loaded {len(df):,} checkpoints from parity log.")
    
    # Calculate differences
    diff_age = np.abs(df["offline_regime_age"] - df["runtime_regime_age"])
    diff_pnl = np.abs(df["offline_current_pnl"] - df["runtime_current_pnl"])
    diff_gb = np.abs(df["offline_giveback"] - df["runtime_giveback"])
    
    max_diff_age = diff_age.max()
    max_diff_pnl = diff_pnl.max()
    max_diff_gb = diff_gb.max()
    
    mean_diff_age = diff_age.mean()
    mean_diff_pnl = diff_pnl.mean()
    mean_diff_gb = diff_gb.mean()
    
    # NOTE: There is no independent "online" W4 score to compare against offline.
    # The live strategy does not run the model at runtime — it looks up the
    # precomputed offline prediction by (direction, regime_start_time,
    # observation_time) key (see w4_exit_strategy.py:_process_5s_checkpoint).
    # So a prediction-parity check is structurally meaningless here (it would
    # always compare a column to itself) and has been removed. What this
    # script actually validates is that the CAUSAL FEATURES the live strategy
    # computes at runtime (regime age, current PnL, giveback) match the values
    # baked into the offline prediction table for the same key — i.e. that the
    # offline table is being looked up against the right, causally-identical
    # observation rather than a mismatched or leaked one.

    print("\n--- Parity Metrics ---")
    print(f"  Regime Age:  Max Diff = {max_diff_age:.6f}s | Mean Diff = {mean_diff_age:.6f}s")
    print(f"  Current PnL: Max Diff = {max_diff_pnl:.6f} ATR | Mean Diff = {mean_diff_pnl:.6f} ATR")
    print(f"  Giveback:    Max Diff = {max_diff_gb:.6f} ATR | Mean Diff = {mean_diff_gb:.6f} ATR")

    # Check if within threshold
    age_ok = max_diff_age < 1.0 # Within 1 second due to bar boundaries
    pnl_ok = max_diff_pnl < 1e-4
    gb_ok = max_diff_gb < 1e-4

    status = "PASS" if (age_ok and pnl_ok and gb_ok) else "FAIL"
    print(f"\nParity Verification Status: **{status}**")

    # Save results as markdown
    report_md = f"""# Parity Verification Report ({year} {policy})

* **Status**: **{status}**
* **Total checkpoints verified**: {len(df):,}
* **Scope**: Verifies that runtime-computed causal features (regime age, current PnL, giveback)
  match the offline prediction table for the same (direction, regime_start_time, observation_time)
  key. Does NOT independently verify the W4 model score itself — the live strategy looks up the
  offline prediction rather than recomputing it, so there is no independent online score to compare.

| Feature | Max Absolute Difference | Mean Absolute Difference | Parity Status |
|---|---|---|---|
| **Regime Age** | {max_diff_age:.6f} s | {mean_diff_age:.6f} s | {"PASS" if age_ok else "FAIL"} |
| **Current PnL** | {max_diff_pnl:.6f} ATR | {mean_diff_pnl:.6f} ATR | {"PASS" if pnl_ok else "FAIL"} |
| **Giveback** | {max_diff_gb:.6f} ATR | {mean_diff_gb:.6f} ATR | {"PASS" if gb_ok else "FAIL"} |
"""
    with open(OUT_DIR / "parity_verification_report.md", "w") as f:
        f.write(report_md)
        
    print(f"Report written to {OUT_DIR / 'parity_verification_report.md'}")

if __name__ == "__main__":
    check_parity(2025, "B1")
