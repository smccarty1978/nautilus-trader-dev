# Broad Post-Confirmation MFE and Opposing-Model Exit Study

## 1. Executive summary

This study covers the first canonical Top-2.5% entry per regime. It does not
represent all 69,432 qualifying observations or repeated entries within a
regime.

All three baselines reconciled exactly. Price-management, supported
opposing-model warnings, and their prescribed combinations were evaluated
causally. Results are hypothesis-generating; no policy is nominated for
production.

Price protection produced positive descriptive incremental ATR across all
three stops for several families, but the largest apparent gains also carried
material same-bar ambiguity. Lower-ambiguity later-activation policies showed
smaller gains. The Top-5 opposing-model crossing did **not** behave as an early
warning of baseline losers: warning incidence was
0.54% among regime-flip losers versus
45.27% among regime-flip winners. Immediate
model exits therefore offer little support for the central loser-warning
hypothesis. Model-triggered P3 tightening was more stable than immediate exits,
but its effect remained small.

## 2. Feasibility and data coverage

Both model scores are present on every path. They are recomputed at causal
five-second checkpoints and carried across one-second rows. All 831,952 unique
opposing score sources link exactly to canonical observations with zero value
or domain mismatches. Opposing-model in-domain coverage is only 2,331/5,836
(39.94%). Bullish Top-10/5/2.5 and bearish Top-5/2.5 thresholds are frozen;
bearish Top-10 is unsupported. Percentiles are unavailable.

## 3. Baseline reproduction

The 0.75, 1.00, and 1.25 ATR outcomes match the accepted artifacts exactly.

## 4. Price-path management results

Top descriptive price rows by cross-stop mean incremental ATR:

| Policy | Mean incremental ATR | Mean realized ATR | Ambiguous |
|---|---:|---:|---:|
| retain_a1_r0.75 | 0.0467 | -0.0590 | 1758 |
| giveback_a0.75_g0.5 | 0.0453 | -0.0188 | 1476 |
| retain_a1_r0.5 | 0.0443 | -0.0263 | 555 |

## 5. Opposing fade-model results

Top supported immediate-warning rows:

| Policy | Mean incremental ATR | Mean realized ATR | Ambiguous |
|---|---:|---:|---:|
| model_top_5_p1 | 0.0133 | -0.0818 | 67 |
| model_top_5_p2 | 0.0093 | -0.0835 | 79 |
| model_top_2_5_p2 | 0.0084 | -0.0934 | 100 |

Warnings count consecutive unique model observations, not carried seconds.
Already-active warnings at confirmation are diagnostic and do not trigger an
exit.

## 6. Combined rules

First-event and model-triggered-tightening policies are present in the
trade-policy and cross-stop artifacts. Unsupported bearish Top-10 combinations
remain explicitly marked and are excluded from performance aggregates.

## 7. Cross-stop robustness

The cross-stop artifact reports matching-baseline incremental ATR, capture,
ambiguity, and stop-specific behavior for every policy. The 1.00 ATR branch is
evaluated independently rather than interpolated. The leading supported
families generally retained the same incremental-return sign across all three
stops, so the effects were not unique to one width; magnitude and ambiguity,
however, varied.

## 8. Stability

Machine evidence includes year, direction, model, model-year, direction-year,
stop-year, and stop-direction breakdowns. Pooled improvements must not be
interpreted as stable unless their subgroup signs agree.

## 9. Interpretation

Confirmed evidence is limited to the prespecified policies and supported model
coverage. Model comparisons apply to the in-domain subset and cannot establish
value for the remaining roughly 60% of trades. Apparent improvements are
refinement hypotheses, not deployable rules.

The strongest negative evidence is that Top-5 crossings occurred in roughly
45% of profitable regime-flip baselines but only about 0.5% of losing
regime-flip baselines. Median remaining MFE after a Top-5 warning was zero,
indicating that the warning was commonly late rather than anticipatory.

## 10. Refinement candidates

The machine summary lists at most three price, model, and combined families by
cross-stop consistency. These are candidates for a separately frozen causal
refinement study only.

## Validation

- Baselines: exact for all three stops.
- Unique trade-policy keys and full policy populations: passed.
- Exact score linkage: passed.
- Independent replay: 100 trades per stop, 300 cases, zero unexplained
  mismatches across baseline, MFE evolution, P1 activation, and Top-5 warning
  timing checks.
- Causal audit and contract verdicts are recorded separately.

## Final verdict

BROAD EVIDENCE IS MIXED

Strongest supported finding: Top-5 opposing-model warnings occurred in 45.27% of profitable regime-flip baselines but only 0.54% of losing regime-flip baselines, contradicting the proposed early-loser-warning role.

Largest methodological limitation: opposing-model in-domain coverage is 39.94%.

Most promising next hypothesis: trigger_P3_top_5
