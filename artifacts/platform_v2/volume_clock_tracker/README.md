# tracker.volume_clock.developing — validation and promotion evidence

Branch `chore/volume_clock_tracker` (from main `e3db799d`). Tracker module unchanged since `9726fb87`
(module sha256 `3e60f955…40fd4fc`); harness + WORKFLOW lesson at `c31d42ec`. Promoted with
`cap promote --parity artifacts/parity/volume_clock_developing.json` (31/31 tests, registry sha256
`75472cf5…5040ea`, `cap generate --check` OK: 237 entries, 0 broken). **Not merged** — merge needs explicit approval.

## 1. Gate table

| Gate | Verdict | Evidence |
|---|---|---|
| Full historical parity | PASS | V1/V5/V15 bars 210,163 / 41,849 / 13,774 exact; primary 193,314 / 38,503 / 12,679 |
| Developing-state parity | PASS | 127,848 sampled states + 631,274 checkpoint crossings exact; state parquets byte-identical |
| Comparison harness | PASS | 8 harness tests (defect classes, linear scaling, hand-built reference) |
| Memory bounds | PASS | tracker state ≤ 626,936 B; bounded buffers; RSS non-monotonic 199–318 MB over 26M rows |
| Causal validation | PASS | prefix invariance, future perturbation, causal_lint 0 CRITICAL / 0 WARNING |
| Broad regressions | PASS | 3,038 ran; 63 failures = main's known 63 (identical node ids); 0 attributable |
| Registry and promotion | PASS | PROMOTED; `cap generate --check` OK |
| Merge readiness | READY — awaiting approval | `DESTRUCTIVE_ACTION_REQUIRES_APPROVAL`; study has no `platform_merge: auto_if_green` |

## 2. Full historical parity (`replay/`, `../../parity/volume_clock_developing.json`)

Source: `NQ_1S_V2_GLOBEX` (catalog logical digest `9e7aecb7…2c64`), built from the same raw `.v.0` files whose sha256
pins the Stage C sources use. Window 2023-10-31 22:00 UTC → 2025-12-31 23:59:59 UTC. 26,041,806 1s rows fed once
through three kernels (k = 1, 5, 15). Oracle: frozen vc_v1 Stage C `out/full` (sha256-verified before compare, all
five pins match; contract `VOLUME_CLOCK_CONTRACT_FROZEN.md` sha256 `3535f09d…69d5`). The frozen reference was not modified.

| Comparison | Reference | Tracker | Matched | Mismatches |
|---|---:|---:|---:|---:|
| Sessions per scale (class, pre_roll, T, RTH bounds, calibration) | 556 | 556 | 556 | 0 |
| V1 bars | 210,163 | 210,163 | 210,163 | 0 |
| V5 bars | 41,849 | 41,849 | 41,849 | 0 |
| V15 bars | 13,774 | 13,774 | 13,774 | 0 |
| Developing states (every 97th RTH row, V1) | 127,848 | 127,848 | 127,848 | 0 |
| Checkpoint crossings (K25/K50/K75, incl. residual bars) | 631,274 | 631,274 | 631,274 | 0 |

Fields compared on bars: session identity, bar_seq, T, start/end/avail ts, dur_raw, duration_s, cumulative session
contracts, collapsed, OHLC, completion_speed and quality flags (start_partial, end_partial, shared_second_completions,
geom_quality). States: consumed, frac, residual, elapsed, rates, rv windows, checkpoint state, dir_d60. Exact
equality, int64 ns timestamps, NaN == NaN, no tolerance or epsilon anywhere.

**Population reconciliation.** 556 sessions = 559 calibration rows − 1 NO_RTH − 2 MISSING_DATA. Primary population
(475 sessions) bars = 193,314 / 38,503 / 12,679 = frozen manifest counts; 2024–25 = 196,784 / 39,187 / 12,897.
The reference's own quality flags re-derive from its bars with 0 differences, so the flag comparison is not circular.

**Mismatch classification:** none to classify (0 in every table; 0 only-ref, 0 only-trk, 0 duplicate keys).

**Why a new replay was run:** the earlier full run compared in-process and persisted nothing; it covered V1 only and
stalled in a quadratic compare. Persisted artifacts covering V1/V5/V15 states and checkpoints required one re-feed.
It was run once; all comparisons are offline (2.8 s) and re-runnable without market data:
`python scripts/parity/volume_clock_developing_parity.py compare --dir artifacts/platform_v2/volume_clock_tracker/replay --out <json>`.

## 3. Harness verification (`scripts/tests/test_volume_clock_parity_harness.py`, 8 pass)

Identical frames pass; 1 ns timestamp change detected with first divergence; missing / extra / duplicate keys;
volume, progress and null-policy mismatch (a 1e-15 difference is a mismatch); empty frames (guarded non-empty by
caller); linear scaling (n vs 4n, < 12×); the independent reference equals the tracker on a hand-built session
(carry, collapsed completion, zero-volume rows, a 39 s gap, residual bar) and catches a planted defect; derived flags
on a known sequence. 3-month full-pipeline smoke before the full run: all exact, compare 0.34 s; it caught a merge
column collision in 2 s.

