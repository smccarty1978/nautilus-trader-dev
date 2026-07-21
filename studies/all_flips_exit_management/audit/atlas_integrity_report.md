# ALL_FLIPS Atlas Integrity Report

Built: 2026-07-11 16:31:57.997162+00:00

- **n_rows**: 30645902
- **n_trades**: 39608
- **n_checkpoint_before_entry**: 0
- **n_negative_mfe**: 0
- **n_negative_mae**: 0
- **n_negative_giveback**: 0
- **n_checkpoint_after_opposite_flip**: 74
- **terminal_label_counts**: {'NEW_MFE': 19033811, 'TERMINAL_WEAKNESS': 11548267, 'RECOVERED_ONLY': 63824}

## Requirements check

- current_pnl/MFE/MAE/giveback measured from entry_px: YES (see studies/_shared_exit_mgmt/mfe_mae.py, used identically live and offline)
- no checkpoint before entry: PASS
- no checkpoint after terminal opposite flip: FAIL
- short trades canonicalized positive MFE/MAE/giveback: PASS

## Investigation: 74 checkpoints past the opposite-flip tolerance

`n_checkpoint_after_opposite_flip: 74` (out of 30,645,902 rows, 0.00024%
-- same order of magnitude as F2_CONFIRMED's 30/15,007,918). Same root
cause confirmed: median excess is only 5.5s (bar-arrival jitter, not a
bug), and the handful of large outliers are exactly US market holidays
(Nov 29 2024 Black Friday, Nov 28 2025 Thanksgiving, Jan 20 2025 MLK
Day) where the exit decision is causal but no bar exists to fill
against until trading resumes. See
studies/f2_confirmed_exit_management/audit/atlas_integrity_report.md
for the full writeup of this shared, non-bug root cause. No code
change needed.
