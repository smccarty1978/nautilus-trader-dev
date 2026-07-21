"""Master runner: executes all 8 phases in order.

Usage:
    python studies/rl_regime_feasibility/expanded_dynamic/run_all.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import importlib


def run_phase(module_name: str, func_name: str, *args, **kwargs):
    t0 = time.time()
    print(f"\n{'='*70}")
    print(f"  Running {module_name}.{func_name}")
    print(f"{'='*70}")
    mod = importlib.import_module(module_name)
    fn  = getattr(mod, func_name)
    result = fn(*args, **kwargs)
    print(f"\n  [{module_name}] Done in {time.time()-t0:.1f}s")
    return result


def main():
    t_start = time.time()
    base = "studies.rl_regime_feasibility.expanded_dynamic"

    # Phase 1+2: Audit + build expanded features
    phase12_mod = importlib.import_module(f"{base}.build_expanded_features")
    phase12_mod.write_audit()
    feat_df = phase12_mod.build_expanded_features()
    phase12_mod.write_inventory(feat_df)
    feat_df.to_parquet(
        "studies/rl_regime_feasibility/expanded_dynamic/results/expanded_features.parquet",
        index=False
    )
    print(f"\n  Expanded features saved: {feat_df.shape}")

    # Phase 3: Build targets
    phase3_mod = importlib.import_module(f"{base}.build_targets")
    phase3_mod.build_entry_targets()
    phase3_mod.build_exit_targets()

    # Phase 4: Ablations
    phase4_mod = importlib.import_module(f"{base}.run_ablations")
    abl_metrics, feat_registry = phase4_mod.run_ablations()

    # Phase 5+6: Policy + replay
    phase56_mod = importlib.import_module(f"{base}.run_policy_and_replay")
    from studies.rl_regime_feasibility.expanded_dynamic.run_policy_and_replay import (
        train_entry_model, train_exit_model, tune_thresholds, run_replay
    )
    import pandas as pd
    OUT_DIR = Path("studies/rl_regime_feasibility/expanded_dynamic/results")

    feat_df    = pd.read_parquet(OUT_DIR / "expanded_features.parquet")
    entry_tgt  = pd.read_parquet(OUT_DIR / "entry_targets.parquet")
    exit_tgt   = pd.read_parquet(OUT_DIR / "exit_targets.parquet")

    entry_model, entry_feats, entry_feat_df, entry_val_auc = train_entry_model(feat_df, entry_tgt)
    exit_model, exit_feats, exit_val_auc = train_exit_model(feat_df, exit_tgt)

    thresholds = tune_thresholds(entry_model, entry_feats, feat_df, entry_tgt)

    import json
    thresholds["entry_val_auc"] = round(entry_val_auc, 4)
    thresholds["exit_val_auc"]  = round(exit_val_auc, 4)
    with open(OUT_DIR / "policy_thresholds.json", "w") as f:
        json.dump(thresholds, f, indent=2)

    trades_df, ep_summary = run_replay(
        entry_model, entry_feats,
        exit_model, exit_feats,
        feat_df, exit_tgt,
        thresholds,
    )

    # Phase 7: Controls
    phase7_mod = importlib.import_module(f"{base}.run_controls")
    phase7_mod.run_controls()

    # Phase 8: Report
    phase8_mod = importlib.import_module(f"{base}.generate_report")
    r = phase8_mod.load_results()
    report = phase8_mod.generate_report(r)
    out_path = OUT_DIR / "final_report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nFinal report saved: {out_path}")

    print(f"\n{'='*70}")
    print(f"  ALL PHASES COMPLETE in {time.time()-t_start:.1f}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
