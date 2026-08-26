# Final research decision — CLOSED_NOT_SUPPORTED

**Result: NOT_SUPPORTED.** Among high-confidence Stage-1 flip predictions (frozen Model C,
TRAIN P90 upcross), the predeclared Stage-2 causal feature surface (Arms A/B/C, 21 inputs)
does not robustly identify economically clean reversals (T1: flip within 300s AND MFE>=1.0 ATR
AND MAE<=0.5 ATR).

LONG's TRAIN-selected primary arm (B, original Stage-1 13 + score) collapses OOS: TRAIN final
validation ROC 0.5610 -> OOS ROC 0.4912, worse than chance. SHORT's TRAIN-selected primary arm
(A, score-only) survives only as a weak signal: TRAIN 0.5400 -> OOS 0.5157, with non-clean
calibration. Neither primary arm separates T1 positives from negative subtypes OOS.

Arm C scored best OOS in both directions (LONG 0.5230, SHORT 0.5362) despite not being TRAIN-
selected. This is recorded as a secondary, non-actionable observation — not a retroactive
reselection. Interpreting it requires a new predeclared study with genuinely unseen data;
2024 cannot serve as untouched OOS for that follow-on hypothesis.

No 2024 refitting, recalibration, or arm reselection was performed. 2025 and 2026 were not
accessed at any point.

**Post-closure correction:** the 2024 OOS population was rebuilt after a bug was found in the
one-off population-derivation script (it wrongly excluded whole regimes on left-censoring
instead of treating that as diagnostic-only — see `results/final_report.md` §9). The frozen
TRAIN population was independently re-verified and was unaffected. OOS moved from 2,853 to the
correct 2,864 identities; every metric changed by <=0.003 ROC; no conclusion changed.
