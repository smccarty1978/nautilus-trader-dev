# Score Semantics and Availability — source-of-truth audit

Produced by `repo-scout` (2026-07-28), with two claims corrected against direct
measurement. Corrections are marked and the measurement shown.

---

## 1. Target semantics — neither model predicts continuation

| Model | Target | Regime domain | Trade direction |
|---|---|---:|---:|
| `BULLISH_STRICT_top25_gbt_v2` | `bearish_regime_flip_within_300s`, interval `(T, T+300s]` | +1 (bullish) | -1 (SHORT) |
| `LONG_STRICT_top25_gbt_v2` | `bullish_regime_flip_within_300s`, interval `(T, T+300s]` | -1 (bearish) | +1 (LONG) |

Sources: `studies/full_trade_path_builder/artifacts/BULLISH_STRICT_top25_gbt_v2/config.yaml:10-12`
· `studies/freeze_long_strict_models_v2/artifacts/LONG_STRICT_top25_gbt_v2/manifest.json:10-12`

**Both models predict a flip AWAY from the regime they operate in. Neither
predicts persistence.** The names are misleading: "BULLISH" denotes the regime it
lives in, not the direction it forecasts.

### Consequence after a confirming flip

A fade SHORT is entered in a bullish regime and confirms when the regime turns
bearish. In that new bearish regime:

- `LONG_STRICT` becomes the in-domain model, and it predicts a **bullish** flip —
  precisely the event that ends the short.
- `BULLISH_STRICT` is out of domain (it requires a bullish regime).

So the only contract-valid post-confirmation signal is a **warning**. There is no
supporting-continuation score to deteriorate, which is why Family A's
"supporting score deteriorating" component is dropped (SPEC DECISION-2).

---

## 2. In-domain gating

`bullish_in_domain = (prevailing_regime == +1) AND established_regime_gate AND RTH`
`bearish_in_domain = (prevailing_regime == -1) AND established_regime_gate AND RTH`

Sources: `studies/full_trade_path_builder/implementation/phase_b_strategy.py:259-264`
· `studies/regime_complete_canonical_store/implementation/collector.py:274-281`

`established_regime_gate` (`PrevailingDomain.snapshot`, `phase_b_strategy.py:57-63`):

```text
age                >= 120 seconds
favorable_extreme  >= 1.0 ATR
progress_count     >= 2
retained_mfe_ratio >= 0.5 and finite
```

### Correction 1 — earliest possible in-domain time

`repo-scout` stated a 240s floor, reasoning that two progress windows require a
120s gap each. That is wrong: `PrevailingDomain.update` increments the first
window immediately (`last_extreme_ns is None`), so only the *second* needs the
120s spacing. The binding floor is therefore ~120s, not 240s.

Measured across all 137,673 regimes:

```text
regime start -> first in-domain score
   min 125s · p05 195s · p25 290s · median 410s · p75 580s · max 5,820s
```

Minimum 125s, consistent with a ~120s floor and inconsistent with 240s.

---

## 3. Availability relative to the confirming flip

### Correction 2 — the reason, which changes the rule

`repo-scout` concluded a score is not available at the confirming-flip bar close
"because the 1m bar is not necessarily aligned to a 5s boundary." The conclusion
holds; the reason does not. Measured:

```text
regime starts on the 5s dispatch grid    137,673 / 137,673  (100%)
regime starts on a 60s minute boundary   137,673 / 137,673  (100%)
regime starts with a dispatch at the exact same ns   83,806  (60.9%)
```

1m closes are multiples of 60s and 60 divides by 5, so **grid misalignment never
occurs**. The real constraint is **event order at equal `ts_init`**: the 1s bar
and its score dispatch precede the 1m bar that flips the regime. A score stamped
at the flip timestamp therefore describes the **pre-flip** regime.

**Frozen rule for this study:** the first score describing the new regime is at
`flip_ts + 5s`. A policy may not treat the dispatch stamped at `flip_ts` as a
post-confirmation observation. This is the same ordering principle that produced
the lifecycle boundary defect corrected in the prior study.

### Cadence

Dispatch fires on exact `ts_init % 5s == 0` (`phase_b_strategy.py:140`).
`score_decision_ns == score_available_ns`: features are complete at the
checkpoint's right boundary.

---

## 4. Threshold contracts — static and frozen

Static frozen values, not within-regime relative statistics.
`numpy.quantile(..., method="linear")`, membership operator `>=`.

Calibration populations, both **calendar-2025**:

- Bullish: 171,334 feature-complete in-domain established bullish RTH checkpoints
- Bearish: 163,397 rows, the LONG_STRICT retrain development population

Every row carries `overlaps_evaluation_window = true`; the study inherits
`full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`. **2025 is never
threshold-out-of-sample.**

---

## 5. Out-of-domain scores — emitted, and permitted for management

A probability **is** emitted when a model is out of domain, provided the feature
vector is complete; `feature_complete` / `probability` are populated
independently of `bullish_in_domain` / `bearish_in_domain`.

The store's prohibition (`REGIME_COMPLETE_CANONICAL_STORE_SPEC.md` §5.2.3) is:

> "It is retained for inspection and may **never** qualify an entry."

**Scoped to entry eligibility.** The contract does not forbid use in exit or
management decisions, and the enforcing negative test only asserts that no
in-domain row carries `session != "RTH"`. This study's use of out-of-domain
scores for management is therefore permitted, and every such result is flagged
`uses_out_of_domain_scores = true` per SPEC DECISION-1.

---

## 6. Measured availability in the study population

Top-2.5%, 4,000 confirmed trades:

| Quantity | Value |
|---|---:|
| Post-confirmation dispatches per trade | median 108 (p25 60, p75 200) |
| Trades with ≥1 score of any kind | 98.7% |
| Trades with ≥1 **in-domain** warning score | **40.4%** |
| Trades with no dispatch at all | 0 |

The binding constraint on every Family A–D policy is domain validity, not data
density. Against a median regime life of 540s and a median 410s to first
in-domain score, the contract-valid warning typically arrives near the end of the
new regime — the structural reason prior work found opposing-model warnings
"usually late."
