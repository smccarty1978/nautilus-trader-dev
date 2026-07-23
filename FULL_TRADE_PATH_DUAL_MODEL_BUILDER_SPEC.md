# Full Trade Path and Dual-Model Score Builder Specification

**Status:** Design specification  
**Purpose:** Build canonical artifacts for complete trade-lifecycle analysis, dual-model signal analysis, and dynamic exit-policy research in the NQ regime-flip project.

---

# Executive Summary

The current checkpoint artifact is sufficient for studying whether a fade model predicts an imminent confirmation flip and for measuring price behavior from the checkpoint to that first confirmation.

It is not sufficient for the intended trade-management problem:

```text
fade entry
→ predicted confirmation flip
→ hold while the new regime aligns with the trade
→ exit at the next opposite confirmed regime flip
```

The replacement builder must preserve the entire causal one-second path from entry through the final opposite-flip exit and must expose **both model outputs at every eligible observation time**, regardless of the prevailing regime.

This dual-score requirement is essential because, after the predicted flip aligns the regime with the position, the model for the opposite fade direction may become a useful early-exit warning.

Example for a long trade:

```text
Bearish Fade model fires while regime is bearish
→ enter long
→ bullish confirmation flip aligns regime with the long
→ Bullish Fade model begins forecasting a bearish flip
→ use that opposite-model score as a candidate early-exit signal
→ fallback exit remains the next confirmed bearish regime flip
```

The builder must record facts, scores, and paths only. It must not embed or optimize an exit policy.

---

# 1. Research Decisions This Builder Must Support

The artifacts must allow us to answer:

1. How much full-trade MFE is captured by the current opposite-regime-flip exit?
2. How much MFE is surrendered before that exit?
3. Can an opposite-model score warn of the exit flip early enough to reduce giveback?
4. Does the opposite model retain calibration and usefulness when evaluated continuously after entry?
5. At what score percentile or threshold does exit-warning precision become economically useful?
6. Would break-even, trailing-stop, retracement, time-stop, or model-score exits improve expectancy?
7. Can exit logic capture an additional 5–10 percentage points of full-trade MFE without materially damaging total expectancy?
8. Are improvements stable by year, direction, session, regime age, time since confirmation, and trade-path archetype?

---

# 2. Canonical Model Semantics

## 2.1 Bullish Fade model

Canonical model:

```text
BULLISH_FADE_TO_BEARISH_FLIP_TOP25_GBT_V1
```

Meaning:

```text
prevailing bullish regime
→ forecast bearish confirmed regime flip within 300 seconds
→ candidate short fade entry
```

For an existing long trade after a bullish confirmation flip, this becomes the **opposite-model exit-warning score**.

---

## 2.2 Bearish Fade model

Canonical model:

```text
BEARISH_FADE_TO_BULLISH_FLIP_TOP25_GBT_V2
```

Meaning:

```text
prevailing bearish regime
→ forecast bullish confirmed regime flip within 300 seconds
→ candidate long fade entry
```

For an existing short trade after a bearish confirmation flip, this becomes the **opposite-model exit-warning score**.

---

# 3. Critical Dual-Model Requirement

## 3.1 Both model outputs must be stored

At every eligible causal observation time, store:

```text
bullish_fade_score
bullish_fade_probability

bearish_fade_score
bearish_fade_probability
```

Also store the threshold/ranking context needed to interpret each model:

```text
bullish_fade_percentile
bullish_fade_decile
bullish_fade_is_top_10pct
bullish_fade_is_top_5pct
bullish_fade_is_top_2_5pct

bearish_fade_percentile
bearish_fade_decile
bearish_fade_is_top_10pct
bearish_fade_is_top_5pct
bearish_fade_is_top_2_5pct
```

If the production contract uses a raw margin rather than a calibrated probability, retain both:

```text
raw_model_score
calibrated_probability
```

Do not use the generic name `score` without a model-direction prefix.

---

## 3.2 Scores must be viewable in all regimes

The artifacts must allow both scores to be inspected while the prevailing regime is:

```text
bullish
bearish
neutral/unconfirmed
```

A model's output must not be deleted merely because the current regime does not match that model's original entry population.

However, the builder must distinguish:

```text
score was causally computed and valid
```

from:

