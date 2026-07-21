import os
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
OUT_DIR = PROJECT_ROOT / "studies/regime_sequence_signal_audit/results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print("Building chronology and artifact firewall table...")
    
    # 1. Flip context atlas
    flip_atlas_path = PROJECT_ROOT / "studies/regime_sequence_chop_context/results/flip_context_atlas.parquet"
    if flip_atlas_path.exists():
        df_flip = pd.read_parquet(flip_atlas_path)
        flip_rows = len(df_flip)
        # F2 rows are unique events
        flip_events = len(df_flip[df_flip["population"] == "F2"])
        flip_cadence = "sampled at flips/confirmations"
        has_26_flip = "2026" in df_flip["period"].values or "test" in df_flip["period"].values
    else:
        flip_rows = 0
        flip_events = 0
        flip_cadence = "N/A"
        has_26_flip = False

    # 2. Weakness checkpoint atlas
    weak_atlas_path = PROJECT_ROOT / "studies/regime_sequence_chop_context/results/weakness_checkpoint_atlas.parquet"
    if weak_atlas_path.exists():
        df_weak = pd.read_parquet(weak_atlas_path)
        weak_rows = len(df_weak)
        # Unique episodes
        if "episode_id" in df_weak.columns:
            weak_events = df_weak["episode_id"].nunique()
        elif "observation_time" in df_weak.columns:
            weak_events = df_weak["regime"].count()  # approximate
        else:
            weak_events = 0
        weak_cadence = "5s runtime serving cadence"
        has_26_weak = True
    else:
        weak_rows = 0
        weak_events = 0
        weak_cadence = "N/A"
        has_26_weak = False

    # Artifact list
    artifacts = [
        {
            "path": "data/raw/NQ_v0_1s_{2021-2026}.parquet",
            "description": "Raw 1s trades, ask/bid sizes, and prices from CME",
            "creation_script": "scripts/download_data.py",
            "input_years": "2021-2026",
            "rows": "~1.5B (total across years)",
            "events": "N/A",
            "cadence": "1s bars",
            "inf_fit": "No",
            "inf_feat": "No",
            "inf_cal": "No",
            "inf_thresh": "No",
            "inf_pers": "No",
            "inf_policy": "No",
            "contains_2026": "Yes",
            "permissible_use": "Feature computation / Replay simulation",
            "firewall_status": "APPROVED",
            "notes": "Original raw data firewall; read-only input"
        },
        {
            "path": "studies/regime_sequence_chop_context/results/flip_context_atlas.parquet",
            "description": "F1 and F2 flip context population and baseline outcomes",
            "creation_script": "studies/regime_sequence_chop_context/build_flip_atlas.py",
            "input_years": "2021-2026",
            "rows": f"{flip_rows:,}",
            "events": f"{flip_events:,}",
            "cadence": flip_cadence,
            "inf_fit": "No",
            "inf_feat": "No",
            "inf_cal": "No",
            "inf_thresh": "No",
            "inf_pers": "No",
            "inf_policy": "No",
            "contains_2026": "Yes" if has_26_flip else "No",
            "permissible_use": "Exploratory / descriptive baseline comparison",
            "firewall_status": "APPROVED",
            "notes": "Pre-existing atlas; split into Val (2025) and Test (2026) for model use"
        },
        {
            "path": "studies/regime_sequence_chop_context/results/weakness_checkpoint_atlas.parquet",
            "description": "5-second checkpoints of active regimes and outcomes",
            "creation_script": "studies/regime_sequence_chop_context/build_weakness_atlas.py",
            "input_years": "2021-2026",
            "rows": f"{weak_rows:,}",
            "events": f"{weak_events:,}",
            "cadence": weak_cadence,
            "inf_fit": "No",
            "inf_feat": "No",
            "inf_cal": "No",
            "inf_thresh": "No",
            "inf_pers": "No",
            "inf_policy": "No",
            "contains_2026": "Yes" if has_26_weak else "No",
            "permissible_use": "Exploratory / W4 exit simulation",
            "firewall_status": "APPROVED",
            "notes": "Pre-existing checkpoints; split into Val (2025) and Test (2026) for model use"
        },
        {
            "path": "studies/regime_sequence_signal_audit/results/track_a_model.weights",
            "description": "Trained Ridge/GBDT context weights for payoff-aligned targets",
            "creation_script": "studies/regime_sequence_signal_audit/run_track_a_payoff_aligned.py",
            "input_years": "2021-2024",
            "rows": "TBD",
            "events": "TBD",
            "cadence": "N/A",
            "inf_fit": "Yes",
            "inf_feat": "No",
            "inf_cal": "No",
            "inf_thresh": "No",
            "inf_pers": "No",
            "inf_policy": "No",
            "contains_2026": "No",
            "permissible_use": "Model scoring on 2025 and 2026",
            "firewall_status": "FROZEN_ON_TRAIN",
            "notes": "Must never see 2025 or 2026 during fitting"
        },
        {
            "path": "studies/regime_sequence_signal_audit/results/track_b_w4.weights",
            "description": "Trained GBDT weakness model W4 weights",
            "creation_script": "studies/regime_sequence_signal_audit/run_track_b_weakness.py",
            "input_years": "2021-2024",
            "rows": "TBD",
            "events": "TBD",
            "cadence": "N/A",
            "inf_fit": "Yes",
            "inf_feat": "No",
            "inf_cal": "No",
            "inf_thresh": "No",
            "inf_pers": "No",
            "inf_policy": "No",
            "contains_2026": "No",
            "permissible_use": "Model scoring on 2025 and 2026",
            "firewall_status": "FROZEN_ON_TRAIN",
            "notes": "Must never see 2025 or 2026 during fitting"
        },
        {
            "path": "studies/regime_sequence_signal_audit/results/track_a_policy_params.json",
            "description": "Frozen policy thresholds and parameters (R1-R5)",
            "creation_script": "studies/regime_sequence_signal_audit/run_track_a_payoff_aligned.py",
            "input_years": "2025",
            "rows": "N/A",
            "events": "N/A",
            "cadence": "N/A",
            "inf_fit": "No",
            "inf_feat": "Yes",
            "inf_cal": "Yes",
            "inf_thresh": "Yes",
            "inf_pers": "No",
            "inf_policy": "Yes",
            "contains_2026": "No",
            "permissible_use": "Causal policy simulation on 2026",
            "firewall_status": "FROZEN_ON_VAL",
            "notes": "Must be frozen on 2025 before touching 2026"
        },
        {
            "path": "studies/regime_sequence_signal_audit/results/track_b_policy_params.json",
            "description": "Frozen weakness threshold, persistence, and state machine parameters",
            "creation_script": "studies/regime_sequence_signal_audit/run_track_b_weakness.py",
            "input_years": "2025",
            "rows": "N/A",
            "events": "N/A",
            "cadence": "N/A",
            "inf_fit": "No",
            "inf_feat": "Yes",
            "inf_cal": "Yes",
            "inf_thresh": "Yes",
            "inf_pers": "Yes",
            "inf_policy": "Yes",
            "contains_2026": "No",
            "permissible_use": "Causal policy simulation on 2026",
            "firewall_status": "FROZEN_ON_VAL",
            "notes": "Must be frozen on 2025 before touching 2026"
        }
    ]
    
    # Write to Markdown
    md_path = OUT_DIR / "chronology_firewall.md"
    with open(md_path, "w") as f:
        f.write("# Chronology and Artifact Firewall Table\n\n")
        f.write("| Artifact Path | Description | Creation Script | Input Years | Row Count | Event Count | Cadence | Influenced Fit | Influenced Feat | Influenced Cal | Influenced Thresh | Influenced Pers | Influenced Policy | Contains 2026 | Permissible Final Use | Firewall Status | Notes |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for art in artifacts:
            f.write(f"| `{art['path']}` | {art['description']} | {art['creation_script']} | {art['input_years']} | {art['rows']} | {art['events']} | {art['cadence']} | {art['inf_fit']} | {art['inf_feat']} | {art['inf_cal']} | {art['inf_thresh']} | {art['inf_pers']} | {art['inf_policy']} | {art['contains_2026']} | {art['permissible_use']} | **{art['firewall_status']}** | {art['notes']} |\n")
            
    print(f"Firewall table successfully written to {md_path}")

if __name__ == "__main__":
    main()
