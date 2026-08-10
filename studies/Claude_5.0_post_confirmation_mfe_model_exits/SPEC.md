# SPEC — Broad Post-Confirmation MFE Conservation and Opposing Fade-Model Exit Study

Study id: `Claude_5.0_post_confirmation_mfe_model_exits`
Stage: broad hypothesis generation. Not a production-policy search.

## 1. Population (frozen)

The canonical **first** Top-2.5% qualifying entry per regime, `N = 5,836`,
from `studies/full_trade_path_builder/consolidated/`.

```
BULLISH_STRICT_top25_gbt_v2 -> SHORT   (3,329)
LONG_STRICT_top25_gbt_v2    -> LONG    (2,507)
```

> This study covers the first canonical Top-2.5% entry per regime. It does not
> represent all 69,432 qualifying observations or repeated entries within a regime.

## 2. Inputs (read-only)

```
consolidated/canonical_observations_all.parquet
consolidated/canonical_trade_summaries_all.parquet
consolidated/canonical_trade_paths_all.parquet
results/top2_5_stop_0_75_regime_exit_results.parquet
results/top2_5_stop_1_00_regime_exit_results.parquet
results/top2_5_stop_1_25_regime_exit_results.parquet
```

Loaded through `implementation/canonical_research_loader.scan_canonical_research_population`.
No NautilusTrader run, no canonical mutation, no research-store rebuild, no
synthetic paths.

## 3. Frozen conventions

```
entry price      = checkpoint_reference_price
entry ATR        = atr_at_entry
stop touch       = completed 1s bar, adverse_intrabar_extreme_atr <= -S
floor violation  = completed 1s bar, adverse_intrabar_extreme_atr <= F_i
fill             = next path-bar open (timestamp_open_ns, open)
flat tolerance   = 0.125 NQ points
initial stops S  = 0.75, 1.00, 1.25 ATR
```

`adverse_intrabar_extreme_atr` is the **signed, unclipped** worst intrabar
excursion in entry-ATR units (`(low-ref)/atr` long, `(ref-high)/atr` short), so
it is a valid detector for any floor level, positive or negative.

### Causal execution window

`exec_start` = first path index with `timestamp_open_ns >= confirm_flip_ns`.
No management rule, model exit, break-even, trail, or profit protection may
execute at an index below `exec_start`. Only the original fixed stop may.
Activation MFE accumulated before confirmation **arms** a rule; it never fires it.

### Lagged-floor rule (no intrabar ordering assumption)

The protective floor in force during bar `i` is computed only from information
complete at the close of bar `i-1`:

```
lag_mfe[i] = running_mfe_atr[i-1]      (lag_mfe[0] = 0.0)
armed[i]   = lag_mfe[i] >= A
F[i]       = A1: constant floor
             A2: max(0.0, lag_mfe[i] - G)
             A3: lag_mfe[i] * R
```

`running_mfe_atr` is non-decreasing, so `F` never loosens. The initial stop stays
active until the floor is more protective; `F >= 0 > -S` in every family, so once
armed the floor governs.

Because the floor is fixed before bar `i` opens, a bar that both sets a new MFE
peak and violates the floor is **not** ambiguous — the floor it violated was the
pre-existing one. Cases where a same-bar interpretation would have differed are
counted as `same_bar_activation_and_violation` for sensitivity.

### Event precedence at one bar

```
management floor exit  >  initial stop      (floor is strictly more protective)
any price exit         >  model warning     (extreme occurs at or before bar close;
                                             the score is effective at bar close)
```

Both fill at the same next-bar open, so precedence changes the label, not the
return. Tie counts are reported.

### AMBIGUOUS EVENT ORDER

Assigned when the exit bar close or the fill bar open coincides with
`confirm_flip_ns` or `fallback_exit_flip_ns` (the baseline convention).

### CENSORED / UNRESOLVED

Assigned when an exit bar has no following path bar, or when no exit occurs and
`path_is_complete = false`.

## 4. Model-observation contract