```text
score lies inside the model's trained/approved regime domain
```

Store:

```text
bullish_fade_score_available
bullish_fade_in_domain

bearish_fade_score_available
bearish_fade_in_domain
```

Recommended definitions:

```text
bullish_fade_in_domain = prevailing confirmed regime is bullish
bearish_fade_in_domain = prevailing confirmed regime is bearish
```

If a model cannot be computed outside its original regime because required features are undefined, store null and an explicit reason:

```text
bullish_fade_unavailable_reason
bearish_fade_unavailable_reason
```

Never silently fill missing values with zero.

---

## 3.3 Preferred implementation

The preferred design is:

1. Maintain all shared causal feature trackers continuously.
2. Produce a complete feature vector at every approved scoring checkpoint.
3. Score both frozen models from that same causally available feature state.
4. Record domain-validity flags separately.
5. Do not suppress the opposite model because it is not the active entry model.

This ensures the study can inspect the opposite model immediately when the regime flips and throughout the aligned holding period.

---

## 3.4 No retraining or reinterpretation

This builder must not:

- retrain either model;
- change either model's feature contract;
- change calibration;
- redefine the 300-second target;
- treat out-of-domain scores as validated entry signals;
- assume that continuous opposite-model scores are useful exits before testing them.

The scores are recorded as research inputs. Their exit value remains a hypothesis.

---

# 4. Canonical Trade Lifecycle

One canonical trade begins at:

```text
selected fade checkpoint observation
```

and ends at:

```text
next confirmed regime flip opposite the trade direction
```

The predicted confirmation flip is an internal milestone, not the final exit.

## Long trade

```text
entry during bearish regime
→ bullish confirmed flip
→ hold while bullish regime aligns with long
→ exit at next confirmed bearish flip
```

## Short trade

```text
entry during bullish regime
→ bearish confirmed flip
→ hold while bearish regime aligns with short
→ exit at next confirmed bullish flip
```

---

# 5. Required Outputs

Produce three canonical artifacts.

```text
canonical_trade_population.parquet
canonical_trade_paths.parquet
canonical_model_scores.parquet
```

CSV exports may be produced for interactive review, but Parquet remains the canonical storage format.

---

# 6. Artifact 1 — canonical_trade_population.parquet

One row per selected trade.

## 6.1 Identity

```text
trade_id
instrument_id
year
session
trade_direction
entry_model
entry_regime_direction
regime_start_ns
checkpoint_observation_ns
```

---

## 6.2 Entry

```text
entry_price
atr_at_entry
entry_model_raw_score
entry_model_probability
entry_model_percentile
entry_model_decile
entry_rank_in_regime
```

All ATR-normalized values throughout the trade must use:

```text
atr_at_entry
```

Do not renormalize later.

---

## 6.3 Both model values at entry

```text
entry_bullish_fade_score
entry_bullish_fade_probability
entry_bullish_fade_percentile
entry_bullish_fade_in_domain

entry_bearish_fade_score
entry_bearish_fade_probability
entry_bearish_fade_percentile
entry_bearish_fade_in_domain
```

---

## 6.4 Predicted confirmation milestone

```text
confirm_flip_ns
confirm_flip_direction
confirm_flip_open_price
confirm_flip_close_price
seconds_entry_to_confirm
confirmed_within_300s
confirmed_within_600s
```

---

## 6.5 Opposite-flip exit

The canonical fallback exit is the next confirmed flip opposite the trade direction.

Store:

```text
exit_flip_ns
exit_flip_direction
exit_flip_open_price
exit_flip_close_price
seconds_entry_to_exit
seconds_confirm_to_exit
```

If the data window ends before the exit flip:

```text
is_right_censored
censor_ns
censor_reason
```

Censored trades must not be silently treated as completed exits.

---

## 6.6 Realized economics at fallback exit

For direction-normalized PnL, positive always means favorable to the trade.

```text
realized_return_points
realized_return_ticks
realized_return_atr
```

Do not store `R` unless a specific frozen initial stop defines the denominator. This fact table must remain policy-neutral.

---

## 6.7 Full-lifecycle excursion

Compute over:

```text
checkpoint_observation_ns
→ exit_flip_ns
```

Store:

