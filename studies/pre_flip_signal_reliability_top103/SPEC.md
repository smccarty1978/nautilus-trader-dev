# Pre-Flip Signal Reliability — Top103 Long Rerun

Exact methodological fork of `studies/pre_flip_signal_reliability`. Candidate
generation, first-crossing selection, thresholds, buckets, timestamps, RTH
filter, raw-bar path measurement, short model, and output schemas are unchanged.
The sole scoring change is the frozen production long artifact
`LONG_STRICT_top103_gbt_v2`; scores are taken from the strict monthly 103-column
contract and merged one-to-one onto the original long checkpoint keys.

2024–2025 remain the research partition; 2026 is untouched. The original Top25
study is read-only. Comparative paired bootstrap uses regime/checkpoint keys and
seed 42. No model is trained or refit.

False positive is the complement of a confirmed flip within the horizon and
includes null/never-flip rows. Reliability curves use the identical full
checkpoint population before selection. `flip_exit_pnl_pts` is a non-executable
last-close mark at the flip boundary, not a fill.

Replace Top25 only if: flip<=300 is non-worse at all Top 1/2.5/5% thresholds and
better at two with at least one paired 95% CI above zero; median time-to-flip is
no later at two and never >60s later; remaining MFE and path MAE never worsen by
more than 0.10 ATR. Otherwise retain Top25.

Raw bars require unique increasing timestamps, finite OHLCV, enveloped open and
close, and nonnegative volume. For exact original-study parity, zero-volume and
single-tick bars remain valid observed path bars.
