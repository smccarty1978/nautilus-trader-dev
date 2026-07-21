# Chronological Data Split Audit

| Period | Start Date | End Date | Role | Feature Fit | Model Fit | Threshold Selection | Policy Selection | Reporting Only |
|---|---|---|---|---|---|---|---|---|
| 2021 | 2021-01-01 | 2021-12-31 | train | False | True | False | False | False |\n| 2022 | 2022-01-01 | 2022-12-31 | train | False | True | False | False | False |\n| 2023 | 2023-01-01 | 2023-12-31 | train | False | True | False | False | False |\n| 2024 | 2024-01-01 | 2024-12-31 | train | False | True | False | False | False |\n| Jan-Feb 2025 | 2025-01-01 | 2025-02-28 | validation | False | False | True | True | False |\n| Mar-May 2025 | 2025-03-01 | 2025-05-31 | inspected development test | False | False | False | False | True |\n| remaining 2025 | 2025-06-01 | 2025-12-31 | secondary OOS | False | False | False | False | True |\n| 2026 | 2026-01-01 | 2026-04-29 | contaminated | False | False | False | False | True |\n
## Split Contamination Summary
* **2021 - 2024**: Strict **train** set. Used only for model training (fitting early-failure classifier and PnL regressor).
* **Jan-Feb 2025**: **Validation** set. Used for hyperparameter tuning, model specification evaluation, and selecting/freezing decision thresholds (e.g. F5 threshold).
* **Mar-May 2025**: **Inspected development test** set. Used for secondary policy simulation and reporting primary metrics (e.g. EV lift, RTH/ETH effects).
* **Remaining 2025**: **Secondary OOS** set. Kept unseen during model tuning.
* **2026**: **Contaminated**. Because the master runner evaluated 2026 within the same script run prior to policy freezing and without an explicit firewall, it cannot be considered a clean out-of-sample (OOS) dataset. It has been flagged as contaminated.
