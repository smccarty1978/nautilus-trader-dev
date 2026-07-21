import pandas as pd
from pathlib import Path

OUT_DIR = Path("studies/regime_sequence_signal_audit/results")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def run_split_audit():
    print("Running Phase 0: Audit data splits and chronology...")
    
    # Define splits data
    data = [
        {
            "period": "2021",
            "start_date": "2021-01-01",
            "end_date": "2021-12-31",
            "role": "train",
            "used_for_feature_fit": False,
            "used_for_model_fit": True,
            "used_for_threshold_selection": False,
            "used_for_policy_selection": False,
            "used_for_reporting_only": False
        },
        {
            "period": "2022",
            "start_date": "2022-01-01",
            "end_date": "2022-12-31",
            "role": "train",
            "used_for_feature_fit": False,
            "used_for_model_fit": True,
            "used_for_threshold_selection": False,
            "used_for_policy_selection": False,
            "used_for_reporting_only": False
        },
        {
            "period": "2023",
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "role": "train",
            "used_for_feature_fit": False,
            "used_for_model_fit": True,
            "used_for_threshold_selection": False,
            "used_for_policy_selection": False,
            "used_for_reporting_only": False
        },
        {
            "period": "2024",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "role": "train",
            "used_for_feature_fit": False,
            "used_for_model_fit": True,
            "used_for_threshold_selection": False,
            "used_for_policy_selection": False,
            "used_for_reporting_only": False
        },
        {
            "period": "Jan-Feb 2025",
            "start_date": "2025-01-01",
            "end_date": "2025-02-28",
            "role": "validation",
            "used_for_feature_fit": False,
            "used_for_model_fit": False,
            "used_for_threshold_selection": True,
            "used_for_policy_selection": True,
            "used_for_reporting_only": False
        },
        {
            "period": "Mar-May 2025",
            "start_date": "2025-03-01",
            "end_date": "2025-05-31",
            "role": "inspected development test",
            "used_for_feature_fit": False,
            "used_for_model_fit": False,
            "used_for_threshold_selection": False,
            "used_for_policy_selection": False,
            "used_for_reporting_only": True
        },
        {
            "period": "remaining 2025",
            "start_date": "2025-06-01",
            "end_date": "2025-12-31",
            "role": "secondary OOS",
            "used_for_feature_fit": False,
            "used_for_model_fit": False,
            "used_for_threshold_selection": False,
            "used_for_policy_selection": False,
            "used_for_reporting_only": True
        },
        {
            "period": "2026",
            "start_date": "2026-01-01",
            "end_date": "2026-04-29",
            "role": "contaminated",
            "used_for_feature_fit": False,
            "used_for_model_fit": False,
            "used_for_threshold_selection": False,
            "used_for_policy_selection": False,
            "used_for_reporting_only": True
        }
    ]
    
    df = pd.DataFrame(data)
    df.to_parquet(OUT_DIR / "data_split_audit.parquet", index=False)
    
    # Generate markdown report
    md_content = """# Chronological Data Split Audit

| Period | Start Date | End Date | Role | Feature Fit | Model Fit | Threshold Selection | Policy Selection | Reporting Only |
|---|---|---|---|---|---|---|---|---|
"""
    for row in data:
        md_content += f"| {row['period']} | {row['start_date']} | {row['end_date']} | {row['role']} | {row['used_for_feature_fit']} | {row['used_for_model_fit']} | {row['used_for_threshold_selection']} | {row['used_for_policy_selection']} | {row['used_for_reporting_only']} |\\n"
        
    md_content += """
## Split Contamination Summary
* **2021 - 2024**: Strict **train** set. Used only for model training (fitting early-failure classifier and PnL regressor).
* **Jan-Feb 2025**: **Validation** set. Used for hyperparameter tuning, model specification evaluation, and selecting/freezing decision thresholds (e.g. F5 threshold).
* **Mar-May 2025**: **Inspected development test** set. Used for secondary policy simulation and reporting primary metrics (e.g. EV lift, RTH/ETH effects).
* **Remaining 2025**: **Secondary OOS** set. Kept unseen during model tuning.
* **2026**: **Contaminated**. Because the master runner evaluated 2026 within the same script run prior to policy freezing and without an explicit firewall, it cannot be considered a clean out-of-sample (OOS) dataset. It has been flagged as contaminated.
"""
    
    with open(OUT_DIR / "data_split_audit.md", "w") as f:
        f.write(md_content)
    print("Phase 0 complete.")

if __name__ == "__main__":
    run_split_audit()