```text
full_trade_mfe_points
full_trade_mfe_atr
full_trade_mfe_ns

full_trade_mae_points
full_trade_mae_atr
full_trade_mae_ns
```

These must be computed relative to the original entry price and normalized by `atr_at_entry`.

---

## 6.8 Exit capture and giveback

For completed trades with positive MFE:

```text
mfe_capture_ratio =
realized_return_atr / full_trade_mfe_atr
```

Store:

```text
mfe_capture_ratio
mfe_capture_pct
giveback_from_mfe_atr
giveback_from_mfe_pct
```

Where:

```text
giveback_from_mfe_atr =
full_trade_mfe_atr - realized_return_atr
```

Do not clip capture ratios to `[0, 1]`.

A trade may:

- exit below entry and have a negative capture ratio;
- exit above a prior sampled high due to close/open conventions;
- have zero MFE and require a null capture ratio.

Store the raw mathematical result and explicit validity flags.

---

## 6.9 Pre-confirmation and post-confirmation decomposition

Retain decomposed path facts in addition to the full lifecycle:

```text
pre_confirm_mfe_atr
pre_confirm_mae_atr
pre_confirm_mfe_ns
pre_confirm_mae_ns

post_confirm_mfe_from_entry_atr
post_confirm_mae_from_entry_atr
post_confirm_mfe_ns
post_confirm_mae_ns
```

Important:

`post_confirm_mfe_from_entry_atr` must remain measured from the original entry price, not reset at confirmation.

---

## 6.10 Opposite-model exit-warning summary

For each trade, identify the relevant opposite model after confirmation.

Long trade:

```text
opposite_exit_model = bullish_fade
```

Short trade:

```text
opposite_exit_model = bearish_fade
```

Store:

```text
opposite_exit_model
opposite_score_at_confirm
opposite_probability_at_confirm
opposite_percentile_at_confirm

max_opposite_score_after_confirm
max_opposite_probability_after_confirm
max_opposite_percentile_after_confirm
max_opposite_score_ns

opposite_first_top_10pct_ns
opposite_first_top_5pct_ns
opposite_first_top_2_5pct_ns
```

Also store lead time to the actual fallback exit:

```text
seconds_top_10pct_to_exit_flip
seconds_top_5pct_to_exit_flip
seconds_top_2_5pct_to_exit_flip
```

Null means the threshold was never reached before the actual exit flip.

These fields are descriptive only and must not define the trade exit in the builder.

---

## 6.11 Entry revisit and milestone facts

Store first causal timestamps for favorable movement of:

```text
0.25 ATR
0.50 ATR
0.75 ATR
1.00 ATR
1.25 ATR
1.50 ATR
2.00 ATR
3.00 ATR
```

Example:

```text
first_reached_plus_0_50_atr_ns
```

For each threshold, store whether price later revisited entry before fallback exit:

```text
revisited_entry_after_plus_0_50_atr
first_entry_revisit_after_plus_0_50_atr_ns
```

Repeat for all approved thresholds.

These are convenience fields. The one-second path remains the source of truth.

---

# 7. Artifact 2 — canonical_trade_paths.parquet

One row per completed one-second bar per trade.

The path begins at the entry observation/fill convention and continues through the canonical fallback exit.

## 7.1 Identity and time

```text
trade_id
timestamp_ns
seconds_from_entry
seconds_from_confirm
trade_direction
prevailing_regime
is_regime_confirmed
```

---

## 7.2 One-second OHLC

```text
open
high
low
close
```

The builder must document whether the bar timestamp denotes bar open or bar close and must preserve the project's canonical completed-bar timing convention.

---

## 7.3 Direction-normalized movement from entry

Positive means favorable for both long and short trades.

```text
open_from_entry_atr
high_from_entry_atr
low_from_entry_atr
close_from_entry_atr
```

For shorts, favorable and adverse intrabar extremes must be transformed correctly.

Also store:

```text
running_mfe_atr
running_mae_atr
running_close_pnl_atr
drawdown_from_running_mfe_atr
```

---

## 7.4 Event flags

```text
is_entry_observation
is_confirm_flip
is_exit_flip
is_final_path_row
is_new_running_mfe
is_new_running_mae
crossed_entry_this_bar
```

---

## 7.5 Both model outputs on every path row

Store:

