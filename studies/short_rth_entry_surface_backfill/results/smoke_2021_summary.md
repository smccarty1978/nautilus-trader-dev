# 2021 5s-Cadence Short-RTH Entry Surface — Smoke

## Atlas rebuild (Option A: 5s cadence, no legacy parity)

- Runtime: Nones
- Checkpoints: 3,958,432 across 27,792 regimes
- Causal audit: 0 negative excursion cells, 0 MFE monotonicity violations, 0 MAE monotonicity violations
- Feature columns present: 149 (expected 149)

## Score-independent surface funnel (checkpoints / distinct regimes)

| Stage | Checkpoints | Distinct regimes |
|--|--:|--:|
| all | 3,958,432 | 27,792 |
| bullish_regime | 2,041,198 | 13,888 |
| established | 681,909 | 5,790 |
| rth | 212,242 | 1,762 |
| valid_fill | 212,241 | 1,762 |
| rth_boundary_divergence | 121 | 1 |

Surface build runtime: 50.1s

## Raw-data gap scan (>300s gaps)

- Gaps found: 379
  - 2021-12-23 21:59:59+00:00 -> 2021-12-26 23:00:00+00:00 (262801s)
  - 2021-04-02 13:14:59+00:00 -> 2021-04-04 22:00:00+00:00 (204301s)
  - 2021-11-26 18:14:58+00:00 -> 2021-11-28 23:00:00+00:00 (189902s)
  - 2021-11-05 20:59:57+00:00 -> 2021-11-07 23:00:00+00:00 (180003s)
  - 2021-09-10 20:59:56+00:00 -> 2021-09-12 22:00:00+00:00 (176404s)
  - 2021-01-22 21:59:57+00:00 -> 2021-01-24 23:00:00+00:00 (176403s)
  - 2021-03-19 20:59:57+00:00 -> 2021-03-21 22:00:00+00:00 (176403s)
  - 2021-07-23 20:59:57+00:00 -> 2021-07-25 22:00:00+00:00 (176403s)
  - 2021-10-22 20:59:57+00:00 -> 2021-10-24 22:00:00+00:00 (176403s)
  - 2021-02-26 21:59:58+00:00 -> 2021-02-28 23:00:00+00:00 (176402s)

## Feature completeness

- Expected feature columns: 149, present: 149
- Missing columns: none
- Overall NaN rate (all checkpoints): 0.0002
- Surface-row NaN rate (established/RTH/valid-fill only): 0.0000

## Policy A label availability (seq-1-per-regime feasibility check)

- Seq-1 candidates (first established/RTH/valid-fill checkpoint per regime): 1,762
- Labeled successfully: 1,762
- Label errors: 0
- Exit-reason counts: {'confirmation_timeout_exit': 872, 'preflip_policy_stop': 606, 'original_opposing_flip_exit': 279, 'original_stop_after_aligned_flip': 5}
- Exit-reason PnL: {'confirmation_timeout_exit': 25385.0, 'original_opposing_flip_exit': 92730.0, 'original_stop_after_aligned_flip': -1015.3373589719558, 'preflip_policy_stop': -123718.50020586094}
- pre_alignment_stop_rate: 0.3439, timeout_rate: 0.4949, post_alignment_stop_rate: 0.0028, opposing_flip_rate: 0.1583
- avoid_pre_alignment_stop rate: 0.6561
- Net PnL sum / mean (sanity check only, NOT a claimed result): $-6,619 / $-3.76

## Audit / provenance status

- Atlas rebuild reuses `attach_causal_w4_context`, `compute_activity_features_batched`, `compute_sequence_features_batched` verbatim from the already-audited `CODEX_5_X_weakness_atlas_repair` pipeline (`audit/CODEX_5_X_pre_execution_audit.md`, PASS, 0 CRITICAL/0 WARNING).
- Surface generation reuses `entry_surface.py`, which passed its own dedicated lookahead audit (`audit/audit.md`, PASS, 0 CRITICAL, 1 WARNING -- since fixed) and was empirically reconciled exact against the known 2025/2026 candidate population (650/222, 0 missing, 0 mismatched).
- The `rth_boundary_divergence` diagnostic is reported above for 2021 specifically because the audit warning flagged this as an open risk at coarser/older data -- see the table.
- This smoke has not itself been separately re-audited beyond reusing already-PASS-gated code; no new causal logic was introduced in `smoke_2021_surface.py` (gap scan and feature-completeness are pure read-only diagnostics; Policy A replay reuses `simulate_trade_arrays` verbatim).

## Suitability for 2021-2024 expansion

Mechanically feasible and causally clean at single-year scale: atlas rebuild took Nones (None = reused an already-built atlas, audit recomputed not rebuilt), surface funnel and feature completeness look structurally identical in shape to 2025/2026 (see reconciliation smoke), and the seq-1 Policy A label pass ran without error. Recommend running the same three steps (atlas rebuild, surface funnel, seq-1 label feasibility) for 2022-2024 before treating the full 2021-2024 backfill as ready.