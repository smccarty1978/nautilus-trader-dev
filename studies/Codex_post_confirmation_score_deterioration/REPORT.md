# Post-Confirmation Score Deterioration / Runner Protection

## Executive summary

**Terminal classification: A — POST-CONFIRMATION SCORE HAS NO USEFUL MANAGEMENT
INFORMATION.** This is a provisional evidence classification: the mandatory
causal and contract-agent gates could not run in this Codex session, so it is
not yet a clean/accepted study result.

1. **Does score deterioration predict regime failure?** No deployable answer is
   available. The only contract-valid score after confirmation is an
   opposing-model warning score, not a continuation score, and it is missing on
   almost all early failures.
2. **Which behavior is most informative?** Not evaluable. Only **159 of 2,181**
   failed trades (7.29%) have even three true, in-domain dispatches before their
   canonical terminal, far below the frozen 50% observability floor.
3. **Does failed re-expansion matter more than a threshold crossing?** Not
   evaluable without representative causal paths; no retreat/recovery event was
   constructed.
4. **How much open profit remains when deterioration is detectable?** The first
   valid score arrives a median **400 seconds** after confirmation among trades
   that receive one. That is too late to characterize the short failure
   populations without selection bias.
5. **How many failed trades could potentially be protected?** At most the 159
   observable failures could be studied; that is not a viable basis for an
   all-population management rule.
6. **How often would a signal interfere with ≥2 / ≥2.5 / ≥3 ATR runners?** Not
   evaluated. A runner-touch calculation would compare a score-covered winner
   subset (69.28% of winners have ≥3 observations) with a heavily uncovered
   failure population and would give a misleading trade-off.
7. **Is a dedicated trade-management policy study justified?** No, not from
   this score stream. Do not simulate exits or substitute out-of-domain scores
   under this contract.

## Canonical reconciliation

The inherited ledger contains 8,950 valid armed regimes. The terminal counts
were independently reproduced: 822 `CONFIRMED_THEN_STOPPED`, 1,359
`FINAL_FLIP_EXIT_LOSER`, 2,350 `FINAL_FLIP_EXIT_WINNER`, and 174 `SESSION_EXIT`.
These total 4,705 confirmed-continuation trades; 4,245 trades stopped before
confirmation. Every confirmed trade joined exactly once to its new canonical
regime.

## Score semantics and availability

The relevant post-confirmation stream is a non-null, in-domain score dispatched
for the **newly confirmed** regime. Its direction always matches the open fade
trade's regime direction, meaning a high score warns of the opposing flip that
would end that trade. It is therefore incorrect to carry over the predecessor
study's pre-confirmation interpretation of a falling score as post-confirmation
"deterioration."

No score was synthesized at missing dispatches and no out-of-domain score was
used. Of all 4,705 confirmed trades, 1,875 (39.85%) had any valid dispatch;
2,830 had none. Among trades with a valid first score, the median delay from
confirmation was 400 seconds (P25 290, P75 560). The canonical dispatch cadence
after eligibility is normally five seconds; density is not the problem—the
new-regime established/domain gate opens too late.

| Terminal group | Trades | ≥3 valid observations | Coverage |
|---|---:|---:|---:|
| Confirmed then stopped | 822 | 32 | 3.89% |
| Final flip exit loser | 1,359 | 127 | 9.35% |
| Failed total | 2,181 | 159 | **7.29%** |
| Final flip exit winner | 2,350 | 1,628 | 69.28% |

The same asymmetry appears in both directions and each 2021–2025 arm-entry
year. Calendar 2025 is descriptive only: the frozen percentile calibration
overlaps it and is not threshold-OOS. Reserved 2026 runtime OOS was not used.

## Gate decision

Gate 1 required at least half of failures to have three true, contract-valid
new-regime observations. It failed by 42.71 percentage points. Building score
retreats, re-expansion, price/score divergence, or runner-touch metrics on the
7.29% survivor subset would turn terminal-duration selection into an apparent
signal. Accordingly, all downstream event artifacts are explicitly
`NOT_EVALUABLE`, and no policy simulation was performed.

## Validation and audit status

The deterministic checks passed: population reconciliation, new-regime join,
inclusive confirmation-to-terminal bounds, no duplicate regime/timestamp score
observations, monotonic endpoints, score polarity, RTH selection, and exclusion
of 2026. The causal lint is clean (0 critical, 0 warning).

The mandatory `lookahead_auditor` and `contract_checker` could not start because
their configured reviewer model is unsupported for this account. Their status
files are deliberately `GATE_UNAVAILABLE`, not PASS. A compatible-harness audit
must clear both before treating this report as accepted evidence.

## Artifacts

- [Population reconciliation](results/population_reconciliation.json)
- [Score-path availability](results/post_confirmation_score_path_summary.json)
- [Stability coverage](results/year_direction_stability.json)
- [Validation](results/validation_report.json)
- [Causal audit status](audit/status.json)
- [Contract audit status](audit/contract_status.json)
