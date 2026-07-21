# CODEX 5.X Established Fade — Policy Pre-Execution Re-Audit

**Scope:** current `CODEX_5_X_run_established_fade.py`, frozen `CODEX_5_X_established_fade_policy.json`, `CODEX_5_X_policy_input_contract.json`, and the 43-test causal/policy/excursion suite, traced against the repaired atlas, frozen scores, raw one-second bars, canonical regime timeline, and prior audit findings.  
**Mode:** read-only pre-execution source, artifact-hash, and deterministic-test audit. The policy remains unexecuted. No policy result artifact was created or modified.  
**Status:** **PASS — POLICY EXECUTION AUTHORIZED**  
**Findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The current policy runner closes every prior critical and warning finding. It fails closed unless both mandatory audits are exact clean passes and a separate authorization JSON binds the exact runner, policy, input contract, and this audit. Before reading data into the study or simulating either year, it independently hashes and exactly compares the selected year's raw bars, repaired atlas, and frozen scores plus the common manifest, bundle, and first-open ledger against the frozen policy input contract.

The causal and execution paths are internally consistent with the declared one-second OHLC research contract. Signals are strict within-regime threshold crossings at causal observation timestamps. Entry is the first available one-second open at or after the decision. Stops are fill-anchored, active on the entry bar, use the checkpoint ATR and the frozen 1.5 ATR distance, fill at the stop on ordinary range touch, and fill at the adverse bar open on a gap through the stop. The scheduled next-against-flip open has priority over that bar's OHLC range. One-position state prevents same-open reuse after a stop while permitting later eligible decisions.

The exit timeline is freshly reconstructed from the canonical causal RegimeEngine and includes checkpointless intermediate regimes. Atlas-populated regimes must agree with canonical direction and end. Only the final canonical regime is censored. Raw timestamps and OHLC geometry, flip ordering, and direction alternation are explicitly validated before matching.

The isolated suite completed with `43 passed` and no failures. Independent pre-execution validation reproduced every frozen input hash for both 2025 and 2026. No policy execution was performed during this audit.

## Prior-finding disposition

| Prior finding | Disposition |
|---|---|
| C1 — 2026 atlas and scores were not hash-bound | **Closed.** `CODEX_5_X_policy_input_contract.json` separately freezes raw, atlas, and scores for 2025 and 2026. `validate_frozen_input_contract(year)` requires exact equality before any data load or simulation. Mutation tests independently reject changed 2026 atlas and score hashes. |
| W1 — material execution branches and malformed-input guards were uncovered | **Closed.** The expanded deterministic suite covers strict regime-local crossing reset, long and short stop paths, entry-bar activation, gap fills, delayed next-open/session attribution, scheduled-exit priority, overlap and same-stop-bar exclusion, checkpointless confirming regimes, malformed raw/timeline inputs, 2026 hash mutation, and output blocking on failed reconciliation. |
| Earlier audit spoofing/optimization risk | **Closed.** Audit status and findings use anchored exact parsing; runtime invariants use explicit exceptions, not optimization-removable Python assertions. |
| Earlier incomplete regime timeline | **Closed.** The fresh canonical timeline retains every flip, validates alternation and ordering, and assigns `None` only to the true trailing regime. |
| Earlier decision-time session attribution | **Closed.** Trades retain `decision_session` and assign execution `session` from the actual entry-fill timestamp. |

## Frozen input contract

Independent calls to `validate_frozen_input_contract` reproduced exact equality for both years:

| Input | 2025 SHA-256 | 2026 SHA-256 |
|---|---|---|
| Raw one-second bars | `c4d498e77da916fd372b1faf455c68513dac38fdf45eced028b9fb99345d1e2d` | `573523c556e9907652e2a2923c704daec6ee5ba7cb9fc3b2d579b5898ceb8b89` |
| Repaired atlas | `c654da5016f7ec4bf26be11a390992dff851d38e81684a2a19f0bbed90ad9ce7` | `76192163897e2075dc72e1742ca38d6d3a24aa5977a21bbc537eb2ebc89e2d44` |
| Frozen W4 scores | `f97c4e739cb11b19dbaaa3954175bb4f44b8346b7cc10d791dde22a122edeac9` | `c5c1b42da0d5b0e42be36cb1642a04865d46d8601cf5d7abed0ba9ff360300a8` |

The shared hashes also match exactly:

| Shared artifact | SHA-256 |
|---|---|
| Frozen manifest | `2b0cc6d0ffd7fdcf28f29a0a73e973fd6b5bc0a797121f23430d220e03dd2180` |
| Frozen model bundle | `cd1243dc0dc0bd37f1141d9d42a732cf5d7e52fa900536f7b64b9acecb9dc237` |
| First-2026-open ledger | `deaa0758f7b19188ff29e8cee803e6549fc32352166d6eb9894ec3baf86aa480` |

`main` performs the audit/authorization gate and frozen input validation before policy loading, raw-frame loading, candidate construction, or simulation. The reconciliation persists the current selected-year input hashes. The 2025 reconciliation additionally seals runner, policy, all 2025 inputs, common provenance, both audits, authorization, and input contract; 2026 requires exact equality with that predecessor seal.

## Causal signal and local-state audit

- Stored scores are joined by exact checkpoint key and must be finite and complete.
- The frozen direction-specific thresholds are validated against the policy contract.
- A crossing is strictly `previous < threshold` and `current >= threshold`, with previous score reset at each exact regime boundary.
- The decision timestamp is the causal checkpoint observation time.
- Entry-local progress state uses only raw bars from entry through strictly before the decision.
- Running MFE is measured from the stored entry open using direction-specific favorable extremes and entry ATR.
- Reconstructed MFE must equal the stored causal checkpoint MFE.
- Retention and progress-window filters therefore use only information available at decision time.
- Policy selection remains frozen before execution; this runner contains no 2026 parameter selection path.

## Execution and exit audit

- Entry is the first available one-second bar open with `ts_event >= decision timestamp`.
- A pending entry is canceled if its fill open is at or after the confirming regime flip.
- The stop is exactly `fill_price - entry_direction × 1.5 × atr_at_checkpoint`.
- Stop evaluation begins on the entry bar.
- Ordinary touch fills at the stop price; an available-bar gap through the stop fills at that adverse bar open.
- No exact intrabar touch ordering is claimed or inferred from OHLC data.
- The confirming regime's next flip is the scheduled fallback exit decision. Its first available market open is evaluated before the range of that exit bar.
- The complete canonical timeline supplies known exits for checkpointless confirming regimes; absent confirming starts fail closed.
- After a stop, the position remains busy through the stop bar's open interval, blocking same-open reuse. Later eligible decisions are not globally suppressed.
- `decision_session` is retained while trade `session` is determined from actual fill time.

## Validation and deterministic tests

Command environment:

```text
PYTHONDONTWRITEBYTECODE=1
pytest -p no:cacheprovider
```

Audited files:

```text
tests/test_CODEX_5_X_causal_contract.py
tests/test_CODEX_5_X_policy_contract.py
tests/test_CODEX_5_X_excursions.py
```

Result:

```text
43 passed in 1.34s
```

The policy runner itself was not invoked, and no 2025 or 2026 policy output was produced by this audit.

## Gate decision

**PASS: 0 CRITICAL, 0 WARNING.** The current exact runner, frozen policy, frozen input contract, and this audit are authorized for policy execution once bound by `CODEX_5_X_policy_pre_execution_authorization.json`. Any change to the runner, policy, input contract, audit report, or frozen inputs invalidates the gate and must fail closed.