```text
bullish_fade_raw_score
bullish_fade_probability
bullish_fade_percentile
bullish_fade_decile
bullish_fade_score_available
bullish_fade_in_domain

bearish_fade_raw_score
bearish_fade_probability
bearish_fade_percentile
bearish_fade_decile
bearish_fade_score_available
bearish_fade_in_domain
```

If models are officially scored less frequently than once per second, carry-forward is allowed only when explicitly labeled.

Store:

```text
bullish_fade_score_source_ns
bullish_fade_score_age_seconds

bearish_fade_score_source_ns
bearish_fade_score_age_seconds
```

Never present a carried score as newly computed.

Preferred behavior is to score at the same causal cadence intended for live deployment.

---

## 7.6 Trade-relative model roles

Store explicit role aliases for easier analysis:

```text
entry_model_score
entry_model_probability

opposite_exit_model_score
opposite_exit_model_probability
opposite_exit_model_percentile
opposite_exit_model_in_domain
```

These aliases must be derived from the canonical prefixed score fields and trade direction. They must not replace them.

---

# 8. Artifact 3 — canonical_model_scores.parquet

One row per global scoring observation, independent of whether a selected trade exists.

This artifact is required so model behavior can be studied across **all regimes**, not only inside selected trade paths.

## 8.1 Identity and state

```text
timestamp_ns
instrument_id
session
prevailing_regime
is_regime_confirmed
regime_start_ns
regime_age_seconds
regime_age_bars
atr_at_score
reference_price
```

---

## 8.2 Both frozen model outputs

```text
bullish_fade_raw_score
bullish_fade_probability
bullish_fade_percentile
bullish_fade_decile
bullish_fade_score_available
bullish_fade_in_domain

bearish_fade_raw_score
bearish_fade_probability
bearish_fade_percentile
bearish_fade_decile
bearish_fade_score_available
bearish_fade_in_domain
```

---

## 8.3 Future labels for research only

Labels must be constructed separately from model features and scores.

Store, where uncensored:

```text
seconds_to_next_bullish_confirm_flip
seconds_to_next_bearish_confirm_flip

bullish_confirm_flip_within_300s
bearish_confirm_flip_within_300s

bullish_confirm_flip_within_600s
bearish_confirm_flip_within_600s
```

These columns must never feed model scoring.

They exist to test whether the opposite model provides useful exit warning in different regimes and holding states.

---

# 9. Scoring Cadence

The builder must define one canonical scoring cadence.

Preferred:

```text
every completed one-second bar
```

If production scoring is intentionally less frequent, use that cadence and record it in the artifact contract.

The cadence must be:

- causal;
- deterministic;
- identical in offline reconstruction and NautilusTrader runtime parity tests;
- explicit about bar-close availability;
- free from future-conditioned sampling.

Do not score only when the model exceeds a threshold. The full score distribution is required.

---

# 10. Exit-Signal Research Enabled

The artifacts must support testing, without rebuilding paths:

```text
exit when opposite model first enters top 10%
exit when opposite model first enters top 5%
exit when opposite model first enters top 2.5%
exit when opposite model probability exceeds threshold X
exit after N consecutive qualifying scores
exit when opposite score rises by delta X
exit when opposite score qualifies after MFE ≥ Y
exit on score plus retracement confirmation
exit on score plus regime-age condition
fallback to confirmed opposite regime flip
```

These are future policies. None belongs in the factual builder.

---

# 11. Causal and Leakage Controls

## 11.1 Feature availability

Every model score must use only feature values available at `score_source_ns`.

No backward joins to finalized future bars.

No use of the eventual confirmation or exit event in feature generation.

---

## 11.2 Population independence

The global score artifact must not be filtered based on:

- whether a future flip occurs;
- whether a selected trade survives a stop;
- whether a trade becomes profitable;
- whether a later exit threshold is reached.

---

## 11.3 Model-domain distinction

Out-of-domain scores may be stored for research, but they must be flagged.

Do not report their calibration as equivalent to in-domain performance without a separate validation.

---

## 11.4 Censoring

Any row or trade lacking sufficient future data for a label or final exit must be explicitly censored.

Do not classify censored observations as non-flips or losing trades.

---

# 12. Validation Requirements

## 12.1 Row-level path validation

For every completed trade:

```text
checkpoint_observation_ns
<= confirm_flip_ns
< exit_flip_ns
```

And:

```text
checkpoint_observation_ns
<= full_trade_mfe_ns
<= exit_flip_ns
```

```text
checkpoint_observation_ns
<= full_trade_mae_ns
<= exit_flip_ns
```

---

## 12.2 Price/PnL reconstruction

Recompute from stored prices:

```text
realized_return_points
realized_return_atr
```

and require exact or documented floating-point agreement.

---

## 12.3 Full-path extrema parity

Recompute MFE and MAE from `canonical_trade_paths.parquet` and require parity with the trade summary.

---

## 12.4 Score parity

For sampled timestamps, require exact parity among:

1. frozen model artifact;
2. builder score output;
3. NautilusTrader runtime feature vector;
4. NautilusTrader runtime model score.

Validate both models independently.

---

## 12.5 Regime coverage

Report score availability counts by:

```text
model
prevailing_regime
year
session
```

The report must make it obvious whether either model is absent during a regime where the user expects it to be viewable.

---

## 12.6 No duplicate or stale scores

Validate:

- one canonical score record per scoring timestamp;
- monotonic score timestamps;
- score-source timestamp not later than row timestamp;
- carried-forward score age correctly reported;
- no score silently carried across invalid resets or session boundaries.

---

# 13. Required Builder Report

The builder run must produce:

```text
BUILD_REPORT.md
```

with:

## Population

- scoring rows by year and regime;
- selected trades by year and direction;
- completed versus censored trades;
- path-row counts.

## Score coverage

- both-model availability by regime;
- in-domain and out-of-domain counts;
- missing-score reasons;
- percentile/decile coverage.

## Path integrity

- extrema timestamp validation;
- summary-versus-path MFE/MAE parity;
- realized PnL reconstruction parity;
- duplicate and ordering checks.

## Exit baseline

For the current fallback regime-flip exit:

- average and median realized ATR;
- average and median full-trade MFE;
- aggregate MFE capture;
- median trade-level MFE capture;
- giveback distribution;
- breakdown by year and direction.

## Opposite-model descriptive analysis

Without optimizing thresholds, report:

- opposite score distribution after confirmation;
- score percentile immediately before the actual exit flip;
- lead-time distributions for top 10%, top 5%, and top 2.5%;
- percentage of exit flips preceded by each threshold;
- false-warning frequency during aligned regimes.

These results are descriptive and must not select a final exit policy.

---

# 14. Acceptance Criteria

The builder is accepted only if:

1. The final opposite-flip exit price is present for every uncensored trade.
2. Full-trade MFE and MAE cover entry through final exit.
3. One-second paths reconstruct summary economics.
4. Both model outputs are inspectable at every approved scoring observation.
5. Scores are visible across bullish, bearish, and neutral/unconfirmed regimes whenever the frozen feature contracts permit computation.
6. Model-domain flags clearly separate validated entry use from exploratory opposite-model use.
7. Score parity passes for both models.
8. Censoring and missing-score reasons are explicit.
9. The current regime-flip exit's full-trade MFE capture can be calculated directly.
10. Opposite-model exit-warning studies can be run without rebuilding source paths.

---

# 15. Non-Goals

This builder does not:

- choose an optimal stop;
- choose an optimal score threshold;
- optimize trailing logic;
- prove that opposite-model scores are valid exits;
- retrain either model;
- alter signal populations;
- claim deployable economics;
- replace later NautilusTrader event-driven execution validation.

It creates the canonical factual substrate for those studies.

---

# 16. Recommended Project Location

```text
studies/full_trade_path_builder/
├── SPEC.md
├── config/
├── implementation/
├── tests/
├── results/
├── audit/
│   └── audit.md
├── BUILD_REPORT.md
└── REPRODUCE.md
```

---

# 17. Immediate Decision After Build

The first bounded study after builder acceptance should compare:

```text
Baseline:
hold until confirmed opposite regime flip
```

against descriptive candidate exits based on the relevant opposite model:

```text
top 10%
top 5%
top 2.5%
```

with the confirmed opposite regime flip retained as the fallback exit.

The primary outcome is not threshold optimization. It is to determine whether the opposite model provides enough causal lead time and enough reduction in MFE giveback to justify a dedicated exit-policy study.