## 4. Memory and throughput

| Component | Measure |
|---|---|
| Tracker (feed-only probe, `streaming_probe.json`) | 26,041,806 rows, 842,549 events, 29,916 rows/s, feed 870.5 s, wall 894.4 s |
| Tracker-owned state | ≤ 626,936 B; price buffer ≤ 4,108 rows, rolling ≤ 4,258 (incl. compaction slack); eligibility history 20 / profile 5 |
| Process RSS during probe (tracker + reader) | 199.1–318.0 MB, non-monotonic (drops to 212–218 MB in 2024-08, 2025-04, 2025-09): no growth with history |
| Full parity replay (3 kernels + harness tables + reference) | load 21.2 s, feed 3,151.9 s, reference 90.4 s, wall 3,190.1 s, peak RSS 1,198.7 MB — growth is harness-held output tables, not tracker state |
| Offline comparison | 2.8 s |

The replay ran concurrently with the broad suite; the probe ran alone.

## 5. Tests

- `features/tests/test_volume_clock_developing.py`: 31 pass. Hand-calculated calibration, classes, roll transition,
  completion epoch, accelerating / decelerating / stalling / reversing, overshoot, collapsed, carry, multi_cross,
  zero volume, gaps, reset, prefix invariance (3 seeds), future perturbation (2 seeds), brute-force references,
  VC/TC same rows, bounded memory, input refusal, fields == contract, end-to-end compile → HostCore.
- Epoch ordering: the epoch at t sees the 1s row closing at t, including any completion it causes; the published
  state is then the new bar (elapsed 0, frac = carry / T, rates null).
- Broad `test_delta` (`test_delta_broad.json`): scope `research_workflow/tests scripts/tests research/analysis/tests
  features/tests`, head `c31d42ec`. 3,038 ran, 2,947 passed, 63 failed; wall 17,033 s. Status `NEW_FAILURES` only
  because the baseline file is stale (BASELINE_COMMIT_MISMATCH, BASELINE_ENVIRONMENT_MISMATCH). The 63 node ids are
  identical to main's last broad gate (`../failed_breakout_tracker/test_delta_broad.json`, 63 at `750dc2a6`); none
  touches the tracker or harness. Classification: existing baseline, 63; new regressions, 0.
- Causal lint (`causal_lint.json`): 0 CRITICAL, 0 WARNING.

## 6. Artifact manifest (sha256)

| File | Rows | sha256 |
|---|---:|---|
| replay/tracker_bars.parquet | 265,786 | 8ef051ef66a2a8e0357165951fb13d5f37f3850528fbf9922432d537ed347baa |
| replay/tracker_sessions.parquet | 3,336 | 3bc8e774ac4bda67d2b805005dfce23bb8bde9626ec767cd90e22d11f5856f5f |
| replay/tracker_states.parquet | 127,848 | f1633d368588a4aade937632e27f16eb8ca63a8b3b66516f7efee95f0012ab75 |
| replay/reference_states.parquet | 127,848 | f1633d368588a4aade937632e27f16eb8ca63a8b3b66516f7efee95f0012ab75 |
| replay/tracker_checkpoints.parquet | 631,274 | c001fc322089e03c61cb0623ceaabdbab8e19c5ba1c16b98ff9022fa3e2aff62 |
| replay/reference_checkpoints.parquet | 631,274 | b611f0493dae1e566d35d7d57c5e0c70ff02b9b15b17d81828df1b25c4bd3c7f |
| replay/replay_manifest.json | — | d30adf8da6974d7039237861a35257e745f6be77038d8937dd52b5450a86c5fa |
| replay/comparison_provenance.json | — | 1b2a3e591c1c2d86ee0895fc4d22c0aaab786c61207f74cd8aa0af9c8417a028 |
| ../../parity/volume_clock_developing.json | — | ffc1e6d06c43e5ef475c42aadb8bed4c7f76c9bfdd57305ce66e81b693042bf0 |
| streaming_probe.json | — | 95a350b1b0a23323af5b6f4e682f9dd33d816d87ef33ac48e781d7c6c6b4849b |
| causal_lint.json | — | 9442ae04fca93c8982da9459c3921a79f47650d5ddff18509c578338010f1704 |
| test_delta_broad.json | — | a3d09234cfd6972c45c1b17ad0ba83eb4d23e4a1f5fd37b7f8ad985dcaf7057a |

The checkpoint parquets differ in bytes because the tracker file carries three extra diagnostic columns
(completed_in_row, collapsed, multi_cross); the keyed comparison on (date, bar_seq, level) → ts is exact. The state
parquets are byte-identical.

## 7. Verdict

**PROMOTED on the chore branch; merge-ready; not merged.** No blockers. See `SESSION_HANDOFF.md`.
