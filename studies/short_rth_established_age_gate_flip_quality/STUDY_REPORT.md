# Study Report: Established-Regime Age Gate — 120s vs 240s

**Study directory:** `studies/short_rth_established_age_gate_flip_quality/`
**Final decision: `AGE_GATE_INCONCLUSIVE`**

## Correction (added during `short_rth_pure_flip_prediction_enriched`'s scout pass, 2026-07-20)

This study's `bearish_flip_within_300s` label (`= aligned`, Policy A's own
alignment flag) is **not** a pure regime-transition label as originally
claimed here — traced to `fable5_common.simulate_trade_arrays`, it
conflates "the regime flipped within 300s" with "a hypothetical short trade
survived (didn't hit the 1.25×ATR pre-alignment stop) long enough to see
it." Verified directly on real data: ~0.95-1.41% of rows every year
(2021-2026) have `hit_pre_alignment_stop == True` yet the regime's true
confirmed flip (`confirm_flip_ns`) still occurs within 300s — these rows
were incorrectly counted as "no flip" throughout this study's flip-rate
diagnostics. **Every reported `bearish_flip_within_300s_rate` figure in this
report (§2's table, `results/gate_label_quality_by_year.csv`,
`results/first_eligible_surface_summary.csv`) is biased low by
approximately this amount.** The bias is a property of Policy A simulation
mechanics, not of the age-gate threshold, so it applies near-identically to
both Gate A and Gate B — the *comparison* between gates (§2-3's core
finding, and the `AGE_GATE_INCONCLUSIVE` decision) is not materially
affected, but the absolute rate figures should not be quoted as precise.
`bearish_flip_within_600s` and `time_to_bearish_flip_s` are unaffected
(already pure `confirm_flip_ns` arithmetic, not `aligned`-derived). See
`[[short_rth_pure_flip_prediction_enriched]]`'s SPEC.md scout-pass finding 1
for the full trace and per-year mislabel counts.

## Summary

Raising the established-regime age gate from 120s to 240s barely changes
the population (well under 1% of regimes lost every year, 2021-2026), and
produces a small but consistent improvement in the raw bearish-flip-within-
300s rate — but does **not** produce a meaningfully cleaner or more
learnable training surface by the metrics that actually matter for a future
model: univariate feature separation is statistically indistinguishable
between gates (AUC differences in the 4th decimal, across all three feature
families and all three primary labels), and a small bounded multivariate
diagnostic model shows no consistent winner across gate × target × model
combinations at this population's sample size. The evidence doesn't clearly
support switching to 240s, but it also doesn't clearly vindicate keeping
120s — hence inconclusive, not a tie-break in either direction.

## 1. Is 120s too early/noisy?

Only mildly, and the effect is smaller than the primary hypothesis
anticipated. The first-eligible checkpoint under the 120s gate already has
a **median age well above 120s** in practice (2021's minimum observed
first-eligible age is 130s, not 120s) — the other three gate criteria
(`running_mfe_atr_min=1.0`, `new_progress_windows_min=2`,
`retained_mfe_ratio_min=0.5`) are usually the binding constraint, not the
age floor itself. Consequently 99.2-99.4% of rows already have
`regime_age_s >= 240` regardless of which gate is nominally applied — the
120s gate is not admitting a large population of genuinely young,
unproven regimes that 240s would exclude.

## 2. Does 240s produce a cleaner established-regime population?

Only at the margin. Comparing first-eligible surfaces (`results/first_eligible_surface_summary.csv`):

| Year | Regimes (120s) | Regimes (240s) | Regimes lost | `bearish_flip_within_300s_rate` 120s | 240s |
|--|--:|--:|--:|--:|--:|
| 2021 | 1,762 | 1,755 | 0.40% | 16.12% | 16.30% |
| 2022 | 1,711 | 1,699 | 0.70% | 15.66% | 16.13% |
| 2023 | 1,732 | 1,719 | 0.75% | 17.32% | 17.57% |
| 2024 | 1,672 | 1,660 | 0.72% | 15.43% | 15.78% |
| 2025 | 1,678 | 1,669 | 0.54% | 17.82% | 18.57% |
| 2026 | 532 | 528 | 0.75% | 12.59% | 13.26% |

240s wins on flip rate in **all six years**, consistently (+0.2 to +0.8pp
every year) — a real, if small, effect: candidates surviving to 240s are
slightly more likely to actually flip bearish within the next 300s. The
`adverse_move_1p25A_before_bearish_flip` rate (pre-alignment-stop rate,
`results/gate_label_quality_by_year.csv`) shows no comparably consistent
direction — flat-to-mixed across years.

## 3. Does 240s improve flip-quality labels?

Not on the metric that matters most for training-surface quality
(learnability), even though it wins on raw flip rate (§2). Two independent
diagnostics, both computed on the first-eligible surface:

- **Univariate feature separation** (`results/gate_feature_separation.csv`):
  mean AUC per feature family is essentially identical across all three
  gates, for all three primary labels. E.g. `volume_delta` family AUC for
  `adverse_move_1p25A_before_bearish_flip`: 0.5190 (120s) vs 0.5188 (180s)
  vs 0.5188 (240s) — a difference of 0.0002, well inside noise. This holds
  for every family × label combination; no gate shows a systematically
  higher AUC, Cohen's d, or decile-monotonicity than another.
- **Bounded multivariate diagnostic model** (`results/optional_model_diagnostics.csv`,
  train 2021-2024 / dev 2025 / sealed 2026, F3 combined features): sealed
  2026 GBT AUC for `bearish_flip_within_300s_and_followthrough_1A`: 0.649
  (120s) vs 0.632 (180s) vs 0.654 (240s) — 240s is marginally best here, but
  for `adverse_move_1p25A_before_bearish_flip`: 0.623 (120s) vs 0.596
  (180s) vs 0.634 (240s) — 240s wins again, narrowly; but for logreg,
  followthrough: 0.578 (120s) vs 0.559 (180s) vs 0.552 (240s) — **120s wins**.
  No gate dominates across all four (target × model) combinations, and with
  only 528-532 sealed-test rows per gate, single-digit-count swings in
  positive cases move AUC by 0.03-0.13 — these differences are not reliably
  distinguishable from sampling noise at this population size.

## 4. Does 240s preserve enough opportunities?

Yes, trivially — this was never a real constraint. Regime loss is under 1%
every year (§2 table). Whatever the final gate decision, opportunity count
is not the deciding factor.

## 5. Which feature families look more informative under 240s?

The **same ranking holds under every gate** (120s, 180s, 240s alike), which
is itself informative: `volume_delta` has the highest mean pooled AUC for
`bearish_flip_within_300s` and `adverse_move_1p25A_before_bearish_flip`
(≈0.515-0.519) in all three gates; `price_level` is highest for the
followthrough label (≈0.512-0.514) in all three gates; `existing` is lowest
everywhere (≈0.506-0.508). The age gate does not change which feature
family is more informative — that ranking is a property of the features
and labels, not the population-construction threshold.

## 6. Should the next enriched training study use 240s as the base gate?

**No strong reason to switch, and no strong reason not to.** Given (a) the
population cost of 240s is negligible, (b) 240s shows a small, consistent
flip-rate improvement, but (c) neither univariate nor bounded-multivariate
diagnostics show 240s producing a more learnable surface, the honest
recommendation is: **keep 120s as the default** (it is the already-audited,
already-reconciled, already-deployed convention — switching has a real
engineering/reconciliation cost with no demonstrated learnability benefit),
but this is a close call, not a confident rejection of 240s. This is why
the decision label is `AGE_GATE_INCONCLUSIVE` rather than
`AGE_GATE_120_REMAINS_BEST` — the evidence doesn't clear the bar for a
confident "120s remains best" claim either, it just doesn't clear the bar
for switching.

## 7. What is the next bounded step?

Not a broader age sweep (explicitly out of scope, and the flat AUC pattern
across 120s/180s/240s suggests a sweep would likely show the same flat
pattern at other values too). Two more targeted options, in order of
expected value:

1. **Test whether the small flip-rate lift (§2) is itself monetizable**,
   independent of feature-separation learnability — e.g. does a *simple*
   240s-gated candidate set (no model, just the gate itself as a filter)
   change Layer-2 economics versus the 120s-gated candidate set, holding
   Policy A fixed? This isolates the one genuinely consistent 240s signal
   from the null result on learnability.
2. **Investigate why AUC is flat across gates at all** — given `[[short_rth_enriched_retrain_overfits_2025]]`
   already found volume/delta and price-level features carry real signal on
   a much larger population (200K+ rows/year vs ~1,700 first-eligible
   regimes/year here), the flat pattern here may simply reflect this
   study's much smaller first-eligible-surface sample size rather than a
   genuine absence of age-gate-dependent signal. A full-checkpoint-surface
   (not first-eligible-only) separation analysis, with the well-understood
   caveat that rows overlap heavily within a regime, would have far more
   statistical power and could sharpen or overturn this inconclusive result.

## Audit

`audit/audit.md`: **PASS, 0 CRITICAL** (1 WARNING, 2 NOTEs — all three
fixed post-audit, full pipeline re-run, `results/*.csv` and `manifest.json`
reflect the fixed code). The WARNING (raw-data-gap inflation of the
post-flip MFE window) was real but low-materiality: fixing it moved
`followthrough_1A_rate_given_flip_300s` by ≤0.7 percentage points in every
(gate, year) cell and changed no downstream conclusion. Confirms this
study's core design is sound: gate-input columns are joined only into label
construction, never into any feature list; the reused `aligned`/
`hit_pre_alignment_stop` columns were traced to their exact source
definition and confirmed equivalent to the SPEC's claimed semantics; and
the central "Gate B is a strict row-subset of Gate A" claim was verified
both by code inspection and by an empirical 0-violation check on real data.

## Primary caveats

1. **Sample size is the dominant limitation**, not a methodology flaw — the
   first-eligible-per-regime surface (the deployable-candidate framing) has
   only ~1,700 rows/year, an order of magnitude smaller than the ~200K-row
   full-checkpoint surface used elsewhere in this project. §7's second
   recommendation addresses this directly.
2. **The 240s flip-rate improvement (§2) is real but unexplained** — this
   study does not identify *why* checkpoints surviving to 240s are
   marginally more likely to flip; it only establishes that they are,
   consistently, every year.
3. **The optional diagnostic model is explicitly not a production
   candidate** and was never intended to be — its only job was to check
   whether combining features (vs. univariate) reveals a gate-dependent
   learnability difference the univariate analysis missed. It did not.

## Final decision: `AGE_GATE_INCONCLUSIVE`

Neither gate demonstrates a decisive advantage as a training-surface
foundation. Population preservation and a small flip-rate lift mildly favor
240s; feature-separation learnability (both univariate and bounded-model)
shows no meaningful difference. Recommend keeping 120s as the operational
default (lower switching cost, no demonstrated downside) while pursuing
§7's two bounded follow-ups before revisiting this decision.
