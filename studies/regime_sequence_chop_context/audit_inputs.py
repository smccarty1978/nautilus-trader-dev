import json
import os
from pathlib import Path
import pandas as pd
import numpy as np
import glob

# Cost scenario specs
NQ_MULTIPLIER = 20.0
NQ_TICK_SIZE = 0.25
CAT_STOP_ATR = 1.50

def run_audit():
    print("Starting Phase 0: Input and Baseline Audit...")
    
    # Check data files
    raw_dir = Path("data/raw")
    nq_files = sorted(glob.glob(str(raw_dir / "NQ_v0_1s_*.parquet")))
    
    print(f"Found {len(nq_files)} NQ 1s files.")
    
    coverage_records = []
    for f in nq_files:
        name = os.path.basename(f)
        df_meta = pd.read_parquet(f, columns=[])
        n_rows = len(df_meta)
        
        # Read index for start/end
        df_idx = pd.read_parquet(f, columns=['close']) # close is small
        start_dt = df_idx.index.min()
        end_dt = df_idx.index.max()
        
        coverage_records.append({
            "filename": name,
            "row_count": n_rows,
            "start_time": str(start_dt),
            "end_time": str(end_dt),
        })
        print(f"  {name}: {n_rows:,} rows, {start_dt} to {end_dt}")
        
    df_coverage = pd.DataFrame(coverage_records)
    out_dir = Path("studies/regime_sequence_chop_context/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    df_coverage.to_parquet(out_dir / "data_coverage.parquet", index=False)
    
    # Save input contract
    contract = {
        "nq_multiplier": NQ_MULTIPLIER,
        "nq_tick_size": NQ_TICK_SIZE,
        "cat_stop_atr": CAT_STOP_ATR,
        "data_sources": coverage_records,
        "commission_rt": 5.0,
        "slippage_scenarios": {
            "base": {"entry_ticks": 0.0, "stop_ticks": 0.0},
            "base_plus_1t": {"entry_ticks": 1.0, "stop_ticks": 1.0},
            "base_plus_2t": {"entry_ticks": 2.0, "stop_ticks": 2.0}
        }
    }
    with open(out_dir / "input_contract.json", "w") as f_out:
        json.dump(contract, f_out, indent=2)
        
    print("Saved data coverage and input contract.")

if __name__ == "__main__":
    run_audit()