Frozen thresholds (`membership_operator = ">="`, cadence 5 s):

| channel | model | top_10 | top_5 | top_2_5 |
| --- | --- | --- | --- | --- |
| bullish | BULLISH_STRICT_top25_gbt_v2 | 0.43167249785595935 | 0.5067081427626979 | 0.5697449423968936 |
| bearish | LONG_STRICT_top25_gbt_v2 | **NOT FROZEN** | 0.5084619230529974 | 0.5641320087327389 |

Opposing channel: SHORT monitors the **bearish** channel (`LONG_STRICT`), LONG
monitors the **bullish** channel (`BULLISH_STRICT`).

`top_10` therefore exists only for the opposing channel of **LONG** trades.
Every `top_10` policy is `policy_scope = LONG_ONLY`. Top-10% is not estimated for
SHORT and no threshold is derived from realized outcomes.

**Eligible model observation** = path bar where the opposing channel is
`is_carried_forward = false` (a genuinely new score arrival) **and**
`in_domain = true`. Carried-forward repeats are not observations; stale
overnight carries are excluded by the same rule.

Persistence K counts consecutive **eligible** observations, not seconds. Elapsed
wall time per K is reported.

## 5. Policy families (prespecified; not expanded after results)

```
BASE                              1
A1 fixed floor  A x F   4 x 3  = 12   A in {0.75,1.00,1.50,2.00} F in {0.00,0.25,0.50}
A2 giveback     A x G   4 x 3  = 12   G in {0.50,0.75,1.00}
A3 retention    A x R   3 x 3  =  9   A in {1.00,1.50,2.00} R in {0.25,0.50,0.75}
B  model exit   T x K   3 x 3  =  9   T in {top_10*,top_5,top_2_5} K in {1,2,3}
C1 first-wins   P x T   3 x 3  =  9   P1=A1(1.00,+0.25) P2=A1(1.50,+0.50) P3=A2(1.50,0.75)
C2 warn-arms    P x T   3 x 3  =  9
                              -----
                                61 policies per initial stop, 183 total
```

`*` top_10 rows exist for LONG trades only.

## 6. Deliverables manifest (frozen)

```
analysis/feasibility_probe.py
analysis/probe2.py
analysis/analyze_post_confirmation_mfe_and_model_exits.py
analysis/validate_post_confirmation_study.py
analysis/aggregate_post_confirmation_results.py
results/feasibility_probe.json
results/feasibility_probe2.json
results/post_confirmation_mfe_model_exit_trade_policy_results.parquet
results/post_confirmation_model_warning_events.parquet
results/post_confirmation_model_diagnostic_anchors.parquet
results/post_confirmation_policy_cross_stop_comparison.parquet
results/post_confirmation_mfe_model_exit_summary.json
results/post_confirmation_validation.json
POST_CONFIRMATION_MFE_AND_MODEL_EXIT_REPORT.md
```

## 7. Completeness and domain

- One row per (trade_id, initial_stop_atr, policy_id); no duplicate keys.
- All 5,836 trades present for every `policy_scope = ALL` policy and all 3 stops.
- All 2,507 LONG trades present for every `LONG_ONLY` policy and all 3 stops.
- Terminal outcome classes mutually exclusive and exhaustive.
- Baseline reconciles exactly to the frozen 0.75 / 1.00 / 1.25 counts.
- >= 100 independently recomputed trades per stop (>= 300 total), 0 unexplained
  mismatches, by a separate implementation that does not import the engine.

## 8. Prohibitions

No production nomination, no threshold optimisation, no grid expansion after
results, no retraining, no new exit classifier, no future labels, no use of final
MFE in a causal decision, no entry/confirmation/regime redefinition, no
transaction costs, no ATR-to-dollar conversion.

## 9. Terminal verdict

Exactly one of:
`BROAD EVIDENCE SUPPORTS REFINEMENT` / `BROAD EVIDENCE IS MIXED` /
`NO EVIDENCE FOR REFINEMENT` / `RESULTS NOT VALID`.
