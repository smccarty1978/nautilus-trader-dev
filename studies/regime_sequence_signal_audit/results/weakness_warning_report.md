# Phase 8: Weakness Warning Lead-Time Quality Report

## Lead Time Statistics
* **Total warning events triggered in Test set**: 6379
* **Median Warning Lead (to opposite flip)**: 70.0 seconds
* **Mean Warning Lead**: 289.6 seconds
* **Median Lead to Final MFE**: 0.0 seconds
* **Average Giveback already incurred at warning**: 0.1262 ATR

## Warning Classification Breakdown
* **EARLY_USEFUL (warning occurs before 50% of eventual giveback)**: 20.77%
* **LATE_DESCRIPTIVE (warning occurs after 75% of eventual giveback)**: 21.27%
* **FALSE_RECOVERY (price recovers to prior MFE or makes new MFE after warning)**: 34.93%
